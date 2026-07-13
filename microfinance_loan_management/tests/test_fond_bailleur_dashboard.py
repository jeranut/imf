# -*- coding: utf-8 -*-
from .test_fond_bailleur import TestFondBailleurCommon


class TestFondDashboardKpi(TestFondBailleurCommon):
    """Cas 1, 2, 8 (non-regression) : tuile KPI "Fonds bailleurs" (get_dashboard_kpi)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_b = cls.env['res.company'].create({'name': 'Agence B dashboard (test)'})

    def test_kpi_sums_single_company_and_multi_company_funds_for_agency_a(self):
        fond_a = self._create_fond(name='Fonds A', scope='single_company')
        self._create_contribution(fond_a, amount=1000.0).action_post()
        fond_shared = self._create_fond(name='Fonds partage', scope='multi_company', company_id=False, passer_gl=False)
        self._create_contribution(fond_shared, amount=500.0).action_post()

        kpi = self.env['microfinance.fond.credit'].get_dashboard_kpi(self.env.company.id)
        self.assertEqual(kpi['total'], 1500.0)
        self.assertEqual(kpi['count'], 2)

    def test_kpi_never_includes_single_company_fund_of_other_agency(self):
        fond_a = self._create_fond(name='Fonds A', scope='single_company')
        self._create_contribution(fond_a, amount=1000.0).action_post()

        kpi_b = self.env['microfinance.fond.credit'].get_dashboard_kpi(self.company_b.id)
        self.assertEqual(kpi_b['total'], 0.0)
        self.assertEqual(kpi_b['count'], 0)


class TestFondDashboardMultiCompanyChart(TestFondBailleurCommon):
    """Cas 3, 11, 12, 13 : graphique A "Utilisation des fonds partages par agence"."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_b = cls.env['res.company'].create({'name': 'Agence B dashboard chart (test)'})
        cls.principal_account_b = cls.env['account.account'].create({
            'name': 'Prets clients agence B (dashboard)', 'code': 'DBFPRET', 'account_type': 'asset_current',
            'company_id': cls.company_b.id,
        })
        cls.interest_account_b = cls.env['account.account'].create({
            'name': 'Interets agence B (dashboard)', 'code': 'DBFINT', 'account_type': 'income',
            'company_id': cls.company_b.id,
        })
        cls.cash_account_b = cls.env['account.account'].create({
            'name': 'Caisse agence B (dashboard)', 'code': 'DBFCASH', 'account_type': 'asset_cash',
            'company_id': cls.company_b.id,
        })
        cls.journal_b = cls.env['account.journal'].create({
            'name': 'Caisse decaissement agence B (dashboard)', 'code': 'DBFDEC', 'type': 'cash',
            'company_id': cls.company_b.id, 'default_account_id': cls.cash_account_b.id,
        })
        cls.product_b = cls.env['microfinance.loan.product'].create({
            'name': 'Produit agence B (dashboard)', 'code': 'PDASHB', 'company_id': cls.company_b.id,
            'min_amount': 100.0, 'max_amount': 100000.0, 'min_term': 1, 'max_term': 36,
            'interest_rate': 12.0, 'interest_method': 'flat', 'repayment_frequency_mode': 'fixed',
            'repayment_frequency_id': cls.env.ref('microfinance_loan_management.repayment_frequency_monthly').id,
            'disbursement_journal_id': cls.journal_b.id, 'payment_journal_id': cls.journal_b.id,
            'account_principal_individuel_id': cls.principal_account_b.id,
            'account_principal_groupe_id': cls.principal_account_b.id,
            'account_interets_recus_individuel_id': cls.interest_account_b.id,
            'account_interets_recus_groupe_id': cls.interest_account_b.id,
        })
        cls.partner_b = cls.env['res.partner'].create({'name': 'Client Test Dashboard Agence B'})

    def test_no_multi_company_fund_hides_chart_without_error(self):
        self._create_fond(name='Fonds unique A', scope='single_company')
        result = self.env['microfinance.fond.credit'].get_multi_company_usage_chart()
        self.assertFalse(result['visible'])
        self.assertEqual(result['labels'], [])

    def test_contribution_from_agency_a_and_disbursement_from_agency_b_both_visible_both_sides(self):
        fond = self._create_fond(scope='multi_company', company_id=False, passer_gl=False,
                                  verification_disponibilite='never')
        self._create_contribution(fond, amount=5000.0, saisie_company_id=self.env.company.id).action_post()

        loan_b = self.env['microfinance.loan'].create({
            'partner_id': self.partner_b.id,
            'product_id': self.product_b.id,
            'company_id': self.company_b.id,
            'loan_amount': 1000.0,
            'term': 3,
            'fond_credit_id': fond.id,
        })
        loan_b.action_generate_schedule()
        loan_b.write({'state': 'approved'})
        loan_b.action_disburse()

        FondCredit = self.env['microfinance.fond.credit']
        result_from_a = FondCredit.get_multi_company_usage_chart()

        user_b = self.env['res.users'].create({
            'name': 'Agent Agence B dashboard (test)',
            'login': 'agent_agence_b_dashboard_test',
            'company_id': self.company_b.id,
            'company_ids': [(6, 0, [self.company_b.id])],
            'groups_id': [(6, 0, [self.env.ref('microfinance_loan_management.group_microfinance_user').id])],
        })
        result_from_b = FondCredit.with_user(user_b).get_multi_company_usage_chart()

        self.assertTrue(result_from_a['visible'])
        self.assertEqual(result_from_a, result_from_b)

        contrib_index = result_from_a['labels'].index(self.env.company.name)
        self.assertEqual(result_from_a['contributions'][contrib_index], 5000.0)

        disb_index = result_from_a['labels'].index(self.company_b.name)
        self.assertEqual(result_from_a['decaissements'][disb_index], 1000.0)


class TestFondDashboardSingleCompanyChart(TestFondBailleurCommon):
    """Cas 14, 15 : graphique B "Fonds propres a l'agence"."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_b = cls.env['res.company'].create({'name': 'Agence B dashboard single (test)'})

    def test_three_single_company_funds_show_three_distinct_bars(self):
        self._create_fond(name='Fonds A1', scope='single_company')
        self._create_fond(name='Fonds A2', scope='single_company')
        self._create_fond(name='Fonds A3', scope='single_company')

        result = self.env['microfinance.fond.credit'].get_single_company_chart(self.env.company.id)
        self.assertEqual(len(result['labels']), 3)
        self.assertEqual(set(result['labels']), {'Fonds A1', 'Fonds A2', 'Fonds A3'})

    def test_single_company_fund_of_other_agency_never_appears(self):
        self._create_fond(name='Fonds A', scope='single_company')

        result_b = self.env['microfinance.fond.credit'].get_single_company_chart(self.company_b.id)
        self.assertEqual(result_b['labels'], [])
        self.assertEqual(result_b['values'], [])
