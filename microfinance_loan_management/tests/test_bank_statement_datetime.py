# -*- coding: utf-8 -*-
"""Relevé bancaire papier : période en date + heure (plusieurs relevés par jour), sans effet sur les écritures."""
import json
from datetime import datetime, timedelta
from unittest.mock import patch

from odoo.exceptions import UserError, ValidationError

from ..models.res_company import ResCompany
from .test_fond_liaison import TestFondLiaison

MADA = timedelta(hours=3)  # Indian/Antananarivo : UTC+3 toute l'année


def utc(local):
    """« AAAA-MM-JJ HH:MM[:SS] » en heure de Madagascar -> chaîne UTC pour la base."""
    fmt = '%Y-%m-%d %H:%M:%S' if local.count(':') == 2 else '%Y-%m-%d %H:%M'
    return (datetime.strptime(local, fmt) - MADA).strftime('%Y-%m-%d %H:%M:%S')


class TestBankStatementDatetime(TestFondLiaison):

    @classmethod
    def setUpClass(cls):
        with patch.object(ResCompany, '_get_microfinance_parent', lambda self: self.browse()):
            super().setUpClass()
        base = cls.env.ref('base.group_user')
        finance = cls.env.ref('microfinance_loan_management.group_microfinance_finance')
        make = lambda login, tz: cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'company_id': cls.agency.id, 'tz': tz,
            'company_ids': [(6, 0, [cls.agency.id])], 'groups_id': [(6, 0, [base.id, finance.id])]})
        cls.user_mada = make('dt_mada', 'Indian/Antananarivo')
        cls.user_notz = make('dt_notz', False)
        cls.agency.partner_id.tz = False
        cls.profit = cls._acc(cls.agency, 'T749001A', 'income_other', False)
        cls.loss = cls._acc(cls.agency, 'T649001A', 'expense', False)
        cls.suspense = cls._acc(cls.agency, 'T324101A', 'asset_current', True)
        cls.ag_journal.write({'profit_account_id': cls.profit.id, 'loss_account_id': cls.loss.id,
                              'suspense_account_id': cls.suspense.id})
        cls.param = cls.env['ir.config_parameter'].sudo()
        cls.param.set_param('mf.default_tz', 'Indian/Antananarivo')

    def _stmt(self, start, end, bal_start=0.0, bal_end=100.0, day='2026-10-09', user=None, entries=None, journal=None):
        """Relevé en brouillon, plage en heure de Madagascar « HH:MM »."""
        model = self.env['account.bank.statement']
        if user:
            model = model.with_user(user).with_company(self.agency)
        entries = entries if entries is not None else [{'name': 'Op', 'date': day, 'amount_in': bal_end - bal_start}]
        return model.create({
            'journal_id': (journal or self.ag_journal).id, 'mf_state': 'draft',
            'mf_datetime_from': utc('%s %s' % (day, start)), 'mf_datetime_to': utc('%s %s' % (day, end)),
            'balance_start': bal_start, 'balance_end_real': bal_end,
            'mf_entry_ids': [(0, 0, e) for e in entries]})

    # ------------------------------------------------------------------ plusieurs relevés le même jour
    def test_two_statements_same_day_back_to_back_are_accepted(self):
        first = self._stmt('08:00', '12:00', 0.0, 100.0, user=self.user_mada)
        second = self._stmt('12:00', '17:00', 100.0, 150.0, user=self.user_mada)
        first.action_mf_validate()
        second.action_mf_validate()
        self.assertEqual((first.mf_state, second.mf_state), ('validated', 'validated'))
        self.assertEqual(second._mf_previous(), first)

    def test_overlapping_statement_is_refused_with_both_ranges_in_local_time(self):
        self._stmt('08:00', '12:00', 0.0, 100.0, user=self.user_mada).action_mf_validate()
        self._stmt('12:00', '17:00', 100.0, 150.0, user=self.user_mada).action_mf_validate()
        third = self._stmt('11:00', '13:00', 150.0, 170.0, user=self.user_mada)
        with self.assertRaises(UserError) as caught:
            third.action_mf_validate()
        message = str(caught.exception)
        for expected in ('09/10/2026 11:00', '09/10/2026 13:00', '09/10/2026 08:00', '09/10/2026 12:00'):
            self.assertIn(expected, message)
        self.assertEqual(third.mf_state, 'draft')

    def test_end_must_be_strictly_after_start(self):
        for start, end in (('12:00', '12:00'), ('12:00', '09:00')):
            with self.assertRaises(ValidationError):
                self._stmt(start, end)
        stmt = self._stmt('08:00', '12:00')
        with self.assertRaises(ValidationError):
            stmt.mf_datetime_to = stmt.mf_datetime_from

    def test_new_paper_statement_requires_a_period(self):
        stmt = self._stmt('08:00', '12:00')
        with self.assertRaises(ValidationError):
            stmt.mf_datetime_to = False

    # ------------------------------------------------------------------ chaînage
    def test_initial_balance_must_equal_previous_final_balance(self):
        self._stmt('08:00', '12:00', 0.0, 100.0).action_mf_validate()
        wrong = self._stmt('12:00', '17:00', 90.0, 150.0)
        with self.assertRaises(UserError):
            wrong.action_mf_validate()

    def test_inserted_statement_is_compared_with_its_real_neighbours(self):
        first = self._stmt('08:00', '12:00', 0.0, 100.0)
        last = self._stmt('17:00', '20:00', 100.0, 130.0)
        both = [{'name': 'Entrée', 'date': '2026-10-09', 'amount_in': 10.0},
                {'name': 'Sortie', 'date': '2026-10-09', 'amount_out': 10.0}]
        first.action_mf_validate()
        last.action_mf_validate()  # son précédent validé est « first » : 100 = 100
        wrong_start = self._stmt('12:00', '17:00', 90.0, 90.0, entries=both)
        with self.assertRaises(UserError):  # comparé à « first » (fin 100), pas à « last »
            wrong_start.action_mf_validate()
        wrong_end = self._stmt('12:00', '17:00', 100.0, 140.0, entries=[both[0]] + [
            {'name': 'Entrée 2', 'date': '2026-10-09', 'amount_in': 30.0}])
        with self.assertRaises(UserError):  # son suivant (17:00) attend 100
            wrong_end.action_mf_validate()
        middle = self._stmt('12:00', '17:00', 100.0, 100.0, entries=both)
        self.assertEqual(middle._mf_previous(), first)
        self.assertEqual(middle._mf_next(), last)
        middle.action_mf_validate()
        self.assertEqual(last._mf_previous(), middle)

    # ------------------------------------------------------------------ dates des lignes
    def test_line_date_outside_the_date_range_is_refused_and_bounds_are_included(self):
        bad = self._stmt('08:00', '12:00', entries=[{'name': 'Hors', 'date': '2026-10-10', 'amount_in': 100.0}])
        with self.assertRaises(UserError):
            bad.action_mf_validate()
        edge = self._stmt('08:00', '12:00', day='2026-10-11',
                          entries=[{'name': 'Bord', 'date': '2026-10-11', 'amount_in': 100.0}])
        edge.action_mf_validate()

    def test_statement_across_two_days_keeps_each_line_date_and_accounting_date(self):
        stmt = self.env['account.bank.statement'].with_user(self.user_mada).with_company(self.agency).create({
            'journal_id': self.ag_journal.id, 'mf_state': 'draft',
            'mf_datetime_from': utc('2026-12-31 22:00'), 'mf_datetime_to': utc('2027-01-01 02:00'),
            'balance_start': 0.0, 'balance_end_real': 80.0,
            'mf_entry_ids': [(0, 0, {'name': 'Avant minuit', 'date': '2026-12-31', 'amount_in': 50.0,
                                     'treatment': 'new'}),
                             (0, 0, {'name': 'Après minuit', 'date': '2027-01-01', 'amount_in': 30.0,
                                     'treatment': 'new'})]})
        self.assertEqual((str(stmt.mf_date_from), str(stmt.mf_date_to)), ('2026-12-31', '2027-01-01'))
        stmt.action_mf_validate()
        stmt.mf_entry_ids.action_treat()
        moves = {e.name: e.statement_line_id.move_id.date for e in stmt.mf_entry_ids}
        self.assertEqual((str(moves['Avant minuit']), str(moves['Après minuit'])), ('2026-12-31', '2027-01-01'))
        self.assertEqual(stmt.name, '%s – 31/12/26 22:00 → 01/01/27 02:00' % self.ag_journal.code)

    # ------------------------------------------------------------------ nom
    def test_name_formats_and_recalculation_in_draft(self):
        stmt = self._stmt('08:00', '12:30', user=self.user_mada)
        self.assertEqual(stmt.name, '%s – 09/10/26 08:00 → 12:30' % self.ag_journal.code)
        stmt.with_user(self.user_mada).mf_datetime_to = utc('2026-10-10 09:15')
        self.assertEqual(stmt.name, '%s – 09/10/26 08:00 → 10/10/26 09:15' % self.ag_journal.code)
        for label in (stmt.name, stmt.display_name):
            self.assertNotIn('False', label)
            self.assertNotIn('None', label)
        stmt.with_user(self.user_mada).action_mf_validate()
        frozen = stmt.name
        stmt.with_context(mf_allow=True).mf_datetime_from = utc('2026-10-09 07:00')
        self.assertEqual(stmt.name, frozen)

    def test_default_period(self):
        Statement = self.env['account.bank.statement'].with_user(self.user_mada).with_context(
            default_mf_state='draft', default_journal_id=self.ag_journal.id)
        before = Statement.default_get(['mf_datetime_from', 'mf_datetime_to'])
        # sans relevé précédent : début de la journée locale ; fin : maintenant, à la minute
        local_start = Statement.new({'journal_id': self.ag_journal.id})._mf_local(before['mf_datetime_from'])
        self.assertEqual((local_start.hour, local_start.minute, local_start.second), (0, 0, 0))
        self.assertEqual(before['mf_datetime_to'].second, 0)
        prev = self._stmt('08:00', '12:00')
        prev.action_mf_validate()
        after = Statement.default_get(['mf_datetime_from', 'mf_datetime_to'])
        self.assertEqual(after['mf_datetime_from'], prev.mf_datetime_to)

    # ------------------------------------------------------------------ fuseaux et anciens champs
    def test_madagascar_midnight_range_is_stored_in_utc_with_the_right_old_dates(self):
        stmt = self._stmt('00:00', '23:59:59', user=self.user_mada)
        self.assertEqual(str(stmt.mf_datetime_from), '2026-10-08 21:00:00')
        self.assertEqual(str(stmt.mf_datetime_to), '2026-10-09 20:59:59')
        self.assertEqual((str(stmt.mf_date_from), str(stmt.mf_date_to)), ('2026-10-09', '2026-10-09'))

    def test_user_without_tz_falls_back_to_company_then_default_parameter(self):
        values = {'mf_datetime_from': '2026-10-08 21:00:00', 'mf_datetime_to': '2026-10-09 20:59:59'}
        Statement = self.env['account.bank.statement'].with_user(self.user_notz).with_company(self.agency)
        stmt = Statement.create(dict(values, journal_id=self.ag_journal.id, mf_state='draft', balance_end_real=0.0,
                                     mf_entry_ids=[(0, 0, {'name': 'x', 'date': '2026-10-09'})]))
        self.assertTrue(stmt.mf_tz_missing)
        self.assertEqual(str(stmt.mf_date_from), '2026-10-09')      # mf.default_tz
        self.agency.partner_id.tz = 'Europe/Paris'                   # le fuseau de la société passe avant
        stmt.mf_datetime_from = '2026-10-08 21:30:00'
        self.assertEqual(str(stmt.mf_date_from), '2026-10-08')
        self.agency.partner_id.tz = False
        self.param.set_param('mf.default_tz', 'Pacific/Auckland')    # le paramètre est bien lu
        stmt.mf_datetime_from = '2026-10-08 21:00:00'
        self.assertEqual(str(stmt.mf_date_from), '2026-10-09')
        self.param.set_param('mf.default_tz', 'Indian/Antananarivo')
        self.assertFalse(self.user_mada.tz is False)
        self.assertFalse(self.env['account.bank.statement'].with_user(self.user_mada).new({}).mf_tz_missing)

    def test_writing_old_date_fields_writes_the_new_range(self):
        stmt = self._stmt('08:00', '12:00', user=self.user_mada)
        stmt.with_user(self.user_mada).write({'mf_date_from': '2026-10-08', 'mf_date_to': '2026-10-09'})
        self.assertEqual(str(stmt.mf_datetime_from), '2026-10-07 21:00:00')
        self.assertEqual(str(stmt.mf_datetime_to), '2026-10-09 20:59:59')
        self.assertEqual((str(stmt.mf_date_from), str(stmt.mf_date_to)), ('2026-10-08', '2026-10-09'))

    # ------------------------------------------------------------------ migration
    def test_migration_gives_whole_local_days_and_is_idempotent(self):
        Statement = self.env['account.bank.statement']
        legacy = self._stmt('08:00', '12:00')
        legacy._write({'mf_datetime_from': None, 'mf_datetime_to': None,
                       'mf_date_from': '2026-10-09', 'mf_date_to': '2026-10-09'})
        legacy.invalidate_recordset()
        self.assertFalse(legacy.mf_datetime_from)
        done = Statement._mf_migrate_period_datetimes()
        self.assertIn(legacy, done)
        self.assertEqual(str(legacy.mf_datetime_from), '2026-10-08 21:00:00')   # 09/10 00:00 à Madagascar
        self.assertEqual(str(legacy.mf_datetime_to), '2026-10-09 20:59:59')     # 09/10 23:59:59
        self.assertEqual((str(legacy.mf_date_from), str(legacy.mf_date_to)), ('2026-10-09', '2026-10-09'))
        self.assertFalse(Statement._mf_migrate_period_datetimes())              # deuxième exécution : sans effet
        self.assertEqual(str(legacy.mf_datetime_from), '2026-10-08 21:00:00')

    # ------------------------------------------------------------------ tuile du tableau de bord
    def test_dashboard_tile_shows_end_of_last_validated_statement(self):
        stmt = self._stmt('08:00', '12:00', user=self.user_mada)
        stmt.action_mf_validate()
        self._stmt('13:00', '15:00', 100.0, 120.0)  # brouillon : ignoré
        journal = self.ag_journal.with_user(self.user_mada).with_company(self.agency)
        data = {journal.id: {}}
        journal._fill_bank_cash_dashboard_data(data)
        self.assertEqual(data[journal.id]['mf_last_statement'], '09/10/2026 12:00')
        self.assertIn('mf_last_statement', json.dumps(data[journal.id]))
