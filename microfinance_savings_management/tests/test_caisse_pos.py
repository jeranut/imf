# -*- coding: utf-8 -*-
from odoo import fields
from odoo.exceptions import UserError

from .common import SavingsCommon


class TestCaisseSearchClients(SavingsCommon):
    """Lot 3.1 : res.partner.search_caisse_clients(query, company_id), recherche dédiée (pas une
    surcharge de name_search) par nom OU numéro de compte permanent, scopée par agence."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.other_company = cls.env['res.company'].create({'name': 'Autre agence test', 'agency_code': 'T1'})
        cls.client_a = cls.env['res.partner'].create({
            'name': 'Rakoto Jean', 'microfinance_partner_type': 'client', 'company_id': cls.env.company.id,
        })
        cls.non_client = cls.env['res.partner'].create({
            'name': 'Rakoto Fournisseur', 'microfinance_partner_type': False, 'company_id': cls.env.company.id,
        })
        cls.client_other_company = cls.env['res.partner'].create({
            'name': 'Rasoa Marie', 'microfinance_partner_type': 'client', 'company_id': cls.other_company.id,
        })

    def test_search_by_name(self):
        results = self.env['res.partner'].search_caisse_clients('Rakoto', self.env.company.id)
        self.assertEqual({r['id'] for r in results}, {self.client_a.id})

    def test_search_by_account_number(self):
        results = self.env['res.partner'].search_caisse_clients(
            self.client_a.microfinance_account_number, self.env.company.id,
        )
        self.assertEqual({r['id'] for r in results}, {self.client_a.id})
        self.assertEqual(results[0]['account_number'], self.client_a.microfinance_account_number)

    def test_search_excludes_non_client_partner_type(self):
        results = self.env['res.partner'].search_caisse_clients('Rakoto', self.env.company.id)
        self.assertNotIn(self.non_client.id, {r['id'] for r in results})

    def test_search_scoped_by_company(self):
        results = self.env['res.partner'].search_caisse_clients('Rasoa', self.env.company.id)
        self.assertEqual(results, [])
        results_other = self.env['res.partner'].search_caisse_clients('Rasoa', self.other_company.id)
        self.assertEqual({r['id'] for r in results_other}, {self.client_other_company.id})


class TestCaisseGetClientAccountsSummary(SavingsCommon):
    """Lot 3.2 : agrège comptes épargne actifs et crédits actionnables en un seul appel."""

    def test_summary_includes_active_savings_account(self):
        account = self._create_active_account(opening_amount=150.0)
        summary = self.env['res.partner'].get_client_accounts_summary(self.partner.id, self.env.company.id)
        self.assertEqual(len(summary['savings_accounts']), 1)
        self.assertEqual(summary['savings_accounts'][0]['id'], account.id)
        self.assertAlmostEqual(summary['savings_accounts'][0]['balance'], 150.0, places=2)

    def test_summary_excludes_draft_savings_account(self):
        self._create_account()  # jamais activé : reste en 'draft'
        summary = self.env['res.partner'].get_client_accounts_summary(self.partner.id, self.env.company.id)
        self.assertEqual(summary['savings_accounts'], [])

    def test_summary_includes_active_loan_with_next_due_installment(self):
        loan = self._activate_loan(loan_amount=1200.0, term=6)
        summary = self.env['res.partner'].get_client_accounts_summary(self.partner.id, self.env.company.id)
        self.assertEqual(len(summary['loans']), 1)
        loan_data = summary['loans'][0]
        self.assertEqual(loan_data['id'], loan.id)
        self.assertEqual(loan_data['state'], 'active')
        self.assertAlmostEqual(loan_data['balance_total'], loan.balance_total, places=2)
        self.assertTrue(loan_data['next_due_date'])

    def test_summary_includes_approved_not_yet_disbursed_loan(self):
        loan = self._create_loan(loan_amount=500.0, term=3)
        loan.action_generate_schedule()
        loan.action_start_enquete()
        loan.action_ca_review()
        loan.action_cdag_review()
        loan.action_view_applications()
        loan.application_ids.write({'committee_first_decision': 'accepted'})
        loan.action_approve()
        summary = self.env['res.partner'].get_client_accounts_summary(self.partner.id, self.env.company.id)
        self.assertEqual([l['id'] for l in summary['loans']], [loan.id])
        self.assertEqual(summary['loans'][0]['state'], 'approved')


class TestCaisseRegisterOperation(SavingsCommon):
    """Lot 3.3 : point d'entrée unique du guichet — dispatch par type, réutilise les mécanismes
    déjà existants (transaction épargne, remboursement, décaissement), refuse hors session
    ouverte, vérifie la cohérence d'agence."""

    def _open_session(self, journal=None):
        session = self.env['microfinance.caisse.session'].create({
            'journal_id': (journal or self.disbursement_journal).id, 'date': fields.Date.today(),
        })
        session.action_open_session()
        return session

    def test_register_deposit_creates_transaction_and_mouvement(self):
        account = self._create_active_account(opening_amount=100.0)
        session = self._open_session()
        mouvement = self.env['microfinance.caisse.mouvement'].register_operation(
            session.id, 'depot_epargne', self.partner.id, 80.0, account.id, False,
        )
        self.assertEqual(mouvement.type, 'depot_epargne')
        self.assertEqual(mouvement.session_id, session)
        self.assertTrue(mouvement.savings_transaction_id)
        self.assertEqual(mouvement.savings_transaction_id.transaction_type, 'deposit')
        self.assertEqual(mouvement.savings_transaction_id.state, 'posted')
        self.assertAlmostEqual(account.balance, 180.0, places=2)
        self.assertIn(mouvement, session.mouvement_ids)

    def test_register_withdrawal_creates_transaction(self):
        account = self._create_active_account(opening_amount=200.0)
        session = self._open_session()
        mouvement = self.env['microfinance.caisse.mouvement'].register_operation(
            session.id, 'retrait_epargne', self.partner.id, 50.0, account.id, False,
        )
        self.assertEqual(mouvement.savings_transaction_id.transaction_type, 'withdrawal')
        self.assertAlmostEqual(account.balance, 150.0, places=2)

    def test_register_remboursement_matches_backend_allocation(self):
        loan = self._activate_loan(loan_amount=1200.0, term=6)
        first = loan.installment_ids.sorted('sequence')[0]
        session = self._open_session(journal=self.payment_journal)
        amount = min(80.0, first.total_amount)
        mouvement = self.env['microfinance.caisse.mouvement'].register_operation(
            session.id, 'remboursement_credit', self.partner.id, amount, False, loan.id,
        )
        self.assertTrue(mouvement.payment_id)
        self.assertEqual(mouvement.payment_id.state, 'posted')
        self.assertEqual(mouvement.payment_id.journal_id, self.payment_journal)
        self.assertAlmostEqual(mouvement.interest_amount, mouvement.payment_id.allocated_interest, places=2)
        self.assertAlmostEqual(mouvement.principal_amount, mouvement.payment_id.allocated_principal, places=2)
        self.assertAlmostEqual(mouvement.penalty_amount, mouvement.payment_id.allocated_penalty, places=2)
        self.assertAlmostEqual(
            mouvement.interest_amount + mouvement.principal_amount + mouvement.penalty_amount,
            amount, places=2,
        )

    def test_register_decaissement_disburses_loan(self):
        loan = self._create_loan(loan_amount=500.0, term=3)
        loan.action_generate_schedule()
        loan.action_start_enquete()
        loan.action_ca_review()
        loan.action_cdag_review()
        loan.action_view_applications()
        loan.application_ids.write({'committee_first_decision': 'accepted'})
        loan.action_approve()
        session = self._open_session()
        mouvement = self.env['microfinance.caisse.mouvement'].register_operation(
            session.id, 'decaissement_credit', self.partner.id, loan.loan_amount, False, loan.id,
        )
        self.assertEqual(loan.state, 'active')
        self.assertAlmostEqual(mouvement.amount, loan.net_disbursed_amount, places=2)

    def test_register_blocked_without_open_session(self):
        account = self._create_active_account(opening_amount=100.0)
        draft_session = self.env['microfinance.caisse.session'].create({
            'journal_id': self.disbursement_journal.id, 'date': fields.Date.today(),
        })  # jamais ouverte : reste 'draft'
        with self.assertRaises(UserError):
            self.env['microfinance.caisse.mouvement'].register_operation(
                draft_session.id, 'depot_epargne', self.partner.id, 50.0, account.id, False,
            )

    def test_register_blocked_cross_company_account(self):
        other_company = self.env['res.company'].create({'name': 'Autre agence test 2', 'agency_code': 'T2'})
        other_journal = self.env['account.journal'].create({
            'name': 'Caisse autre agence test', 'code': 'TOTH', 'type': 'cash', 'company_id': other_company.id,
        })
        session = self.env['microfinance.caisse.session'].create({
            'journal_id': other_journal.id, 'date': fields.Date.today(), 'company_id': other_company.id,
        })
        session.action_open_session()
        account = self._create_active_account(opening_amount=100.0)  # société par défaut (env.company)
        with self.assertRaises(UserError):
            self.env['microfinance.caisse.mouvement'].register_operation(
                session.id, 'depot_epargne', self.partner.id, 50.0, account.id, False,
            )


