# -*- coding: utf-8 -*-
from odoo.exceptions import UserError

from .common import SavingsCommon


class TestSavingsClosure(SavingsCommon):

    def test_closure_generates_full_withdrawal_transaction(self):
        account = self._create_active_account(opening_amount=150.0)
        account.action_close()
        self.assertEqual(account.state, 'closed')
        self.assertEqual(account.balance, 0.0)
        withdrawal = account.transaction_ids.filtered(lambda t: t.transaction_type == 'withdrawal')
        self.assertTrue(withdrawal)
        self.assertEqual(withdrawal.amount, 150.0)

    def test_closure_blocked_when_linked_to_active_compulsory_loan(self):
        compulsory_product = self.env['microfinance.savings.product'].create({
            'name': 'Épargne obligatoire test', 'code': 'SAVCOMP', 'product_type': 'compulsory',
            'account_epargne_individuel_id': self.savings_deposit_account.id,
            'account_epargne_groupe_id': self.savings_deposit_account_groupe.id,
            'account_epargne_entreprise_id': self.savings_deposit_account_entreprise.id,
            'account_interet_paye_individuel_id': self.savings_interest_account.id,
            'deposit_journal_id': self.savings_deposit_journal.id,
            'withdrawal_journal_id': self.savings_withdrawal_journal.id,
        })
        account = self._create_account(product_id=compulsory_product.id)
        account._create_transaction('deposit', 100.0)
        account.action_activate()
        loan = self._activate_loan()
        account.microfinance_loan_id = loan.id
        with self.assertRaises(UserError):
            account.action_close()

    def test_closure_allowed_once_loan_closed(self):
        compulsory_product = self.env['microfinance.savings.product'].create({
            'name': 'Épargne obligatoire test 2', 'code': 'SAVCOMP2', 'product_type': 'compulsory',
            'account_epargne_individuel_id': self.savings_deposit_account.id,
            'account_epargne_groupe_id': self.savings_deposit_account_groupe.id,
            'account_epargne_entreprise_id': self.savings_deposit_account_entreprise.id,
            'account_interet_paye_individuel_id': self.savings_interest_account.id,
            'deposit_journal_id': self.savings_deposit_journal.id,
            'withdrawal_journal_id': self.savings_withdrawal_journal.id,
        })
        account = self._create_account(product_id=compulsory_product.id)
        account._create_transaction('deposit', 100.0)
        account.action_activate()
        loan = self._activate_loan(loan_amount=100.0, term=1)
        account.microfinance_loan_id = loan.id
        payment = self.env['microfinance.loan.payment'].create({
            'loan_id': loan.id, 'amount': loan.balance_total, 'journal_id': self.payment_journal.id,
        })
        payment.action_post()
        self.assertEqual(loan.state, 'closed')
        account.action_close()
        self.assertEqual(account.state, 'closed')
