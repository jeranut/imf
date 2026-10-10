# -*- coding: utf-8 -*-
from types import SimpleNamespace
from unittest.mock import patch

from odoo.http import Response
from odoo.tools import file_open

from odoo.addons.base_accounting_kit.controllers import journal_ledger_report_controller as journal_ctrl

from ..controllers import general_ledger_report as gl_ctrl
from ..controllers import trial_balance_report as tb_ctrl
from ..controllers.trial_balance_report import TrialBalanceReportController
from .test_general_ledger import D_FROM, D_TO, TestGeneralLedger


class TestTrialBalance(TestGeneralLedger):
    """Balance générale interactive : mêmes chiffres que le Grand livre, classes, témoin d'équilibre, exports."""

    def _balance(self, company=None, journal_ids=(), target_move='posted', display='all', init=True, search=None,
                 user=None):
        company = company or self.agency
        model = self.env['account.trial.balance.report']
        model = model.with_user(user) if user else model.with_company(company)
        data = model.get_balance(
            company, list(journal_ids), D_FROM, D_TO, target_move, display, init, search)
        return {a['code']: a for a in data['accounts']}, data

    # ------------------------------------------------------------------ chiffres
    def test_each_account_opening_plus_movements_equals_closing_and_set_is_balanced(self):
        accounts, data = self._balance()
        for a in accounts.values():
            self.assertAlmostEqual(a['opening_debit'] - a['opening_credit'] + a['debit'] - a['credit'],
                                   a['closing_debit'] - a['closing_credit'], 2, a['code'])
        totals = data['totals']
        for debit, credit in (('opening_debit', 'opening_credit'), ('debit', 'credit'),
                              ('closing_debit', 'closing_credit')):
            self.assertAlmostEqual(totals[debit], totals[credit], 2)

    def test_balance_never_has_both_columns_filled(self):
        accounts, _ = self._balance()
        for a in accounts.values():
            self.assertFalse(a['opening_debit'] and a['opening_credit'], a['code'])
            self.assertFalse(a['closing_debit'] and a['closing_credit'], a['code'])
        self.assertEqual(accounts['T131999G']['closing_debit'], 70000000.0)
        self.assertEqual(accounts['T563000G']['closing_credit'], 10000000.0)

    def test_totals_identical_to_the_general_ledger_for_the_same_filters(self):
        for kwargs in ({}, {'journal_ids': [self.journal_b.id], 'display': 'movement'},
                       {'target_move': 'all'}, {'display': 'not_zero', 'init': False}, {'search': 'T1319'}):
            balance, _ = self._balance(**kwargs)
            ledger, _ = self._accounts(**kwargs)
            self.assertEqual(set(balance), set(ledger), kwargs)
            for code, row in ledger.items():
                for key in ('opening', 'debit', 'credit', 'closing'):
                    self.assertEqual(balance[code][key], row[key], (code, key, kwargs))

    def test_opening_entry_before_period_is_in_opening_and_period_entry_is_not(self):
        accounts, _ = self._balance()
        self.assertEqual(accounts['T131999G']['opening_debit'], 10000000.0)
        self.assertEqual(accounts['T131999G']['debit'], 100000000.0)
        no_init, _ = self._balance(init=False)
        self.assertEqual(no_init['T131999G']['opening_debit'], 0.0)

    # ------------------------------------------------------------------ filtres
    def test_filters_journal_posted_all_movement_not_zero(self):
        by_journal, _ = self._balance(journal_ids=[self.journal_b.id], display='movement')
        self.assertEqual(set(by_journal), {'T622000G', 'T131999G'})
        posted, _ = self._balance(display='movement')
        everything, _ = self._balance(target_move='all', display='movement')
        self.assertEqual(posted['T762000G']['credit'], 100000000.0)
        self.assertEqual(everything['T762000G']['credit'], 100001000.0)  # le brouillon seulement avec « toutes »
        movement, _ = self._balance(display='movement')
        not_zero, _ = self._balance(display='not_zero')
        self.assertNotIn('T499999G', movement)
        self.assertIn('T498888G', movement)
        self.assertNotIn('T498888G', not_zero)
        self.assertEqual(set(self._balance(search='T131999')[0]), {'T131999G'})

    # ------------------------------------------------------------------ classes
    def test_class_subtotals_sum_to_grand_total_and_class_is_first_digit(self):
        for code, kind in (('131777', 'asset_cash'), ('563777', 'equity')):
            self._acc(self.agency, code, kind, False)
        self._gl_post(self.agency, self.journal_a, '2026-02-01', [
            (self.env['account.account'].search([('code', '=', '131777'), ('company_id', '=', self.agency.id)]), 70.0, 0.0),
            (self.env['account.account'].search([('code', '=', '563777'), ('company_id', '=', self.agency.id)]), 0.0, 70.0)])
        self.env.flush_all()
        accounts, data = self._balance()
        self.assertEqual({g['key'] for g in data['classes']}, {c[0] if c[0].isdigit() else '?' for c in accounts})
        self.assertTrue({'1', '5', '?'} <= {g['key'] for g in data['classes']})
        for key in ('opening_debit', 'opening_credit', 'debit', 'credit', 'closing_debit', 'closing_credit'):
            self.assertAlmostEqual(sum(g[key] for g in data['classes']), data['totals'][key], 2, key)
        for group in data['classes']:
            self.assertTrue(all((a['code'][0] if a['code'][0].isdigit() else '?') == group['key']
                                for a in group['accounts']))
            if group['key'] != '?':
                self.assertTrue(group['label'].startswith('Classe %s' % group['key']))

    # ------------------------------------------------------------------ témoin d'équilibre
    def test_balance_check_is_ok_then_shows_the_gap_after_a_raw_sql_imbalance(self):
        _accounts, data = self._balance()
        self.assertTrue(data['balance_check']['balanced'])
        line = self.env['account.move.line'].search([
            ('account_id.code', '=', 'T622000G'), ('company_id', '=', self.agency.id), ('parent_state', '=', 'posted')],
            limit=1)
        self.env.cr.execute("UPDATE account_move_line SET debit = debit + 250 WHERE id = %s", (line.id,))
        self.env['account.move.line'].invalidate_model()
        _accounts, data = self._balance()
        check = data['balance_check']
        self.assertFalse(check['balanced'])
        self.assertEqual(check['gaps']['movements'], 250.0)
        self.assertEqual(abs(check['gap']), 250.0)
        # le témoin ignore les filtres d'affichage et la recherche
        self.assertFalse(self._balance(display='movement', search='T1319')[1]['balance_check']['balanced'])

    # ------------------------------------------------------------------ clic vers le Grand livre
    def test_account_click_target_gives_the_right_account_period_and_journals(self):
        bank = self._balance(search='T131999')[0]['T131999G']
        data = self.Report.with_company(self.agency).get_accounts(
            self.agency, [self.journal_b.id], D_FROM, D_TO, 'posted', 'all', True, None, bank['id'])
        self.assertEqual([a['code'] for a in data['accounts']], ['T131999G'])
        self.assertEqual(data['accounts'][0]['credit'], 40000000.0)  # journal B seulement, sur la période
        everything = self.Report.with_company(self.agency).get_accounts(
            self.agency, [], D_FROM, D_TO, 'posted', 'all', True, None, 'pas-un-id')
        self.assertEqual(everything['accounts'], [])
        with file_open('microfinance_loan_management/static/src/js/trial_balance_report.js') as js:
            source = js.read()
        for expected in ('microfinance_loan_management.general_ledger', 'accountId: account.id', 'dateFrom: this.state.dateFrom',
                         'dateTo: this.state.dateTo', 'selectedJournalIds', 'targetMove: this.state.targetMove'):
            self.assertIn(expected, source)

    # ------------------------------------------------------------------ société et droits
    def test_agency_user_never_sees_another_companys_lines(self):
        hq_account = self._acc(self.hq, 'T131998H', 'asset_cash', False)
        hq_equity = self._acc(self.hq, 'T563001H', 'equity', False)
        self._gl_post(self.hq, self._gl_journal(self.hq, 'TGLH'), '2026-03-01',
                      [(hq_account, 888.0, 0.0), (hq_equity, 0.0, 888.0)])
        self.env.flush_all()
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Comptable agence TB', 'login': 'tb_agency_user', 'company_id': self.agency.id,
            'company_ids': [(6, 0, [self.agency.id])],
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id, self.env.ref('account.group_account_user').id])]})
        accounts, _ = self._balance(company=self.hq, target_move='all', user=user)
        self.assertEqual(accounts, {})
        fake = SimpleNamespace(env=self.env(user=user))
        with patch.object(tb_ctrl, 'request', fake), patch.object(gl_ctrl, 'request', fake), \
                patch.object(journal_ctrl, 'request', fake):
            result = TrialBalanceReportController().trial_balance_data(
                date_from=D_FROM, date_to=D_TO, company_id=self.hq.id)
        self.assertTrue(result['success'])
        self.assertEqual(result['company_name'], self.agency.name)
        self.assertNotIn('T131998H', [a['code'] for a in result['data']['accounts']])

    # ------------------------------------------------------------------ exports et menu
    def test_pdf_and_xlsx_are_generated_with_current_filters(self):
        fake = SimpleNamespace(env=self.env, make_response=lambda data, headers=None: Response(data, headers=headers))
        kw = {'date_from': D_FROM, 'date_to': D_TO, 'target_move': 'posted', 'company_id': self.agency.id,
              'journal_ids': str(self.journal_a.id), 'display_account': 'movement', 'init_balance': 'true',
              'search': ''}
        with patch.object(tb_ctrl, 'request', fake), patch.object(gl_ctrl, 'request', fake), \
                patch.object(journal_ctrl, 'request', fake):
            xlsx = TrialBalanceReportController().trial_balance_xlsx(**kw)
            pdf = TrialBalanceReportController().trial_balance_pdf(**kw)
        self.assertTrue(xlsx.data.startswith(b'PK'))
        self.assertIn('spreadsheetml', xlsx.headers.get('Content-Type'))
        self.assertTrue(pdf.data)
        self.assertEqual(pdf.headers.get('Content-Type'), 'application/pdf')

    def test_menu_opens_the_interactive_screen_and_old_wizard_is_kept(self):
        menu = self.env.ref('base_accounting_kit.menu_Balance_report')
        self.assertEqual(menu.action._name, 'ir.actions.client')
        self.assertEqual(menu.action.tag, 'microfinance_loan_management.trial_balance')
        self.assertFalse(menu.groups_id)
        self.assertTrue(self.env.ref('base_accounting_kit.action_account_balance_menu').exists())
        self.assertTrue(self.env['ir.model']._get('account.balance.report'))
        ledger_menu = self.env.ref('base_accounting_kit.menu_general_ledger')
        self.assertEqual(ledger_menu.action.tag, 'microfinance_loan_management.general_ledger')
