# -*- coding: utf-8 -*-
from odoo.exceptions import UserError

from .common import MicrofinanceCommon


class TestFee(MicrofinanceCommon):

    def setUp(self):
        super().setUp()
        self.fee_account = self.env['account.account'].create({
            'name': 'Frais de dossier test', 'code': 'TFEE', 'account_type': 'income_other', 'company_id': self.env.company.id,
        })
        self.product.write({
            'account_commission_credit_id': self.fee_account.id,
            'fee_journal_id': self.disbursement_journal.id,
        })

    def _approve_loan(self, **kwargs):
        loan = self._create_loan(**kwargs)
        loan.action_generate_schedule()
        loan.action_submit()
        loan.action_manager_validate()
        loan.action_finance_validate()
        loan.action_approve()
        return loan

    def test_fee_amount_fixed(self):
        self.product.write({'fee_type': 'fixed', 'fee_amount': 25.0})
        loan = self._create_loan(loan_amount=1000.0)
        self.assertEqual(loan.fee_amount_due, 25.0)

    def test_fee_amount_percentage(self):
        self.product.write({'fee_type': 'percentage', 'fee_rate': 2.0})
        loan = self._create_loan(loan_amount=1000.0)
        self.assertEqual(loan.fee_amount_due, 20.0)

    def test_disburse_blocked_when_fee_unpaid_and_required(self):
        self.product.write({'fee_type': 'fixed', 'fee_amount': 25.0, 'fee_charged_before_disbursement': True})
        loan = self._approve_loan(loan_amount=1000.0, term=3)
        with self.assertRaises(UserError):
            loan.action_disburse()

    def test_disburse_allowed_when_fee_not_required(self):
        self.product.write({'fee_type': 'fixed', 'fee_amount': 25.0, 'fee_charged_before_disbursement': False})
        loan = self._approve_loan(loan_amount=1000.0, term=3)
        loan.action_disburse()
        self.assertEqual(loan.state, 'active')

    def test_charge_fee_generates_move_and_unblocks_disbursement(self):
        self.product.write({'fee_type': 'fixed', 'fee_amount': 25.0, 'fee_charged_before_disbursement': True})
        loan = self._approve_loan(loan_amount=1000.0, term=3)

        loan.action_charge_fee()

        self.assertTrue(loan.fee_paid)
        self.assertTrue(loan.fee_move_id)
        self.assertEqual(loan.fee_move_id.state, 'posted')
        debit_lines = loan.fee_move_id.line_ids.filtered(lambda l: l.debit > 0)
        credit_lines = loan.fee_move_id.line_ids.filtered(lambda l: l.credit > 0)
        self.assertEqual(sum(debit_lines.mapped('debit')), 25.0)
        self.assertEqual(credit_lines.account_id, self.fee_account)

        loan.action_disburse()
        self.assertEqual(loan.state, 'active')

    def test_charge_fee_twice_blocked(self):
        self.product.write({'fee_type': 'fixed', 'fee_amount': 25.0})
        loan = self._approve_loan(loan_amount=1000.0, term=3)
        loan.action_charge_fee()
        with self.assertRaises(UserError):
            loan.action_charge_fee()

    def test_net_disbursed_amount_equals_loan_amount_when_fee_charged_separately(self):
        self.product.write({'fee_type': 'fixed', 'fee_amount': 25.0, 'fee_charged_before_disbursement': True})
        loan = self._create_loan(loan_amount=1000.0)
        self.assertEqual(loan.net_disbursed_amount, 1000.0)

    def test_disburse_nets_fee_in_single_move(self):
        self.product.write({'fee_type': 'fixed', 'fee_amount': 25.0, 'fee_charged_before_disbursement': False})
        loan = self._approve_loan(loan_amount=1000.0, term=3)

        self.assertEqual(loan.net_disbursed_amount, 975.0)
        loan.action_disburse()

        move = loan.move_ids
        self.assertEqual(len(move), 1)
        debit_lines = move.line_ids.filtered(lambda l: l.debit > 0)
        self.assertEqual(sum(debit_lines.mapped('debit')), 1000.0)
        self.assertEqual(debit_lines.account_id, self.loan_account)
        fee_line = move.line_ids.filtered(lambda l: l.account_id == self.fee_account)
        self.assertEqual(fee_line.credit, 25.0)
        cash_line = move.line_ids.filtered(lambda l: l.account_id == self.bank_account)
        self.assertEqual(cash_line.credit, 975.0)
        # Le capital dû reste plein : le client rembourse 1000, pas 975.
        self.assertEqual(loan.balance_total, 1000.0)
