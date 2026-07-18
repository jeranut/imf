# -*- coding: utf-8 -*-
from .test_fond_bailleur import TestFondBailleurCommon


class TestFondDashboardKpi(TestFondBailleurCommon):
    """Cas 1, 2, 8 (non-regression) : tuile KPI "Fonds bailleurs" (get_dashboard_kpi)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_b = cls.env['res.company'].create({'name': 'Agence B dashboard (test)', 'agency_code': 'FD1'})

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
        cls.company_b = cls.env['res.company'].create({'name': 'Agence B dashboard chart (test)', 'agency_code': 'FD2'})
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

        loan_b = self.env['microfinance.loan'].with_context(microfinance_loan_creation_allowed=True).create({
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
        cls.company_b = cls.env['res.company'].create({'name': 'Agence B dashboard single (test)', 'agency_code': 'FD3'})

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


class TestFondMatrix(TestFondBailleurCommon):
    """Matrice "Fonds par agence" (get_fond_matrix) : portée volontairement plus large que les
    trois méthodes ci-dessus (toutes scopées à la société active) - couvre toutes les sociétés
    autorisées de l'utilisateur, pas seulement celle(s) actuellement cochée(s) dans le sélecteur.
    Individualise chaque fonds (y compris multi_company, contrairement à
    get_multi_company_usage_chart) et distingue "fonds configuré par défaut" (res.company) de
    "fonds réellement utilisé" (fond_credit_id du crédit décaissé)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_b = cls.env['res.company'].create({'name': 'Agence B matrice (test)', 'agency_code': 'FD4'})
        cls.principal_account_b = cls.env['account.account'].create({
            'name': 'Prets clients agence B (matrice)', 'code': 'MFPRET', 'account_type': 'asset_current',
            'company_id': cls.company_b.id,
        })
        cls.interest_account_b = cls.env['account.account'].create({
            'name': 'Interets agence B (matrice)', 'code': 'MFINT', 'account_type': 'income',
            'company_id': cls.company_b.id,
        })
        cls.cash_account_b = cls.env['account.account'].create({
            'name': 'Caisse agence B (matrice)', 'code': 'MFCASH', 'account_type': 'asset_cash',
            'company_id': cls.company_b.id,
        })
        cls.journal_b = cls.env['account.journal'].create({
            'name': 'Caisse decaissement agence B (matrice)', 'code': 'MFDEC', 'type': 'cash',
            'company_id': cls.company_b.id, 'default_account_id': cls.cash_account_b.id,
        })
        cls.product_b = cls.env['microfinance.loan.product'].create({
            'name': 'Produit agence B (matrice)', 'code': 'PMATB', 'company_id': cls.company_b.id,
            'min_amount': 100.0, 'max_amount': 100000.0, 'min_term': 1, 'max_term': 36,
            'interest_rate': 12.0, 'interest_method': 'flat', 'repayment_frequency_mode': 'fixed',
            'repayment_frequency_id': cls.env.ref('microfinance_loan_management.repayment_frequency_monthly').id,
            'disbursement_journal_id': cls.journal_b.id, 'payment_journal_id': cls.journal_b.id,
            'account_principal_individuel_id': cls.principal_account_b.id,
            'account_principal_groupe_id': cls.principal_account_b.id,
            'account_interets_recus_individuel_id': cls.interest_account_b.id,
            'account_interets_recus_groupe_id': cls.interest_account_b.id,
        })
        cls.partner_b = cls.env['res.partner'].create({'name': 'Client Test Matrice Agence B'})

    def _disburse_loan_b(self, fond, amount=1000.0):
        loan_b = self.env['microfinance.loan'].with_context(microfinance_loan_creation_allowed=True).create({
            'partner_id': self.partner_b.id,
            'product_id': self.product_b.id,
            'company_id': self.company_b.id,
            'loan_amount': amount,
            'term': 3,
            'fond_credit_id': fond.id,
        })
        loan_b.action_generate_schedule()
        loan_b.write({'state': 'approved'})
        loan_b.action_disburse()
        return loan_b

    def test_matrix_includes_authorized_company_not_active_in_selector(self):
        fond_shared = self._create_fond(scope='multi_company', company_id=False, passer_gl=False,
                                         verification_disponibilite='never')
        self._disburse_loan_b(fond_shared, amount=1000.0)

        multi_user = self.env['res.users'].create({
            'name': 'Utilisateur multi-agences (matrice test)',
            'login': 'multi_agence_matrice_test',
            'company_id': self.env.company.id,
            'company_ids': [(6, 0, [self.env.company.id, self.company_b.id])],
            'groups_id': [(6, 0, [self.env.ref('microfinance_loan_management.group_microfinance_user').id])],
        })
        # Sélecteur limité à la seule agence A (allowed_company_ids) alors que l'utilisateur est
        # autorisé sur A et B : la matrice doit malgré tout couvrir les deux (self.env.user.company_ids,
        # pas allowed_company_ids) - c'est tout l'objet du sudo() dans get_fond_matrix().
        FondCredit = self.env['microfinance.fond.credit'].with_user(multi_user).with_context(
            allowed_company_ids=[self.env.company.id],
        )
        result = FondCredit.get_fond_matrix(multi_user.company_ids.ids)
        company_names = {c['name'] for c in result['companies']}
        self.assertEqual(company_names, {self.env.company.name, self.company_b.name})

    def test_matrix_limited_to_single_authorized_company(self):
        fond_a = self._create_fond(name='Fonds unique A (matrice)')
        result = self.env['microfinance.fond.credit'].get_fond_matrix(self.env.company.ids)
        self.assertEqual([c['name'] for c in result['companies']], [self.env.company.name])
        fund_names = {f['name'] for f in result['funds']}
        self.assertIn(fond_a.name, fund_names)

    def test_single_company_fund_of_unauthorized_company_never_appears(self):
        self._create_fond(name='Fonds isole agence B (matrice)', scope='single_company', company_id=self.company_b.id)
        result = self.env['microfinance.fond.credit'].get_fond_matrix(self.env.company.ids)
        fund_names = {f['name'] for f in result['funds']}
        self.assertNotIn('Fonds isole agence B (matrice)', fund_names)

    def test_matrix_reflects_actual_disbursed_fund_not_configured_default(self):
        default_fond = self._create_fond(name='Fonds configure par defaut (matrice)',
                                          scope='multi_company', company_id=False, passer_gl=False)
        used_fond = self._create_fond(name='Fonds reellement utilise (matrice)',
                                       scope='multi_company', company_id=False, passer_gl=False,
                                       verification_disponibilite='never')
        self.company_b.microfinance_fond_credit_default_id = default_fond.id
        self._disburse_loan_b(used_fond, amount=1500.0)

        result = self.env['microfinance.fond.credit'].get_fond_matrix([self.env.company.id, self.company_b.id])
        funds_by_name = {f['name']: f for f in result['funds']}

        used_row = funds_by_name['Fonds reellement utilise (matrice)']
        self.assertEqual(used_row['amounts'][self.company_b.id], 1500.0)
        self.assertNotIn(self.company_b.id, used_row['is_default_for'])

        default_row = funds_by_name['Fonds configure par defaut (matrice)']
        self.assertEqual(default_row['amounts'][self.company_b.id], 0.0)
        self.assertIn(self.company_b.id, default_row['is_default_for'])
