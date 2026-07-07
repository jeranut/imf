# -*- coding: utf-8 -*-
from odoo.exceptions import UserError

from .common import SavingsCommon


class TestProgressiveEligibility(SavingsCommon):

    def test_first_loan_disbursable_without_savings(self):
        # Produit commun de test : savings_requirement_type = 'none' par défaut.
        loan = self._activate_loan(loan_amount=500.0, term=3)
        self.assertEqual(loan.state, 'active')

    def test_second_loan_blocked_until_target_reached(self):
        self.product.write({'savings_requirement_type': 'target_during_loan', 'savings_target_ratio': 20.0})
        first_loan = self._activate_loan(loan_amount=500.0, term=3)
        account = self._create_active_account(opening_amount=0.0)
        first_loan.savings_account_id = account.id
        self.assertEqual(first_loan.savings_target_amount, 100.0)
        self.assertFalse(first_loan.savings_target_reached)

        second_loan = self._create_loan(loan_amount=800.0, term=6)
        with self.assertRaises(UserError) as ctx:
            second_loan.action_submit()
        self.assertIn('100.00', str(ctx.exception))

        account._create_transaction('deposit', 100.0)
        self.assertTrue(first_loan.savings_target_reached)
        second_loan.action_submit()  # ne lève plus d'exception
        self.assertEqual(second_loan.state, 'submitted')

    def test_no_block_for_first_loan_of_none_type(self):
        # Le produit reste en 'none' : même en présence d'un crédit précédent, aucun blocage
        # puisque celui-ci n'imposait pas de cible d'épargne pendant le remboursement.
        self._activate_loan(loan_amount=500.0, term=3)
        second_loan = self._create_loan(loan_amount=600.0, term=3)
        second_loan.action_submit()
        self.assertEqual(second_loan.state, 'submitted')
