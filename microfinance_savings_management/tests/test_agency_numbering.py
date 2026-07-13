# -*- coding: utf-8 -*-
from .common import SavingsCommon


class TestAgencyNumbering(SavingsCommon):
    """Numérotation AGENCE/TYPE/SÉRIE pour microfinance.savings.account, TYPE dérivé du type de
    client (I individuel / G groupe / E entreprise) sauf pour un produit à terme, toujours T."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_isotry = cls.env['res.company'].create({'name': 'CEFOR Isotry Épargne (test)', 'agency_code': 'XI'})
        cls.company_ambanidia = cls.env['res.company'].create({'name': 'CEFOR Ambanidia Épargne (test)', 'agency_code': 'XB'})
        cls.account_isotry = cls._create_savings_account_placeholder(cls.company_isotry, 'XISAV')
        cls.account_ambanidia = cls._create_savings_account_placeholder(cls.company_ambanidia, 'XBSAV')
        cls.company_product_isotry = cls.env['microfinance.savings.product'].create({
            'name': 'Épargne Isotry (test)', 'code': 'SAVXI', 'product_type': 'voluntary', 'company_id': cls.company_isotry.id,
            'interest_rate': 6.0, 'balance_method': 'min_balance', 'capitalization_frequency': 'monthly',
            'account_epargne_individuel_id': cls.account_isotry.id,
            'account_epargne_groupe_id': cls.account_isotry.id,
            'account_epargne_entreprise_id': cls.account_isotry.id,
        })
        cls.company_product_ambanidia = cls.env['microfinance.savings.product'].create({
            'name': 'Épargne Ambanidia (test)', 'code': 'SAVXB', 'product_type': 'voluntary', 'company_id': cls.company_ambanidia.id,
            'interest_rate': 6.0, 'balance_method': 'min_balance', 'capitalization_frequency': 'monthly',
            'account_epargne_individuel_id': cls.account_ambanidia.id,
            'account_epargne_groupe_id': cls.account_ambanidia.id,
            'account_epargne_entreprise_id': cls.account_ambanidia.id,
        })
        cls.company_product_term_isotry = cls.env['microfinance.savings.product'].create({
            'name': 'Épargne à terme Isotry (test)', 'code': 'SAVXIT', 'product_type': 'term_deposit', 'company_id': cls.company_isotry.id,
            'interest_rate': 8.0, 'balance_method': 'closing_balance', 'capitalization_frequency': 'annual', 'term_months': 12,
            'account_epargne_individuel_id': cls.account_isotry.id,
            'account_epargne_groupe_id': cls.account_isotry.id,
            'account_epargne_entreprise_id': cls.account_isotry.id,
        })
        cls.partner_individual = cls.env['res.partner'].create({
            'name': 'Client individuel test (numérotation)', 'microfinance_client_type': 'individual',
        })
        cls.partner_company = cls.env['res.partner'].create({
            'name': 'Client entreprise test (numérotation)', 'microfinance_client_type': 'company',
        })

    @classmethod
    def _create_savings_account_placeholder(cls, company, code):
        """Compte comptable minimal requis par microfinance.savings.product (les 3 comptes
        épargne individuel/groupe/entreprise), sans intérêt pour ces tests de numérotation qui
        ne comptabilisent aucune transaction."""
        return cls.env['account.account'].create({
            'name': 'Épargne (%s)' % company.name, 'code': code, 'account_type': 'liability_current', 'company_id': company.id,
        })

    def _account_vals(self, company, product, partner=None, **kwargs):
        vals = {
            'partner_id': (partner or self.partner_individual).id,
            'product_id': product.id,
            'company_id': company.id,
        }
        vals.update(kwargs)
        return vals

    def test_individual_numbering_per_agency(self):
        acc1 = self.env['microfinance.savings.account'].create(
            self._account_vals(self.company_isotry, self.company_product_isotry))
        acc2 = self.env['microfinance.savings.account'].create(
            self._account_vals(self.company_isotry, self.company_product_isotry))
        self.assertEqual(acc1.name, 'XI/I/000001')
        self.assertEqual(acc2.name, 'XI/I/000002')

    def test_individual_numbering_independent_per_agency(self):
        self.env['microfinance.savings.account'].create(
            self._account_vals(self.company_isotry, self.company_product_isotry))
        acc_other = self.env['microfinance.savings.account'].create(
            self._account_vals(self.company_ambanidia, self.company_product_ambanidia))
        self.assertEqual(acc_other.name, 'XB/I/000001')

    def test_individual_and_company_types_have_independent_series(self):
        acc_individual = self.env['microfinance.savings.account'].create(
            self._account_vals(self.company_isotry, self.company_product_isotry, partner=self.partner_individual))
        acc_company = self.env['microfinance.savings.account'].create(
            self._account_vals(self.company_isotry, self.company_product_isotry, partner=self.partner_company))
        self.assertEqual(acc_individual.name, 'XI/I/000001')
        self.assertEqual(acc_company.name, 'XI/E/000001')

    def test_term_deposit_uses_type_code_t_regardless_of_client_type(self):
        acc = self.env['microfinance.savings.account'].create(
            self._account_vals(self.company_isotry, self.company_product_term_isotry, partner=self.partner_company))
        self.assertEqual(acc.name, 'XI/T/000001')

