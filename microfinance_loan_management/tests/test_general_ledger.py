# -*- coding: utf-8 -*-
from types import SimpleNamespace
from unittest.mock import patch

from odoo.http import Response
from odoo.tests import TransactionCase

from odoo.addons.base_accounting_kit.controllers import journal_ledger_report_controller as journal_ctrl

from ..controllers import general_ledger_report as gl_ctrl
from ..controllers.general_ledger_report import GeneralLedgerReportController

D_FROM, D_TO = '2026-01-01', '2026-12-31'


class TestGeneralLedger(TransactionCase):
    """Grand livre interactif : soldes, filtres, pagination, sociétés, exports."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Report = cls.env['account.general.ledger.report']
        cls.agency = cls.env['res.company'].create({'name': 'Agence GL (test)', 'agency_code': 'ZG1'})
        cls.hq = cls.env['res.company'].create({'name': 'Siège GL (test)', 'agency_code': 'ZG2'})
        ag = cls.agency
        cls.bank = cls._acc(ag, 'T131999G', 'asset_cash', False)
        cls.capital = cls._acc(ag, 'T563000G', 'equity', False)
        cls.subvention = cls._acc(ag, 'T762000G', 'income_other', False)
        cls.charge = cls._acc(ag, 'T622000G', 'expense', False)
        cls.unused = cls._acc(ag, 'T499999G', 'liability_current', False)
        cls.settled = cls._acc(ag, 'T498888G', 'liability_current', False)
        cls.journal_a = cls._gl_journal(ag, 'TGLA')
        cls.journal_b = cls._gl_journal(ag, 'TGLB')
        # écriture d'ouverture avant la période ; mouvements dans la période, dont un brouillon
        cls._gl_post(ag, cls.journal_a, '2025-12-31', [(cls.bank, 10000000.0, 0.0), (cls.capital, 0.0, 10000000.0)])
        cls._gl_post(ag, cls.journal_a, '2026-03-01', [(cls.bank, 100000000.0, 0.0), (cls.subvention, 0.0, 100000000.0)])
        cls._gl_post(ag, cls.journal_b, '2026-04-01', [(cls.charge, 40000000.0, 0.0), (cls.bank, 0.0, 40000000.0)])
        cls._gl_post(ag, cls.journal_a, '2026-05-01', [(cls.settled, 500.0, 0.0), (cls.capital, 0.0, 500.0)])
        cls._gl_post(ag, cls.journal_a, '2026-05-02', [(cls.capital, 500.0, 0.0), (cls.settled, 0.0, 500.0)])
        cls.draft = cls._gl_post(ag, cls.journal_a, '2026-06-01', [(cls.bank, 1000.0, 0.0), (cls.subvention, 0.0, 1000.0)],
                                 post=False)
        cls.env.flush_all()

    @classmethod
    def _acc(cls, company, code, account_type, reconcile):
        return cls.env['account.account'].create({'code': code, 'name': 'Test ' + code, 'account_type': account_type,
                                                  'reconcile': reconcile, 'company_id': company.id})

    @classmethod
    def _gl_journal(cls, company, code):
        Journal = cls.env['account.journal']
        return Journal.search([('company_id', '=', company.id), ('code', '=', code)], limit=1) or Journal.create(
            {'name': 'Journal ' + code, 'code': code, 'type': 'general', 'company_id': company.id})

    @classmethod
    def _gl_post(cls, company, journal, date, lines, post=True):
        move = cls.env['account.move'].with_company(company).create({
            'move_type': 'entry', 'journal_id': journal.id, 'date': date, 'company_id': company.id,
            'line_ids': [(0, 0, {'account_id': a.id, 'debit': d, 'credit': c, 'name': 'test %s' % a.code})
                         for a, d, c in lines]})
        if post:
            move.action_post()
        return move

    def _accounts(self, company=None, journal_ids=(), target_move='posted', display='all', init=True, search=None):
        company = company or self.agency
        data = self.Report.with_company(company).get_accounts(
            company, list(journal_ids), D_FROM, D_TO, target_move, display, init, search)
        return {a['code']: a for a in data['accounts']}, data

    # ------------------------------------------------------------------ soldes
    def test_opening_plus_movements_equals_closing_and_all_accounts_sum_to_zero(self):
        accounts, data = self._accounts()
        for account in accounts.values():
            self.assertAlmostEqual(account['opening'] + account['debit'] - account['credit'], account['closing'], 2)
        mine = [accounts[c] for c in ('T131999G', 'T563000G', 'T762000G', 'T622000G')]
        self.assertAlmostEqual(sum(a['closing'] for a in mine), 0.0, 2)  # jeu équilibré
        self.assertAlmostEqual(data['totals']['debit'] - data['totals']['credit'] + data['totals']['opening'],
                               data['totals']['closing'], 2)

    def test_opening_balance_includes_opening_entry_but_not_period_entries(self):
        accounts, _ = self._accounts()
        self.assertEqual(accounts['T131999G']['opening'], 10000000.0)
        self.assertEqual(accounts['T131999G']['debit'], 100000000.0)      # l'écriture d'ouverture n'est pas dans la période
        self.assertEqual(accounts['T131999G']['closing'], 70000000.0)
        no_init, _ = self._accounts(init=False)
        self.assertEqual(no_init['T131999G']['opening'], 0.0)
        self.assertEqual(no_init['T131999G']['closing'], 60000000.0)

    def test_totals_match_trial_balance_of_base_accounting_kit(self):
        accounts, _ = self._accounts(init=False)
        trial = self.env['report.base_accounting_kit.report_trial_balance'].with_company(self.agency).with_context(
            date_from=D_FROM, date_to=D_TO, strict_range=True, state='posted', company_id=self.agency.id,
            allowed_company_ids=[self.agency.id])
        rows = trial._get_accounts(self.env['account.account'].search([('company_id', '=', self.agency.id)]), 'movement')
        self.assertTrue(rows)
        for row in rows:
            self.assertAlmostEqual(accounts[row['code']]['debit'], row['debit'], 2, row['code'])
            self.assertAlmostEqual(accounts[row['code']]['credit'], row['credit'], 2, row['code'])
            self.assertAlmostEqual(accounts[row['code']]['closing'], row['balance'], 2, row['code'])

    # ------------------------------------------------------------------ filtres
    def test_journal_filter_keeps_only_those_journals(self):
        accounts, _ = self._accounts(journal_ids=[self.journal_b.id], display='movement')
        self.assertEqual(set(accounts), {'T622000G', 'T131999G'})
        self.assertEqual(accounts['T131999G']['credit'], 40000000.0)
        page = self.Report.get_lines(self.agency, accounts['T131999G']['id'], [self.journal_b.id], D_FROM, D_TO, 'posted')
        self.assertEqual({r['journal'] for r in page['rows']}, {'TGLB'})

    def test_draft_entry_only_in_all_entries_mode(self):
        posted, _ = self._accounts(display='movement')
        everything, _ = self._accounts(target_move='all', display='movement')
        self.assertEqual(posted['T762000G']['credit'], 100000000.0)
        self.assertEqual(everything['T762000G']['credit'], 100001000.0)

    def test_display_modes_movement_and_non_zero(self):
        everything, _ = self._accounts(display='all')
        movement, _ = self._accounts(display='movement')
        not_zero, _ = self._accounts(display='not_zero')
        self.assertIn('T499999G', everything)
        self.assertNotIn('T499999G', movement)                      # sans mouvement
        self.assertIn('T498888G', movement)                         # mouvements mais soldé
        self.assertNotIn('T498888G', not_zero)                      # soldé exclu
        self.assertIn('T131999G', not_zero)

    def test_search_by_code_or_label(self):
        accounts, _ = self._accounts(search='T131999')
        self.assertEqual(set(accounts), {'T131999G'})

    # ------------------------------------------------------------------ pagination
    def test_account_with_200_lines_loads_in_pages_of_80_with_running_balance(self):
        ag = self.agency
        extra = self._acc(ag, 'T611111G', 'expense', False)
        for i in range(100):
            self._gl_post(ag, self.journal_a, '2026-07-%02d' % (1 + i % 28),
                          [(extra, 10.0, 0.0), (self.bank, 0.0, 10.0)])
        self._gl_post(ag, self.journal_a, '2026-08-01', [(extra, 10.0, 0.0), (self.bank, 0.0, 10.0)])
        for _i in range(99):
            self._gl_post(ag, self.journal_a, '2026-08-02', [(extra, 10.0, 0.0), (self.bank, 0.0, 10.0)])
        self.env.flush_all()
        account = self._accounts(search='T611111')[0]['T611111G']
        self.assertEqual(account['count'], 200)
        rows = []
        for offset, expected in ((0, 80), (80, 80), (160, 40)):
            page = self.Report.get_lines(ag, account['id'], [], D_FROM, D_TO, 'posted', offset=offset, limit=80)
            self.assertEqual(len(page['rows']), expected)
            self.assertEqual(page['has_more'], offset + expected < 200)
            rows += page['rows']
        self.assertEqual([r['balance'] for r in rows], [10.0 * (i + 1) for i in range(200)])
        self.assertEqual(rows[-1]['balance'], account['closing'])
        self.assertEqual(len({r['line_id'] for r in rows}), 200)

    def test_running_balance_starts_from_opening_balance(self):
        bank = self._accounts(search='T131999')[0]['T131999G']
        page = self.Report.get_lines(self.agency, bank['id'], [], D_FROM, D_TO, 'posted')
        self.assertEqual(page['rows'][0]['balance'], 110000000.0)
        self.assertEqual(page['rows'][-1]['balance'], bank['closing'])

    # ------------------------------------------------------------------ sociétés et droits
    def test_agency_user_never_sees_another_companys_lines(self):
        hq_account = self._acc(self.hq, 'T131999H', 'asset_cash', False)
        hq_equity = self._acc(self.hq, 'T563000H', 'equity', False)
        self._gl_post(self.hq, self._gl_journal(self.hq, 'TGLH'), '2026-03-01',
                      [(hq_account, 777.0, 0.0), (hq_equity, 0.0, 777.0)])
        self.env.flush_all()
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Comptable agence GL', 'login': 'gl_agency_user', 'company_id': self.agency.id,
            'company_ids': [(6, 0, [self.agency.id])],
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id, self.env.ref('account.group_account_user').id])]})
        model = self.env['account.general.ledger.report'].with_user(user)
        data = model.get_accounts(self.hq, [], D_FROM, D_TO, 'all', 'all', True, None)  # société modifiée dans le filtre
        self.assertEqual(data['accounts'], [])
        lines = model.get_lines(self.hq, hq_account.id, [], D_FROM, D_TO, 'all')
        self.assertEqual(lines['rows'], [])
        # via le contrôleur : une société interdite retombe sur celle de l'utilisateur
        env = self.env(user=user)
        fake = SimpleNamespace(env=env)
        with patch.object(gl_ctrl, 'request', fake), patch.object(journal_ctrl, 'request', fake):
            result = GeneralLedgerReportController().general_ledger_data(
                date_from=D_FROM, date_to=D_TO, company_id=self.hq.id)
        self.assertTrue(result['success'])
        self.assertEqual(result['company_name'], self.agency.name)
        self.assertNotIn('T131999H', [a['code'] for a in result['data']['accounts']])

    # ------------------------------------------------------------------ exports
    def test_pdf_and_xlsx_are_generated_with_current_filters(self):
        fake = SimpleNamespace(env=self.env, make_response=lambda data, headers=None: Response(data, headers=headers))
        kw = {'date_from': D_FROM, 'date_to': D_TO, 'target_move': 'posted', 'company_id': self.agency.id,
              'journal_ids': str(self.journal_a.id), 'display_account': 'movement', 'sortby': 'sort_date',
              'init_balance': 'true', 'search': ''}
        with patch.object(gl_ctrl, 'request', fake), patch.object(journal_ctrl, 'request', fake):
            xlsx = GeneralLedgerReportController().general_ledger_xlsx(**kw)
            pdf = GeneralLedgerReportController().general_ledger_pdf(**kw)
        self.assertTrue(xlsx.data.startswith(b'PK'))
        self.assertIn('spreadsheetml', xlsx.headers.get('Content-Type'))
        self.assertTrue(pdf.data)
        self.assertEqual(pdf.headers.get('Content-Type'), 'application/pdf')

    def test_general_ledger_menu_opens_the_interactive_screen_and_old_wizard_is_kept(self):
        menu = self.env.ref('base_accounting_kit.menu_general_ledger')
        self.assertEqual(menu.action._name, 'ir.actions.client')
        self.assertEqual(menu.action.tag, 'microfinance_loan_management.general_ledger')
        self.assertFalse(menu.groups_id)
        self.assertTrue(self.env.ref('base_accounting_kit.action_account_general_ledger_menu').exists())
        self.assertTrue(self.env.ref('base_accounting_kit.action_report_general_ledger').exists())
