# -*- coding: utf-8 -*-
from odoo.addons.microfinance_loan_management.tests.common import MicrofinanceCommon


class SavingsCommon(MicrofinanceCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company = cls.env.company
        cls.savings_deposit_account = cls.env['account.account'].create({
            'name': 'Passif épargne clients test', 'code': 'TSAV', 'account_type': 'liability_current', 'company_id': company.id,
        })
        cls.savings_deposit_account_groupe = cls.env['account.account'].create({
            'name': 'Passif épargne groupe test', 'code': 'TSAVG', 'account_type': 'liability_current', 'company_id': company.id,
        })
        cls.savings_deposit_account_entreprise = cls.env['account.account'].create({
            'name': 'Passif épargne entreprise test', 'code': 'TSAVE', 'account_type': 'liability_current', 'company_id': company.id,
        })
        cls.savings_interest_account = cls.env['account.account'].create({
            'name': 'Charge intérêts épargne test', 'code': 'TSAVINT', 'account_type': 'expense', 'company_id': company.id,
        })
        cls.savings_fee_account = cls.env['account.account'].create({
            'name': 'Produit frais épargne test', 'code': 'TSAVFEE', 'account_type': 'income_other', 'company_id': company.id,
        })
        cls.savings_deposit_journal = cls.env['account.journal'].create({
            'name': 'Caisse dépôt épargne test', 'code': 'TSAVD', 'type': 'cash', 'company_id': company.id,
            'default_account_id': cls.bank_account.id,
        })
        cls.savings_withdrawal_journal = cls.env['account.journal'].create({
            'name': 'Caisse retrait épargne test', 'code': 'TSAVW', 'type': 'cash', 'company_id': company.id,
            'default_account_id': cls.bank_account.id,
        })
        cls.savings_product = cls.env['microfinance.savings.product'].create({
            'name': 'Épargne Test', 'code': 'SAVTEST', 'product_type': 'voluntary',
            'interest_rate': 6.0, 'balance_method': 'min_balance', 'capitalization_frequency': 'monthly',
            'min_opening_amount': 0.0, 'min_balance': 50.0,
            'account_epargne_individuel_id': cls.savings_deposit_account.id,
            'account_epargne_groupe_id': cls.savings_deposit_account_groupe.id,
            'account_epargne_entreprise_id': cls.savings_deposit_account_entreprise.id,
            'account_interet_paye_individuel_id': cls.savings_interest_account.id,
            'account_commission_id': cls.savings_fee_account.id,
            'deposit_journal_id': cls.savings_deposit_journal.id,
            'withdrawal_journal_id': cls.savings_withdrawal_journal.id,
        })

    def _create_account(self, **kwargs):
        vals = {'partner_id': self.partner.id, 'product_id': self.savings_product.id}
        vals.update(kwargs)
        return self.env['microfinance.savings.account'].create(vals)

    def _create_active_account(self, opening_amount=200.0, **kwargs):
        account = self._create_account(**kwargs)
        if opening_amount:
            account._create_transaction('deposit', opening_amount)
        account.action_activate()
        return account
