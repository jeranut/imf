# -*- coding: utf-8 -*-
from odoo import fields
from odoo.exceptions import UserError

from .common import MicrofinanceCommon


class TestEligibility(MicrofinanceCommon):

    def _set_partner_create_date(self, partner, days_ago):
        past_date = fields.Datetime.subtract(fields.Datetime.now(), days=days_ago)
        self.env.cr.execute(
            'UPDATE res_partner SET create_date = %s WHERE id = %s', (past_date, partner.id)
        )
        partner.invalidate_recordset(['create_date'])

    # -- Ancienneté client --

    def test_membership_too_short_blocks_submit(self):
        self.product.min_membership_days = 30
        self._set_partner_create_date(self.partner, 5)
        loan = self._create_loan()
        with self.assertRaises(UserError):
            loan.action_submit()

    def test_membership_sufficient_allows_submit(self):
        self.product.min_membership_days = 30
        self._set_partner_create_date(self.partner, 40)
        loan = self._create_loan()
        loan.action_submit()
        self.assertEqual(loan.state, 'submitted')

    # -- Second crédit --

    def test_second_loan_blocked_when_not_allowed(self):
        self.product.allow_second_loan = False
        self._activate_loan()
        second = self._create_loan()
        with self.assertRaises(UserError):
            second.action_submit()

    def test_second_loan_allowed_when_flag_true_and_no_arrears(self):
        self.product.allow_second_loan = True
        self.product.block_second_if_arrears = True
        self._activate_loan()
        second = self._create_loan()
        second.action_submit()
        self.assertEqual(second.state, 'submitted')

    def test_second_loan_blocked_when_first_has_arrears(self):
        self.product.allow_second_loan = True
        self.product.block_second_if_arrears = True
        first = self._activate_loan()
        first_installment = first.installment_ids.sorted('sequence')[0]
        first_installment.due_date = fields.Date.subtract(fields.Date.context_today(first), days=5)
        self.assertEqual(first.overdue_installment_count, 1)
        second = self._create_loan()
        with self.assertRaises(UserError):
            second.action_submit()

    def test_second_loan_allowed_despite_arrears_when_flag_false(self):
        self.product.allow_second_loan = True
        self.product.block_second_if_arrears = False
        first = self._activate_loan()
        first_installment = first.installment_ids.sorted('sequence')[0]
        first_installment.due_date = fields.Date.subtract(fields.Date.context_today(first), days=5)
        second = self._create_loan()
        second.action_submit()
        self.assertEqual(second.state, 'submitted')

    # -- Co-emprunteur --

    def test_co_borrower_with_active_loan_blocks(self):
        co_borrower = self.env['res.partner'].create({'name': 'Co-emprunteur actif'})
        self._activate_loan(partner_id=co_borrower.id)
        loan = self._create_loan(co_borrower_id=co_borrower.id)
        with self.assertRaises(UserError):
            loan.action_submit()

    def test_co_borrower_without_active_loan_allows(self):
        co_borrower = self.env['res.partner'].create({'name': 'Co-emprunteur libre'})
        loan = self._create_loan(co_borrower_id=co_borrower.id)
        loan.action_submit()
        self.assertEqual(loan.state, 'submitted')
