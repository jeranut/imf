# -*- coding: utf-8 -*-
import base64
import io

import xlsxwriter

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase

from ..models import microfinance_opening_xlsx as xlsx
from .common import MicrofinanceNoFundMixin


def _workbook(rows, header=True):
    """Classeur .xlsx en mémoire : lignes = listes de cellules (texte ou nombre)."""
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    sheet = workbook.add_worksheet('Balance')
    if header:
        sheet.write_row(0, 0, xlsx.HEADERS)
    for number, row in enumerate(rows, start=1 if header else 0):
        for col, value in enumerate(row):
            if isinstance(value, (int, float)):
                sheet.write_number(number, col, value)
            elif value is not None:
                sheet.write_string(number, col, value)
    workbook.close()
    return base64.b64encode(output.getvalue())


class TestOpeningBalance(MicrofinanceNoFundMixin, TransactionCase):
    """Balance d'ouverture : équilibre, double validation, écritures antérieures, modèle, import Excel, droits."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({'name': 'Agence OB (test)', 'agency_code': 'ZO1'})
        cls.other = cls.env['res.company'].create({'name': 'Agence OB 2 (test)', 'agency_code': 'ZO2'})
        cls.bank = cls._acc(cls.company, '131101', 'asset_cash')
        cls.cash = cls._acc(cls.company, '101000', 'asset_cash')
        cls.capital = cls._acc(cls.company, '563000', 'equity')
        cls.principal = cls._acc(cls.company, '203001', 'asset_current')
        cls.other_account = cls._acc(cls.other, '563000', 'equity')
        cls.an = cls._journal(cls.company, 'AN', 'general')
        cls.other_an = cls._journal(cls.other, 'AN', 'general')
        cls.bank_journal = cls._journal(cls.company, 'BMCR', 'bank', cls.bank)
        cls.partner = cls.env['res.partner'].create({'name': 'Bailleur OB test'})

    @classmethod
    def _acc(cls, company, code, account_type):
        return cls.env['account.account'].create({'code': code, 'name': 'Test ' + code, 'account_type': account_type,
                                                  'company_id': company.id})

    @classmethod
    def _journal(cls, company, code, jtype, account=None):
        vals = {'name': 'Journal ' + code, 'code': code, 'type': jtype, 'company_id': company.id}
        if account:
            vals['default_account_id'] = account.id
        return cls.env['account.journal'].create(vals)

    def _balance(self, lines=None, date='2026-10-10', company=None, user=None):
        company = company or self.company
        Balance = self.env['microfinance.opening.balance'].with_context(mf_opening_allow_multiple=True)
        if user:
            Balance = Balance.with_user(user)
        return Balance.create({
            'company_id': company.id, 'date': date,
            'line_ids': [(0, 0, {'account_id': a.id, 'debit': d, 'credit': c}) for a, d, c in (lines or [])]})

    def _balanced(self, **kw):
        return self._balance([(self.bank, 1000.0, 0.0), (self.cash, 500.0, 0.0), (self.capital, 0.0, 1500.0)], **kw)

    # ------------------------------------------------------------------ équilibre et validation
    def test_default_date_is_today_and_validation_creates_one_move_then_locks(self):
        balance = self.env['microfinance.opening.balance'].with_context(mf_opening_allow_multiple=True).create({
            'company_id': self.company.id})
        self.assertEqual(balance.date, self.env['microfinance.opening.balance']._fields['date'].default(balance))
        balance.unlink()  # une seule balance en brouillon par société
        balance = self._balanced()
        balance.action_validate()
        self.assertEqual(balance.state, 'validated')
        move = balance.move_id
        self.assertEqual((move.state, move.journal_id, str(move.date), move.company_id),
                         ('posted', self.an, '2026-10-10', self.company))
        self.assertEqual(len(move.line_ids), 3)
        self.assertEqual(sum(move.line_ids.mapped('debit')), sum(move.line_ids.mapped('credit')))
        with self.assertRaises(UserError):
            balance.date = '2026-10-11'
        with self.assertRaises(UserError):
            balance.line_ids[0].debit = 5.0
        with self.assertRaises(UserError):
            balance.line_ids[0].unlink()
        with self.assertRaises(UserError):
            balance.unlink()

    def test_unbalanced_balance_is_refused(self):
        balance = self._balance([(self.bank, 1000.0, 0.0), (self.capital, 0.0, 900.0)])
        self.assertEqual(balance.difference, 100.0)
        with self.assertRaises(UserError):
            balance.action_validate()
        self.assertEqual(balance.state, 'draft')
        self.assertFalse(balance.move_id)

    def test_empty_or_zero_balance_is_refused_and_zero_lines_are_not_posted(self):
        empty = self._balance([(self.bank, 0.0, 0.0)])
        with self.assertRaises(UserError):
            empty.action_validate()
        empty.unlink()  # une seule balance en brouillon par société
        balance = self._balance([(self.bank, 100.0, 0.0), (self.cash, 0.0, 0.0), (self.capital, 0.0, 100.0)])
        balance.action_validate()
        self.assertEqual(len(balance.move_id.line_ids), 2)

    def test_both_debit_and_credit_or_negative_amount_refused(self):
        with self.assertRaises(ValidationError):
            self._balance([(self.bank, 10.0, 10.0)])
        with self.assertRaises(ValidationError):
            self._balance([(self.bank, -10.0, 0.0)])

    def test_second_validation_for_the_same_company_is_refused(self):
        self._balanced().action_validate()
        second = self._balanced(date='2026-10-12')
        with self.assertRaises(UserError):
            second.action_validate()
        self.assertEqual(second.state, 'draft')
        # une autre société n'est pas concernée
        other = self._balance([(self.other_account, 10.0, 0.0), (self.other_account, 0.0, 10.0)], company=self.other)
        other.action_validate()
        self.assertEqual(other.state, 'validated')

    def test_posted_entries_before_the_opening_date_refuse_validation(self):
        self.env['account.move'].with_company(self.company).create({
            'move_type': 'entry', 'journal_id': self.an.id, 'date': '2026-10-01', 'company_id': self.company.id,
            'line_ids': [(0, 0, {'account_id': self.bank.id, 'debit': 5.0, 'credit': 0.0}),
                         (0, 0, {'account_id': self.capital.id, 'debit': 0.0, 'credit': 5.0})]}).action_post()
        balance = self._balanced(date='2026-10-10')
        with self.assertRaises(UserError):
            balance.action_validate()
        balance.unlink()  # une seule balance en brouillon par société
        self._balanced(date='2026-10-01').action_validate()  # écriture le même jour : pas antérieure

    def test_validation_needs_the_opening_journal(self):
        self.an.unlink()
        with self.assertRaises(UserError):
            self._balanced().action_validate()

    # ------------------------------------------------------------------ modèle
    def test_load_template_fills_zero_lines_for_existing_accounts_only(self):
        balance = self._balance()
        balance.action_load_template()
        codes = set(balance.line_ids.mapped('account_code'))
        self.assertTrue({'101000', '131101', '563000', '203001'} <= codes)  # modèle + compte du journal de banque
        self.assertFalse(any(balance.line_ids.mapped('debit')) or any(balance.line_ids.mapped('credit')))
        self.assertIn('213001', balance._missing_template_codes())  # compte du modèle absent de la société de test
        count = len(balance.line_ids)
        balance.action_load_template()
        self.assertEqual(len(balance.line_ids), count)  # pas de doublon au deuxième chargement

    def test_template_accounts_list_is_configurable_data(self):
        templates = self.env['microfinance.opening.template'].search([])
        self.assertTrue({'101000', '203001', '213001', '563000'} <= set(templates.mapped('code')))

    # ------------------------------------------------------------------ Excel
    def test_downloaded_template_can_be_read_back(self):
        balance = self._balanced()
        content = balance._template_workbook()
        rows = xlsx.read_rows(content)
        self.assertEqual(rows[0][1][:5], xlsx.HEADERS)
        by_code = {r[1][0]: r[1] for r in rows[1:]}
        self.assertEqual(by_code['131101'][3], 1000.0)
        self.assertEqual(by_code['563000'][4], 1500.0)

    def test_import_reports_each_faulty_row_and_imports_nothing(self):
        balance = self._balance()
        wizard = self.env['microfinance.opening.balance.import'].create({
            'balance_id': balance.id, 'filename': 'x.xlsx', 'file': _workbook([
                ['131101', 'ok', None, 100.0, 0.0],             # ligne 2 : valide
                ['999999', 'inconnu', None, 5.0, 0.0],           # ligne 3 : compte inconnu
                ['101000', 'texte', None, 'abc', 0.0],           # ligne 4 : montant invalide
                ['563000', 'négatif', None, -5.0, 0.0],          # ligne 5 : négatif
                ['203001', 'deux', None, 5.0, 5.0],              # ligne 6 : débit et crédit
                ['563000', 'partenaire', 'Personne inconnue', 0.0, 10.0],  # ligne 7 : partenaire inconnu
            ])})
        valid, errors = wizard._parse()
        self.assertEqual([n for n, _m in errors], [3, 4, 5, 6, 7])
        self.assertEqual(len(valid), 1)
        by_row = dict(errors)
        self.assertIn('compte inconnu', by_row[3])
        self.assertIn('montant invalide', by_row[4])
        self.assertIn('négatif', by_row[5])
        self.assertIn('ensemble', by_row[6])
        self.assertIn('partenaire inconnu', by_row[7])
        wizard.action_import()
        self.assertTrue(wizard.has_errors)
        self.assertFalse(balance.line_ids)  # tout ou rien
        self.assertIn('Fichier refusé', wizard.report)

    def test_valid_import_creates_and_updates_lines_and_then_validates(self):
        balance = self._balance([(self.bank, 1.0, 0.0)])
        wizard = self.env['microfinance.opening.balance.import'].create({
            'balance_id': balance.id, 'filename': 'ok.xlsx', 'file': _workbook([
                ['131101', 'Banque', None, 700.0, 0.0],
                ['101000', 'Caisse', None, '300,00', 0.0],
                ['563000', 'Capital', 'Bailleur OB test', 0.0, 1000.0]])})
        wizard.action_import()
        self.assertFalse(wizard.has_errors)
        self.assertEqual(len(balance.line_ids), 3)  # la ligne 131101 existante est mise à jour, pas dupliquée
        self.assertEqual(balance.line_ids.filtered(lambda l: l.account_code == '131101').debit, 700.0)
        self.assertEqual(balance.line_ids.filtered(lambda l: l.account_code == '101000').debit, 300.0)
        self.assertEqual(balance.line_ids.filtered(lambda l: l.account_code == '563000').partner_id, self.partner)
        balance.action_validate()
        self.assertEqual(balance.state, 'validated')

    def test_import_rejects_a_file_that_is_not_excel(self):
        balance = self._balance()
        wizard = self.env['microfinance.opening.balance.import'].create({
            'balance_id': balance.id, 'file': base64.b64encode(b'pas un classeur')})
        valid, errors = wizard._parse()
        self.assertFalse(valid)
        self.assertIn('Excel', errors[0][1])

    # ------------------------------------------------------------------ point de départ des relevés
    def test_bank_balance_is_the_starting_point_of_the_first_statement(self):
        self.assertIsNone(self.env['microfinance.opening.balance'].bank_starting_balance(self.bank_journal, '2026-10-20'))
        self._balanced().action_validate()
        Balance = self.env['microfinance.opening.balance']
        self.assertEqual(Balance.bank_starting_balance(self.bank_journal, '2026-10-20'), 1000.0)
        self.assertIsNone(Balance.bank_starting_balance(self.bank_journal, '2026-10-09'))  # avant l'ouverture
        statement = self.env['account.bank.statement'].new({
            'journal_id': self.bank_journal.id, 'mf_state': 'draft',
            'mf_datetime_from': '2026-10-20 05:00:00', 'mf_datetime_to': '2026-10-20 09:00:00'})
        statement._onchange_mf_previous_balance()
        self.assertEqual(statement.balance_start, 1000.0)

    # ------------------------------------------------------------------ droits et menu
    def test_access_rights_and_company_isolation(self):
        base = self.env.ref('base.group_user')
        finance = self.env.ref('microfinance_loan_management.group_microfinance_finance')
        auditor = self.env.ref('microfinance_loan_management.group_microfinance_auditor')
        make = lambda login, group, company: self.env['res.users'].with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'company_id': company.id, 'company_ids': [(6, 0, [company.id])],
            'groups_id': [(6, 0, [base.id, group.id])]})
        finance_user = make('ob_finance', finance, self.company)
        auditor_user = make('ob_auditor', auditor, self.company)
        balance = self._balance(user=finance_user)  # la finance saisit
        other = self._balance(company=self.other)
        visible = self.env['microfinance.opening.balance'].with_user(auditor_user).search([])
        self.assertIn(balance, visible)
        self.assertNotIn(other, visible)  # jamais une autre société
        with self.assertRaises(AccessError):
            self.env['microfinance.opening.balance'].with_user(auditor_user).create({'company_id': self.company.id})
        with self.assertRaises(AccessError):
            balance.with_user(auditor_user).write({'date': '2026-10-11'})
        with self.assertRaises(AccessError):
            other.with_user(finance_user).read(['name'])

    def test_menu_is_in_accounting_for_finance_and_accountant_not_in_configuration_or_cash(self):
        menu = self.env.ref('microfinance_loan_management.menu_microfinance_opening_balance')
        self.assertEqual(menu.parent_id, self.env.ref('account.menu_finance_entries'))
        groups = menu.groups_id
        for xmlid in ('microfinance_loan_management.group_microfinance_finance',
                      'microfinance_loan_management.group_microfinance_comptable',
                      'microfinance_loan_management.group_microfinance_auditor'):
            self.assertIn(self.env.ref(xmlid), groups)
        self.assertNotIn(self.env.ref('microfinance_loan_management.group_microfinance_cashier'), groups)
        ancestors, parent = [], menu
        while parent:
            ancestors.append(parent)
            parent = parent.parent_id
        self.assertNotIn(self.env.ref('microfinance_loan_management.menu_caisse_root'), ancestors)
        self.assertNotIn(self.env.ref('account.menu_finance_configuration'), ancestors)
