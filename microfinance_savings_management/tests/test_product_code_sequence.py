# -*- coding: utf-8 -*-
from odoo.exceptions import UserError

from .common import SavingsCommon


class TestSavingsProductCodeSequence(SavingsCommon):

    def _product_vals(self, **kwargs):
        vals = {
            'name': 'Produit épargne auto', 'product_type': 'voluntary',
            'account_epargne_individuel_id': self.savings_deposit_account.id,
            'account_epargne_groupe_id': self.savings_deposit_account_groupe.id,
            'account_epargne_entreprise_id': self.savings_deposit_account_entreprise.id,
            'account_interet_paye_individuel_id': self.savings_interest_account.id,
            'deposit_journal_id': self.savings_deposit_journal.id,
            'withdrawal_journal_id': self.savings_withdrawal_journal.id,
        }
        vals.update(kwargs)
        return vals

    def test_code_auto_generated_with_default_prefix(self):
        self.assertEqual(self.env.company.savings_product_code_prefix, 'EP')
        product = self.env['microfinance.savings.product'].create(self._product_vals())
        self.assertTrue(product.code.startswith('EP'))
        self.assertNotEqual(product.code, 'Nouveau')

    def test_code_explicit_value_kept(self):
        product = self.env['microfinance.savings.product'].create(self._product_vals(code='MANUEL01'))
        self.assertEqual(product.code, 'MANUEL01')

    def test_prefix_locked_after_first_product_created(self):
        # self.env.company a déjà un produit épargne (fixture commune cls.savings_product) : le
        # préfixe est donc déjà verrouillé dès le début de ce test.
        self.assertTrue(self.env.company.savings_product_code_locked)
        with self.assertRaises(UserError):
            self.env.company.savings_product_code_prefix = 'AUTRE'

    def test_prefix_editable_and_lockable_on_fresh_company(self):
        fresh_company = self.env['res.company'].create({'name': 'Société sans produit épargne (test)'})
        self.assertFalse(fresh_company.savings_product_code_locked)
        fresh_company.savings_product_code_prefix = 'SAV'
        product = self.env['microfinance.savings.product'].create(self._product_vals(company_id=fresh_company.id))
        self.assertTrue(product.code.startswith('SAV'))
        # savings_product_code_locked est calculé (non stocké, sans dépendance inter-modèle
        # possible) : invalidation explicite nécessaire pour relire l'état à jour après la
        # création ci-dessus dans ce même script — un rechargement d'écran classique (nouvel
        # appel RPC) n'a pas ce problème, chaque lecture y repart d'un cache vide.
        fresh_company.invalidate_recordset(['savings_product_code_locked'])
        self.assertTrue(fresh_company.savings_product_code_locked)
        with self.assertRaises(UserError):
            fresh_company.savings_product_code_prefix = 'AUTRE2'

    def test_sequence_never_resets_across_creations(self):
        product_a = self.env['microfinance.savings.product'].create(self._product_vals())
        product_b = self.env['microfinance.savings.product'].create(self._product_vals())
        prefix = self.env.company.savings_product_code_prefix
        number_a = int(product_a.code[len(prefix):])
        number_b = int(product_b.code[len(prefix):])
        self.assertEqual(number_b, number_a + 1)
