# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError, ValidationError
from odoo.tools.safe_eval import safe_eval

from .common import MicrofinanceCommon


class TestMultiCompanyIsolation(MicrofinanceCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_b = cls.env['res.company'].create({'name': 'Agence B crédit (test)'})
        cls.account_company_b = cls.env['account.account'].create({
            'name': 'Prêts clients agence B',
            'code': 'BPRET',
            'account_type': 'asset_current',
            'company_id': cls.company_b.id,
        })
        cls.user_b = cls.env['res.users'].create({
            'name': 'Agent Agence B (test)',
            'login': 'agent_agence_b_credit_test',
            'company_id': cls.company_b.id,
            'company_ids': [(6, 0, [cls.company_b.id])],
            'groups_id': [(6, 0, [cls.env.ref('microfinance_loan_management.group_microfinance_user').id])],
        })

    # --- Point 1 : les domaines account.account des produits filtrent par société ---
    def test_loan_product_account_domain_excludes_other_company(self):
        field = self.env['microfinance.loan.product']._fields['account_principal_individuel_id']
        domain = safe_eval(field.domain, {'company_id': self.env.company.id})
        accounts = self.env['account.account'].search(domain)
        self.assertIn(self.loan_account, accounts)
        self.assertNotIn(self.account_company_b, accounts)

    def test_loan_product_account_domains_all_filter_by_company(self):
        # Garde-fou : tous les champs account.account des produits doivent référencer
        # company_id dans leur domaine, pas seulement l'exemple ci-dessus.
        Product = self.env['microfinance.loan.product']
        for field_name, field in Product._fields.items():
            if field.type == 'many2one' and field.comodel_name == 'account.account':
                self.assertIn(
                    "'company_id'", field.domain or '',
                    "Le domaine de %s ne filtre pas par company_id" % field_name,
                )

    # --- Point 2 : ir.rule cloisonne les enregistrements par société ---
    def test_loan_not_visible_to_other_company_user(self):
        loan = self._create_loan()
        loans_for_user_b = self.env['microfinance.loan'].with_user(self.user_b).search(
            [('id', '=', loan.id)])
        self.assertFalse(loans_for_user_b)
        with self.assertRaises(AccessError):
            loan.with_user(self.user_b).read(['name'])

    def test_loan_product_not_visible_to_other_company_user(self):
        products_for_user_b = self.env['microfinance.loan.product'].with_user(self.user_b).search(
            [('id', '=', self.product.id)])
        self.assertFalse(products_for_user_b)

    # --- Point 3 : company_id requis sur res.partner en contexte microfinance ---
    def test_partner_company_required_in_microfinance_context(self):
        with self.assertRaises(ValidationError):
            self.env['res.partner'].with_context(microfinance_context=True).create({
                'name': 'Client sans société',
                'microfinance_client_type': 'individual',
                'company_id': False,
            })

    def test_partner_company_not_required_outside_microfinance_context(self):
        # Les autres usages de l'instance (EAT, immobilier...) partagent des partenaires
        # sans société : le champ ne doit rester obligatoire qu'en contexte microfinance.
        partner = self.env['res.partner'].create({'name': 'Client hors contexte microfinance'})
        self.assertFalse(partner.company_id)

    def test_partner_company_defaults_in_microfinance_context(self):
        partner = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client agence par défaut',
            'microfinance_client_type': 'individual',
        })
        self.assertEqual(partner.company_id, self.env.company)
