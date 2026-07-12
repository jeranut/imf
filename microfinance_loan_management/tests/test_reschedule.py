# -*- coding: utf-8 -*-
from odoo import fields
from odoo.exceptions import UserError

from .common import MicrofinanceCommon


class TestReschedule(MicrofinanceCommon):

    def _make_active_loan(self, **kwargs):
        loan = self._create_loan(**kwargs)
        loan.action_generate_schedule()
        loan.action_submit()
        loan.action_manager_validate()
        loan.action_finance_validate()
        loan.action_approve()
        loan.action_disburse()
        return loan

    def test_reschedule_not_allowed_when_not_active(self):
        loan = self._create_loan(term=3)
        loan.action_generate_schedule()
        with self.assertRaises(UserError):
            loan.action_reschedule()

    def test_reschedule_recomputes_unpaid_installments_only(self):
        loan = self._make_active_loan(loan_amount=1200.0, term=3)
        installments = loan.installment_ids.sorted('sequence')
        first = installments[0]
        # Fully pay the first installment.
        payment = self.env['microfinance.loan.payment'].create({
            'loan_id': loan.id,
            'amount': first.total_amount,
            'journal_id': self.payment_journal.id,
        })
        payment.action_post()
        self.assertEqual(first.state, 'paid')

        old_paid_principal = first.paid_principal
        wizard = self.env['microfinance.loan.reschedule.wizard'].create({
            'loan_id': loan.id,
            'new_term': 4,
        })
        wizard.action_apply()

        # Paid installment untouched.
        self.assertEqual(first.state, 'paid')
        self.assertEqual(first.paid_principal, old_paid_principal)

        remaining = loan.installment_ids.filtered(lambda inst: inst.state != 'paid')
        self.assertEqual(len(remaining), 4)
        self.assertEqual(loan.reschedule_count, 1)
        self.assertAlmostEqual(sum(remaining.mapped('principal_amount')), loan.loan_amount - first.principal_amount, places=2)

    def test_reschedule_with_new_first_due_date(self):
        loan = self._make_active_loan(loan_amount=900.0, term=3)
        new_date = fields.Date.add(fields.Date.context_today(loan), months=2)
        wizard = self.env['microfinance.loan.reschedule.wizard'].create({
            'loan_id': loan.id,
            'new_first_due_date': new_date,
        })
        wizard.action_apply()
        remaining = loan.installment_ids.filtered(lambda inst: inst.state != 'paid').sorted('sequence')
        self.assertEqual(remaining[0].due_date, new_date)

    def test_reschedule_carries_overdue_interest_in_dedicated_line(self):
        loan = self._make_active_loan(loan_amount=900.0, term=3)
        first = loan.installment_ids.sorted('sequence')[0]
        first.due_date = fields.Date.subtract(fields.Date.context_today(loan), days=5)
        self.assertEqual(first.state, 'overdue')
        overdue_interest = first.interest_amount

        wizard = self.env['microfinance.loan.reschedule.wizard'].create({
            'loan_id': loan.id,
            'new_term': 2,
        })
        wizard.action_apply()

        remaining = loan.installment_ids.filtered(lambda inst: inst.state != 'paid').sorted('sequence')
        carried_line = remaining[0]
        self.assertEqual(carried_line.principal_amount, 0.0)
        self.assertAlmostEqual(carried_line.interest_amount, overdue_interest, places=2)
        # 1 carried-interest line + 2 new principal installments.
        self.assertEqual(len(remaining), 3)

    def test_reschedule_requires_some_input(self):
        loan = self._make_active_loan(term=2)
        wizard = self.env['microfinance.loan.reschedule.wizard'].create({'loan_id': loan.id})
        with self.assertRaises(UserError):
            wizard.action_apply()
