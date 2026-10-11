# -*- coding: utf-8 -*-
"""Écriture complète du bulletin (brut, cotisations patronales, net, retenues)
et comptes de paie par société. Données réelles de MOWGLI, TransactionCase
annulé. Bulletin : base 600 000 + transport 150 000."""
from odoo.addons.mowgli_payroll_pcec.tests.common import MowgliSmeTestMixin
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

EXPECTED_AMOUNTS = {
    'GROSS': 750000.0, 'CNAPS': -7500.0, 'OSTIE': -7500.0, 'CNAPS_ER': 97500.0,
    'OSTIE_ER': 37500.0, 'NETIMP': 735000.0, 'IRSA': -54500.0, 'NET': 680500.0}
# compte -> [débit, crédit]
EXPECTED_MOVE = {
    '652100': [750000.0, 0.0], '652500': [135000.0, 0.0],
    '315100': [0.0, 680500.0], '315200': [0.0, 105000.0],
    '315300': [0.0, 45000.0], '315400': [0.0, 54500.0]}
ACCOUNT_CODES = ('652100', '652500', '315100', '315200', '315300', '315400')


@tagged('post_install', '-at_install')
class TestPayrollAccounts(MowgliSmeTestMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.structure = cls.env['hr.payroll.structure'].search(
            [('code', '=', 'BASE')], limit=1)
        cls.companies = cls.env['res.company'].search(
            [('chart_template', '!=', False)])
        cls.Rule = cls.env['hr.salary.rule']

    def setUp(self):
        super().setUp()
        if not self.structure or not self.companies:
            self.skipTest("Données MOWGLI absentes de cette base.")
        self._mowgli_add_test_sme(250000.0)
        self.Account = self.env['account.account'].sudo()
        for company in self.companies:
            self.Rule._mf_ensure_payroll_accounts(company)

    def _enable_entries(self, company):
        journal = self.env['account.journal'].search(
            [('company_id', '=', company.id), ('type', '=', 'general'),
             ('code', '!=', 'CSOC')], limit=1)
        company.write({'hr_payroll_entries': True,
                       'payroll_journal_id': journal.id})

    def _slip(self, company):
        self._enable_entries(company)
        employee = self.env['hr.employee'].create(
            {'name': 'Employé comptes', 'company_id': company.id})
        contract = self.env['hr.contract'].create({
            'name': 'Contrat comptes', 'employee_id': employee.id,
            'company_id': company.id, 'wage': 600000, 'travel_allowance': 150000,
            'state': 'open', 'struct_id': self.structure.id,
            'date_start': '2026-01-01'})
        slip = self.env['hr.payslip'].with_company(company).create({
            'name': 'Bulletin comptes', 'employee_id': employee.id,
            'contract_id': contract.id, 'struct_id': self.structure.id,
            'company_id': company.id,
            'date_from': '2026-10-01', 'date_to': '2026-10-10'})
        slip.action_payslip_verify()
        slip.action_payslip_done()
        return slip

    def _by_account(self, move):
        totals = {}
        for line in move.line_ids:
            entry = totals.setdefault(line.account_id.code, [0.0, 0.0])
            entry[0] += line.debit
            entry[1] += line.credit
        return totals

    def _check_slip(self, slip):
        totals = {l.code: l.total for l in slip.line_ids}
        self.assertEqual({k: totals[k] for k in EXPECTED_AMOUNTS}, EXPECTED_AMOUNTS,
                         "montants calculés : %s" % totals)
        move = slip.move_id
        self.assertEqual(move.state, 'posted')
        self.assertEqual(len(move.line_ids), 6, "une seule ligne par compte")
        self.assertEqual(self._by_account(move), EXPECTED_MOVE)
        self.assertEqual(sum(move.line_ids.mapped('debit')), 885000.0)
        self.assertEqual(sum(move.line_ids.mapped('credit')), 885000.0)
        self.assertFalse(slip.mowgli_csoc_move_id,
                         "la part patronale n'est pas comptée deux fois")
        self.assertEqual(len(slip.mowgli_contribution_ids), 5)

    def test_ecriture_complete_des_trois_societes(self):
        for company in self.companies.filtered('active'):
            self._check_slip(self._slip(company))

    def test_configuration_des_regles(self):
        company = self.companies.filtered('active')[:1]
        expected = {
            ('CNAPS', 'credit'): '315200', ('OSTIE', 'credit'): '315300',
            ('IRSA', 'credit'): '315400', ('NET', 'credit'): '315100',
            ('CNAPS_ER', 'debit'): '652500', ('CNAPS_ER', 'credit'): '315200',
            ('OSTIE_ER', 'debit'): '652500', ('OSTIE_ER', 'credit'): '315300',
            ('BASIC', 'debit'): '652100', ('Travel', 'debit'): '652100'}
        rules = {r.code: r for r in self.structure.rule_ids}
        for (code, role), account in expected.items():
            value = rules[code].sudo().with_company(company)[role + '_account_id']
            self.assertEqual(value.code, account, "%s %s" % (code, role))
        for code in ('GROSS', 'NETIMP'):
            scoped = rules[code].sudo().with_company(company)
            self.assertFalse(scoped.debit_account_id or scoped.credit_account_id)

    def test_resultat_perte_identique_compte_de_resultat_et_bilan(self):
        company = self.companies.filtered('active')[:1]
        before = self._reports(company)
        self._check_slip(self._slip(company))
        after = self._reports(company)
        self.assertEqual(after['expense'] - before['expense'], 885000.0)
        self.assertEqual(after['net'] - before['net'], -885000.0)
        self.assertEqual(after['bilan'] - before['bilan'], -885000.0)

    def _reports(self, company):
        """Valeurs des lignes « Charges d'exploitation », « Résultat net » du
        Compte de résultat et « Résultat de l'exercice » du Bilan."""
        self.env.flush_all()
        values = {}
        for key, xmlid in (('pl', 'account_financial_report_profitandloss0'),
                           ('bs', 'account_financial_report_balancesheet0')):
            wizard = self.env['financial.report'].with_context(
                allowed_company_ids=[company.id]).create({
                    'account_report_id': self.env.ref('base_accounting_kit.' + xmlid).id,
                    'date_to': '2026-12-31', 'company_id': company.id,
                    'target_move': 'posted'})
            data = {'form': wizard.read([
                'date_from', 'enable_filter', 'debit_credit', 'date_to',
                'account_report_id', 'target_move', 'view_format', 'company_id',
                'journal_ids'])[0]}
            data['form']['used_context'] = dict(
                wizard._build_contexts(data), lang='en_US')
            lines = {l['name']: l['balance'] for l in wizard.get_account_lines(data['form'])}
            values[key] = lines
        pl, bs = values['pl'], values['bs']
        return {
            'expense': pl.get('Expenses', 0.0),
            'net': pl.get('Résultat net', pl.get('Net Profit', 0.0)),
            'bilan': bs.get('Profit (Loss) to report', 0.0)}

    def test_societe_neuve_recoit_comptes_et_ecriture(self):
        company = self.env['res.company'].create(
            {'name': 'Agence test paie neuve', 'agency_code': 'ZPN'})
        self.env['account.chart.template'].try_loading(
            'mg_pcec', company, install_demo=False)
        for code in ACCOUNT_CODES:
            self.assertEqual(self.Account.search_count(
                [('code', '=', code), ('company_id', '=', company.id)]), 1, code)
        rules = {r.code: r for r in self.structure.rule_ids}
        self.assertEqual(
            rules['NET'].sudo().with_company(company).credit_account_id.code, '315100')
        self.assertEqual(
            rules['CNAPS_ER'].sudo().with_company(company).debit_account_id.code, '652500')
        self._check_slip(self._slip(company))

    def test_script_idempotent_sans_doublon(self):
        company = self.companies.filtered('active')[:1]
        first = self.Rule._mf_ensure_payroll_accounts(company)
        second = self.Rule._mf_ensure_payroll_accounts(company)
        self.assertEqual((second['created'], second['rules']), ([], []))
        self.assertEqual((first['created'], first['rules']), ([], []))
        for code in ACCOUNT_CODES:
            self.assertEqual(self.Account.search_count(
                [('code', '=', code), ('company_id', '=', company.id)]), 1)

    def test_regle_mal_configuree_corrigee_et_compte_manquant_cree(self):
        company = self.companies.filtered('active')[:1]
        net = self.structure.rule_ids.filtered(lambda r: r.code == 'NET').sudo()
        other = self.Account.search(
            [('code', '=', '315000'), ('company_id', '=', company.id)], limit=1)
        net.with_company(company).write({'credit_account_id': other.id})
        irsa = self.structure.rule_ids.filtered(lambda r: r.code == 'IRSA').sudo()
        irsa.with_company(company).write({'credit_account_id': False})
        self.Account.search(
            [('code', '=', '315400'), ('company_id', '=', company.id)]).unlink()
        result = self.Rule._mf_ensure_payroll_accounts(company)
        self.assertEqual(result['created'], ['315400'])
        self.assertIn(('NET', 'credit', '315000', '315100'), result['rules'])

    def test_compte_de_nature_differente_arrete_tout(self):
        company = self.companies.filtered('active')[:1]
        account = self.Account.search(
            [('code', '=', '315200'), ('company_id', '=', company.id)], limit=1)
        account.reconcile = False
        with self.assertRaisesRegex(UserError, "nature différente"):
            self.Rule._mf_ensure_payroll_accounts(company)

    def test_formules_inchangees(self):
        rules = {r.code: r for r in self.structure.rule_ids}
        self.assertIn("categories.BASIC + categories.Travel + categories.ALW",
                      rules['GROSS'].amount_python_compute)
        self.assertEqual(rules['NET'].amount_python_compute,
                         "result = categories.GROSS + categories.DED")
