# -*- coding: utf-8 -*-
from .common import MicrofinanceCommon


class TestRescheduleHistory(MicrofinanceCommon):
    """action_reschedule() used to only keep a text summary of the dropped schedule in the
    chatter. It now also snapshots it into a queryable microfinance.loan.reschedule.history
    record (with structured history lines), created before the installments are mutated."""

    def test_reschedule_creates_structured_history_before_mutating_schedule(self):
        loan = self._activate_loan(loan_amount=1200.0, term=3)
        # _reschedule_installments() unlinks the pending installments below, so the amount
        # to compare against must be captured now, before the wizard runs.
        original_principal_total = sum(loan.installment_ids.sorted('sequence').mapped('principal_amount'))

        wizard = self.env['microfinance.loan.reschedule.wizard'].create({
            'loan_id': loan.id,
            'new_term': 4,
            'reason': 'Difficultés temporaires du client',
        })
        wizard.action_apply()

        self.assertEqual(len(loan.reschedule_history_ids), 1)
        history = loan.reschedule_history_ids[0]
        self.assertEqual(history.reason, 'Difficultés temporaires du client')
        self.assertEqual(len(history.old_installment_ids), 3)
        self.assertAlmostEqual(
            sum(history.old_installment_ids.mapped('principal_amount')),
            original_principal_total,
            places=2,
        )

    def test_two_successive_reschedules_keep_separate_history_snapshots(self):
        loan = self._activate_loan(loan_amount=1200.0, term=3)

        wizard1 = self.env['microfinance.loan.reschedule.wizard'].create({
            'loan_id': loan.id,
            'new_term': 4,
            'reason': 'Premier rééchelonnement',
        })
        wizard1.action_apply()
        schedule_after_first = loan.installment_ids.filtered(lambda inst: inst.state != 'paid').sorted('sequence')
        principal_after_first = sum(schedule_after_first.mapped('principal_amount'))

        wizard2 = self.env['microfinance.loan.reschedule.wizard'].create({
            'loan_id': loan.id,
            'new_term': 6,
            'reason': 'Second rééchelonnement',
        })
        wizard2.action_apply()

        self.assertEqual(len(loan.reschedule_history_ids), 2)
        first_history, second_history = loan.reschedule_history_ids.sorted('id')

        self.assertEqual(first_history.reason, 'Premier rééchelonnement')
        self.assertEqual(second_history.reason, 'Second rééchelonnement')

        # The first snapshot must still reflect the original 3-installment schedule: it must
        # not have been overwritten by the second reschedule.
        self.assertEqual(len(first_history.old_installment_ids), 3)
        # The second snapshot reflects the schedule as it stood right after the first
        # reschedule (4 remaining installments) — kept separate from the first snapshot.
        self.assertEqual(len(second_history.old_installment_ids), 4)
        self.assertAlmostEqual(
            sum(second_history.old_installment_ids.mapped('principal_amount')),
            principal_after_first,
            places=2,
        )
