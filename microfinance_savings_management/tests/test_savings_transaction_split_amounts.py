# -*- coding: utf-8 -*-
"""Colonnes Dépôt / Retrait séparées sur la liste des transactions du compte épargne :
deposit_amount = montant si crédit du compte (CREDIT_TYPES : deposit + interest_credit),
withdrawal_amount = montant si débit (DEBIT_TYPES : withdrawal + fee_debit + auto_debit +
transfer), 0 dans l'autre colonne. Champs calculés stockés (sommes en pied de liste).
N'affectent pas le calcul du solde."""
from .common import SavingsCommon


class TestSavingsTransactionSplitAmounts(SavingsCommon):

    def _txn(self, account, ttype, amount, **extra):
        vals = {'account_id': account.id, 'transaction_type': ttype, 'amount': amount}
        vals.update(extra)
        return self.env['microfinance.savings.transaction'].create(vals)

    def test_deposit_and_interest_credit_populate_deposit_column_only(self):
        account = self._create_active_account(opening_amount=500.0)
        for ttype in ('deposit', 'interest_credit'):
            txn = self._txn(account, ttype, 120.0)
            self.assertEqual(txn.deposit_amount, 120.0, ttype)
            self.assertEqual(txn.withdrawal_amount, 0.0, ttype)

    def test_debit_types_populate_withdrawal_column_only(self):
        account = self._create_active_account(opening_amount=500.0)
        for ttype in ('withdrawal', 'fee_debit', 'auto_debit', 'transfer'):
            txn = self._txn(account, ttype, 10.0, bypass_min_balance=True)
            self.assertEqual(txn.deposit_amount, 0.0, ttype)
            self.assertEqual(txn.withdrawal_amount, 10.0, ttype)

    def test_recomputes_on_type_change(self):
        account = self._create_active_account(opening_amount=500.0)
        txn = self._txn(account, 'deposit', 50.0)
        self.assertEqual(txn.withdrawal_amount, 0.0)
        txn.write({'transaction_type': 'withdrawal', 'bypass_min_balance': True})
        self.assertEqual(txn.deposit_amount, 0.0)
        self.assertEqual(txn.withdrawal_amount, 50.0)

    def test_balance_unchanged_by_split_fields(self):
        account = self._create_active_account(opening_amount=200.0)
        balance_before = account.balance
        account._create_transaction('deposit', 30.0)
        self.assertAlmostEqual(account.balance, balance_before + 30.0, places=2)

    def test_get_account_transactions_payload_and_order(self):
        account = self._create_active_account(opening_amount=200.0)
        account._create_transaction('deposit', 40.0)
        account._create_transaction('withdrawal', 10.0, bypass_min_balance=True)

        rows = self.env['microfinance.savings.account'].get_account_transactions(
            account.id, self.env.company.id)

        self.assertEqual(len(rows), 3)
        # Tri par date décroissante (départage par id décroissant à date égale).
        self.assertEqual([r['id'] for r in rows], sorted((r['id'] for r in rows), reverse=True))
        keys = set(rows[0])
        self.assertEqual(
            keys, {'id', 'date', 'deposit_amount', 'withdrawal_amount', 'payment_method', 'payment_method_label'})
        deposits = [r for r in rows if r['deposit_amount']]
        withdrawals = [r for r in rows if r['withdrawal_amount']]
        self.assertEqual(len(deposits), 2)
        self.assertEqual(len(withdrawals), 1)
        self.assertTrue(all(r['payment_method_label'] for r in rows))

    def test_get_account_transactions_company_mismatch_returns_empty(self):
        account = self._create_active_account(opening_amount=200.0)
        other = self.env['res.company'].create({'name': 'Autre agence txn (test)', 'agency_code': 'ZT9'})
        self.assertEqual(
            self.env['microfinance.savings.account'].get_account_transactions(account.id, other.id), [])
        self.assertEqual(
            self.env['microfinance.savings.account'].get_account_transactions(0, self.env.company.id), [])
