# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import Form

from ..models.res_company import ResCompany
from .test_fond_liaison import TestFondLiaison
from .test_fond_origine import TestFondOrigine


class TestBankStatementPaper(TestFondLiaison):
    """Relevé bancaire papier : saisie, contrôles, rapprochement, pointage, tolérance, annulation, isolation."""

    _auto_fond = TestFondOrigine._auto_fond
    _deposit = TestFondOrigine._deposit
    _shared = TestFondOrigine._shared

    D_FROM, D_TO = '2026-10-01', '2026-10-31'

    @classmethod
    def setUpClass(cls):
        # base déjà configurée avec une société mère (MOWGLI) : les fixtures de départ la refuseraient
        with patch.object(ResCompany, '_get_microfinance_parent', lambda self: self.browse()):
            super().setUpClass()
        base = cls.env.ref('base.group_user')
        finance = cls.env.ref('microfinance_loan_management.group_microfinance_finance')
        comptable = cls.env.ref('microfinance_loan_management.group_microfinance_comptable')
        cls.user_agency = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Finance agence (test)', 'login': 'bank_ag_finance', 'company_id': cls.agency.id,
            'company_ids': [(6, 0, [cls.agency.id])], 'groups_id': [(6, 0, [base.id, finance.id])]})
        cls.user_accountant = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Comptable (test)', 'login': 'bank_accountant', 'company_id': cls.agency.id,
            'company_ids': [(6, 0, [cls.agency.id, cls.hq.id])], 'groups_id': [(6, 0, [base.id, finance.id, comptable.id])]})
        cls.profit = cls._acc(cls.agency, 'T749000A', 'income_other', False)
        cls.loss = cls._acc(cls.agency, 'T649000A', 'expense', False)
        cls.suspense = cls._acc(cls.agency, 'T324100A', 'asset_current', True)
        cls.ag_journal.write({'profit_account_id': cls.profit.id, 'loss_account_id': cls.loss.id,
                              'suspense_account_id': cls.suspense.id})

    # ------------------------------------------------------------------ outils
    def _mf_statement(self, journal, start, end, entries, d_from=None, d_to=None, user=None):
        Statement = self.env['account.bank.statement']
        if user:
            Statement = Statement.with_user(user).with_company(journal.company_id)
        return Statement.create({
            'journal_id': journal.id, 'mf_state': 'draft', 'mf_date_from': d_from or self.D_FROM,
            'mf_date_to': d_to or self.D_TO, 'balance_start': start, 'balance_end_real': end,
            'mf_entry_ids': [(0, 0, dict({'date': '2026-10-05'}, **e)) for e in entries]})

    def _mirror_line(self, partage, side='agency'):
        move = self._moves(partage).filtered(lambda m: m.microfinance_partage_side == side)
        return move.line_ids.filtered(lambda l: l.debit > 0 if side != 'hq' else l.credit > 0)

    def _allocation(self, fond, company):
        allocation = self.env['microfinance.fond.allocation'].sudo().search(
            [('fond_id', '=', fond.id), ('company_id', '=', company.id)])
        allocation.invalidate_recordset()
        return allocation

    # (1)-(3) contrôles
    def test_consistent_statement_is_validated(self):
        stmt = self._mf_statement(self.ag_journal, 1000.0, 1200.0,
                                  [{'name': 'Virement', 'amount_in': 500.0}, {'name': 'Frais', 'amount_out': 300.0}])
        self.assertEqual((stmt.mf_balance_computed, stmt.mf_gap), (1200.0, 0.0))
        stmt.action_mf_validate()
        self.assertEqual(stmt.mf_state, 'validated')

    def test_inconsistent_balances_are_refused(self):
        stmt = self._mf_statement(self.ag_journal, 1000.0, 1300.0, [{'name': 'Virement', 'amount_in': 500.0}])
        self.assertEqual(stmt.mf_gap, -200.0 + 0.0)
        with self.assertRaises(UserError):
            stmt.action_mf_validate()
        self.assertEqual(stmt.mf_state, 'draft')

    def test_initial_balance_must_match_previous_final_balance(self):
        first = self._mf_statement(self.ag_journal, 0.0, 200.0, [{'name': 'Dépôt', 'amount_in': 200.0}])
        first.action_mf_validate()
        gap = self._mf_statement(self.ag_journal, 150.0, 250.0, [{'name': 'Dépôt', 'amount_in': 100.0}],
                                 d_from='2026-11-01', d_to='2026-11-30')
        gap.mf_entry_ids.write({'date': '2026-11-05'})
        with self.assertRaises(UserError):
            gap.action_mf_validate()
        ok = self._mf_statement(self.ag_journal, 200.0, 300.0, [{'name': 'Dépôt', 'amount_in': 100.0}],
                                d_from='2026-12-01', d_to='2026-12-31')
        ok.mf_entry_ids.write({'date': '2026-12-05'})
        ok._onchange_mf_previous_balance()
        self.assertEqual(ok.balance_start, 200.0)

    # (4) relevé validé non modifiable
    def test_validated_statement_is_locked_and_reopened_with_reason(self):
        stmt = self._mf_statement(self.ag_journal, 0.0, 100.0, [{'name': 'Dépôt', 'amount_in': 100.0}])
        stmt.action_mf_validate()
        with self.assertRaises(UserError):
            stmt.balance_end_real = 999.0
        with self.assertRaises(UserError):
            stmt.mf_entry_ids.amount_in = 5.0
        with self.assertRaises(UserError):
            stmt.mf_entry_ids.unlink()
        with self.assertRaises(AccessError):
            stmt.with_user(self.user_agency)._mf_reopen('test')
        stmt.with_user(self.user_accountant)._mf_reopen('Erreur de saisie')
        self.assertEqual(stmt.mf_state, 'draft')
        log = self.env['microfinance.bank.statement.log'].search([('statement_id', '=', stmt.id), ('action', '=', 'reopen')])
        self.assertEqual((log.user_id, log.reason), (self.user_accountant, 'Erreur de saisie'))

    # (5) 67 Ha : virement reçu rapproché avec la ligne 139100 du miroir
    def test_incoming_transfer_reconciled_moves_share_from_transit_to_received(self):
        fond, partage = self._shared(500.0, 300.0)
        mirror = self._mirror_line(partage)
        allocation = self._allocation(fond, self.agency)
        self.assertEqual((allocation.amount_in_transit, allocation.amount_received), (300.0, 0.0))
        stmt = self._mf_statement(self.ag_journal, 0.0, 300.0, [{
            'name': 'Virement BMOI', 'amount_in': 300.0, 'treatment': 'reconcile', 'target_line_id': mirror.id}],
            user=self.user_agency)
        stmt.mf_entry_ids.action_treat()
        allocation = self._allocation(fond, self.agency)
        self.assertEqual((allocation.amount_in_transit, allocation.amount_received), (0.0, 300.0))
        self.assertEqual(stmt.mf_entry_ids.state, 'done')
        self.assertTrue(stmt.mf_entry_ids.statement_line_id)
        self.assertTrue(mirror.reconciled)

    # (6) siège : deux virements émis rapprochés avec les crédits 139500
    def test_outgoing_transfers_reconciled_reduce_the_fund_bank_account(self):
        fond = self._auto_fond()
        self._deposit(fond, 100000.0)
        partage = self.env['microfinance.fond.partage'].create({'fond_id': fond.id, 'base_amount': 500.0})
        partage.line_ids.filtered(lambda l: l.company_id == self.agency).write({'amount': 300.0})
        partage.line_ids.filtered(lambda l: l.company_id == self.agency2).write({'amount': 200.0})
        partage.action_validate()
        lines = self._moves(partage).filtered(lambda m: m.microfinance_partage_side == 'hq').mapped('line_ids').filtered(
            lambda l: l.credit > 0)
        self.assertEqual(sorted(lines.mapped('credit')), [200.0, 300.0])
        before = self._balance(self.fdbm.default_account_id)
        entries = [{'name': 'Virement %s' % l.credit, 'amount_out': l.credit, 'treatment': 'reconcile',
                    'target_line_id': l.id} for l in lines]
        stmt = self._mf_statement(self.fdbm, before, before - 500.0, entries)
        stmt.mf_entry_ids.action_treat()
        self.assertEqual(self._balance(self.fdbm.default_account_id), before - 500.0)
        self.assertTrue(all(lines.mapped('reconciled')))

    # (7) pointage d'une écriture directe sur la banque : pas de doublon
    def test_pointing_a_direct_bank_entry_creates_no_entry(self):
        other = self._acc(self.hq, 'T116000P', 'liability_current', False)
        direct = self.env['account.move'].create({
            'move_type': 'entry', 'journal_id': self.fdbm.id, 'date': '2026-10-02', 'ref': 'Dépôt direct',
            'line_ids': [(0, 0, {'account_id': self.fdbm.default_account_id.id, 'debit': 1000.0, 'credit': 0.0}),
                         (0, 0, {'account_id': other.id, 'debit': 0.0, 'credit': 1000.0})]})
        direct.action_post()
        line = direct.line_ids.filtered(lambda l: l.debit)
        before = self._balance(self.fdbm.default_account_id)
        st_lines_before = self.env['account.bank.statement.line'].search_count([('journal_id', '=', self.fdbm.id)])
        stmt = self._mf_statement(self.fdbm, 0.0, 1000.0, [{
            'name': 'Dépôt bailleur', 'amount_in': 1000.0, 'treatment': 'point', 'target_line_id': line.id}])
        stmt.mf_entry_ids.action_treat()
        self.assertEqual(self._balance(self.fdbm.default_account_id), before)
        self.assertEqual(self.env['account.bank.statement.line'].search_count([('journal_id', '=', self.fdbm.id)]), st_lines_before)
        self.assertEqual(line.mf_pointed_entry_id, stmt.mf_entry_ids)
        again = self._mf_statement(self.fdbm, 1000.0, 2000.0, [{
            'name': 'Doublon', 'amount_in': 1000.0, 'treatment': 'point', 'target_line_id': line.id}],
            d_from='2026-11-01', d_to='2026-11-30')
        again.mf_entry_ids.write({'date': '2026-11-03'})
        with self.assertRaises(UserError):
            again.mf_entry_ids.action_treat()

    def test_a_bank_statement_line_move_cannot_be_pointed(self):
        st_line = self.env['account.bank.statement.line'].create({
            'journal_id': self.ag_journal.id, 'amount': 50.0, 'payment_ref': 'Existante', 'date': '2026-10-03',
            'counterpart_account_id': self.ag_in.id})
        line = st_line.move_id.line_ids.filtered(lambda l: l.account_id == self.ag_journal.default_account_id)
        stmt = self._mf_statement(self.ag_journal, 0.0, 50.0, [{
            'name': 'Existante', 'amount_in': 50.0, 'treatment': 'point', 'target_line_id': line.id}])
        with self.assertRaises(UserError):
            stmt.mf_entry_ids.action_treat()

    # (8) tolérance d'arrondi
    def test_rounding_gap_follows_the_tolerance_setting(self):
        fond, partage = self._shared(500.0, 300.0)
        mirror = self._mirror_line(partage)
        entry = {'name': 'Virement arrondi', 'amount_in': 300.4, 'treatment': 'reconcile', 'target_line_id': mirror.id}
        # désactivée (défaut) : lettrage partiel, l'écart reste sur la ligne de relevé
        self.assertEqual(self.agency.mf_bank_tolerance, 0.0)
        stmt = self._mf_statement(self.ag_journal, 0.0, 300.4, [dict(entry)])
        stmt.mf_entry_ids.action_treat()
        counterpart = stmt.mf_entry_ids.statement_line_id.move_id.line_ids.filtered(lambda l: l.account_id == self.ag_in)
        self.assertEqual(round(counterpart.amount_residual, 2), -0.4)
        # activée : l'écart est soldé sur le compte de produit du journal
        fond2, partage2 = self._shared(500.0, 300.0)
        mirror2 = self._mirror_line(partage2)
        self.agency.mf_bank_tolerance = 1.0
        stmt2 = self._mf_statement(self.ag_journal, 300.4, 600.8, [dict(entry, target_line_id=mirror2.id)],
                                   d_from='2026-11-01', d_to='2026-11-30')
        stmt2.mf_entry_ids.write({'date': '2026-11-05'})
        stmt2.mf_entry_ids.action_treat()
        move = stmt2.mf_entry_ids.statement_line_id.move_id
        self.assertEqual({(l.account_id, round(l.debit, 2), round(l.credit, 2)) for l in move.line_ids},
                         {(self.ag_journal.default_account_id, 300.4, 0.0), (self.ag_in, 0.0, 300.0), (self.profit, 0.0, 0.4)})
        self.assertTrue(mirror2.reconciled)

    # (9) annulation : lettrage défait, extourne, traçabilité
    def test_cancelling_a_reconciliation_is_traced_and_restricted(self):
        fond, partage = self._shared(500.0, 300.0)
        mirror = self._mirror_line(partage)
        stmt = self._mf_statement(self.ag_journal, 0.0, 300.0, [{
            'name': 'Virement', 'amount_in': 300.0, 'treatment': 'reconcile', 'target_line_id': mirror.id}])
        entry = stmt.mf_entry_ids
        entry.action_treat()
        st_move = entry.statement_line_id.move_id
        with self.assertRaises(AccessError):
            entry.with_user(self.user_agency)._cancel_treatment('test')
        entry.with_user(self.user_accountant)._cancel_treatment('Mauvais rapprochement')
        self.assertEqual(entry.state, 'todo')
        self.assertFalse(mirror.reconciled)
        self.assertTrue(self.env['account.move'].sudo().search([('reversed_entry_id', '=', st_move.id)]))
        log = entry.log_ids.filtered(lambda l: l.action == 'cancel')
        self.assertEqual((log.user_id, log.reason), (self.user_accountant, 'Mauvais rapprochement'))
        allocation = self._allocation(fond, self.agency)
        self.assertEqual((allocation.amount_in_transit, allocation.amount_received), (300.0, 0.0))

    def test_cancelling_a_pointing_releases_the_entry(self):
        other = self._acc(self.hq, 'T116000Q', 'liability_current', False)
        direct = self.env['account.move'].create({
            'move_type': 'entry', 'journal_id': self.fdbm.id, 'date': '2026-10-02',
            'line_ids': [(0, 0, {'account_id': self.fdbm.default_account_id.id, 'debit': 70.0, 'credit': 0.0}),
                         (0, 0, {'account_id': other.id, 'debit': 0.0, 'credit': 70.0})]})
        direct.action_post()
        line = direct.line_ids.filtered(lambda l: l.debit)
        stmt = self._mf_statement(self.fdbm, 0.0, 70.0, [{'name': 'Dépôt', 'amount_in': 70.0, 'treatment': 'point', 'target_line_id': line.id}])
        stmt.mf_entry_ids.action_treat()
        stmt.mf_entry_ids.with_user(self.user_accountant)._cancel_treatment('Erreur')
        self.assertFalse(line.mf_pointed_entry_id)
        self.assertEqual(stmt.mf_entry_ids.state, 'todo')

    # nouvelle opération et suggestions
    def test_new_operation_uses_chosen_account_or_flags_suspense(self):
        fees = self._acc(self.agency, 'T627000A', 'expense', False)
        stmt = self._mf_statement(self.ag_journal, 0.0, -80.0, [
            {'name': 'Frais de tenue de compte', 'amount_out': 50.0, 'treatment': 'new', 'account_id': fees.id},
            {'name': 'Opération inconnue', 'amount_out': 30.0, 'treatment': 'new'}])
        stmt.mf_entry_ids.action_treat()
        known, unknown = stmt.mf_entry_ids.sorted('id')
        self.assertIn(fees, known.statement_line_id.move_id.line_ids.account_id)
        self.assertTrue(unknown.to_check)
        self.assertIn(self.ag_journal.suspense_account_id, unknown.statement_line_id.move_id.line_ids.account_id)

    def test_suggestion_is_proposed_but_never_applied(self):
        fond, partage = self._shared(500.0, 300.0)
        mirror = self._mirror_line(partage)
        stmt = self._mf_statement(self.ag_journal, 0.0, 300.0, [{'name': 'Virement', 'amount_in': 300.0}])
        entry = stmt.mf_entry_ids
        self.assertEqual(entry.suggested_line_id, mirror)
        self.assertEqual(entry.state, 'todo')
        self.assertFalse(entry.target_line_id)
        entry.action_take_suggestion()
        self.assertEqual((entry.treatment, entry.target_line_id), ('reconcile', mirror))
        self.assertEqual(entry.state, 'todo')

    def test_extra_pending_accounts_of_the_journal_are_candidates(self):
        cheques = self._acc(self.agency, 'T219010A', 'liability_current', True)
        self.ag_journal.mf_pending_account_ids = cheques
        issued = self.env['account.move'].create({
            'move_type': 'entry', 'journal_id': self.ag_journal.id, 'date': '2026-10-02',
            'line_ids': [(0, 0, {'account_id': cheques.id, 'debit': 0.0, 'credit': 90.0}),
                         (0, 0, {'account_id': self.profit.id, 'debit': 90.0, 'credit': 0.0})]})
        issued.action_post()
        line = issued.line_ids.filtered(lambda l: l.credit)
        stmt = self._mf_statement(self.ag_journal, 0.0, -90.0, [{'name': 'Chèque 0001', 'amount_out': 90.0, 'reference': '0001'}])
        self.assertIn(line, stmt.mf_entry_ids.candidate_line_ids)

    # (10) isolation par société
    def test_agency_user_sees_only_its_company_statements_and_journals(self):
        hq_stmt = self._mf_statement(self.fdbm, 0.0, 10.0, [{'name': 'Dépôt', 'amount_in': 10.0}])
        ag_stmt = self._mf_statement(self.ag_journal, 0.0, 10.0, [{'name': 'Dépôt', 'amount_in': 10.0}])
        user = self.user_agency
        Statement = self.env['account.bank.statement'].with_user(user).with_company(self.agency)
        seen = Statement.search([('id', 'in', (hq_stmt | ag_stmt).ids)])
        self.assertEqual(seen, ag_stmt)
        journals = self.env['account.journal'].with_user(user).with_company(self.agency).search([('type', '=', 'bank')])
        self.assertEqual(journals.mapped('company_id'), self.agency)
        entries = self.env['microfinance.bank.statement.entry'].with_user(user).with_company(self.agency).search([])
        self.assertEqual(entries.mapped('statement_id'), ag_stmt)

    def test_journal_dashboard_exposes_statement_and_book_balances(self):
        stmt = self._mf_statement(self.ag_journal, 0.0, 100.0, [{'name': 'Dépôt', 'amount_in': 100.0}])
        stmt.action_mf_validate()
        data = self.ag_journal._get_journal_dashboard_data_batched()[self.ag_journal.id]
        self.assertTrue(data['mf_enabled'])
        self.assertEqual(data['mf_todo_count'], 1)
        self.assertIn('mf_gap', data)

    # ouverture d'un NOUVEAU relevé : ce que fait le client web (default_get + onchange avec la spec de la vue)
    FORM_VIEW = 'microfinance_loan_management.view_microfinance_bank_statement_form'

    def test_new_statement_without_journal_does_not_crash(self):
        Statement = self.env['account.bank.statement']
        blank = Statement.new({})
        self.assertEqual((blank.mf_balance_computed, blank.mf_gap, blank.mf_todo_count), (0.0, 0.0, 0))
        form = Form(Statement.with_context(default_mf_state='draft'), view=self.FORM_VIEW)
        self.assertFalse(form.journal_id)
        self.assertEqual(form.mf_gap, 0.0)

    def test_new_statement_form_then_journal_then_a_line(self):
        form = Form(self.env['account.bank.statement'].with_context(default_mf_state='draft'), view=self.FORM_VIEW)
        form.journal_id = self.ag_journal
        form.mf_date_from = self.D_FROM
        form.mf_date_to = self.D_TO
        form.balance_start = 0.0
        form.balance_end_real = 300.0
        self.assertEqual(form.mf_gap, 300.0)
        with form.mf_entry_ids.new() as line:
            line.name = 'Virement BMOI'
            line.amount_in = 300.0
        self.assertEqual((form.mf_balance_computed, form.mf_gap), (300.0, 0.0))
        statement = form.save()
        self.assertEqual(statement.mf_entry_ids.date, statement.mf_date_from)
        self.assertEqual(statement.mf_gap, 0.0)

    def test_new_statement_opened_from_the_journal_kanban(self):
        action = self.ag_journal.action_mf_new_statement()
        form = Form(self.env['account.bank.statement'].with_context(**action['context']), view=self.FORM_VIEW)
        self.assertEqual(form.journal_id, self.ag_journal)
        self.assertEqual(form.mf_state, 'draft')
        form.mf_date_from = self.D_FROM
        form.mf_date_to = self.D_TO
        form.balance_end_real = 0.0
        self.assertEqual(form.mf_gap, 0.0)
        self.assertEqual(self.env['account.bank.statement'].with_context(**action['context']).new({})._mf_currency(),
                         self.ag_journal.company_id.currency_id)

    # nom lisible : jamais « False » ni « None »
    def _assert_clean_name(self, statement):
        for label in (statement.name, statement.display_name):
            self.assertTrue(label)
            self.assertNotIn('False', label)
            self.assertNotIn('None', label)

    def test_statement_name_from_the_form_with_a_single_journal(self):
        form = Form(self.env['account.bank.statement'].with_context(default_mf_state='draft'), view=self.FORM_VIEW)
        form.journal_id = self.ag_journal
        statement = form.save()
        self._assert_clean_name(statement)
        self.assertEqual(statement.name, self.ag_journal.code)

    def test_statement_name_created_by_the_orm_without_period_or_journal(self):
        no_period = self.env['account.bank.statement'].create({'journal_id': self.ag_journal.id, 'mf_state': 'draft'})
        self._assert_clean_name(no_period)
        self.assertEqual(no_period.name, self.ag_journal.code)
        no_journal = self.env['account.bank.statement'].create({'mf_state': 'draft'})
        self._assert_clean_name(no_journal)
        self.assertEqual(no_journal.name, 'Nouveau relevé')

    def test_statement_name_with_period_follows_changes_in_draft_and_is_frozen_once_validated(self):
        stmt = self._mf_statement(self.ag_journal, 0.0, 200.0, [{'name': 'Dépôt', 'amount_in': 200.0}])
        self._assert_clean_name(stmt)
        self.assertEqual(stmt.name, '%s – 01/10/26 → 31/10/26' % self.ag_journal.code)
        stmt.mf_date_to = '2026-10-30'
        self.assertEqual(stmt.name, '%s – 01/10/26 → 30/10/26' % self.ag_journal.code)
        stmt.mf_date_to = '2026-10-31'
        stmt.action_mf_validate()
        frozen = stmt.name
        stmt.with_context(mf_allow=True).write({'mf_date_from': '2026-09-28'})
        self.assertEqual(stmt.name, frozen)
        self._assert_clean_name(stmt)

    def test_new_statement_prefills_initial_balance_from_the_previous_one(self):
        first = self._mf_statement(self.ag_journal, 0.0, 200.0, [{'name': 'Dépôt', 'amount_in': 200.0}])
        first.action_mf_validate()
        form = Form(self.env['account.bank.statement'].with_context(default_mf_state='draft'), view=self.FORM_VIEW)
        form.journal_id = self.ag_journal
        form.mf_date_from = '2026-11-01'
        self.assertEqual(form.balance_start, 200.0)
