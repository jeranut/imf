# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import fields

from .common import MicrofinanceCommon


class TestGracePeriod(MicrofinanceCommon):

    def test_schedule_without_grace_period(self):
        loan = self._create_loan(term=3)
        loan.action_generate_schedule()
        start = loan.application_date
        first = loan.installment_ids.sorted('sequence')[0]
        self.assertEqual(first.due_date, start + relativedelta(months=1))
        self.assertEqual(len(loan.installment_ids), 3)

    def test_first_installment_after_short_grace_period(self):
        self.product.grace_period_days = 10
        loan = self._create_loan(term=3)
        loan.action_generate_schedule()
        start = loan.application_date
        installments = loan.installment_ids.sorted('sequence')
        first = installments[0]
        self.assertGreater(first.due_date, fields.Date.add(start, days=10) - relativedelta(days=1))
        self.assertEqual(first.due_date, fields.Date.add(start, days=10) + relativedelta(months=1))
        # Grace period shorter than one repayment period: no dedicated interest bucket.
        self.assertEqual(len(installments), 3)
        self.assertEqual(first.principal_amount, loan.loan_amount / loan.term)

    def test_grace_period_longer_than_period_creates_dedicated_installment(self):
        self.product.grace_period_days = 45
        loan = self._create_loan(term=3)
        loan.action_generate_schedule()
        start = loan.application_date
        installments = loan.installment_ids.sorted('sequence')
        # An extra installment captures the interest accrued during the grace period.
        self.assertEqual(len(installments), 4)
        grace_installment = installments[0]
        self.assertEqual(grace_installment.principal_amount, 0.0)
        self.assertGreater(grace_installment.interest_amount, 0.0)
        schedule_start = fields.Date.add(start, days=45)
        self.assertEqual(grace_installment.due_date, schedule_start)
        first_normal = installments[1]
        self.assertEqual(first_normal.due_date, schedule_start + relativedelta(months=1))
        self.assertGreater(first_normal.due_date, start + relativedelta(days=45))
        self.assertEqual(first_normal.principal_amount, loan.loan_amount / loan.term)
