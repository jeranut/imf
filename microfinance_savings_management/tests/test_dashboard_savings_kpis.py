# -*- coding: utf-8 -*-
from .common import SavingsCommon


class TestDashboardSavingsKpis(SavingsCommon):
    """Non-régression : la surcharge épargne de microfinance.loan.get_dashboard_data()
    (ex-contrôleur MicrofinanceSavingsDashboardController, désormais simple super()
    Python dans le module épargne) ajoute bien les KPI épargne, et ceux-ci suivent la
    société active du sélecteur multi-société comme le reste du tableau de bord.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company
        cls.company_b = cls.env['res.company'].create({
            'name': 'Agence B KPI épargne (test)', 'agency_code': 'DBSV',
        })
        cls.env.user.company_ids = [(4, cls.company_b.id)]

    def test_savings_kpis_present_and_scoped_to_active_company(self):
        self._create_active_account(opening_amount=200.0)

        data_a = self.env['microfinance.loan'].get_dashboard_data()
        self.assertIn('savings_outstanding_total', data_a['kpis'])
        self.assertIn('active_savings_account_count', data_a['kpis'])
        self.assertGreaterEqual(data_a['kpis']['active_savings_account_count'], 1)
        self.assertGreaterEqual(data_a['kpis']['savings_outstanding_total'], 200.0)

        data_b = self.env['microfinance.loan'].with_company(self.company_b).get_dashboard_data()
        self.assertEqual(data_b['kpis']['active_savings_account_count'], 0)
        self.assertEqual(data_b['kpis']['savings_outstanding_total'], 0.0)
