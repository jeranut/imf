# -*- coding: utf-8 -*-
"""Tests d'intégration pour le bouton de synchronisation multi-agences.

Comme test_payroll_pcec.py, ces tests supposent les données réelles de
MOWGLI (société CEFOR Isotry, structure BASE) : à exécuter sur une copie
jetable, jamais sur la production. TransactionCase annule (rollback)
toute donnée créée par ces tests.
"""
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged

SOURCE_CODES = ('BASIC', 'Travel', 'GROSS', 'CNAPS', 'OSTIE', 'NETIMP',
                'IRSA', 'NET')


@tagged('post_install', '-at_install')
class TestPayrollSync(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].search(
            [('name', '=', 'CEFOR Isotry')], limit=1)
        cls.structure = cls.env['hr.payroll.structure'].search(
            [('code', '=', 'BASE')], limit=1)
        cls.target1 = cls.env['res.company'].search(
            [('name', '=', 'CEFOR Ambanidia')], limit=1)
        cls.target2 = cls.env['res.company'].search(
            [('name', '=', 'CEFOR Ampitatafika')], limit=1)
        if cls.company and cls.structure:
            cls.env['hr.salary.rule']._mowgli_setup_payroll_rules()

    def setUp(self):
        super().setUp()
        if not (self.company and self.structure
                and self.target1 and self.target2):
            self.skipTest(
                "Données MOWGLI (CEFOR Isotry/Ambanidia/Ampitatafika, "
                "structure BASE) absentes de cette base.")
        self._configure_source_accounts()

    def _configure_source_accounts(self):
        debit_account = self.env['account.account'].search(
            [('code', '=', '652100'), ('company_id', '=', self.company.id)],
            limit=1)
        credit_account = self.env['account.account'].search(
            [('code', '=', '315000'), ('company_id', '=', self.company.id)],
            limit=1)
        self.rules = {r.code: r for r in self.structure.rule_ids}
        self.rules['BASIC'].write({'debit_account_id': debit_account.id})
        for code in ('CNAPS', 'OSTIE', 'IRSA', 'NET'):
            self.rules[code].write({'credit_account_id': credit_account.id})

    def _target_structure(self, company):
        return self.env['hr.payroll.structure'].search([
            ('code', '=', 'BASE'), ('company_id', '=', company.id)])

    def test_sync_creates_structure_and_rules(self):
        report = self.structure._mowgli_sync_to_company(self.target1)
        self.assertEqual(report['structure']['status'], 'created')
        self.assertEqual(
            {r['status'] for r in report['rules']}, {'created'})

        target_structure = self._target_structure(self.target1)
        self.assertTrue(target_structure)
        self.assertEqual(len(target_structure), 1)
        # Le nombre et la liste des règles copiées suivent la structure source telle que lue
        # en base (pas un total figé) : d'autres modules (ex. microfinance_payroll_loan,
        # installé ou non selon l'environnement) peuvent ajouter leurs propres règles à la
        # structure BASE, synchronisées comme n'importe quelle autre règle.
        self.assertEqual(
            {r.code for r in target_structure.rule_ids},
            set(self.structure.rule_ids.mapped('code')))

        rules_by_code = {r.code: r for r in target_structure.rule_ids}
        for code in SOURCE_CODES:
            self.assertIn(code, rules_by_code)
            self.assertEqual(rules_by_code[code].company_id, self.target1)
            self.assertEqual(
                rules_by_code[code].sequence, self.rules[code].sequence)

        debit_account = self.env['account.account'].search(
            [('code', '=', '652100'), ('company_id', '=', self.target1.id)],
            limit=1)
        credit_account = self.env['account.account'].search(
            [('code', '=', '315000'), ('company_id', '=', self.target1.id)],
            limit=1)
        self.assertEqual(
            rules_by_code['BASIC'].debit_account_id, debit_account)
        for code in ('CNAPS', 'OSTIE', 'IRSA', 'NET'):
            self.assertEqual(
                rules_by_code[code].credit_account_id, credit_account)
        # GROSS et NETIMP ne doivent jamais recevoir de compte
        self.assertFalse(rules_by_code['GROSS'].debit_account_id)
        self.assertFalse(rules_by_code['GROSS'].credit_account_id)
        self.assertFalse(rules_by_code['NETIMP'].debit_account_id)
        self.assertFalse(rules_by_code['NETIMP'].credit_account_id)

    def test_sync_idempotent_no_duplicates(self):
        self.structure._mowgli_sync_to_company(self.target1)
        report2 = self.structure._mowgli_sync_to_company(self.target1)

        self.assertEqual(report2['structure']['status'], 'unchanged')
        self.assertEqual(
            {r['status'] for r in report2['rules']}, {'unchanged'})

        structures = self.env['hr.payroll.structure'].search([
            ('code', '=', 'BASE'), ('company_id', '=', self.target1.id)])
        self.assertEqual(len(structures), 1)
        rules = self.env['hr.salary.rule'].search([
            ('code', '=', 'NET'), ('company_id', '=', self.target1.id)])
        self.assertEqual(len(rules), 1)

    def test_sync_updates_on_source_change(self):
        self.structure._mowgli_sync_to_company(self.target1)
        self.rules['OSTIE'].write({'name': 'OSTIE (modifié pour test)'})

        report2 = self.structure._mowgli_sync_to_company(self.target1)
        ostie_report = next(
            r for r in report2['rules'] if r['code'] == 'OSTIE')
        self.assertEqual(ostie_report['status'], 'updated')

        target_structure = self._target_structure(self.target1)
        target_ostie = target_structure.rule_ids.filtered(
            lambda r: r.code == 'OSTIE')
        self.assertEqual(target_ostie.name, 'OSTIE (modifié pour test)')

    def test_sync_missing_account_warning(self):
        blank_company = self.env['res.company'].create({
            'name': 'Agence Test Sans Plan PCEC',
            'agency_code': 'ZZT',
        })
        self.assertFalse(self.env['account.account'].sudo().search(
            [('company_id', '=', blank_company.id)]))

        report = self.structure._mowgli_sync_to_company(blank_company)
        self.assertTrue(report['accounts_missing'])
        self.assertTrue(report['journal_missing'])

        target_structure = self._target_structure(blank_company)
        rules_by_code = {r.code: r for r in target_structure.rule_ids}
        self.assertFalse(rules_by_code['BASIC'].debit_account_id)
        self.assertFalse(rules_by_code['NET'].credit_account_id)

    def test_sync_payslip_matches_expected(self):
        self.structure._mowgli_sync_to_company(self.target1)
        target_structure = self._target_structure(self.target1)

        employee = self.env['hr.employee'].create({
            'name': 'Employé agence test',
            'company_id': self.target1.id,
        })
        contract = self.env['hr.contract'].create({
            'name': 'Contrat agence test',
            'employee_id': employee.id,
            'company_id': self.target1.id,
            'wage': 1000000,
            'state': 'open',
            'struct_id': target_structure.id,
            'date_start': '2026-01-01',
        })
        payslip = self.env['hr.payslip'].create({
            'employee_id': employee.id,
            'contract_id': contract.id,
            'struct_id': target_structure.id,
            'date_from': '2026-01-01',
            'date_to': '2026-01-31',
        })
        payslip.action_compute_sheet()

        def total(code):
            return payslip.line_ids.filtered(
                lambda l: l.code == code).total

        self.assertAlmostEqual(total('GROSS'), 1000000)
        self.assertAlmostEqual(total('CNAPS'), -10000)
        self.assertAlmostEqual(total('OSTIE'), -10000)
        self.assertAlmostEqual(total('NETIMP'), 980000)
        self.assertAlmostEqual(total('IRSA'), -103500)
        self.assertAlmostEqual(total('NET'), 876500)

    def test_sync_preserves_extra_rule_at_target(self):
        self.structure._mowgli_sync_to_company(self.target1)
        target_structure = self._target_structure(self.target1)

        category = self.env['hr.salary.rule.category'].search(
            [('code', '=', 'NET')], limit=1)
        extra_rule = self.env['hr.salary.rule'].create({
            'name': 'Règle locale agence (hors source)',
            'code': 'EXTRA_LOCAL',
            'category_id': category.id,
            'sequence': 950,
            'condition_select': 'none',
            'amount_select': 'fix',
            'amount_fix': 0.0,
            'company_id': self.target1.id,
        })
        target_structure.write({'rule_ids': [(4, extra_rule.id)]})

        report2 = self.structure._mowgli_sync_to_company(self.target1)
        self.assertIn('EXTRA_LOCAL', report2['extra_rules'])

        target_structure = self._target_structure(self.target1)
        self.assertIn('EXTRA_LOCAL', target_structure.rule_ids.mapped('code'))

    def test_sync_requires_manager_group(self):
        officer_group = self.env.ref(
            'hr_payroll_community.group_hr_payroll_community_user')
        test_user = self.env['res.users'].create({
            'name': 'Utilisateur sans droit synchro',
            'login': 'mowgli_sync_test_user',
            'groups_id': [(6, 0, [officer_group.id])],
            'company_id': self.company.id,
        })
        structure_as_user = self.structure.with_user(test_user)
        with self.assertRaises(AccessError):
            structure_as_user.action_open_mowgli_sync_wizard()
        with self.assertRaises(AccessError):
            structure_as_user._mowgli_sync_to_company(self.target1)
