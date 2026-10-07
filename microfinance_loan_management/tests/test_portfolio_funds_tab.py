# -*- coding: utf-8 -*-
"""7e onglet "Fonds de crédit" du dashboard portefeuille agent (get_portfolio_tab('fonds', ...)).
MVP : remboursement du capital hors périmètre (cf. consigne), journal = allocations validées
(CRÉDIT) + décaissements (DÉBIT) uniquement."""
from odoo.exceptions import AccessError, UserError, ValidationError

from .test_fond_bailleur import TestFondBailleurCommon


class TestPortfolioFundsTabJournal(TestFondBailleurCommon):
    """Test 1 : portefeuille avec 2 fonds, une allocation + un décaissement sur chacun."""

    def setUp(self):
        super().setUp()
        self.portfolio = self.env['microfinance.portfolio'].create({
            'agent_id': self.env.user.id, 'company_id': self.env.company.id,
        })
        self.fond_pce = self._create_fond(name='PCE', verification_disponibilite='never')
        self.fond_fb = self._create_fond(name='FB', verification_disponibilite='never')

    def _allocate(self, fond, amount):
        repartition = self.env['microfinance.portfolio.allocation'].create({
            'fond_id': fond.id, 'company_id': self.env.company.id, 'base_amount': amount,
            'line_ids': [(0, 0, {'portfolio_id': self.portfolio.id, 'percent': 100.0, 'amount': amount})],
        })
        repartition.action_validate()
        return repartition

    def test_aggregate_journal_has_four_lines_and_matches_fonds_utilise(self):
        self._allocate(self.fond_pce, 5000.0)
        self._allocate(self.fond_fb, 3000.0)
        self._activate_loan(officer_id=self.env.user.id, fond_credit_id=self.fond_pce.id, loan_amount=1000.0)
        self._activate_loan(officer_id=self.env.user.id, fond_credit_id=self.fond_fb.id, loan_amount=800.0)

        Loan = self.env['microfinance.loan']
        result = Loan.get_portfolio_tab('fonds', self.env.user.id, 0, 20)
        self.assertEqual(result['total_rows'], 4)
        self.assertEqual(result['aggregate']['used'], self.portfolio.montant_utilise)

        result_pce = Loan.get_portfolio_tab('fonds', self.env.user.id, 0, 20, self.fond_pce.id)
        self.assertEqual(result_pce['total_rows'], 2)
        self.assertTrue(all(row['fund'] == self.fond_pce.name for row in result_pce['rows']))
        # Solde du fonds PCE après les 2 mouvements (tri desc : décaissement en tête) :
        # 5000 (allocation) - 1000 (décaissement) = 4000.
        self.assertEqual(result_pce['rows'][0]['balance'], 4000.0)


