# -*- coding: utf-8 -*-
"""Onglet « Trésorerie » du tableau de bord (données serveur) et tuile compacte de la Vue d'ensemble.

TransactionCase annulés. Société de test avec comptes aux codes PCEC, 5 banques à journal d'exploitation, une banque avec
crédit et épargne, un journal de fonds, la caisse et Mvola. Le regroupement par banque, le filtre d'usage et les totaux
d'affichage sont faits dans le navigateur sur les lignes testées ici (une ligne par journal, usage et banque inclus).
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError

from .test_payslip_payment import NET, PayslipPaymentCommon


class TestTreasuryTab(PayslipPaymentCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.context_today(cls.env['res.users'])
        cls.company_c = cls.env['res.company'].create({'name': 'Siège trésorerie (test)', 'agency_code': 'PZ3'})
        cls.env.user.company_ids = [(4, cls.company_c.id)]
        cls.setup_c = cls._setup_company(cls.company_c, ())
        cls.banks = [cls.env['res.bank'].create({'name': 'Banque tréso %s (test)' % i}) for i in range(6)]
        cls.operating = [cls._journal(cls.company_c, cls.setup_c, 'OP%d' % i, cls.banks[i], 'operating')
                         for i in range(5)]
        cls.credit = cls._journal(cls.company_c, cls.setup_c, 'CR0', cls.banks[0], 'credit')
        cls.savings = cls._journal(cls.company_c, cls.setup_c, 'EP0', cls.banks[0], 'savings')
        cls.fund = cls._journal(cls.company_c, cls.setup_c, 'FD0', cls.banks[5], 'fund')
        cls.cash_account = cls._acc(cls.company_c, '101001', 'asset_cash', False)
        cls.mobile_account = cls._acc(cls.company_c, '141010', 'asset_cash', False)
        cls.cash = cls.env['account.journal'].create({
            'name': 'Caisse (test)', 'code': 'CAS', 'type': 'cash', 'company_id': cls.company_c.id,
            'default_account_id': cls.cash_account.id, 'microfinance_usage': 'cash'})
        cls.mobile = cls.env['account.journal'].create({
            'name': 'Mobile (test)', 'code': 'MOB', 'type': 'bank', 'company_id': cls.company_c.id,
            'default_account_id': cls.mobile_account.id, 'microfinance_usage': 'mobile'})
        cls.company_c.microfinance_operating_journal_id = cls.operating[0]
        cls.env['ir.config_parameter'].sudo().set_param('microfinance.parent_company_id', cls.company_c.id)

    @classmethod
    def _journal(cls, company, setup, code, bank, usage):
        account = cls._acc(company, '1311%s' % code, 'asset_cash', False)
        journal = cls.env['account.journal'].create({
            'name': 'Journal %s' % code, 'code': code, 'type': 'bank', 'company_id': company.id,
            'default_account_id': account.id, 'suspense_account_id': setup['suspense'].id,
            'microfinance_usage': usage, 'microfinance_bank_id': bank.id})
        journal.inbound_payment_method_line_ids.write({'payment_account_id': setup['in'].id})
        journal.outbound_payment_method_line_ids.write({'payment_account_id': setup['out'].id})
        return journal

    # ------------------------------------------------------------------ outils
    def _move(self, journal, debit_account, credit_account, amount, days_ago=0, setup=None):
        move = self.env['account.move'].create({
            'move_type': 'entry', 'journal_id': journal.id, 'date': self.today - timedelta(days=days_ago),
            'line_ids': [
                (0, 0, {'account_id': debit_account.id, 'debit': amount, 'credit': 0.0, 'name': 'Test'}),
                (0, 0, {'account_id': credit_account.id, 'debit': 0.0, 'credit': amount, 'name': 'Test'})]})
        move.action_post()
        return move

    def _fund_bank(self, journal, amount, days_ago=0):
        return self._move(journal, journal.default_account_id, self.setup_c['equity'], amount, days_ago)

    def _out_transit(self, journal, amount, days_ago=0):
        return self._move(journal, self.setup_c['charge'], self.setup_c['out'], amount, days_ago)

    def _in_transit(self, journal, amount, days_ago=0):
        return self._move(journal, self.setup_c['in'], self.setup_c['equity'], amount, days_ago)

    def _validated_statement(self, journal, days_ago):
        end = fields.Datetime.now().replace(hour=12, minute=0, second=0, microsecond=0) - timedelta(days=days_ago)
        return self.env['account.bank.statement'].create({
            'journal_id': journal.id, 'mf_state': 'validated', 'mf_datetime_from': end - timedelta(days=5),
            'mf_datetime_to': end, 'balance_start': 0.0, 'balance_end_real': 0.0})

    def _loan(self, user=None, companies=None):
        Loan = self.env['microfinance.loan']
        if user:
            Loan = Loan.with_user(user)
        ids = (companies or self.company_c).ids
        return Loan.with_company(ids[0]).with_context(allowed_company_ids=ids)

    def _rows(self, **kwargs):
        data = self._loan(**kwargs).get_treasury_data()
        return {row['journal_id']: row for row in data['rows']}

    # ------------------------------------------------------------------ chiffres
    def test_scenario_figures_and_statement(self):
        bmop = self.operating[0]
        self._fund_bank(bmop, 3000000.0)
        self._out_transit(bmop, NET)
        self._in_transit(bmop, 1000000.0)
        row = self._rows()[bmop.id]
        self.assertEqual((row['bank_balance'], row['out_transit'], row['in_transit'], row['available']),
                         (3000000.0, NET, 1000000.0, 3000000.0 - NET))
        out_line = self.env['account.move.line'].search([
            ('account_id', '=', self.setup_c['out'].id), ('journal_id', '=', bmop.id)])
        statement = self.env['account.bank.statement'].create({
            'journal_id': bmop.id, 'mf_state': 'draft', 'mf_date_from': '2026-11-01', 'mf_date_to': '2026-11-30',
            'balance_start': 0.0, 'balance_end_real': -NET,
            'mf_entry_ids': [(0, 0, {'date': '2026-11-28', 'name': 'Virement', 'amount_out': NET})]})
        entry = statement.mf_entry_ids
        entry.write({'treatment': 'reconcile', 'target_line_id': out_line.id})
        entry.action_treat()
        self.env.invalidate_all()
        row = self._rows()[bmop.id]
        self.assertEqual((row['bank_balance'], row['out_transit'], row['available']),
                         (3000000.0 - NET, 0.0, 3000000.0 - NET))

    def test_receivable_older_than_n_days(self):
        journal = self.operating[1]
        self._in_transit(journal, 100000.0, days_ago=10)
        self._in_transit(journal, 40000.0, days_ago=2)
        row = self._rows()[journal.id]
        self.assertEqual((row['in_transit'], row['in_transit_old']), (140000.0, 100000.0))
        self.company_c.mf_treasury_receivable_days = 1
        self.assertEqual(self._rows()[journal.id]['in_transit_old'], 140000.0)

    def test_settings_defaults(self):
        self.assertEqual((self.company_c.mf_treasury_watch_pct, self.company_c.mf_treasury_statement_days,
                          self.company_c.mf_treasury_receivable_days), (10, 7, 7))

    # ------------------------------------------------------------------ lignes / filtres
    def test_rows_scope_and_usages(self):
        data = self._loan().get_treasury_data()
        journal_ids = {row['journal_id'] for row in data['rows']}
        expected = {j.id for j in self.operating} | {self.credit.id, self.savings.id, self.fund.id}
        self.assertEqual(journal_ids, expected)
        self.assertNotIn(self.cash.id, journal_ids)       # caisse et Mvola ne sont pas des comptes du tableau
        self.assertNotIn(self.mobile.id, journal_ids)
        ids = {u['id'] for u in data['usages']}
        selection = {key for key, _label in self.env['account.journal']._fields['microfinance_usage'].selection}
        self.assertEqual(ids, selection - {'cash', 'mobile'})
        by_bank = {}
        for row in data['rows']:
            by_bank.setdefault(row['bank_id'], []).append(row)
        self.assertEqual(len(by_bank[self.banks[0].id]), 3)   # exploitation + crédit + épargne de la même banque
        self.assertEqual({row['usage'] for row in by_bank[self.banks[0].id]}, {'operating', 'credit', 'savings'})

    def test_total_equals_compact_tile_and_rows(self):
        for index, journal in enumerate(self.operating):
            self._fund_bank(journal, 100000.0 * (index + 1))
        self._out_transit(self.operating[2], 50000.0)
        self._fund_bank(self.credit, 70000.0)
        rows = self._loan().get_treasury_data()['rows']
        tiles = {t['key']: t for t in self._loan()._get_overview_tiles()}
        self.assertEqual(tiles['treasury_overview']['value'], sum(r['available'] for r in rows))
        self.assertEqual(tiles['treasury_overview']['value'], 1500000.0 + 70000.0 - 50000.0)
        for row in rows:
            self.assertEqual(row['available'], row['bank_balance'] - row['out_transit'])

    # ------------------------------------------------------------------ À surveiller
    def test_watch_flag(self):
        a, b, c = self.operating[0], self.operating[1], self.operating[2]
        self._fund_bank(a, 750000.0)
        self._out_transit(a, 750000.0)          # disponible 0 <= 10 % du solde
        self._fund_bank(c, 500000.0)
        self._out_transit(c, 800000.0)          # disponible négatif
        rows = self._rows()
        self.assertTrue(rows[a.id]['watch'])
        self.assertFalse(rows[b.id]['watch'])   # solde nul : jamais signalé
        self.assertTrue(rows[c.id]['watch'])
        self._fund_bank(b, 1000000.0)
        self.assertFalse(self._rows()[b.id]['watch'])   # disponible = 100 % du solde

    # ------------------------------------------------------------------ Relevés à saisir
    def test_statement_to_enter_flag(self):
        a, b, c, d = self.operating[0], self.operating[1], self.operating[2], self.operating[3]
        self._fund_bank(a, 1000.0, days_ago=3)
        self._validated_statement(a, 9)                       # relevé de 9 jours, mouvements postérieurs
        self._validated_statement(b, 9)                       # relevé de 9 jours, rien depuis
        self._fund_bank(b, 1000.0, days_ago=12)
        self._fund_bank(c, 1000.0, days_ago=1)                # mouvements, aucun relevé
        rows = self._rows()
        self.assertTrue(rows[a.id]['late'])
        self.assertFalse(rows[b.id]['late'])
        self.assertTrue(rows[c.id]['late'])
        self.assertFalse(rows[d.id]['late'])                  # sans mouvement
        self.assertEqual(rows[a.id]['last_statement_days'], 9)
        self.assertIsNone(rows[c.id]['last_statement_days'])
        # relevé récent : même avec des mouvements, pas en retard
        self._validated_statement(c, 2)
        self.assertFalse(self._rows()[c.id]['late'])

    # ------------------------------------------------------------------ bande espèces / Mvola
    def test_cash_and_mobile_band(self):
        self._fund_bank(self.cash, 250000.0)
        self._fund_bank(self.mobile, 80000.0)
        self.company_c.cash_journal_id = self.cash
        session = self.env['microfinance.caisse.session'].with_company(self.company_c).create({'journal_id': self.cash.id})
        denomination = self.env['microfinance.caisse.denomination'].create({
            'name': 'Billet 1000 (test tréso)', 'value': 1000.0, 'currency_id': self.company_c.currency_id.id})
        self.env['microfinance.caisse.comptage'].create({
            'session_id': session.id, 'theoretical_total': 250000.0, 'variance_comment': 'test',
            'line_ids': [(0, 0, {'denomination_id': denomination.id, 'quantity': 245})]})
        band = {item['kind']: item for item in self._loan().get_treasury_data()['band']}
        self.assertEqual(band['cash']['balance'], 250000.0)
        self.assertEqual(band['mobile']['balance'], 80000.0)
        self.assertEqual((band['cash']['count']['variance'], band['cash']['count']['ok']), (-5000.0, False))

    # ------------------------------------------------------------------ tuile compacte
    def test_compact_tile_replaces_old_tile_and_counts(self):
        self._fund_bank(self.operating[0], 750000.0)
        self._out_transit(self.operating[0], 750000.0)
        self._fund_bank(self.operating[1], 1000.0, days_ago=2)
        tiles = {t['key']: t for t in self._loan()._get_overview_tiles()}
        self.assertNotIn('operating_treasury', tiles)
        tile = tiles['treasury_overview']
        rows = self._loan().get_treasury_data()['rows']
        self.assertEqual(tile['counts'], {'watch': sum(r['watch'] for r in rows), 'late': sum(r['late'] for r in rows),
                                          'unexplained': sum(1 for r in rows if r['unexplained'])})
        self.assertFalse(tile['model'])
        self.assertEqual(tile['extra_links'][0]['topic'], 'tresorerie')
        keys = list(tiles)
        self.assertEqual(keys.index('treasury_overview'), keys.index('exploitation_funds') + 1)
        funds = tiles['exploitation_funds']
        self.assertEqual(funds['extra_links'], [{'label': "Voir la trésorerie d'exploitation", 'topic': 'tresorerie',
                                                  'usage': 'operating'}])
        # « Fonds d'exploitation reçus » : mêmes chiffres qu'avant (contributions et partages seulement)
        amounts = self.env['microfinance.fond.credit'].with_company(self.company_c)._get_exploitation_amounts(
            self.company_c.id)
        self.assertEqual(funds['value'], amounts['recu'])
        values = {i['label']: i['value'] for i in funds['secondary_items'] if 'value' in i}
        self.assertEqual((values['En transit'], values['Reçu en banque']), (amounts['en_transit'], amounts['recu_banque']))

    def test_query_count_independent_of_journal_count(self):
        loan = self._loan()

        def count():
            self.env.invalidate_all()
            before = self.env.cr.sql_log_count
            loan.get_treasury_data()
            return self.env.cr.sql_log_count - before

        count()   # échauffement (caches de champs, traductions)
        few = count()
        for index in range(25):
            self._journal(self.company_c, self.setup_c, 'XQ%d' % index, self.banks[index % 5], 'operating')
        many = count()
        self.assertLessEqual(abs(many - few), 2, (few, many))

    # ------------------------------------------------------------------ droits
    def _user(self, login, groups, company):
        return self.env['res.users'].with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'company_id': company.id, 'company_ids': [(6, 0, company.ids)],
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id] + [self.env.ref(g).id for g in groups])]})

    def test_rights(self):
        mod = 'microfinance_loan_management.'
        self._fund_bank(self.fund, 1000.0)
        # direction du siège : tout, y compris les journaux de fonds
        head = self._user('tre_head', [mod + 'group_microfinance_manager', 'account.group_account_user'], self.company_c)
        self.assertIn(self.fund.id, {r['journal_id'] for r in self._loan(user=head).get_treasury_data()['rows']})
        # chef d'agence : sa société seulement, pas de journal de fonds
        agency = self._user('tre_agency', [mod + 'group_microfinance_manager', 'account.group_account_user'],
                            self.company_b)
        data = self._loan(user=agency, companies=self.company_b).get_treasury_data()
        self.assertEqual({r['company_id'] for r in data['rows']}, {self.company_b.id})
        self.assertNotIn('fund', {u['id'] for u in data['usages']})
        # caissier : refusé (appel serveur) et onglet masqué
        cashier = self._user('tre_cashier', [mod + 'group_microfinance_cashier'], self.company_c)
        with self.assertRaises(AccessError):
            self._loan(user=cashier).get_treasury_data()
        self.assertFalse(self._loan(user=cashier)._treasury_has_rights())
        # chef d'agence qui force allowed_company_ids sur une autre société : refus
        with self.assertRaises(AccessError):
            self.env['microfinance.loan'].with_user(agency).with_context(
                allowed_company_ids=[self.company_c.id]).get_treasury_data()

    def test_opening_the_tab_writes_nothing(self):
        self._fund_bank(self.operating[0], 1000.0)
        self.env.flush_all()
        moves = self.env['account.move'].search_count([])
        statements = self.env['account.bank.statement'].search_count([])
        lines = self.env['account.move.line'].search_count([])
        self._loan().get_treasury_data()
        self._loan()._get_overview_tiles()
        self.assertEqual((self.env['account.move'].search_count([]), self.env['account.bank.statement'].search_count([]),
                          self.env['account.move.line'].search_count([])), (moves, statements, lines))
