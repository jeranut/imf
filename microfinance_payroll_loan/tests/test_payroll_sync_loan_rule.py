# -*- coding: utf-8 -*-
"""Vérifie que le wizard de synchro agences (mowgli_payroll_pcec, non modifié) propage la
règle LOAN comme n'importe quelle autre règle de la structure BASE — aucune logique de
synchro dédiée n'est nécessaire côté microfinance_payroll_loan."""
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestMicrofinancePayrollSyncLoanRule(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].search([('name', '=', 'CEFOR Isotry')], limit=1)
        cls.structure = cls.env['hr.payroll.structure'].search([('code', '=', 'BASE')], limit=1)
        cls.target = cls.env['res.company'].search([('name', '=', 'CEFOR Ambanidia')], limit=1)

    def setUp(self):
        super().setUp()
        if not (self.company and self.structure and self.target):
            self.skipTest(
                "Données MOWGLI (CEFOR Isotry/Ambanidia, structure BASE) absentes de cette "
                "base, ou règle LOAN non posée (microfinance_payroll_loan non installé).")
        self.loan_rule = self.structure.rule_ids.filtered(lambda r: r.code == 'LOAN')
        if not self.loan_rule:
            self.skipTest("Règle LOAN absente de la structure BASE.")

    def _target_loan_rule(self):
        target_structure = self.env['hr.payroll.structure'].search([
            ('code', '=', 'BASE'), ('company_id', '=', self.target.id),
        ])
        return target_structure.rule_ids.filtered(lambda r: r.code == 'LOAN')

    def test_sync_copies_loan_rule_with_mapped_account(self):
        report = self.structure._mowgli_sync_to_company(self.target)
        loan_report = [r for r in report['rules'] if r['code'] == 'LOAN']
        self.assertTrue(loan_report, "La règle LOAN doit apparaître dans le rapport de synchro.")
        self.assertEqual(loan_report[0]['status'], 'created')

        target_rule = self._target_loan_rule()
        self.assertTrue(target_rule)
        self.assertEqual(target_rule.credit_account_id.code, '315000')
        self.assertEqual(target_rule.credit_account_id.company_id, self.target)
        self.assertEqual(target_rule.amount_python_compute, self.loan_rule.amount_python_compute)
        self.assertEqual(target_rule.sequence, self.loan_rule.sequence)

    def test_sync_replay_is_unchanged(self):
        self.structure._mowgli_sync_to_company(self.target)
        report = self.structure._mowgli_sync_to_company(self.target)
        loan_report = [r for r in report['rules'] if r['code'] == 'LOAN']
        self.assertTrue(loan_report)
        self.assertEqual(loan_report[0]['status'], 'unchanged')
