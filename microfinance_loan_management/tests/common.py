# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class MicrofinanceCommon(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company = cls.env.company
        cls.loan_account = cls.env['account.account'].create({
            'name': 'Prêts clients test',
            'code': 'TPRET',
            'account_type': 'asset_current',
            'company_id': company.id,
        })
        cls.interest_account = cls.env['account.account'].create({
            'name': 'Produits intérêts test',
            'code': 'TINT',
            'account_type': 'income',
            'company_id': company.id,
        })
        cls.penalty_account = cls.env['account.account'].create({
            'name': 'Produits pénalités test',
            'code': 'TPEN',
            'account_type': 'income_other',
            'company_id': company.id,
        })
        cls.bank_account = cls.env['account.account'].create({
            'name': 'Caisse test',
            'code': 'TCASH',
            'account_type': 'asset_cash',
            'company_id': company.id,
        })
        cls.disbursement_journal = cls.env['account.journal'].create({
            'name': 'Caisse décaissement test',
            'code': 'TDEC',
            'type': 'cash',
            'company_id': company.id,
            'default_account_id': cls.bank_account.id,
        })
        cls.payment_journal = cls.env['account.journal'].create({
            'name': 'Caisse remboursement test',
            'code': 'TREM',
            'type': 'cash',
            'company_id': company.id,
            'default_account_id': cls.bank_account.id,
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Client Test Microfinance'})
        cls.product = cls.env['microfinance.loan.product'].create({
            'name': 'Produit Test',
            'code': 'PTEST',
            'min_amount': 100.0,
            'max_amount': 100000.0,
            'min_term': 1,
            'max_term': 36,
            'interest_rate': 12.0,
            'interest_method': 'flat',
            'repayment_frequency_mode': 'fixed',
            'repayment_frequency_id': cls.env.ref('microfinance_loan_management.repayment_frequency_monthly').id,
            'disbursement_journal_id': cls.disbursement_journal.id,
            'payment_journal_id': cls.payment_journal.id,
            'loan_account_id': cls.loan_account.id,
            'interest_account_id': cls.interest_account.id,
            'penalty_account_id': cls.penalty_account.id,
        })

    def _create_loan(self, **kwargs):
        vals = {
            'partner_id': self.partner.id,
            'product_id': self.product.id,
            'loan_amount': 1200.0,
            'term': 6,
        }
        vals.update(kwargs)
        return self.env['microfinance.loan'].create(vals)

    def _activate_loan(self, **kwargs):
        loan = self._create_loan(**kwargs)
        loan.action_generate_schedule()
        loan.action_submit()
        loan.action_manager_validate()
        loan.action_finance_validate()
        loan.action_approve()
        loan.action_disburse()
        return loan
