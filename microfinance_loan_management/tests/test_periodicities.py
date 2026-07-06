# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from .common import MicrofinanceCommon


class TestPeriodicities(MicrofinanceCommon):

    def _schedule_for(self, frequency, **kwargs):
        self.product.repayment_frequency = frequency
        loan = self._create_loan(**kwargs)
        loan.action_generate_schedule()
        return loan.installment_ids.sorted('sequence')

    def test_biweekly_schedule_dates(self):
        installments = self._schedule_for('biweekly', term=3)
        start = installments[0].loan_id.application_date
        for idx, inst in enumerate(installments, start=1):
            self.assertEqual(inst.due_date, start + relativedelta(days=15 * idx))

    def test_four_weekly_schedule_dates(self):
        installments = self._schedule_for('four_weekly', term=3)
        start = installments[0].loan_id.application_date
        for idx, inst in enumerate(installments, start=1):
            self.assertEqual(inst.due_date, start + relativedelta(days=28 * idx))

    def test_bimonthly_schedule_dates(self):
        installments = self._schedule_for('bimonthly', term=3)
        start = installments[0].loan_id.application_date
        for idx, inst in enumerate(installments, start=1):
            self.assertEqual(inst.due_date, start + relativedelta(months=2 * idx))

    def test_four_monthly_schedule_dates(self):
        installments = self._schedule_for('four_monthly', term=3)
        start = installments[0].loan_id.application_date
        for idx, inst in enumerate(installments, start=1):
            self.assertEqual(inst.due_date, start + relativedelta(months=4 * idx))

    def test_quarterly_schedule_dates_and_interest(self):
        installments = self._schedule_for('quarterly', term=4, loan_amount=1200.0)
        start = installments[0].loan_id.application_date
        for idx, inst in enumerate(installments, start=1):
            self.assertEqual(inst.due_date, start + relativedelta(months=3 * idx))
        # Flat method: annual rate (12%) prorated to a quarter (3/12) on the full loan amount.
        expected_interest = 1200.0 * 0.12 * (3 / 12.0)
        for inst in installments:
            self.assertAlmostEqual(inst.interest_amount, expected_interest, places=2)

    def test_semiannual_schedule_dates_and_interest(self):
        installments = self._schedule_for('semiannual', term=2, loan_amount=1200.0)
        start = installments[0].loan_id.application_date
        for idx, inst in enumerate(installments, start=1):
            self.assertEqual(inst.due_date, start + relativedelta(months=6 * idx))
        expected_interest = 1200.0 * 0.12 * (6 / 12.0)
        for inst in installments:
            self.assertAlmostEqual(inst.interest_amount, expected_interest, places=2)

    def test_annual_schedule_dates_and_interest(self):
        installments = self._schedule_for('annual', term=2, loan_amount=1000.0)
        start = installments[0].loan_id.application_date
        for idx, inst in enumerate(installments, start=1):
            self.assertEqual(inst.due_date, start + relativedelta(years=idx))
        # A full year at the 12% annual rate: no proration needed.
        expected_interest = 1000.0 * 0.12
        for inst in installments:
            self.assertAlmostEqual(inst.interest_amount, expected_interest, places=2)

    def test_reducing_balance_quarterly_declines(self):
        self.product.interest_method = 'reducing'
        installments = self._schedule_for('quarterly', term=3, loan_amount=900.0)
        # Reducing balance: interest computed on the declining principal, strictly decreasing.
        amounts = installments.mapped('interest_amount')
        self.assertGreater(amounts[0], amounts[1])
        self.assertGreater(amounts[1], amounts[2])
