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

    def test_tuiles_epargne_egales_leurs_listes(self):
        self._create_active_account(opening_amount=300.0)
        tiles = {t['key']: t for t in self.env['microfinance.loan'].get_dashboard_data()['tiles']}
        sums = {'savings_outstanding_total': 'balance'}
        for key in ('active_savings_holder_count', 'active_savings_account_count', 'savings_outstanding_total'):
            tile = tiles[key]
            records = self.env[tile['model']].search(tile['domain'])
            expected = sum(records.mapped(sums[key])) if key in sums else len(records)
            self.assertAlmostEqual(tile['value'], expected, places=2, msg=key)
            self.assertIn(('company_id', '=', self.company_a.id), [tuple(t) for t in tile['domain']])
            for view_id, view_type in tile['views']:
                arch = self.env[tile['model']].get_view(view_id, 'tree' if view_type == 'list' else view_type)['arch']
                self.assertTrue('create="false"' in arch or 'create="0"' in arch, key)
        self.assertEqual(tiles['active_savings_holder_count']['model'], 'microfinance.savings.holder.account')
        holders = self.env['microfinance.savings.holder.account'].search(tiles['active_savings_holder_count']['domain'])
        self.assertAlmostEqual(sum(holders.mapped('balance_total')), tiles['savings_outstanding_total']['value'], places=2)

    def test_tuiles_epargne_masquees_sans_droit_de_lecture(self):
        agent = self.env['res.users'].create({
            'name': 'Agent sans épargne', 'login': 'agent_sans_epargne_test',
            'groups_id': [(6, 0, (self.env.ref('base.group_user') | self.env.ref(
                'microfinance_loan_management.group_microfinance_user')).ids)],
        })
        keys = [t['key'] for t in self.env['microfinance.loan'].with_user(agent).get_dashboard_data()['tiles']]
        for key in ('active_savings_holder_count', 'active_savings_account_count', 'savings_outstanding_total'):
            self.assertNotIn(key, keys)
