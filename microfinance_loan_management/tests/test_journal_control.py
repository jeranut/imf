# -*- coding: utf-8 -*-
from types import SimpleNamespace
from unittest.mock import patch

from odoo.http import Response

from odoo.addons.base_accounting_kit.controllers import journal_ledger_report_controller as journal_ctrl

from ..controllers import general_ledger_report as gl_ctrl
from ..controllers import journal_control_report as jc_ctrl
from ..controllers.journal_control_report import JournalControlReportController
from .test_general_ledger import D_FROM, D_TO, TestGeneralLedger


class TestJournalControl(TestGeneralLedger):
    """Contrôle des journaux interactif : totaux, anomalies, pagination, sociétés, exports."""

    def _control(self, company=None, journal_ids=(), target_move='posted', search=None, user=None):
        company = company or self.agency
        model = self.env['account.journal.control.report']
        model = model.with_user(user) if user else model.with_company(company)
        data = model.get_journals(company, list(journal_ids), D_FROM, D_TO, target_move, search)
        return {j['code']: j for j in data['journals']}, data

    def _numbered_journal(self, code, numbers, with_prefix='%s/2026/'):
        """Journal dont les pièces portent les numéros demandés (un trou = un numéro absent de la liste)."""
        journal = self._gl_journal(self.agency, code)
        moves = self.env['account.move']
        for n in numbers:
            move = self.env['account.move'].with_company(self.agency).create({
                'move_type': 'entry', 'journal_id': journal.id, 'date': '2026-05-10', 'company_id': self.agency.id,
                'name': (with_prefix % code) + str(n).zfill(5),
                'line_ids': [(0, 0, {'account_id': self.bank.id, 'debit': 10.0, 'credit': 0.0, 'name': 'n'}),
                             (0, 0, {'account_id': self.capital.id, 'debit': 0.0, 'credit': 10.0, 'name': 'n'})]})
            move.action_post()
            moves |= move
        self.env.flush_all()
        return journal, moves

    # ------------------------------------------------------------------ totaux
    def test_journal_totals_equal_their_lines_and_sum_to_the_general_ledger_total(self):
        for kwargs in ({}, {'target_move': 'all'}, {'journal_ids': [self.journal_a.id]}):
            by_code, data = self._control(**kwargs)
            ledger = self.Report.with_company(self.agency).get_accounts(
                self.agency, list(kwargs.get('journal_ids', [])), D_FROM, D_TO, kwargs.get('target_move', 'posted'),
                'all', False)
            self.assertAlmostEqual(data['totals']['debit'], ledger['totals']['debit'], 2, kwargs)
            self.assertAlmostEqual(data['totals']['credit'], ledger['totals']['credit'], 2, kwargs)
            for code, row in by_code.items():
                journal = self.env['account.journal'].browse(row['id'])
                domain = [('journal_id', '=', journal.id), ('date', '>=', D_FROM), ('date', '<=', D_TO),
                          ('parent_state', '=', 'posted' if kwargs.get('target_move') != 'all' else 'draft')]
                if kwargs.get('target_move') == 'all':
                    domain = [d for d in domain if d[0] != 'parent_state'] + [('parent_state', '!=', 'cancel')]
                lines = self.env['account.move.line'].search(domain)
                self.assertAlmostEqual(row['debit'], sum(lines.mapped('debit')), 2, code)
                self.assertAlmostEqual(row['credit'], sum(lines.mapped('credit')), 2, code)
        self.assertTrue(data['balanced'])

    # ------------------------------------------------------------------ anomalies
    def test_unbalanced_move_injected_in_database_is_detected_and_counted(self):
        by_code, data = self._control()
        self.assertEqual(by_code['TGLB']['anomalies']['unbalanced'], 0)
        self.assertEqual(by_code['TGLB']['status'], 'ok')
        line = self.env['account.move.line'].search([
            ('journal_id', '=', self.journal_b.id), ('account_id', '=', self.charge.id)], limit=1)
        self.env.cr.execute("UPDATE account_move_line SET debit = debit + 10 WHERE id = %s", (line.id,))
        self.env['account.move.line'].invalidate_model()
        by_code, data = self._control()
        self.assertEqual(by_code['TGLB']['anomalies']['unbalanced'], 1)
        self.assertEqual(by_code['TGLB']['status'], 'anomaly')
        self.assertEqual(data['totals']['anomalies']['unbalanced'], 1)
        self.assertFalse(data['balanced'])
        page = self.env['account.journal.control.report'].with_company(self.agency).get_moves(
            self.agency, self.journal_b.id, D_FROM, D_TO, 'posted', anomaly='unbalanced')
        self.assertEqual([r['move_id'] for r in page['rows']], [line.move_id.id])
        self.assertFalse(page['rows'][0]['balanced'])

    def test_numbering_gap_is_detected_with_the_missing_number(self):
        _journal, _moves = self._numbered_journal('TGLC', [1, 2, 4, 5])
        _journal2, _moves2 = self._numbered_journal('TGLD', [1, 2, 3])
        by_code, data = self._control()
        self.assertEqual(by_code['TGLC']['anomalies']['gaps'], 1)
        gap = by_code['TGLC']['gap_details'][0]
        self.assertEqual(gap['missing'], [3])
        self.assertEqual(gap['labels'], ['TGLC/2026/00003'])
        self.assertEqual(by_code['TGLC']['status'], 'info')  # information, pas une erreur
        self.assertEqual(by_code['TGLD']['anomalies'], {'unbalanced': 0, 'draft': 0, 'cancel': 0, 'gaps': 0})
        self.assertEqual(by_code['TGLD']['status'], 'ok')
        self.assertEqual(by_code['TGLD']['gap_details'], [])

    def test_drafts_only_with_all_entries_and_cancelled_are_counted(self):
        posted, _ = self._control()
        everything, _ = self._control(target_move='all')
        self.assertEqual(posted['TGLA']['anomalies']['draft'], 0)
        self.assertEqual(everything['TGLA']['anomalies']['draft'], 1)  # le brouillon du jeu de test
        self.assertEqual(everything['TGLA']['count'], posted['TGLA']['count'] + 1)
        move = self._gl_post(self.agency, self.journal_b, '2026-07-01', [(self.bank, 5.0, 0.0), (self.capital, 0.0, 5.0)])
        move.button_draft()
        move.button_cancel()
        self.env.flush_all()
        after, _ = self._control()
        self.assertEqual(after['TGLB']['anomalies']['cancel'], 1)
        page = self.env['account.journal.control.report'].with_company(self.agency).get_moves(
            self.agency, self.journal_b.id, D_FROM, D_TO, 'posted', anomaly='cancel')
        self.assertEqual([r['move_id'] for r in page['rows']], [move.id])
        self.assertEqual(page['rows'][0]['state_label'], 'Annulée')

    def test_search_by_piece_number_restricts_journals_and_pieces(self):
        _journal, moves = self._numbered_journal('TGLE', [1, 2, 3])
        by_code, _ = self._control(search='TGLE/2026/00002')
        self.assertEqual(set(by_code), {'TGLE'})
        self.assertEqual(by_code['TGLE']['count'], 1)

    # ------------------------------------------------------------------ pagination
    def test_journal_with_200_moves_loads_in_pages_of_80_and_totals_stay_correct(self):
        journal = self._gl_journal(self.agency, 'TGLP')
        vals = [{'move_type': 'entry', 'journal_id': journal.id, 'date': '2026-09-%02d' % (1 + i % 28),
                 'company_id': self.agency.id,
                 'line_ids': [(0, 0, {'account_id': self.bank.id, 'debit': 1.0, 'credit': 0.0, 'name': 'p'}),
                              (0, 0, {'account_id': self.capital.id, 'debit': 0.0, 'credit': 1.0, 'name': 'p'})]}
                for i in range(200)]
        self.env['account.move'].with_company(self.agency).create(vals)._post()
        self.env.flush_all()
        by_code, _ = self._control()
        self.assertEqual(by_code['TGLP']['count'], 200)
        self.assertEqual((by_code['TGLP']['debit'], by_code['TGLP']['credit']), (200.0, 200.0))
        model = self.env['account.journal.control.report'].with_company(self.agency)
        ids = []
        for offset, expected in ((0, 80), (80, 80), (160, 40)):
            page = model.get_moves(self.agency, journal.id, D_FROM, D_TO, 'posted', 'sort_number', None, None, offset, 80)
            self.assertEqual(len(page['rows']), expected)
            self.assertEqual(page['has_more'], offset + expected < 200)
            ids += [r['move_id'] for r in page['rows']]
        self.assertEqual(len(set(ids)), 200)
        first = model.get_move_lines(self.agency, ids[0])
        self.assertEqual(len(first), 2)

    # ------------------------------------------------------------------ sociétés et droits
    def test_agency_user_never_sees_another_companys_moves(self):
        hq_account = self._acc(self.hq, 'T131997H', 'asset_cash', False)
        hq_equity = self._acc(self.hq, 'T563002H', 'equity', False)
        move = self._gl_post(self.hq, self._gl_journal(self.hq, 'TGLH'), '2026-03-01',
                             [(hq_account, 999.0, 0.0), (hq_equity, 0.0, 999.0)])
        self.env.flush_all()
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Comptable agence JC', 'login': 'jc_agency_user', 'company_id': self.agency.id,
            'company_ids': [(6, 0, [self.agency.id])],
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id, self.env.ref('account.group_account_user').id])]})
        by_code, _ = self._control(company=self.hq, target_move='all', user=user)
        self.assertEqual(by_code, {})
        fake = SimpleNamespace(env=self.env(user=user))
        with patch.object(jc_ctrl, 'request', fake), patch.object(gl_ctrl, 'request', fake), \
                patch.object(journal_ctrl, 'request', fake):
            ctrl = JournalControlReportController()
            result = ctrl.journal_control_data(date_from=D_FROM, date_to=D_TO, company_id=self.hq.id)
            moves = ctrl.journal_control_moves(journal_id=move.journal_id.id, date_from=D_FROM, date_to=D_TO,
                                               company_id=self.hq.id)
            lines = ctrl.journal_control_move_lines(move_id=move.id, company_id=self.hq.id)
        self.assertTrue(result['success'])
        self.assertEqual(result['company_name'], self.agency.name)
        self.assertNotIn('TGLH', [j['code'] for j in result['data']['journals']])
        self.assertEqual(moves['rows'], [])
        self.assertEqual(lines, [])

    # ------------------------------------------------------------------ exports et menu
    def test_pdf_and_xlsx_are_generated_with_current_filters(self):
        fake = SimpleNamespace(env=self.env, make_response=lambda data, headers=None: Response(data, headers=headers))
        self._numbered_journal('TGLF', [1, 3])
        kw = {'date_from': D_FROM, 'date_to': D_TO, 'target_move': 'all', 'company_id': self.agency.id,
              'journal_ids': '', 'sortby': 'sort_number', 'search': ''}
        with patch.object(jc_ctrl, 'request', fake), patch.object(gl_ctrl, 'request', fake), \
                patch.object(journal_ctrl, 'request', fake):
            xlsx = JournalControlReportController().journal_control_xlsx(**kw)
            pdf = JournalControlReportController().journal_control_pdf(**kw)
        self.assertTrue(xlsx.data.startswith(b'PK'))
        self.assertIn('spreadsheetml', xlsx.headers.get('Content-Type'))
        self.assertTrue(pdf.data)
        self.assertEqual(pdf.headers.get('Content-Type'), 'application/pdf')

    def test_menu_opens_the_interactive_screen_and_old_wizard_is_kept(self):
        menu = self.env.ref('base_accounting_kit.menu_print_journal')
        self.assertEqual(menu.action._name, 'ir.actions.client')
        self.assertEqual(menu.action.tag, 'microfinance_loan_management.journal_control')
        self.assertFalse(menu.groups_id)
        self.assertTrue(self.env.ref('base_accounting_kit.action_account_print_journal_menu').exists())
        self.assertTrue(self.env['ir.model']._get('account.print.journal'))
        self.assertEqual(self.env.ref('base_accounting_kit.menu_general_ledger').action.tag,
                         'microfinance_loan_management.general_ledger')
        self.assertEqual(self.env.ref('base_accounting_kit.menu_Balance_report').action.tag,
                         'microfinance_loan_management.trial_balance')

    def test_manual_entries_check_is_not_implemented_because_it_is_not_reliable(self):
        _by_code, data = self._control()
        self.assertEqual(set(data['totals']['anomalies']), {'unbalanced', 'draft', 'cancel', 'gaps'})
