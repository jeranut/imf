# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.tests import Form

from .common import MicrofinanceCommon


class TestPaymentPrefill(MicrofinanceCommon):

    def test_wizard_prefills_amount_and_journal_from_loan(self):
        loan = self._activate_loan(loan_amount=900.0, term=3)
        first = loan.installment_ids.sorted('sequence')[0]
        with Form(self.env['microfinance.loan.payment.wizard'].with_context(default_loan_id=loan.id)) as wizard_form:
            pass
        wizard = wizard_form.save()
        self.assertEqual(wizard.journal_id, self.product.payment_journal_id)
        self.assertAlmostEqual(wizard.amount, first.total_amount, places=2)

    def test_wizard_amount_still_manually_editable(self):
        loan = self._activate_loan(loan_amount=900.0, term=3)
        with Form(self.env['microfinance.loan.payment.wizard'].with_context(default_loan_id=loan.id)) as wizard_form:
            wizard_form.amount = 42.0
        wizard = wizard_form.save()
        self.assertEqual(wizard.amount, 42.0)

    def test_payment_form_prefills_from_loan_id_onchange(self):
        # Le menu direct "Remboursements" (formulaire microfinance.loan.payment, pas le wizard)
        # doit aussi bénéficier du préremplissage, via son propre onchange sur loan_id.
        loan = self._activate_loan(loan_amount=900.0, term=3)
        first = loan.installment_ids.sorted('sequence')[0]
        with Form(self.env['microfinance.loan.payment']) as payment_form:
            payment_form.loan_id = loan
        payment = payment_form.save()
        self.assertEqual(payment.journal_id, self.product.payment_journal_id)
        self.assertAlmostEqual(payment.amount, first.total_amount, places=2)

    def test_prefill_sums_overdue_installments_rather_than_next_due(self):
        loan = self._activate_loan(loan_amount=900.0, term=3)
        installments = loan.installment_ids.sorted('sequence')
        installments[0].due_date = fields.Date.today() - timedelta(days=10)
        installments[1].due_date = fields.Date.today() - timedelta(days=5)
        self.assertEqual(installments[0].state, 'overdue')
        self.assertEqual(installments[1].state, 'overdue')
        expected = installments[0].residual_amount + installments[1].residual_amount
        with Form(self.env['microfinance.loan.payment.wizard'].with_context(default_loan_id=loan.id)) as wizard_form:
            pass
        wizard = wizard_form.save()
        self.assertAlmostEqual(wizard.amount, expected, places=2)
