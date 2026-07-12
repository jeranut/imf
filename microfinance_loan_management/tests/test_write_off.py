# -*- coding: utf-8 -*-
from odoo.exceptions import UserError

from .common import MicrofinanceCommon


class TestWriteOff(MicrofinanceCommon):

    def test_write_off_requires_product_account_configured(self):
        loan = self._activate_loan()
        self.assertFalse(self.product.account_credits_perte_individuel_id)
        with self.assertRaises(UserError):
            loan.action_confirm_write_off('Client introuvable', loan.disbursement_date)

    def test_write_off_active_loan_generates_move_and_changes_state(self):
        writeoff_account = self.env['account.account'].create({
            'name': 'Pertes créances irrécouvrables test',
            'code': 'TWOF',
            'account_type': 'expense',
            'company_id': self.env.company.id,
        })
        self.product.account_credits_perte_individuel_id = writeoff_account.id
        loan = self._activate_loan(loan_amount=600.0, term=3)
        balance_before = loan.balance_total
        self.assertGreater(balance_before, 0.0)

        move = loan.action_confirm_write_off('Client décédé, aucun recours possible', loan.disbursement_date)

        self.assertEqual(loan.state, 'written_off')
        self.assertEqual(move.state, 'posted')
        debit_lines = move.line_ids.filtered(lambda l: l.debit > 0)
        credit_lines = move.line_ids.filtered(lambda l: l.credit > 0)
        self.assertEqual(debit_lines.account_id, writeoff_account)
        self.assertAlmostEqual(sum(debit_lines.mapped('debit')), balance_before, places=2)
        self.assertEqual(credit_lines.account_id, self.loan_account)
        self.assertAlmostEqual(sum(credit_lines.mapped('credit')), balance_before, places=2)

    def test_write_off_not_allowed_from_draft(self):
        loan = self._create_loan()
        with self.assertRaises(UserError):
            loan.action_write_off()

    def test_written_off_loan_excluded_from_scoring(self):
        writeoff_account = self.env['account.account'].create({
            'name': 'Pertes créances irrécouvrables test 2',
            'code': 'TWOF2',
            'account_type': 'expense',
            'company_id': self.env.company.id,
        })
        self.product.account_credits_perte_individuel_id = writeoff_account.id
        loan = self._activate_loan(loan_amount=300.0, term=2)
        loan.action_confirm_write_off('Insolvabilité', loan.disbursement_date)
        loan.action_calculate_scoring()
        self.assertEqual(loan.internal_score, 0)
        self.assertEqual(loan.risk_level, 'critical')
