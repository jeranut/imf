# -*- coding: utf-8 -*-
from odoo import fields
from odoo.exceptions import UserError, ValidationError

from .common import MicrofinanceCommon


class TestProvision(MicrofinanceCommon):

    def setUp(self):
        super().setUp()
        # Start from a clean slate: the module ships default tranches for the main
        # company, which would collide with the dedicated ones created below.
        self.env['microfinance.provision.rule'].search([('company_id', '=', self.env.company.id)]).unlink()
        self.Rule = self.env['microfinance.provision.rule']
        self.rule_0_30 = self.Rule.create({'min_days': 0, 'max_days': 30, 'provision_rate': 0.0})
        self.rule_31_60 = self.Rule.create({'min_days': 31, 'max_days': 60, 'provision_rate': 25.0})
        self.rule_61_plus = self.Rule.create({'min_days': 61, 'max_days': 0, 'provision_rate': 100.0})
        self.provision_account = self.env['account.account'].create({
            'name': 'Charge provision test', 'code': 'TPROV', 'account_type': 'expense', 'company_id': self.env.company.id,
        })
        self.provision_contra_account = self.env['account.account'].create({
            'name': 'Contrepartie provision test', 'code': 'TPROVC', 'account_type': 'asset_current', 'company_id': self.env.company.id,
        })

    def test_overlapping_rules_rejected(self):
        with self.assertRaises(ValidationError):
            self.Rule.create({'min_days': 20, 'max_days': 40, 'provision_rate': 10.0})

    def test_provision_zero_when_not_overdue(self):
        loan = self._activate_loan(loan_amount=1000.0, term=4)
        loan._compute_provision()
        self.assertEqual(loan.provision_amount, 0.0)

    def test_provision_matches_tranche_for_overdue_days(self):
        loan = self._activate_loan(loan_amount=1000.0, term=4)
        first = loan.installment_ids.sorted('sequence')[0]
        first.due_date = fields.Date.subtract(fields.Date.context_today(loan), days=45)
        loan._compute_provision()
        self.assertAlmostEqual(loan.provision_amount, loan.balance_total * 0.25, places=2)

    def test_provision_never_exceeds_balance(self):
        loan = self._activate_loan(loan_amount=1000.0, term=4)
        first = loan.installment_ids.sorted('sequence')[0]
        first.due_date = fields.Date.subtract(fields.Date.context_today(loan), days=200)
        loan._compute_provision()
        self.assertLessEqual(loan.provision_amount, loan.balance_total + 0.01)
        self.assertAlmostEqual(loan.provision_amount, loan.balance_total, places=2)

    def test_post_provisions_requires_product_accounts_configured(self):
        loan = self._activate_loan(loan_amount=1000.0, term=4)
        first = loan.installment_ids.sorted('sequence')[0]
        first.due_date = fields.Date.subtract(fields.Date.context_today(loan), days=45)
        loan._compute_provision()
        with self.assertRaises(UserError):
            loan.action_post_provisions()

    def test_post_provisions_generates_move_and_tracks_posted_amount(self):
        self.product.provision_account_id = self.provision_account.id
        self.product.provision_contra_account_id = self.provision_contra_account.id
        loan = self._activate_loan(loan_amount=1000.0, term=4)
        first = loan.installment_ids.sorted('sequence')[0]
        first.due_date = fields.Date.subtract(fields.Date.context_today(loan), days=45)
        loan._compute_provision()
        expected = loan.provision_amount

        loan.action_post_provisions()

        self.assertAlmostEqual(loan.provision_posted_amount, expected, places=2)
        moves = self.env['account.move'].search([('microfinance_loan_id', '=', loan.id), ('ref', 'like', 'Dotation provision%')])
        self.assertEqual(len(moves), 1)
        move = moves[0]
        self.assertEqual(move.state, 'posted')
        debit_lines = move.line_ids.filtered(lambda l: l.debit > 0)
        self.assertEqual(debit_lines.account_id, self.provision_account)
        self.assertAlmostEqual(sum(debit_lines.mapped('debit')), expected, places=2)

        # Calling again with no change in provision must not create a new move.
        loan.action_post_provisions()
        moves_after = self.env['account.move'].search([('microfinance_loan_id', '=', loan.id), ('ref', 'like', '%provision%')])
        self.assertEqual(len(moves_after), 1)

    def test_post_provisions_reversal_when_arrears_clear(self):
        self.product.provision_account_id = self.provision_account.id
        self.product.provision_contra_account_id = self.provision_contra_account.id
        loan = self._activate_loan(loan_amount=1000.0, term=4)
        first = loan.installment_ids.sorted('sequence')[0]
        first.due_date = fields.Date.subtract(fields.Date.context_today(loan), days=45)
        loan._compute_provision()
        loan.action_post_provisions()
        posted_after_first = loan.provision_posted_amount
        self.assertGreater(posted_after_first, 0.0)

        # Arrears clear (installment back to a future due date) -> provision drops to 0.
        first.due_date = fields.Date.add(fields.Date.context_today(loan), days=10)
        loan._compute_provision()
        self.assertEqual(loan.provision_amount, 0.0)
        loan.action_post_provisions()
        self.assertEqual(loan.provision_posted_amount, 0.0)

        reversal_moves = self.env['account.move'].search([('microfinance_loan_id', '=', loan.id), ('ref', 'like', 'Reprise provision%')])
        self.assertEqual(len(reversal_moves), 1)
        credit_lines = reversal_moves.line_ids.filtered(lambda l: l.credit > 0)
        self.assertEqual(credit_lines.account_id, self.provision_account)
        self.assertAlmostEqual(sum(credit_lines.mapped('credit')), posted_after_first, places=2)