class TestCaissePosNoRegression(SavingsCommon):
    """Vérifie que les opérations existantes créées HORS de ce nouveau flux (script, import,
    utilisation directe des mécanismes déjà en place) restent inchangées par les hooks ajoutés
    pour la caisse — aucun microfinance.caisse.mouvement n'est requis ni créé implicitement."""

    def test_direct_savings_transaction_unaffected(self):
        account = self._create_active_account(opening_amount=100.0)
        transaction = account._create_transaction('deposit', 50.0)
        self.assertEqual(transaction.state, 'posted')
        self.assertFalse(self.env['microfinance.caisse.mouvement'].search([
            ('savings_transaction_id', '=', transaction.id),
        ]))

    def test_direct_loan_payment_unaffected(self):
        loan = self._activate_loan(loan_amount=1200.0, term=6)
        payment = self.env['microfinance.loan.payment'].create({
            'loan_id': loan.id, 'amount': 50.0, 'journal_id': self.payment_journal.id,
        })
        payment.action_post()
        self.assertEqual(payment.state, 'posted')
        self.assertFalse(self.env['microfinance.caisse.mouvement'].search([
            ('payment_id', '=', payment.id),
        ]))

    def test_direct_disbursement_unaffected(self):
        loan = self._create_loan(loan_amount=500.0, term=3)
        loan.action_generate_schedule()
        loan.action_start_enquete()
        loan.action_ca_review()
        loan.action_cdag_review()
        loan.action_view_applications()
        loan.application_ids.write({'committee_first_decision': 'accepted'})
        loan.action_approve()
        loan.action_disburse()
        self.assertEqual(loan.state, 'active')
        self.assertFalse(self.env['microfinance.caisse.mouvement'].search([
            ('loan_id', '=', loan.id),
        ]))
