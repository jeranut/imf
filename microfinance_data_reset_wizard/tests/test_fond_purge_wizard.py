# -*- coding: utf-8 -*-
"""Purge des fonds (crédit + exploitation) : scénarios complets sur des sociétés de test, tous annulés.

La classe réutilise les fixtures des tests de liaison / relevés bancaires du module microfinance_loan_management
(sociétés mère + agences, comptes de liaison, journaux, relevés papier). Les tests hérités sont neutralisés ici :
ils tournent déjà dans leur module."""
import json
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError

from odoo.addons.microfinance_loan_management.models.microfinance_fond_allocation import MicrofinanceFondAllocation
from odoo.addons.microfinance_loan_management.models.res_company import ResCompany
from odoo.addons.microfinance_loan_management.tests.test_bank_statement_paper import TestBankStatementPaper


class TestFondPurgeWizard(TestBankStatementPaper):

    for _inherited in dir(TestBankStatementPaper):
        if _inherited.startswith('test_'):
            locals()[_inherited] = None
    del _inherited

    APPLY = 'microfinance.fond_credit_purge_apply'
    TEST_ENV = 'microfinance.raz_environnement_test'

    @classmethod
    def setUpClass(cls):
        # Les fixtures de départ créent des bailleurs avant que chaque test désigne sa société mère : sur une base qui
        # a déjà une société mère configurée (MOWGLI), la garde « mère uniquement » les refuserait.
        with patch.object(ResCompany, '_get_microfinance_parent', lambda self: self.browse()):
            super().setUpClass()
        # Administrateur technique dont la société courante est une AGENCE (pas la mère) : la purge doit passer quand
        # même, les gardes « mère uniquement » ne s'appliquent pas à cet outil d'administration.
        cls.admin = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Admin technique purge (test)', 'login': 'purge_admin', 'company_id': cls.agency.id,
            'company_ids': [(6, 0, [cls.hq.id, cls.agency.id, cls.agency2.id])],
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id, cls.env.ref('base.group_system').id])]})
        cls.Wizard = cls.env['microfinance.fond.purge.wizard'].with_user(cls.admin)
        # agence 2 complètement configurée (côté agence non configuré dans la fixture de base)
        cls.ag2_in = cls._acc(cls.agency2, 'T139100C', 'asset_current', True)
        cls.ag2_liaison = cls._acc(cls.agency2, 'T301010C', 'asset_current', True)
        cls.ag2_bank = cls._acc(cls.agency2, 'T131101C', 'asset_cash', False)
        cls.ag2_journal = cls._journal(cls.agency2, 'BMCRC', cls.ag2_bank, inbound=cls.ag2_in, usage='credit')
        cls.agency2.microfinance_liaison_agency_account_id = cls.ag2_liaison
        # fonds d'exploitation : comptes de suspens, produit de subvention, journal d'exploitation
        cls.ex_in = cls._acc(cls.hq, 'T139100X', 'asset_current', True)
        cls.ex_out = cls._acc(cls.hq, 'T139500X', 'liability_current', True)
        cls.ex_produit = cls._acc(cls.hq, 'T762XTEST', 'income_other', False)
        ex_bank = cls._acc(cls.hq, 'TBKEXPL', 'asset_cash', False)
        cls.ex_journal = cls.env['account.journal'].create({
            'name': 'BMOP test', 'code': 'BMOPT', 'type': 'bank', 'company_id': cls.hq.id,
            'default_account_id': ex_bank.id, 'microfinance_usage': 'operating', 'microfinance_bank_id': cls.bank.id})
        cls.ex_journal.inbound_payment_method_line_ids.write({'payment_account_id': cls.ex_in.id})
        cls.ex_journal.outbound_payment_method_line_ids.write({'payment_account_id': cls.ex_out.id})
        cls.hq.microfinance_fond_subvention_account_id = cls.ex_produit

    def setUp(self):
        super().setUp()
        # aucun paramètre n'est lu par la purge : on retire ceux de la base de test pour le prouver
        self.env['ir.config_parameter'].sudo().search([('key', 'in', (self.APPLY, self.TEST_ENV))]).unlink()

    # ------------------------------------------------------------------ fixtures
    def _credit_scenario(self):
        """Fonds de crédit : contribution, partage à deux agences + part gardée (écritures siège, miroirs agence et
        part gardée), une ligne de relevé rapprochée avec le miroir d'une agence."""
        fond = self._auto_fond()
        self._deposit(fond, 100000.0)
        partage = self.env['microfinance.fond.partage'].create({'fond_id': fond.id, 'base_amount': 800.0})
        for company, amount in ((self.hq, 200.0), (self.agency, 300.0), (self.agency2, 300.0)):
            partage.line_ids.filtered(lambda l: l.company_id == company).write({'amount': amount})
        partage.action_validate()
        mirror = self._mirror_line(partage).filtered(lambda l: l.company_id == self.agency)
        stmt = self._mf_statement(self.ag_journal, 0.0, 300.0, [{
            'name': 'Virement BMOI', 'amount_in': 300.0, 'treatment': 'reconcile', 'target_line_id': mirror.id}],
            user=self.user_agency)
        stmt.mf_entry_ids.action_treat()
        self.assertEqual(stmt.mf_entry_ids.state, 'done')
        self.assertTrue(mirror.reconciled)
        stmt.action_mf_validate()
        return fond, partage, stmt.mf_entry_ids

    def _expl_fond(self, nature, **kwargs):
        vals = {'name': 'Exploitation %s' % nature, 'destination': 'exploitation', 'nature': nature,
                'bank_id': self.bank.id, 'account_id': False}
        vals.update(kwargs)
        return self._create_fond(**vals)

    def _expl_contribution(self, fond, amount, reference, type_mouvement='depot'):
        contrib = self._create_contribution(fond, amount=amount, reference_paiement=reference,
                                            type_mouvement=type_mouvement)
        contrib.action_post()
        return contrib

    def _tile(self, journal):
        """Tuile du tableau de bord de la Comptabilité pour un journal bancaire."""
        self.env.flush_all()
        journal.invalidate_recordset()
        return json.loads(journal.kanban_dashboard)

    def _assert_tile_zero(self, journal):
        tile = self._tile(journal)
        zero = journal.currency_id.format(0.0) if journal.currency_id else journal.company_id.currency_id.format(0.0)
        self.assertEqual(tile['mf_statement_balance'], zero)
        self.assertFalse(tile['mf_gap_nonzero'])
        self.assertEqual(tile['mf_todo_count'], 0)

    def _exploitation_statement(self, contrib, amount):
        line = contrib.move_id.line_ids.filtered(lambda l: l.debit > 0)
        stmt = self._mf_statement(self.ex_journal, 0.0, amount, [{
            'name': 'Virement exploitation', 'amount_in': amount, 'treatment': 'reconcile',
            'target_line_id': line.id}])
        stmt.mf_entry_ids.action_treat()
        stmt.action_mf_validate()
        return stmt

    def _exploitation_scenario(self):
        subvention = self._expl_fond('subvention')
        self._expl_contribution(subvention, 7000.0, 'VIR-S')
        avance = self._expl_fond('avance')
        self._expl_contribution(avance, 5000.0, 'VIR-A')
        self._expl_contribution(avance, 2000.0, 'REMB-A', 'remboursement')
        return subvention, avance

    def _fund_moves(self, funds):
        Move = self.env['account.move'].sudo()
        partages = self.env['microfinance.fond.partage'].sudo().search([('fond_id', 'in', funds.ids)])
        contribs = self.env['microfinance.fond.contribution'].sudo().search([('fond_id', 'in', funds.ids)])
        return Move.search(['|', ('microfinance_fond_partage_id', 'in', partages.ids),
                            ('microfinance_fond_contribution_id', 'in', contribs.ids)])

    def _accounts_of(self, moves, funds=None):
        accounts = moves.line_ids.account_id
        for fond in funds or []:
            accounts |= fond.account_id
        return accounts

    def _snapshot(self):
        """Solde comptabilisé de TOUS les comptes : les bases de test (MOWGLI) portent déjà des écritures réelles, on
        compare donc l'état d'avant à l'état d'après plutôt qu'à zéro."""
        self.env.flush_all()
        self.env.cr.execute(
            "SELECT account_id, ROUND(SUM(balance)::numeric, 2) FROM account_move_line WHERE parent_state = 'posted' "
            "GROUP BY account_id")
        return {account_id: float(balance) for account_id, balance in self.env.cr.fetchall() if balance}

    def assertSnapshotEqual(self, before):
        self.assertEqual(self._snapshot(), before, 'Soldes comptables modifiés par la purge')

    def _run(self, funds, execute=True, mode_raz='reset', **options):
        # sans orphelines par défaut : les bases de test (copie de MOWGLI) en portent de réelles
        options.setdefault('include_orphans', False)
        wizard = self.Wizard.create(dict({
            'scope': 'selection', 'fond_ids': [(6, 0, funds.ids)], 'mode_raz': mode_raz}, **options))
        if execute:
            wizard.action_execute()
        else:
            wizard.action_simulate()
        return wizard

    def _audit(self):
        return self.env['microfinance.fond.purge.log'].sudo().search([], order='id desc', limit=1)

    def _all_scenario_accounts(self):
        return (self.hq_liaison, self.ag_liaison, self.ag2_liaison, self.hq_out, self.ag_in, self.fond_account,
                self.ex_in, self.ex_out, self.ex_produit)

    # ------------------------------------------------------------------ fonds de crédit complet
    def test_credit_fund_purge_without_parameter_or_simulation(self):
        zero = self._snapshot()
        fond, partage, entry = self._credit_scenario()
        moves = self._fund_moves(fond)
        # contribution + (siège, miroir) x 2 agences + part gardée
        self.assertEqual(len(moves), 6)
        self.assertNotEqual(self._snapshot(), zero)
        statement = entry.statement_id
        self.assertEqual(self._tile(self.ag_journal)['mf_statement_balance'], self.agency.currency_id.format(300.0))
        wizard = self._run(fond)
        self.assertNotIn('ERREUR', wizard.log)
        self.assertTrue(wizard.done)
        self.assertFalse(moves.exists(), "Les écritures liées sont supprimées, miroirs des agences compris.")
        self.assertSnapshotEqual(zero)
        for account in self._all_scenario_accounts() + (fond.account_id,):
            self.assertEqual(self._balance(account), 0.0, account.code)
        self.assertFalse(statement.exists() or entry.exists(), "Plus aucun relevé ne référence les fonds purgés.")
        self.assertFalse(self.env['account.bank.statement.line'].sudo().search([
            ('journal_id', 'in', (self.ag_journal | self.ag2_journal | self.fdbm).ids)]))
        self._assert_tile_zero(self.ag_journal)
        self.assertTrue(fond.exists())
        for model in ('contribution', 'partage', 'allocation'):
            self.assertFalse(self.env['microfinance.fond.' + model].sudo().search([('fond_id', '=', fond.id)]))
        self.assertEqual((fond.total_contributions, fond.reste_partageable), (0.0, 0.0))
        log = self._audit()
        self.assertEqual((log.state, log.user_id), ('done', self.admin))
        self.assertTrue(log.counts and log.balances_before and log.balances_after)
        self.assertFalse(log.anomalies)
        self.assertEqual((log.n_statements, log.n_entries), (1, 1))
        self.assertGreaterEqual(log.n_moves, 8)  # 6 écritures de fonds + écriture du relevé (+ miroir)

    def test_simulation_changes_nothing_and_is_optional(self):
        fond, partage, entry = self._credit_scenario()
        before = self._snapshot()
        moves = self._fund_moves(fond)
        wizard = self._run(fond, execute=False)
        self.assertNotIn('ERREUR', wizard.log)
        self.assertSnapshotEqual(before)
        self.assertEqual(self._fund_moves(fond), moves)
        self.assertEqual(entry.state, 'done')
        items = {(line.company_name, line.item): line.count for line in wizard.line_ids}
        self.assertEqual(items[(self.hq.name, 'Contributions')], 1)
        self.assertEqual(items[(self.agency.name, 'Lignes de relevé délettrées (remises à traiter)')], 1)
        self.assertEqual(items[(self.agency2.name, 'Parts de partage')], 1)
        self.assertEqual(items[(self.agency.name, 'Relevés bancaires supprimés')], 1)
        self.assertEqual(items[(self.agency.name, 'Lignes de relevé supprimées')], 1)
        self.assertTrue(entry.exists() and entry.statement_id.exists())
        self.assertTrue(wizard.balance_ids)
        self.assertFalse(wizard.balance_ids.filtered(lambda b: b.flag.startswith('ANOMALIE')))
        self.assertFalse(self.env['microfinance.fond.purge.log'].sudo().search([]))
        self.assertIn('1 fonds, 1 relevés', wizard.summary)

    # ------------------------------------------------------------------ fonds d'exploitation
    def test_exploitation_funds_purge_zero_balances(self):
        zero = self._snapshot()
        subvention, avance = self._exploitation_scenario()
        funds = subvention | avance
        moves = self._fund_moves(funds)
        self.assertEqual(len(moves), 3)
        stmt = self._exploitation_statement(subvention.contribution_ids, 7000.0)
        self.assertNotEqual(self._tile(self.ex_journal)['mf_statement_balance'], '')
        self.assertEqual(self._balance(self.ex_produit), -7000.0)
        self.assertEqual(self._balance(avance.account_id), -3000.0)
        wizard = self._run(funds)
        self.assertNotIn('ERREUR', wizard.log)
        self.assertFalse(moves.exists())
        self.assertFalse(stmt.exists())
        self._assert_tile_zero(self.ex_journal)
        self.assertSnapshotEqual(zero)
        for account in (self.ex_in, self.ex_out, self.ex_produit, avance.account_id):
            self.assertEqual(self._balance(account), 0.0, account.code)
        self.assertTrue(funds.exists() == funds)
        self.assertEqual((avance.exploitation_recu, avance.exploitation_du), (0.0, 0.0))

    def test_exploitation_partage_is_purged_with_its_two_moves_and_its_link(self):
        """Partage d'un fonds d'exploitation à une agence : la purge supprime le partage, sa part, l'écriture du siège et
        le miroir de l'agence, et remet les soldes comme avant."""
        zero = self._snapshot()
        ag_bank = self._acc(self.agency, 'T131OPA', 'asset_cash', False)
        self._journal(self.agency, 'BMOPA', ag_bank, inbound=self.ag_in, usage='operating')
        fond = self._expl_fond('subvention')
        self._expl_contribution(fond, 10000.0, 'VIR-P')
        partage = self.env['microfinance.fond.partage'].with_context(partage_destination='exploitation').create({
            'fond_id': fond.id, 'line_ids': [(0, 0, {'company_id': self.agency.id, 'amount': 4000.0})]})
        partage.action_validate()
        line = partage.line_ids.filtered(lambda l: l.amount)
        moves = self._fund_moves(fond)
        self.assertEqual(len(moves), 3)   # contribution + écriture du siège + miroir de l'agence
        self.assertTrue(line.hq_move_id and line.agency_move_id)
        wizard = self._run(fond)
        self.assertNotIn('ERREUR', wizard.log)
        self.assertFalse(moves.exists())
        self.assertFalse(partage.exists() or line.exists())
        self.assertFalse(self.env['account.move'].sudo().search([('microfinance_fond_partage_id', '=', partage.id)]))
        self.assertSnapshotEqual(zero)
        self.assertEqual((fond.total_contributions, fond.reste_partageable), (0.0, 0.0))

    def test_credit_and_exploitation_together(self):
        zero = self._snapshot()
        fond, partage, entry = self._credit_scenario()
        subvention, avance = self._exploitation_scenario()
        wizard = self._run(fond | subvention | avance)
        self.assertNotIn('ERREUR', wizard.log)
        self.assertSnapshotEqual(zero)
        self.assertFalse(entry.exists())

    # ------------------------------------------------------------------ reset / suppression du fonds
    def test_reset_keeps_the_fund_and_delete_removes_it_and_archives_its_account(self):
        subvention, avance = self._exploitation_scenario()
        account = avance.account_id
        self.assertTrue(avance.account_auto and account.code.startswith('240'))
        self._run(avance, mode_raz='reset')
        self.assertTrue(avance.exists())
        self.assertEqual(avance.exploitation_recu, 0.0)
        self.assertTrue(account.deprecated is False)
        autre = self._expl_fond('avance')
        self._expl_contribution(autre, 900.0, 'VIR-B')
        autre_account, autre_id = autre.account_id, autre.id
        wizard = self._run(autre, mode_raz='delete_fund')
        self.assertNotIn('ERREUR', wizard.log)
        self.assertFalse(self.env['microfinance.fond.credit'].sudo().with_context(active_test=False).search(
            [('id', '=', autre_id)]))
        self.assertTrue(autre_account.exists(), "Le compte d'origine n'est jamais supprimé.")
        self.assertTrue(autre_account.deprecated)
        self.assertTrue(subvention.exists() and avance.exists())

    def test_non_automatic_account_is_never_archived(self):
        fond = self._expl_fond('avance', account_id=self.fond_account.id)
        self.assertFalse(fond.account_auto)
        self._run(fond, mode_raz='delete_fund')
        self.assertFalse(fond.exists())
        self.assertFalse(self.fond_account.deprecated)

    # ------------------------------------------------------------------ dépendance inconnue
    def test_unknown_foreign_key_stops_before_any_deletion(self):
        subvention, avance = self._exploitation_scenario()
        self.env.cr.execute("CREATE TABLE test_purge_dep (id serial PRIMARY KEY, "
                            "fond_id integer REFERENCES microfinance_fond_credit(id))")
        self.env.cr.execute("INSERT INTO test_purge_dep (fond_id) VALUES (%s)", (avance.id,))
        moves = self._fund_moves(avance)
        wizard = self._run(avance, execute=False)
        self.assertIn('test_purge_dep', wizard.log)
        with self.assertRaises(UserError) as caught:
            self._run(avance)
        self.assertIn('test_purge_dep', str(caught.exception))
        self.assertTrue(moves.exists() == moves)
        self.assertEqual(len(avance.contribution_ids), 2)

    # ------------------------------------------------------------------ rollback complet
    def test_error_in_the_middle_rolls_everything_back(self):
        fond, partage, entry = self._credit_scenario()
        moves = self._fund_moves(fond)
        move_count = self.env['account.move'].sudo().search_count([])
        wizard = self.Wizard.create({'scope': 'selection', 'fond_ids': [(6, 0, fond.ids)]})
        with patch.object(MicrofinanceFondAllocation, 'unlink', side_effect=UserError('Erreur injectée')):
            wizard.action_execute()
        self.assertIn('ERREUR', wizard.log)
        self.assertIn('Erreur injectée', wizard.log)
        self.assertFalse(wizard.done)
        self.assertEqual(self.env['account.move'].sudo().search_count([]), move_count)
        self.assertEqual(entry.state, 'done')
        self.assertTrue(entry.statement_line_id)
        self.assertEqual(len(self.env['microfinance.fond.partage'].sudo().search([('fond_id', '=', fond.id)])), 1)
        self.assertEqual(len(self.env['microfinance.fond.contribution'].sudo().search([('fond_id', '=', fond.id)])), 1)
        self.assertEqual(len(self.env['microfinance.fond.allocation'].sudo().search([('fond_id', '=', fond.id)])), 3)
        self.assertEqual(self._fund_moves(fond), moves)
        self.assertEqual(self._audit().state, 'failed')

    # ------------------------------------------------------------------ droits
    def test_only_the_technical_administrator_reaches_menu_action_and_model(self):
        manager = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Manager crédit (test)', 'login': 'purge_manager', 'company_id': self.hq.id,
            'company_ids': [(6, 0, [self.hq.id])],
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id,
                                  self.env.ref('microfinance_loan_management.group_microfinance_manager').id])]})
        menu = self.env.ref('microfinance_data_reset_wizard.menu_microfinance_fond_purge_wizard')
        action = self.env.ref('microfinance_data_reset_wizard.action_microfinance_fond_purge_wizard')
        self.assertEqual(menu.name, 'Purge des fonds')
        self.assertEqual(action.groups_id, self.env.ref('base.group_system'))
        self.assertNotIn(menu.id, self.env['ir.ui.menu'].with_user(manager)._visible_menu_ids())
        self.assertIn(menu.id, self.env['ir.ui.menu'].with_user(self.admin)._visible_menu_ids())
        # accès direct par URL (#action=...) : l'écran ne peut ni s'ouvrir ni s'exécuter sans le groupe
        Wizard = self.env['microfinance.fond.purge.wizard'].with_user(manager)
        self.assertFalse(Wizard.check_access_rights('read', raise_exception=False))
        with self.assertRaises(AccessError):
            Wizard.search([])
        with self.assertRaises(AccessError):
            Wizard.create({'scope': 'both'})
        with self.assertRaises(AccessError):
            self.env['microfinance.fond.purge.log'].with_user(manager).search([])
        wizard = self.Wizard.create({'scope': 'both'})
        with self.assertRaises(AccessError):
            wizard.with_user(manager).action_execute()

    # ------------------------------------------------------------------ fonds non sélectionnés intacts
    def test_unselected_funds_and_unrelated_moves_stay_untouched(self):
        subvention, avance = self._exploitation_scenario()
        other_moves = self._fund_moves(subvention)
        free = self.env['account.move'].sudo().with_company(self.hq).create({
            'move_type': 'entry', 'journal_id': self.ex_journal.id, 'date': '2026-10-08', 'ref': 'Hors fonds',
            'line_ids': [(0, 0, {'name': 'x', 'account_id': self.ex_in.id, 'debit': 123.0, 'credit': 0.0}),
                         (0, 0, {'name': 'x', 'account_id': self.ex_produit.id, 'debit': 0.0, 'credit': 123.0})]})
        free.action_post()
        other_stmt = self._exploitation_statement(subvention.contribution_ids, 7000.0)
        before_other = self._balance(self.ex_produit)
        wizard = self._run(avance, mode_raz='delete_fund')
        self.assertNotIn('ERREUR', wizard.log)
        self.assertTrue(subvention.exists())
        self.assertEqual(subvention.contribution_ids.move_id, other_moves)
        self.assertEqual(other_moves.state, 'posted')
        self.assertEqual(free.state, 'posted')
        self.assertEqual(self._balance(self.ex_produit), before_other)
        self.assertTrue(other_stmt.exists())
        self.assertEqual(other_stmt.mf_entry_ids.state, 'done')
        self.assertEqual(other_stmt.mf_state, 'validated')

    # ------------------------------------------------------------------ écritures orphelines
    def test_orphan_moves_of_fund_journals_are_purged_but_not_those_of_existing_funds(self):
        subvention, avance = self._exploitation_scenario()
        ancien = self._expl_fond('subvention')
        contrib = self._expl_contribution(ancien, 400.0, 'VIR-OLD')
        orphan = contrib.move_id
        contrib.unlink()
        ancien.unlink()
        self.assertFalse(orphan.microfinance_fond_contribution_id)
        kept = self._fund_moves(subvention)
        wizard = self._run(avance, execute=False, include_orphans=False)
        self.assertFalse(wizard.line_ids.filtered(lambda l: l.item.startswith('Écritures orphelines')))
        wizard = self._run(avance, include_orphans=True)
        self.assertNotIn('ERREUR', wizard.log)
        self.assertFalse(orphan.exists())
        self.assertTrue(kept.exists() == kept, "L'écriture d'un fonds existant non sélectionné reste intacte.")
        self.assertEqual(self._balance(self.ex_produit), -7000.0)
        self._run(subvention, include_orphans=True)
        for account in (self.ex_in, self.ex_out, self.ex_produit):
            self.assertEqual(self._balance(account), 0.0, account.code)

    # ------------------------------------------------------------------ relevés sans lien avec les fonds
    def test_unrelated_statement_is_kept_by_default_and_deleted_when_the_box_is_checked(self):
        zero = self._snapshot()
        fond, partage, entry = self._credit_scenario()
        free = self._mf_statement(self.ag_journal, 300.0, 250.0, [{
            'name': 'Frais bancaires', 'amount_out': 50.0, 'treatment': 'new', 'account_id': self.loss.id}])
        free.mf_entry_ids.action_treat()
        free.action_mf_validate()
        free_move = free.line_ids.move_id
        self.assertTrue(free_move)
        wizard = self._run(fond)
        self.assertNotIn('ERREUR', wizard.log)
        self.assertTrue(free.exists() and free_move.exists(), "Relevé sans lien avec les fonds : conservé par défaut.")
        self.assertFalse(entry.exists())
        # le relevé conservé est supprimé quand la case est cochée
        wizard = self._run(fond, delete_other_statements=True)
        self.assertNotIn('ERREUR', wizard.log)
        self.assertFalse(free.exists() or free_move.exists())
        self._assert_tile_zero(self.ag_journal)
        self.assertSnapshotEqual(zero)

    def test_statement_with_unlinked_lines_is_deleted_and_listed_in_the_audit(self):
        fond, partage, entry = self._credit_scenario()
        stmt = entry.statement_id
        extra = self.env['microfinance.bank.statement.entry'].sudo()
        # relevé validé : on le rouvre pour y ajouter une ligne sans lien avant la purge
        stmt.sudo().with_context(mf_allow=True).mf_state = 'draft'
        extra = extra.create({'statement_id': stmt.id, 'name': 'Ligne libre', 'amount_out': 10.0, 'date': '2026-10-06'})
        wizard = self._run(fond)
        self.assertNotIn('ERREUR', wizard.log)
        self.assertFalse(stmt.exists() or extra.exists())
        self.assertIn('dont 1 sans lien avec les fonds', self._audit().statements)
