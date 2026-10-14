# -*- coding: utf-8 -*-
"""Règles d'indemnités du contrat (HRA, DA, Meal, Medical, Other) dans la
structure BASE. Suppose les données réelles de MOWGLI (copie jetable)."""
from odoo.tests.common import TransactionCase, tagged

CODES = ('HRA', 'DA', 'Meal', 'Medical', 'Other')


@tagged('post_install', '-at_install')
class TestPayrollAllowances(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].search(
            [('name', '=', 'CEFOR Isotry')], limit=1)
        cls.c6 = cls.env['res.company'].search(
            [('name', '=', 'CEFOR Mahitsy')], limit=1)
        cls.structure = cls.env['hr.payroll.structure'].search(
            [('code', '=', 'BASE')], limit=1)
        if cls.company and cls.structure:
            cls.env['hr.salary.rule']._mowgli_setup_payroll_rules()

    def setUp(self):
        super().setUp()
        if not self.company or not self.structure:
            self.skipTest("Données MOWGLI absentes de cette base.")

    def _slip(self, **allowances):
        employee = self.env['hr.employee'].create({
            'name': 'Employé indemnités', 'company_id': self.company.id})
        contract = self.env['hr.contract'].create(dict({
            'name': 'Contrat indemnités', 'employee_id': employee.id,
            'company_id': self.company.id, 'wage': 750000,
            'travel_allowance': 150000, 'state': 'open',
            'struct_id': self.structure.id, 'date_start': '2026-01-01',
        }, **allowances))
        slip = self.env['hr.payslip'].create({
            'employee_id': employee.id, 'contract_id': contract.id,
            'struct_id': self.structure.id,
            'date_from': '2026-10-01', 'date_to': '2026-10-31'})
        slip.action_compute_sheet()
        return slip

    def _totals(self, slip):
        return {l.code: l.total for l in slip.line_ids}

    def test_a_sans_indemnite_aucune_ligne(self):
        totals = self._totals(self._slip())
        for code in CODES:
            self.assertNotIn(code, totals)
        self.assertEqual(
            {k: totals[k] for k in ('GROSS', 'CNAPS', 'OSTIE', 'NETIMP', 'IRSA', 'NET')},
            {'GROSS': 900000, 'CNAPS': -9000, 'OSTIE': -9000,
             'NETIMP': 882000, 'IRSA': -83900, 'NET': 798100})

    def test_b_avec_hra_et_meal(self):
        totals = self._totals(self._slip(hra=50000, meal_allowance=30000))
        self.assertEqual(totals['HRA'], 50000)
        self.assertEqual(totals['Meal'], 30000)
        for code in ('DA', 'Medical', 'Other'):
            self.assertNotIn(code, totals)
        self.assertEqual(
            {k: totals[k] for k in ('GROSS', 'CNAPS', 'OSTIE', 'NETIMP', 'IRSA', 'NET')},
            {'GROSS': 980000, 'CNAPS': -9800, 'OSTIE': -9800,
             'NETIMP': 960400, 'IRSA': -99580, 'NET': 860820})

    def test_c_ecriture_equilibree_sur_remunerations(self):
        journal = self.env['account.journal'].search(
            [('company_id', '=', self.company.id), ('type', '=', 'general')],
            limit=1)
        self.company.write({'hr_payroll_entries': True,
                            'payroll_journal_id': journal.id})
        slip = self._slip(hra=50000, meal_allowance=30000)
        slip.action_payslip_verify()
        slip.action_payslip_done()
        move = slip.move_id
        self.assertTrue(move)
        self.assertAlmostEqual(sum(move.line_ids.mapped('debit')),
                               sum(move.line_ids.mapped('credit')),
                               msg="Écriture non équilibrée")
        debit = move.line_ids.filtered(lambda l: l.debit)
        self.assertEqual(debit.account_id.code, '652100')
        self.assertAlmostEqual(sum(debit.mapped('debit')), 980000)

    def test_d_rejeu_sans_doublon_ni_perte(self):
        Rule = self.env['hr.salary.rule']
        before = self.structure.rule_ids.mapped('code')
        Rule._mowgli_setup_payroll_rules()
        Rule._microfinance_payroll_setup_loan_rule()
        Rule._mowgli_setup_payroll_rules()
        after = self.structure.rule_ids.mapped('code')
        self.assertLessEqual(set(before), set(after))
        self.assertEqual(len(after), len(set(after)), "Doublon de code")
        for code in CODES:
            self.assertEqual(after.count(code), 1)
        gross = self.structure.rule_ids.filtered(lambda r: r.code == 'GROSS')
        self.assertEqual(gross.amount_python_compute.count('categories.ALW'), 1)
        travel = self.structure.rule_ids.filtered(lambda r: r.code == 'Travel')
        self.assertNotEqual(travel.category_id.code, 'ALW')

    def test_e_synchro_comptes_par_societe(self):
        if not self.c6:
            self.skipTest("CEFOR Mahitsy absente.")
        Rule = self.env['hr.salary.rule'].sudo()
        rules = self.structure.sudo().rule_ids.filtered(lambda r: r.code in CODES)
        self.assertEqual(len(rules), 5)
        for rule in rules:
            rule.with_company(self.c6).write({'debit_account_id': False})
        rows = Rule._mowgli_complete_company_accounts(rules, self.c6, apply=False)
        self.assertEqual({r['regle'] for r in rows if r['role'] == 'debit'}, set(CODES))
        self.assertTrue(all(r['statut'] == 'resolu' for r in rows))
        for rule in rules:
            self.assertFalse(rule.with_company(self.c6).debit_account_id)
        Rule._mowgli_complete_company_accounts(rules, self.c6, apply=True)
        account = self.env['account.account'].sudo().search(
            [('code', '=', '652100'), ('company_id', '=', self.c6.id)], limit=1)
        for rule in rules:
            self.assertEqual(rule.with_company(self.c6).debit_account_id, account)
            self.assertFalse(rule.with_company(self.c6).credit_account_id)
        rows = Rule._mowgli_complete_company_accounts(rules, self.c6, apply=True)
        self.assertTrue(all(r['statut'] == 'deja_renseigne' for r in rows))
