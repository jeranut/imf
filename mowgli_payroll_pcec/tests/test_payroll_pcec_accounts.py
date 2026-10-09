# -*- coding: utf-8 -*-
"""Tests pour la Tâche 5 : alignement des comptes PCEC, compte 652500,
comptes des règles source, et journal de paie à la synchro.

Comme les autres fichiers de ce dossier, suppose les données réelles de
MOWGLI (copie jetable uniquement). TransactionCase : rollback automatique.
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPayrollPcecAccounts(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].search(
            [('name', '=', 'CEFOR Isotry')], limit=1)
        cls.structure = cls.env['hr.payroll.structure'].search(
            [('code', '=', 'BASE')], limit=1)
        cls.target = cls.env['res.company'].search(
            [('name', '=', 'CEFOR Ambanidia')], limit=1)

    def setUp(self):
        super().setUp()
        if not (self.company and self.structure and self.target):
            self.skipTest(
                "Données MOWGLI (CEFOR Isotry/Ambanidia, structure BASE) "
                "absentes de cette base.")

    def _account(self, code, company=None):
        return self.env['account.account'].search([
            ('code', '=', code),
            ('company_id', '=', (company or self.company).id),
        ], limit=1)

    def _create_test_company_with_chart(self):
        """Société jetable avec un mini-plan (315000/316000/652100, mal
        libellés, sans référence), isolée des effets de bord de
        l'installation du module sur CEFOR Isotry (déjà réalignée)."""
        company = self.env['res.company'].create({
            'name': 'Agence Test Comptes PCEC',
            'agency_code': 'ZZC',
        })
        accounts = {}
        for code, name, account_type, reconcile in (
            ('315000', 'Créditeurs divers *', 'liability_current', True),
            ('316000', 'Personnel *', 'asset_current', True),
            ('652100', 'Charges sociales - cotisations *', 'expense', False),
        ):
            accounts[code] = self.env['account.account'].create({
                'code': code, 'name': name, 'account_type': account_type,
                'reconcile': reconcile, 'company_id': company.id,
            })
        journal = self.env['account.journal'].create({
            'name': 'Opérations diverses test', 'code': 'ODT',
            'type': 'general', 'company_id': company.id,
        })
        return company, accounts, journal

    def test_relabel_safe_account(self):
        company, accounts, _journal = self._create_test_company_with_chart()

        self.env['account.account']._mowgli_setup_pcec_accounts()

        account = self._account('652100', company)
        self.assertEqual(account.name, 'Rémunérations du personnel')

    def test_relabel_blocked_account_with_move_lines(self):
        company, accounts, journal = self._create_test_company_with_chart()
        move = self.env['account.move'].create({
            'journal_id': journal.id,
            'date': '2026-01-01',
            'line_ids': [
                (0, 0, {'account_id': accounts['316000'].id, 'name': 'test',
                        'debit': 100.0, 'credit': 0.0}),
                (0, 0, {'account_id': accounts['315000'].id, 'name': 'test',
                        'debit': 0.0, 'credit': 100.0}),
            ],
        })
        move._post()
        old_name = accounts['316000'].name

        report = self.env['account.account']._mowgli_setup_pcec_accounts()

        account_316 = self._account('316000', company)
        self.assertEqual(account_316.name, old_name)
        entry = next(
            e for e in report
            if e['company'] == company.name and e['code'] == '316000')
        self.assertEqual(entry['status'], 'blocked')
        self.assertTrue(entry['references'])

    def test_create_652500_not_duplicated(self):
        company, _accounts, _journal = self._create_test_company_with_chart()
        self.assertFalse(self._account('652500', company))

        self.env['account.account']._mowgli_setup_pcec_accounts()
        account = self._account('652500', company)
        self.assertTrue(account)
        self.assertEqual(account.name, 'Cotisations aux organismes sociaux')

        self.env['account.account']._mowgli_setup_pcec_accounts()
        accounts652500 = self.env['account.account'].search([
            ('code', '=', '652500'), ('company_id', '=', company.id)])
        self.assertEqual(len(accounts652500), 1)

    def test_rule_accounts_configured_correctly(self):
        self.env['account.account']._mowgli_setup_pcec_accounts()
        self.env['hr.salary.rule']._mowgli_setup_payroll_rules()

        rules = {r.code: r for r in self.structure.rule_ids}
        self.assertEqual(rules['BASIC'].debit_account_id.code, '652100')
        for code in ('CNAPS', 'OSTIE', 'IRSA', 'NET'):
            self.assertEqual(rules[code].credit_account_id.code, '315000')
        self.assertFalse(rules['GROSS'].debit_account_id)
        self.assertFalse(rules['GROSS'].credit_account_id)
        self.assertFalse(rules['NETIMP'].debit_account_id)
        self.assertFalse(rules['NETIMP'].credit_account_id)

    def test_accounting_entry_1000000_with_auto_accounts(self):
        self.env['account.account']._mowgli_setup_pcec_accounts()
        self.env['hr.salary.rule']._mowgli_setup_payroll_rules()
        self.company.write({'hr_payroll_entries': True})
        journal = self.env['account.journal'].search(
            [('company_id', '=', self.company.id), ('type', '=', 'general')],
            limit=1)
        self.company.write({'payroll_journal_id': journal.id})

        employee = self.env['hr.employee'].create({
            'name': 'Employé test comptes PCEC',
            'company_id': self.company.id,
        })
        contract = self.env['hr.contract'].create({
            'name': 'Contrat test comptes PCEC',
            'employee_id': employee.id,
            'company_id': self.company.id,
            'wage': 1000000,
            'state': 'open',
            'struct_id': self.structure.id,
            'date_start': '2026-01-01',
        })
        payslip = self.env['hr.payslip'].create({
            'employee_id': employee.id,
            'contract_id': contract.id,
            'struct_id': self.structure.id,
            'date_from': '2026-01-01',
            'date_to': '2026-01-31',
        })
        payslip.action_compute_sheet()
        payslip.action_payslip_verify()
        payslip.action_payslip_done()

        move = payslip.move_id
        self.assertTrue(move)
        total_debit = sum(move.line_ids.mapped('debit'))
        total_credit = sum(move.line_ids.mapped('credit'))
        self.assertAlmostEqual(total_debit, total_credit)
        self.assertAlmostEqual(total_debit, 1000000)

        debit_lines = move.line_ids.filtered(lambda l: l.debit)
        credit_lines = move.line_ids.filtered(lambda l: l.credit)
        self.assertEqual(debit_lines.account_id.code, '652100')
        self.assertAlmostEqual(debit_lines.debit, 1000000)
        self.assertEqual(credit_lines.account_id.code, '315000')
        self.assertAlmostEqual(credit_lines.credit, 1000000)
