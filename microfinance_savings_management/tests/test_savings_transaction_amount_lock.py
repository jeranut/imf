# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError

from .common import SavingsCommon


class TestSavingsTransactionAmountLock(SavingsCommon):
    """docs_dev/savings_readonly_amount_history_button/ (Lot 1) : amount ne doit plus être
    modifiable une fois qu'une écriture comptable (move_id) existe pour la transaction -
    garde serveur en plus du readonly de vue."""

    def test_amount_locked_once_posted(self):
        account = self._create_active_account(opening_amount=200.0)
        txn = account.transaction_ids[:1]
        self.assertTrue(txn.move_id)
        with self.assertRaises(ValidationError):
            txn.write({'amount': 999.0})

    def test_amount_editable_before_posting(self):
        account = self._create_account()
        txn = self.env['microfinance.savings.transaction'].create({
            'account_id': account.id, 'transaction_type': 'deposit', 'amount': 100.0,
        })
        self.assertFalse(txn.move_id)
        txn.write({'amount': 150.0})
        self.assertEqual(txn.amount, 150.0)

    def test_other_fields_still_editable_once_posted(self):
        """Scope strictement limité à amount (docs_dev AUDIT.md §4) : les autres champs
        restent modifiables une fois postée, la garde ne doit pas déborder."""
        account = self._create_active_account(opening_amount=200.0)
        txn = account.transaction_ids[:1]
        txn.write({'note': 'commentaire ajouté après coup'})
        self.assertEqual(txn.note, 'commentaire ajouté après coup')
