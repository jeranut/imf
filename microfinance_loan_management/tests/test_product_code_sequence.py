# -*- coding: utf-8 -*-
from odoo.exceptions import UserError

from .common import MicrofinanceCommon


class TestLoanProductCodeSequence(MicrofinanceCommon):

    def _product_vals(self, **kwargs):
        vals = {
            'name': 'Produit auto', 'min_amount': 100.0, 'max_amount': 100000.0,
            'min_term': 1, 'max_term': 36, 'interest_rate': 12.0, 'interest_method': 'flat',
            'repayment_frequency_mode': 'fixed',
            'repayment_frequency_id': self.env.ref('microfinance_loan_management.repayment_frequency_monthly').id,
            'disbursement_journal_id': self.disbursement_journal.id,
            'payment_journal_id': self.payment_journal.id,
            'account_principal_individuel_id': self.loan_account.id,
            'account_principal_groupe_id': self.loan_account_groupe.id,
            'account_interets_recus_individuel_id': self.interest_account.id,
            'account_interets_recus_groupe_id': self.interest_account_groupe.id,
            'account_penalites_id': self.penalty_account.id,
        }
        vals.update(kwargs)
        return vals

    def test_code_auto_generated_with_default_prefix(self):
        self.assertEqual(self.env.company.loan_product_code_prefix, 'CR')
        product = self.env['microfinance.loan.product'].create(self._product_vals())
        self.assertTrue(product.code.startswith('CR'))
        self.assertNotEqual(product.code, 'Nouveau')

    def test_code_explicit_value_kept(self):
        product = self.env['microfinance.loan.product'].create(self._product_vals(code='MANUEL01'))
        self.assertEqual(product.code, 'MANUEL01')

    def test_prefix_change_before_any_product_applies_to_next_code(self):
        # self.env.company a déjà un produit crédit (fixture commune cls.product) : on utilise
        # une société neuve, sans aucun produit, pour tester un changement de préfixe encore
        # autorisé (pas encore verrouillé).
        fresh_company = self.env['res.company'].create({'name': 'Société sans produit crédit (test)'})
        self.assertFalse(fresh_company.loan_product_code_locked)
        fresh_company.loan_product_code_prefix = 'PRET'
        product = self.env['microfinance.loan.product'].create(self._product_vals(company_id=fresh_company.id))
        self.assertTrue(product.code.startswith('PRET'))

    def test_prefix_locked_after_first_product_created(self):
        # self.env.company a déjà un produit crédit (fixture commune cls.product) : le préfixe
        # est donc déjà verrouillé dès le début de ce test.
        self.assertTrue(self.env.company.loan_product_code_locked)
        with self.assertRaises(UserError):
            self.env.company.loan_product_code_prefix = 'AUTRE'

    def test_prefix_editable_and_lockable_on_fresh_company(self):
        fresh_company = self.env['res.company'].create({'name': 'Société sans produit crédit (test 2)'})
        fresh_company.loan_product_code_prefix = 'PRET'  # toujours modifiable, aucun produit
        self.env['microfinance.loan.product'].create(self._product_vals(company_id=fresh_company.id))
        self.assertTrue(fresh_company.loan_product_code_locked)
        with self.assertRaises(UserError):
            fresh_company.loan_product_code_prefix = 'AUTRE'

    def test_sequence_never_resets_across_creations(self):
        product_a = self.env['microfinance.loan.product'].create(self._product_vals())
        product_b = self.env['microfinance.loan.product'].create(self._product_vals())
        prefix = self.env.company.loan_product_code_prefix
        number_a = int(product_a.code[len(prefix):])
        number_b = int(product_b.code[len(prefix):])
        self.assertEqual(number_b, number_a + 1)
