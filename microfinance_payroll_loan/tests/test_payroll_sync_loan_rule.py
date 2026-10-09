# -*- coding: utf-8 -*-
"""La règle LOAN est PARTAGÉE (company_id vide) dans la structure BASE ; son
compte de crédit (315000) est résolu PAR SOCIÉTÉ, sans copie par agence."""
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestMicrofinancePayrollSyncLoanRule(TransactionCase):

    def setUp(self):
        super().setUp()
        self.structure = self.env['hr.payroll.structure'].search(
            [('code', '=', 'BASE')], limit=1)
        self.loan_rule = self.structure.rule_ids.filtered(lambda r: r.code == 'LOAN')
        if not self.loan_rule:
            self.skipTest("Règle LOAN absente de la structure BASE.")

    def test_loan_rule_shared_with_account_per_company(self):
        self.assertFalse(self.loan_rule.company_id)
        companies = self.env['res.company'].search([('chart_template', '!=', False)])
        self.assertTrue(companies)
        for company in companies:
            account = self.loan_rule.sudo().with_company(company).credit_account_id
            self.assertEqual(account.code, '315000', company.name)
            self.assertEqual(account.company_id, company, company.name)

    def test_setup_replay_keeps_accounts_and_company_empty(self):
        Rule = self.env['hr.salary.rule']
        company = self.env['res.company'].search([('chart_template', '!=', False)], limit=1)
        before = self.loan_rule.sudo().with_company(company).credit_account_id
        Rule._microfinance_payroll_setup_loan_rule()
        Rule._microfinance_payroll_setup_loan_rule()
        self.assertEqual(self.loan_rule.sudo().with_company(company).credit_account_id, before)
        self.assertFalse(self.loan_rule.company_id)
        self.assertEqual(len(self.structure.rule_ids.filtered(lambda r: r.code == 'LOAN')), 1)
