# -*- coding: utf-8 -*-
from .common import MicrofinanceCommon


class TestDashboardMultiCompany(MicrofinanceCommon):
    """Non-régression : microfinance.loan.get_dashboard_data() (ex-route HTTP
    /microfinance/dashboard/data) doit refléter la société active du sélecteur
    multi-société, résolue nativement via allowed_company_ids, et non
    res.users.company_id (société figée de la fiche utilisateur).

    Avant la migration en méthode de modèle, la route personnalisée appelée via
    this.rpc() ne recevait jamais allowed_company_ids : le tableau de bord restait
    verrouillé sur la société par défaut de l'utilisateur quel que soit le sélecteur.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company
        cls.company_b = cls.env['res.company'].create({
            'name': 'Agence B tableau de bord (test)', 'agency_code': 'DBMC',
        })
        # with_company(B) ne résout env.company que si l'utilisateur courant a accès à B.
        cls.env.user.company_ids = [(4, cls.company_b.id)]

    def test_dashboard_data_follows_active_company_not_user_default(self):
        # Portefeuille présent dans l'agence A uniquement.
        self._activate_loan(term=3)

        data_a = self.env['microfinance.loan'].get_dashboard_data()
        self.assertEqual(data_a['company']['id'], self.company_a.id)
        self.assertEqual(
            data_a['company']['address_subtitle'],
            self.company_a._get_microfinance_dashboard_subtitle(),
        )
        self.assertGreaterEqual(data_a['kpis']['active_loan_count'], 1)
        self.assertGreater(data_a['kpis']['outstanding_amount'], 0.0)

        # Même utilisateur, même appel : seule l'agence active du sélecteur change.
        data_b = self.env['microfinance.loan'].with_company(self.company_b).get_dashboard_data()
        self.assertEqual(data_b['company']['id'], self.company_b.id)
        self.assertEqual(
            data_b['company']['address_subtitle'],
            self.company_b._get_microfinance_dashboard_subtitle(),
        )
        self.assertEqual(data_b['kpis']['active_loan_count'], 0)
        self.assertEqual(data_b['kpis']['outstanding_amount'], 0.0)
        self.assertEqual(data_b['kpis']['overdue_amount'], 0.0)
        self.assertFalse(data_b['recent_loans'])
