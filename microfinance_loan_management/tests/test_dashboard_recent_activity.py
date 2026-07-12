# -*- coding: utf-8 -*-
from odoo import fields

from .common import MicrofinanceCommon


class TestDashboardRecentActivity(MicrofinanceCommon):

    def test_get_recent_loans_limits_and_orders_and_scopes_by_company(self):
        loans = [self._activate_loan(term=2) for _ in range(7)]
        other_company = self.env['res.company'].create({'name': 'Société sans prêts récents (test)'})

        recent = self.env['microfinance.loan'].get_recent_loans(self.env.company.id, limit=5)
        expected_ids = sorted((loan.id for loan in loans), reverse=True)[:5]

        self.assertEqual(len(recent), 5)
        self.assertEqual(recent.ids, expected_ids)

        recent_other_company = self.env['microfinance.loan'].get_recent_loans(other_company.id, limit=5)
        self.assertFalse(recent_other_company)

    def test_get_due_today_filters_date_and_excludes_paid_and_scopes_company(self):
        loan = self._activate_loan(term=3)
        today = fields.Date.context_today(loan)
        first, second, third = loan.installment_ids.sorted('sequence')[:3]
        first.due_date = today
        second.due_date = today
        third.due_date = fields.Date.add(today, days=30)

        payment = self.env['microfinance.loan.payment'].create({
            'loan_id': loan.id,
            'amount': first.total_amount,
            'payment_date': today,
            'journal_id': self.payment_journal.id,
        })
        payment.action_post()
        self.assertEqual(first.state, 'paid')

        due_today = self.env['microfinance.loan.installment'].get_due_today(self.env.company.id)

        self.assertIn(second, due_today)
        self.assertNotIn(first, due_today, 'Une échéance déjà soldée ne doit pas apparaître dans les échéances du jour')
        self.assertNotIn(third, due_today)

        other_company = self.env['res.company'].create({'name': 'Société sans échéances du jour (test)'})
        self.assertFalse(self.env['microfinance.loan.installment'].get_due_today(other_company.id))
