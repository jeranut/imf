# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError

from .common import SavingsCommon


class TestAutoDebit(SavingsCommon):

    def _loan_with_overdue_installment(self, partner_id=None, **product_kwargs):
        self.product.write({
            'allow_savings_auto_debit': True,
            'auto_debit_grace_days': 0,
            **product_kwargs,
        })
        loan = self._activate_loan(loan_amount=900.0, term=3, partner_id=partner_id or self.partner.id)
        first = loan.installment_ids.sorted('sequence')[0]
        first.write({'due_date': fields.Date.today() - timedelta(days=10)})
        return loan, first

    def test_auto_debit_nominal_full_amount(self):
        loan, first = self._loan_with_overdue_installment()
        account = self._create_active_account(opening_amount=500.0)
        loan.savings_account_id = account.id
        overdue_amount = loan.overdue_amount
        result = loan._process_savings_auto_debit()
        self.assertTrue(result)
        self.assertEqual(account.balance, 500.0 - overdue_amount)
        payment = loan.payment_ids.filtered(lambda p: p.payment_origin == 'savings_auto_debit')
        self.assertEqual(len(payment), 1)
        self.assertEqual(payment.amount, overdue_amount)
        auto_debit_txn = account.transaction_ids.filtered(lambda t: t.transaction_type == 'auto_debit')
        self.assertEqual(auto_debit_txn.related_loan_payment_id, payment)

    def test_auto_debit_partial_when_balance_insufficient(self):
        loan, first = self._loan_with_overdue_installment()
        overdue_amount = loan.overdue_amount
        # solde minimum du produit épargne = 50 (commun de test) : ne laisse que peu de marge.
        small_balance = 50.0 + overdue_amount / 2.0
        account = self._create_active_account(opening_amount=small_balance)
        loan.savings_account_id = account.id
        result = loan._process_savings_auto_debit()
        self.assertTrue(result)
        payment = loan.payment_ids.filtered(lambda p: p.payment_origin == 'savings_auto_debit')
        self.assertAlmostEqual(payment.amount, small_balance - 50.0, places=2)
        self.assertLess(payment.amount, overdue_amount)
        first.invalidate_recordset()
        self.assertIn(first.state, ('partial', 'overdue'))

    def test_auto_debit_zero_balance_logs_and_does_not_raise(self):
        loan, first = self._loan_with_overdue_installment()
        account = self._create_active_account(opening_amount=50.0)  # == min_balance : rien de prélevable
        loan.savings_account_id = account.id
        result = loan._process_savings_auto_debit()
        self.assertFalse(result)
        self.assertFalse(loan.payment_ids.filtered(lambda p: p.payment_origin == 'savings_auto_debit'))
        self.assertIn('insuffisant', loan.message_ids[0].body)

    def test_auto_debit_bypass_minimum_balance(self):
        loan, first = self._loan_with_overdue_installment(auto_debit_respect_minimum_balance=False)
        account = self._create_active_account(opening_amount=30.0)  # sous le solde minimum (50)
        loan.savings_account_id = account.id
        loan._process_savings_auto_debit()
        self.assertLess(account.balance, 50.0)  # solde vidé sous le minimum, dérogation active

    def test_cron_isolates_failures_across_loans(self):
        # Deux clients distincts : _check_eligibility interdit à un même client d'avoir deux
        # crédits actifs en arriérés simultanément (allow_second_loan non activé sur le produit
        # de test), ce qui n'a rien à voir avec ce que ce test vérifie (l'isolation des échecs
        # entre crédits par le cron).
        other_partner = self.env['res.partner'].create({'name': 'Client Test Microfinance 2'})
        # Pas de journal de retrait du tout (plutôt qu'un journal sans compte par défaut) : Odoo
        # provisionne automatiquement un default_account_id pour tout journal de type cash/bank à
        # la création, donc un journal "cassé" de cette façon ne casse en réalité rien.
        broken_product = self.savings_product.copy({'code': 'SAVBRK', 'withdrawal_journal_id': False})

        loan_broken, first_broken = self._loan_with_overdue_installment()
        broken_account = self._create_account(product_id=broken_product.id)
        broken_account._create_transaction('deposit', 500.0)
        broken_account.action_activate()
        loan_broken.savings_account_id = broken_account.id

        loan_ok, first_ok = self._loan_with_overdue_installment(partner_id=other_partner.id)
        ok_account = self._create_active_account(opening_amount=500.0, partner_id=other_partner.id)
        loan_ok.savings_account_id = ok_account.id

        self.env['microfinance.loan'].cron_process_savings_auto_debit()

        self.assertTrue(loan_ok.payment_ids.filtered(lambda p: p.payment_origin == 'savings_auto_debit'))
        self.assertFalse(loan_broken.payment_ids.filtered(lambda p: p.payment_origin == 'savings_auto_debit'))

    def test_multi_company_savings_account_isolation(self):
        other_company = self.env['res.company'].create({'name': 'Autre société test', 'agency_code': 'ZC'})
        other_account = self._create_account(company_id=other_company.id)
        loan = self._create_loan()
        with self.assertRaises(ValidationError):
            loan.savings_account_id = other_account.id
