# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError

from .common import SavingsCommon


class TestSavingsProduct(SavingsCommon):

    def _product_vals(self, **kwargs):
        vals = {
            'name': 'Produit', 'code': 'PVAL',
            'account_epargne_individuel_id': self.savings_deposit_account.id,
            'account_epargne_groupe_id': self.savings_deposit_account_groupe.id,
            'account_epargne_entreprise_id': self.savings_deposit_account_entreprise.id,
            'account_interet_paye_individuel_id': self.savings_interest_account.id,
            'deposit_journal_id': self.savings_deposit_journal.id,
            'withdrawal_journal_id': self.savings_withdrawal_journal.id,
        }
        vals.update(kwargs)
        return vals

    def test_create_compulsory_product(self):
        product = self.env['microfinance.savings.product'].create(self._product_vals(code='PCOMP', product_type='compulsory'))
        self.assertEqual(product.product_type, 'compulsory')

    def test_create_voluntary_product(self):
        product = self.env['microfinance.savings.product'].create(self._product_vals(code='PVOL', product_type='voluntary'))
        self.assertEqual(product.product_type, 'voluntary')

    def test_create_term_deposit_product_requires_term_months(self):
        with self.assertRaises(ValidationError):
            self.env['microfinance.savings.product'].create(self._product_vals(code='PTERM', product_type='term_deposit'))

    def test_create_term_deposit_product_with_term_months(self):
        product = self.env['microfinance.savings.product'].create(
            self._product_vals(code='PTERM2', product_type='term_deposit', term_months=12)
        )
        self.assertEqual(product.term_months, 12)

    def test_negative_interest_rate_blocked(self):
        with self.assertRaises(ValidationError):
            self.savings_product.write({'interest_rate': -1.0})