class TestPortfolioFundsTabPeriodAndAccess(TestFondBailleurCommon):
    """Test 2 : filtre de période (ouverture/clôture) + isolation d'accès entre agents."""

    def setUp(self):
        super().setUp()
        group_ids = [(6, 0, [
            self.env.ref('base.group_user').id,
            self.env.ref('microfinance_loan_management.group_microfinance_user').id,
        ])]
        self.agent_a = self.env['res.users'].create({
            'name': 'Agent A funds', 'login': 'agent_a_funds_test', 'groups_id': group_ids,
        })
        self.agent_b = self.env['res.users'].create({
            'name': 'Agent B funds', 'login': 'agent_b_funds_test', 'groups_id': group_ids,
        })
        self.portfolio_a = self.env['microfinance.portfolio'].create({
            'agent_id': self.agent_a.id, 'company_id': self.env.company.id,
        })
        self.portfolio_b = self.env['microfinance.portfolio'].create({
            'agent_id': self.agent_b.id, 'company_id': self.env.company.id,
        })
        self.fond = self._create_fond(name='Fonds periode', verification_disponibilite='never')
        repartition = self.env['microfinance.portfolio.allocation'].create({
            'fond_id': self.fond.id, 'company_id': self.env.company.id, 'base_amount': 10000.0,
            'date': '2024-01-10',
            'line_ids': [(0, 0, {'portfolio_id': self.portfolio_a.id, 'percent': 100.0, 'amount': 10000.0})],
        })
        repartition.action_validate()
        self.loan = self._activate_loan(
            officer_id=self.agent_a.id, fond_credit_id=self.fond.id, loan_amount=2000.0)
        self.loan.disbursement_date = '2024-02-15'

    def test_period_filter_opening_totals_and_closing_balance(self):
        result = self.env['microfinance.loan'].get_portfolio_tab(
            'fonds', self.agent_a.id, 0, 20, False, 'all', '2024-02-01', '2024-02-28')
        self.assertEqual(result['opening_balance'], 10000.0)
        self.assertEqual(result['totals']['debit'], 2000.0)
        self.assertEqual(result['totals']['credit'], 0.0)
        self.assertEqual(result['totals']['closing'], 8000.0)

    def test_fund_id_not_allocated_to_portfolio_raises(self):
        with self.assertRaises(UserError):
            self.env['microfinance.loan'].get_portfolio_tab('fonds', self.agent_b.id, 0, 20, self.fond.id)

    def test_agent_b_cannot_query_agent_a_portfolio(self):
        with self.assertRaises(AccessError):
            self.env['microfinance.loan'].with_user(self.agent_b).get_portfolio_tab(
                'fonds', self.agent_a.id, 0, 20)


class TestPortfolioFundsTabDisbursementRules(TestFondBailleurCommon):
    """Test 3 : règles de décaissement existantes (non-régression) + crédit historique sans
    fonds affiché au journal, en cohérence avec fonds_utilise."""

    def setUp(self):
        super().setUp()
        self.portfolio = self.env['microfinance.portfolio'].create({
            'agent_id': self.env.user.id, 'company_id': self.env.company.id,
        })

    def test_disbursement_without_fund_blocked_when_active_fund_exists(self):
        self._create_fond(name='Fonds existant', verification_disponibilite='at_disbursement')
        with self.assertRaises(UserError):
            self._activate_loan(officer_id=self.env.user.id, fond_credit_id=False, loan_amount=500.0)

    def test_disbursement_blocked_when_fund_balance_insufficient(self):
        fond = self._create_fond(name='Fonds insuffisant', verification_disponibilite='at_disbursement')
        self._create_contribution(fond, amount=100.0).action_post()
        with self.assertRaises(UserError):
            self._activate_loan(officer_id=self.env.user.id, fond_credit_id=fond.id, loan_amount=500.0)

    def test_fund_locked_after_disbursement(self):
        fond = self._create_fond(name='Fonds verrou', verification_disponibilite='never')
        loan = self._activate_loan(officer_id=self.env.user.id, fond_credit_id=fond.id, loan_amount=500.0)
        other_fond = self._create_fond(name='Autre fonds', verification_disponibilite='never')
        with self.assertRaises(ValidationError):
            loan.fond_credit_id = other_fond.id

    def test_historical_loan_without_fund_shown_and_matches_fonds_utilise(self):
        # Aucun fonds actif pour cette société : décaissement sans fond_credit_id toléré
        # (comportement mutualiste d'origine, cf. audit H1) -> apparaît au journal sous
        # "Sans fonds (historique)", comptabilisé dans aggregate.used comme n'importe quel crédit.
        self._activate_loan(officer_id=self.env.user.id, fond_credit_id=False, loan_amount=700.0)
        result = self.env['microfinance.loan'].get_portfolio_tab('fonds', self.env.user.id, 0, 20)
        sans_fonds_rows = [r for r in result['rows'] if r['fund'] == 'Sans fonds (historique)']
        self.assertEqual(len(sans_fonds_rows), 1)
        self.assertEqual(sans_fonds_rows[0]['debit'], 700.0)
        self.assertEqual(result['aggregate']['used'], self.portfolio.montant_utilise)
