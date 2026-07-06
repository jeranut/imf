# -*- coding: utf-8 -*-
from odoo import fields
from odoo.exceptions import UserError

from .common import MicrofinanceCommon


class TestPaymentCancel(MicrofinanceCommon):

    def _make_payment(self, loan, amount):
        payment = self.env['microfinance.loan.payment'].create({
            'loan_id': loan.id,
            'amount': amount,
            'journal_id': self.payment_journal.id,
        })
        payment.action_post()
        return payment

    def test_cancel_partial_payment_restores_installment_amounts(self):
        loan = self._activate_loan(loan_amount=900.0, term=3)
        first = loan.installment_ids.sorted('sequence')[0]
        partial_amount = first.total_amount / 2.0
        payment = self._make_payment(loan, partial_amount)
        self.assertEqual(first.state, 'partial')
        self.assertGreater(first.paid_principal + first.paid_interest, 0.0)

        payment.action_cancel(reason='Erreur de saisie')

        self.assertEqual(payment.state, 'cancelled')
        self.assertTrue(payment.reversal_move_id)
        self.assertEqual(payment.reversal_move_id.state, 'posted')
        self.assertEqual(first.paid_principal, 0.0)
        self.assertEqual(first.paid_interest, 0.0)
        self.assertEqual(first.paid_penalty, 0.0)
        self.assertIn(first.state, ('pending', 'overdue'))

    def test_cancel_payment_that_closed_loan_reopens_it(self):
        loan = self._activate_loan(loan_amount=300.0, term=1)
        installment = loan.installment_ids[0]
        payment = self._make_payment(loan, installment.total_amount)
        self.assertEqual(loan.state, 'closed')

        payment.action_cancel(reason='Chèque rejeté')

        self.assertEqual(loan.state, 'active')
        self.assertEqual(payment.state, 'cancelled')
        self.assertEqual(installment.residual_amount, installment.total_amount)

    def test_cancel_blocked_by_locked_period(self):
        loan = self._activate_loan(loan_amount=600.0, term=2)
        first = loan.installment_ids.sorted('sequence')[0]
        payment = self._make_payment(loan, first.total_amount)
        move_date = payment.move_id.date

        # Bypass the ORM write() validation on res.company (base_accounting_kit checks the
        # whole company for unposted entries before allowing a lock date change at all, which
        # is unrelated to what this test is exercising): set the lock date directly.
        self.env.cr.execute(
            'UPDATE res_company SET fiscalyear_lock_date = %s WHERE id = %s',
            (move_date, self.env.company.id),
        )
        self.env.company.invalidate_recordset(['fiscalyear_lock_date'])

        with self.assertRaises(UserError):
            payment.action_cancel(reason='Tentative bloquée')

        # No reversal attempted: payment stays posted, no reversal move created.
        self.assertEqual(payment.state, 'posted')
        self.assertFalse(payment.reversal_move_id)

    def test_cancel_wizard_requires_reason(self):
        loan = self._activate_loan(loan_amount=400.0, term=2)
        first = loan.installment_ids.sorted('sequence')[0]
        payment = self._make_payment(loan, first.total_amount / 2.0)
        # The field itself is required=True (blank rejected before reaching the DB); a
        # whitespace-only reason passes that but must still be rejected by action_confirm().
        wizard = self.env['microfinance.loan.payment.cancel.wizard'].create({'payment_id': payment.id, 'reason': '   '})
        with self.assertRaises(UserError):
            wizard.action_confirm()
