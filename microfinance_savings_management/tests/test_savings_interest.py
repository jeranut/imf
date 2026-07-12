# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields

from .common import SavingsCommon


class TestSavingsInterest(SavingsCommon):

    def _account_with_history(self):
        account = self._create_account()
        account.write({'state': 'active', 'opening_date': fields.Date.today() - timedelta(days=60)})
        account._create_transaction('deposit', 200.0, date=fields.Date.today() - timedelta(days=40))
        account._create_transaction('withdrawal', 50.0, date=fields.Date.today() - timedelta(days=10))
        return account

    def test_min_balance_method(self):
        self.savings_product.balance_method = 'min_balance'
        account = self._account_with_history()
        period_start = fields.Date.today() - timedelta(days=30)
        reference = account._reference_balance(period_start, fields.Date.today())
        self.assertAlmostEqual(reference, 150.0, places=2)

    def test_average_balance_method(self):
        self.savings_product.balance_method = 'average_balance'
        account = self._account_with_history()
        period_start = fields.Date.today() - timedelta(days=30)
        reference = account._reference_balance(period_start, fields.Date.today())
        self.assertAlmostEqual(reference, 183.33, places=1)

    def test_closing_balance_method(self):
        self.savings_product.balance_method = 'closing_balance'
        account = self._account_with_history()
        period_start = fields.Date.today() - timedelta(days=30)
        reference = account._reference_balance(period_start, fields.Date.today())
        self.assertAlmostEqual(reference, 150.0, places=2)

    def test_capitalization_cron_creates_interest_transaction(self):
        self.savings_product.write({'balance_method': 'closing_balance', 'interest_rate': 12.0})
        account = self._account_with_history()
        balance_before = account.balance
        self.env['microfinance.savings.account'].cron_capitalize_interest('monthly')
        interest_txns = account.transaction_ids.filtered(lambda t: t.transaction_type == 'interest_credit')
        self.assertTrue(interest_txns)
        self.assertGreater(account.balance, balance_before)
        self.assertEqual(interest_txns.state, 'posted')
