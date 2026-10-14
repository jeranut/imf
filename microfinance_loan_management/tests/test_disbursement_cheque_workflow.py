# -*- coding: utf-8 -*-
from odoo.exceptions import UserError

from .common import MicrofinanceCommon, MicrofinanceNoFundMixin


class TestDisbursementChequeWorkflow(MicrofinanceNoFundMixin, MicrofinanceCommon):
    """Sous-lot A-D (docs_dev/guichet_caisse/AUDIT_decaissement_journal_cheque.md) : choix du
    journal de décaissement + compte d'attente chèques émis, patron inversé de
    microfinance.savings.transaction (test_cheque_workflow.py) — ici le décaissement engage une
    dette envers le client (compte de passif) tant que le chèque n'est pas encaissé, au lieu
    d'une créance (compte d'actif) pour un chèque reçu en dépôt."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cheques_emis_attente_account = cls.env['account.account'].create({
            'name': 'Attente chèques émis test', 'code': 'TCHQE', 'account_type': 'liability_current',
            'company_id': cls.env.company.id,
        })
        cls.product.write({'account_cheques_emis_attente_id': cls.cheques_emis_attente_account.id})
        cls.alt_journal = cls.env['account.journal'].create({
            'name': 'Journal décaissement alternatif test', 'code': 'TALT', 'type': 'bank',
            'company_id': cls.env.company.id, 'default_account_id': cls.bank_account.id,
        })

    def _disburse_by_cheque(self, **kwargs):
        loan = self._activate_loan_without_disbursement(**kwargs)
        loan.disbursement_payment_method = 'cheque'
        loan.action_process_disbursement()
        return loan

    def test_disbursement_cheque_uses_waiting_account_and_sets_en_attente(self):
        loan = self._disburse_by_cheque()
        self.assertEqual(loan.disbursement_cheque_state, 'en_attente')
        move = loan.move_ids.filtered(lambda m: m.state == 'posted')
        outflow_line = move.line_ids.filtered(lambda l: l.credit > 0)
        self.assertEqual(outflow_line.account_id, self.cheques_emis_attente_account)
        self.assertAlmostEqual(outflow_line.credit, loan.net_disbursed_amount, places=2)

    def test_disbursement_cheque_requires_waiting_account_configured(self):
        self.product.write({'account_cheques_emis_attente_id': False})
        loan = self._activate_loan_without_disbursement()
        loan.disbursement_payment_method = 'cheque'
        with self.assertRaises(UserError):
            loan.action_process_disbursement()

    def test_clear_disbursement_cheque_opens_writeoff_wizard_on_waiting_line(self):
        # La compensation passe par l'assistant générique de lettrage (le dénouement lui-même est
        # testé via le pointage du relevé : test_disbursement_waiting_account). Avant le dénouement
        # la banque n'a pas bougé : la sortie réelle n'est constatée qu'à la compensation.
        loan = self._disburse_by_cheque()
        action = loan.action_clear_disbursement_cheque()
        self.assertEqual(action['res_model'], 'account.move.line.writeoff.wizard')
        waiting_line = loan.disbursement_move_id.line_ids.filtered(
            lambda l: l.account_id == self.cheques_emis_attente_account)
        self.assertEqual(action['context']['default_move_line_id'], waiting_line.id)
        self.assertEqual(loan.disbursement_cheque_state, 'en_attente')
        self.assertAlmostEqual(self.bank_account.current_balance, 0.0, places=2)

    def test_clear_disbursement_cheque_blocked_if_not_en_attente(self):
        loan = self._disburse_by_cheque()
        loan.sudo().disbursement_cheque_state = 'compense'
        with self.assertRaises(UserError):
            loan.action_clear_disbursement_cheque()

    def test_clear_disbursement_cheque_blocked_on_non_cheque_disbursement(self):
        loan = self._activate_loan_without_disbursement()
        loan.action_process_disbursement()  # cash par défaut
        with self.assertRaises(UserError):
            loan.action_clear_disbursement_cheque()

    def test_reject_disbursement_cheque_reverses_move_and_reopens_pending_queue(self):
        loan = self._disburse_by_cheque()
        loan.action_reject_disbursement_cheque(reason='Provision insuffisante')
        self.assertEqual(loan.disbursement_cheque_state, 'rejete')
        self.assertFalse(loan.disbursement_date)
        self.assertEqual(loan.state, 'active')
        pending_ids = [row['id'] for row in self.env['microfinance.loan'].get_pending_disbursements(self.env.company.id)]
        self.assertIn(loan.id, pending_ids)

    def test_reject_disbursement_cheque_blocked_if_not_en_attente(self):
        loan = self._disburse_by_cheque()
        loan.action_reject_disbursement_cheque()
        with self.assertRaises(UserError):
            loan.action_reject_disbursement_cheque()

    def test_reject_disbursement_cheque_blocked_if_repayment_already_applied(self):
        loan = self._disburse_by_cheque()
        first = loan.installment_ids.sorted('sequence')[0]
        first.write({'paid_principal': 10.0})
        with self.assertRaises(UserError):
            loan.action_reject_disbursement_cheque()

    def test_disbursement_after_reject_can_retry_with_different_payment_method(self):
        loan = self._disburse_by_cheque()
        loan.action_reject_disbursement_cheque(reason='Provision insuffisante')
        loan.disbursement_payment_method = 'cash'
        loan.action_process_disbursement()
        self.assertFalse(
            loan.disbursement_cheque_state,
            "Un résidu 'rejete' de la tentative précédente ne doit pas survivre à un nouveau "
            "décaissement réglé autrement que par chèque.",
        )
        self.assertTrue(loan.disbursement_date)
        # Le décaissement actif (pas la contre-passation de la tentative rejetée, aussi listée dans move_ids).
        outflow_line = loan.disbursement_move_id.line_ids.filtered(lambda l: l.credit > 0)
        self.assertEqual(outflow_line.account_id, self.bank_account)

    def test_cash_disbursement_unaffected_by_cheque_workflow(self):
        loan = self._activate_loan_without_disbursement()
        loan.action_process_disbursement()
        self.assertFalse(loan.disbursement_cheque_state)
        # Le décaissement actif (pas la contre-passation de la tentative rejetée, aussi listée dans move_ids).
        outflow_line = loan.disbursement_move_id.line_ids.filtered(lambda l: l.credit > 0)
        self.assertEqual(outflow_line.account_id, self.bank_account)

    def test_disbursement_journal_override_takes_precedence_over_product(self):
        loan = self._activate_loan_without_disbursement()
        loan.disbursement_journal_id = self.alt_journal.id
        loan.action_process_disbursement()
        move = loan.move_ids.filtered(lambda m: m.state == 'posted')
        self.assertEqual(move.journal_id, self.alt_journal)

    def test_disbursement_without_journal_override_falls_back_to_product(self):
        loan = self._activate_loan_without_disbursement()
        self.assertFalse(loan.disbursement_journal_id)
        loan.action_process_disbursement()
        move = loan.move_ids.filtered(lambda m: m.state == 'posted')
        self.assertEqual(move.journal_id, self.disbursement_journal)
