# -*- coding: utf-8 -*-
from odoo.exceptions import UserError

from .common import SavingsCommon


class TestSavingsChequeWorkflow(SavingsCommon):
    """Compte d'attente chèques + état de compensation (Lot 5), scope limité aux dépôts
    (payment_method='cheque', transaction_type='deposit') — un retrait par chèque n'est pas
    pris en charge par ce mécanisme (voir docs_dev/savings/ecarts_lpf.md)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cheques_attente_account = cls.env['account.account'].create({
            'name': 'Chèques à encaisser test', 'code': 'TCHQ', 'account_type': 'asset_cash', 'company_id': cls.env.company.id,
        })
        cls.savings_product.write({'account_cheques_attente_id': cls.cheques_attente_account.id})

    def test_cheque_deposit_uses_waiting_account_and_sets_en_attente(self):
        account = self._create_active_account(opening_amount=0.0)
        txn = account._create_transaction('deposit', 200.0, payment_method='cheque')
        self.assertEqual(txn.cheque_state, 'en_attente')
        counterpart_line = txn.move_id.line_ids.filtered(lambda l: l.debit > 0)
        self.assertEqual(counterpart_line.account_id, self.cheques_attente_account)
        self.assertEqual(counterpart_line.debit, 200.0)
        self.assertEqual(self.cheques_attente_account.current_balance, 200.0)
        self.assertEqual(self.bank_account.current_balance, 0.0)

    def test_cheque_deposit_requires_waiting_account_configured(self):
        self.savings_product.write({'account_cheques_attente_id': False})
        account = self._create_active_account(opening_amount=0.0)
        with self.assertRaises(UserError):
            account._create_transaction('deposit', 200.0, payment_method='cheque')

    def test_clear_cheque_transfers_to_real_account(self):
        account = self._create_active_account(opening_amount=0.0)
        txn = account._create_transaction('deposit', 200.0, payment_method='cheque')
        txn.action_clear_cheque()
        self.assertEqual(txn.cheque_state, 'compense')
        self.assertTrue(txn.clearing_move_id)
        self.assertEqual(self.cheques_attente_account.current_balance, 0.0)
        self.assertEqual(self.bank_account.current_balance, 200.0)
        # Le solde du compte épargne, lui, ne change pas à la compensation : il a déjà été
        # crédité à la comptabilisation du dépôt (state='posted' dès l'origine).
        self.assertEqual(account.balance, 200.0)

    def test_clear_cheque_blocked_if_not_en_attente(self):
        account = self._create_active_account(opening_amount=0.0)
        txn = account._create_transaction('deposit', 200.0, payment_method='cheque')
        txn.action_clear_cheque()
        with self.assertRaises(UserError):
            txn.action_clear_cheque()

    def test_clear_cheque_blocked_on_non_cheque_transaction(self):
        account = self._create_active_account(opening_amount=200.0)
        txn = account.transaction_ids[:1]
        with self.assertRaises(UserError):
            txn.action_clear_cheque()

    def test_reject_cheque_reverses_move_and_excludes_from_balance(self):
        # min_balance à 0 pour ce test : ici on vérifie la mécanique de contre-passation elle-même,
        # pas l'interaction avec le solde minimum (couverte séparément ci-dessous).
        self.savings_product.write({'min_balance': 0.0})
        account = self._create_active_account(opening_amount=0.0)
        txn = account._create_transaction('deposit', 200.0, payment_method='cheque')
        txn.action_reject_cheque(reason='Provision insuffisante')
        self.assertEqual(txn.cheque_state, 'rejete')
        self.assertEqual(txn.state, 'cancelled')
        self.assertEqual(account.balance, 0.0)
        self.assertEqual(self.cheques_attente_account.current_balance, 0.0)

    def test_reject_cheque_blocked_if_would_go_below_min_balance(self):
        # min_balance=50.0 (fixture SavingsCommon) : dépôt chèque de 200, puis retrait de 100
        # (solde 100, au-dessus du minimum, retrait autorisé). Rejeter le chèque ensuite ferait
        # descendre le solde projeté à -100 (100 - 200), sous le minimum : refusé, car le client
        # a déjà utilisé une partie de ces fonds.
        account = self._create_active_account(opening_amount=0.0)
        txn = account._create_transaction('deposit', 200.0, payment_method='cheque')
        account._create_transaction('withdrawal', 100.0)
        with self.assertRaises(UserError):
            txn.action_reject_cheque()

    def test_cash_deposit_unaffected_by_cheque_workflow(self):
        account = self._create_active_account(opening_amount=0.0)
        txn = account._create_transaction('deposit', 200.0)
        self.assertFalse(txn.cheque_state)
        counterpart_line = txn.move_id.line_ids.filtered(lambda l: l.debit > 0)
        self.assertEqual(counterpart_line.account_id, self.bank_account)
