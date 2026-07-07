# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo.exceptions import UserError, ValidationError

from .common import SavingsCommon


class TestSavingsAccount(SavingsCommon):

    def test_open_activate_deposit_withdraw(self):
        account = self._create_account()
        self.assertEqual(account.state, 'draft')
        account._create_transaction('deposit', 200.0)
        self.assertEqual(account.balance, 200.0)
        account.action_activate()
        self.assertEqual(account.state, 'active')

        account._create_transaction('withdrawal', 50.0)
        self.assertEqual(account.balance, 150.0)

    def test_activation_blocked_below_minimum_opening_amount(self):
        self.savings_product.min_opening_amount = 100.0
        account = self._create_account()
        account._create_transaction('deposit', 50.0)
        with self.assertRaises(UserError):
            account.action_activate()

    def test_withdrawal_blocked_below_minimum_balance(self):
        account = self._create_active_account(opening_amount=100.0)
        # min_balance = 50 sur le produit commun de test : un retrait de 60 ferait descendre le
        # solde à 40, sous le minimum.
        with self.assertRaises(ValidationError):
            account._create_transaction('withdrawal', 60.0)

    def test_withdrawal_at_minimum_balance_allowed(self):
        account = self._create_active_account(opening_amount=100.0)
        account._create_transaction('withdrawal', 50.0)
        self.assertEqual(account.balance, 50.0)

    def test_deposit_blocked_on_closed_account(self):
        account = self._create_active_account(opening_amount=0.0)
        account.action_close()
        self.assertEqual(account.state, 'closed')
        with self.assertRaises(UserError):
            account._create_transaction('deposit', 10.0)

    def test_deposit_accounting_entry(self):
        account = self._create_active_account(opening_amount=0.0)
        txn = account._create_transaction('deposit', 100.0)
        self.assertEqual(txn.state, 'posted')
        debit_lines = txn.move_id.line_ids.filtered(lambda l: l.debit > 0)
        credit_lines = txn.move_id.line_ids.filtered(lambda l: l.credit > 0)
        self.assertEqual(debit_lines.account_id, self.bank_account)
        self.assertEqual(credit_lines.account_id, self.savings_deposit_account)
        self.assertEqual(debit_lines.debit, 100.0)

    def test_withdrawal_accounting_entry(self):
        account = self._create_active_account(opening_amount=200.0)
        txn = account._create_transaction('withdrawal', 50.0)
        debit_lines = txn.move_id.line_ids.filtered(lambda l: l.debit > 0)
        credit_lines = txn.move_id.line_ids.filtered(lambda l: l.credit > 0)
        self.assertEqual(debit_lines.account_id, self.savings_deposit_account)
        self.assertEqual(credit_lines.account_id, self.bank_account)

    def test_interest_credit_accounting_entry(self):
        account = self._create_active_account(opening_amount=1000.0)
        txn = account._create_transaction('interest_credit', 5.0)
        debit_lines = txn.move_id.line_ids.filtered(lambda l: l.debit > 0)
        credit_lines = txn.move_id.line_ids.filtered(lambda l: l.credit > 0)
        self.assertEqual(debit_lines.account_id, self.savings_interest_account)
        self.assertEqual(credit_lines.account_id, self.savings_deposit_account)
        self.assertEqual(account.balance, 1005.0)

    def test_fee_debit_accounting_entry(self):
        account = self._create_active_account(opening_amount=1000.0)
        txn = account._create_transaction('fee_debit', 10.0)
        debit_lines = txn.move_id.line_ids.filtered(lambda l: l.debit > 0)
        credit_lines = txn.move_id.line_ids.filtered(lambda l: l.credit > 0)
        self.assertEqual(debit_lines.account_id, self.savings_deposit_account)
        self.assertEqual(credit_lines.account_id, self.savings_fee_account)
        self.assertEqual(account.balance, 990.0)

    def test_dormancy_detection(self):
        account = self._create_active_account(opening_amount=100.0)
        old_date = account.opening_date - timedelta(days=400)
        account.transaction_ids.write({'date': old_date})
        account.write({'opening_date': old_date})
        account.invalidate_recordset()
        self.assertTrue(account.is_dormant)
        self.env['microfinance.savings.account'].cron_detect_dormant_accounts()
        self.assertEqual(account.state, 'dormant')
