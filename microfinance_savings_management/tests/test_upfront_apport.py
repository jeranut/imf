# -*- coding: utf-8 -*-
from odoo.exceptions import UserError

from .common import SavingsCommon


class TestUpfrontApport(SavingsCommon):

    def _approve_ready_loan(self, **kwargs):
        loan = self._create_loan(**kwargs)
        loan.action_generate_schedule()
        loan.action_submit()
        loan.action_manager_validate()
        loan.action_finance_validate()
        return loan

    def test_approve_blocked_when_apport_insufficient(self):
        self.product.write({'savings_requirement_type': 'upfront_apport', 'savings_apport_ratio': 20.0})
        loan = self._approve_ready_loan(loan_amount=1000.0, term=3)
        account = self._create_active_account(opening_amount=50.0)
        loan.savings_account_id = account.id
        self.assertEqual(loan.savings_apport_required, 200.0)
        self.assertFalse(loan.savings_apport_verified)
        with self.assertRaises(UserError):
            loan.action_approve()

    def test_approve_allowed_once_apport_covered(self):
        self.product.write({'savings_requirement_type': 'upfront_apport', 'savings_apport_ratio': 20.0})
        loan = self._approve_ready_loan(loan_amount=1000.0, term=3)
        account = self._create_active_account(opening_amount=250.0)
        loan.savings_account_id = account.id
        self.assertTrue(loan.savings_apport_verified)
        loan.action_approve()
        self.assertEqual(loan.state, 'approved')

    def test_combined_target_reached_and_apport_required_are_independent(self):
        # Le premier produit exige une cible pendant le remboursement (palier 1) ; le second, un
        # apport en amont (palier 2). Les deux contrôles doivent s'appliquer indépendamment.
        self.product.write({'savings_requirement_type': 'target_during_loan', 'savings_target_ratio': 20.0})
        first_loan = self._activate_loan(loan_amount=500.0, term=3)
        account = self._create_active_account(opening_amount=100.0)  # atteint la cible (100)
        first_loan.savings_account_id = account.id
        self.assertTrue(first_loan.savings_target_reached)

        apport_product = self.product.copy({
            'code': 'PAPPORT', 'savings_requirement_type': 'upfront_apport', 'savings_apport_ratio': 50.0,
        })
        second_loan = self._create_loan(loan_amount=1000.0, term=6, product_id=apport_product.id)
        # L'éligibilité progressive (cible atteinte sur le 1er prêt) ne bloque pas la soumission...
        second_loan.action_submit()
        second_loan.action_manager_validate()
        second_loan.action_finance_validate()
        # ...mais l'apport du palier 2 reste exigé indépendamment, et le même compte n'a pas assez.
        second_loan.savings_account_id = account.id
        with self.assertRaises(UserError):
            second_loan.action_approve()

        account._create_transaction('deposit', 400.0)  # solde total 500, couvre l'apport requis (500)
        second_loan.action_approve()
        self.assertEqual(second_loan.state, 'approved')
