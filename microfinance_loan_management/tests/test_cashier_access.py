# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError
from odoo.tests import Form

from .common import MicrofinanceCommon


class TestCashierAccess(MicrofinanceCommon):
    """Lot 7 (audit gestion_caisse) : vérifie empiriquement si l'absence d'accès de
    group_microfinance_cashier à microfinance.loan.product casse un flux réel du caissier,
    avant de décider s'il faut modifier ir.model.access.csv."""

    def _cashier_user(self):
        return self.env['res.users'].create({
            'name': 'Caissier accès test', 'login': 'cashier_access_test',
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('microfinance_loan_management.group_microfinance_cashier').id,
            ])],
        })

    def test_cashier_can_prefill_payment_form_from_loan(self):
        loan = self._activate_loan(loan_amount=900.0, term=3)
        cashier = self._cashier_user()
        with Form(self.env['microfinance.loan.payment'].with_user(cashier)) as payment_form:
            payment_form.loan_id = loan
        payment = payment_form.save()
        self.assertEqual(payment.journal_id, self.product.payment_journal_id)
