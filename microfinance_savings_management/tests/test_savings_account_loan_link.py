# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError

from .common import SavingsCommon


class TestSavingsAccountLoanLink(SavingsCommon):
    """Correctif Lot 1 (docs_dev/epargne_exigee_display/AUDIT_COMPLEMENT_credit_lie.md) :
    microfinance_loan_id ne doit jamais pointer vers un crédit d'un autre titulaire que
    partner_id. Le domain= posé sur le champ n'est qu'un filtre d'affichage côté formulaire (non
    testable côté serveur) - la vraie garantie est la contrainte serveur ci-dessous, qui couvre
    aussi les chemins hors UI (import, ORM direct)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.other_partner = cls.env['res.partner'].create({
            'name': 'Autre client test', 'microfinance_partner_type': 'client',
        })

    def test_smart_button_prefills_loan_in_context(self):
        loan = self._create_loan()
        action = loan.action_view_savings_accounts()
        self.assertEqual(action['context'].get('default_microfinance_loan_id'), loan.id)
        self.assertEqual(action['context'].get('default_partner_id'), loan.partner_id.id)

    def test_smart_button_context_creates_account_prelinked(self):
        loan = self._create_loan()
        action = loan.action_view_savings_accounts()
        account = self.env['microfinance.savings.account'].with_context(action['context']).create({
            'product_id': self.savings_product.id,
        })
        self.assertEqual(account.microfinance_loan_id, loan)
        self.assertEqual(account.partner_id, loan.partner_id)

    def test_create_with_mismatched_loan_partner_raises(self):
        loan = self._create_loan(partner_id=self.other_partner.id)
        with self.assertRaises(ValidationError):
            self._create_account(microfinance_loan_id=loan.id)

    def test_write_mismatched_loan_partner_raises(self):
        loan = self._create_loan(partner_id=self.other_partner.id)
        account = self._create_account()
        with self.assertRaises(ValidationError):
            account.write({'microfinance_loan_id': loan.id})

    def test_matching_loan_partner_allowed(self):
        loan = self._create_loan()
        account = self._create_account(microfinance_loan_id=loan.id)
        self.assertEqual(account.microfinance_loan_id, loan)
