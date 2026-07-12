# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError
from odoo.tools.safe_eval import safe_eval

from .common import SavingsCommon


class TestSavingsMultiCompanyIsolation(SavingsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_b = cls.env['res.company'].create({'name': 'Agence B épargne (test)'})
        cls.savings_account_company_b = cls.env['account.account'].create({
            'name': 'Épargne agence B',
            'code': 'BSAV',
            'account_type': 'liability_current',
            'company_id': cls.company_b.id,
        })
        cls.user_b = cls.env['res.users'].create({
            'name': 'Agent Épargne Agence B (test)',
            'login': 'agent_agence_b_epargne_test',
            'company_id': cls.company_b.id,
            'company_ids': [(6, 0, [cls.company_b.id])],
            'groups_id': [(6, 0, [cls.env.ref('microfinance_savings_management.group_savings_agent').id])],
        })

    # --- Point 1 : les domaines account.account du produit d'épargne filtrent par société ---
    def test_savings_product_account_domain_excludes_other_company(self):
        field = self.env['microfinance.savings.product']._fields['account_epargne_individuel_id']
        domain = safe_eval(field.domain, {'company_id': self.env.company.id})
        accounts = self.env['account.account'].search(domain)
        self.assertIn(self.savings_deposit_account, accounts)
        self.assertNotIn(self.savings_account_company_b, accounts)

    def test_savings_product_account_domains_all_filter_by_company(self):
        Product = self.env['microfinance.savings.product']
        for field_name, field in Product._fields.items():
            if field.type == 'many2one' and field.comodel_name == 'account.account':
                self.assertIn(
                    "'company_id'", field.domain or '',
                    "Le domaine de %s ne filtre pas par company_id" % field_name,
                )

    # --- Point 2 : ir.rule cloisonne les comptes/produits épargne par société ---
    def test_savings_account_not_visible_to_other_company_user(self):
        account = self._create_account()
        accounts_for_user_b = self.env['microfinance.savings.account'].with_user(self.user_b).search(
            [('id', '=', account.id)])
        self.assertFalse(accounts_for_user_b)
        with self.assertRaises(AccessError):
            account.with_user(self.user_b).read(['name'])

    def test_savings_product_not_visible_to_other_company_user(self):
        products_for_user_b = self.env['microfinance.savings.product'].with_user(self.user_b).search(
            [('id', '=', self.savings_product.id)])
        self.assertFalse(products_for_user_b)
