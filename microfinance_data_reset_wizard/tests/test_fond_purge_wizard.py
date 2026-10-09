# -*- coding: utf-8 -*-
"""Purge des fonds (crédit + exploitation) : scénarios complets sur des sociétés de test, tous annulés.

La classe réutilise les fixtures des tests de liaison / relevés bancaires du module microfinance_loan_management
(sociétés mère + agences, comptes de liaison, journaux, relevés papier). Les tests hérités sont neutralisés ici :
ils tournent déjà dans leur module."""
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
        self.env['ir.config_parameter'].sudo().set_param(self.APPLY, 'True')
        self.env['ir.config_parameter'].sudo().set_param(self.TEST_ENV, 'False')

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

    def _run(self, funds, execute=True, mode_raz='reset', move_mode='reverse', **options):
        wizard = self.Wizard.create(dict({
            'scope': 'selection', 'fond_ids': [(6, 0, funds.ids)], 'mode_raz': mode_raz, 'move_mode': move_mode},
            **options))
        wizard.action_simulate()
        if execute:
            self.assertTrue(wizard.simulated_key, wizard.log)
            wizard.confirm_text = 'PURGER'
            wizard.action_execute()
        return wizard

    def _audit(self):
        return self.env['microfinance.fond.purge.log'].sudo().search([], order='id desc', limit=1)

    # ------------------------------------------------------------------ (1) fonds de crédit complet, mode A
    def test_credit_fund_mode_a_reverses_everything_and_resets_statement_lines(self):
        zero = self._snapshot()
        fond, partage, entry = self._credit_scenario()
        moves = self._fund_moves(fond)
        # contribution + (siège, miroir) x 2 agences + part gardée
        self.assertEqual(len(moves), 6)
        self.assertNotEqual(self._snapshot(), zero)
        wizard = self._run(fond)
        self.assertNotIn('ERREUR', wizard.log)
        self.assertTrue(wizard.done)
        self.assertSnapshotEqual(zero)
        for account in (self.hq_liaison, self.ag_liaison, self.ag2_liaison, self.hq_out, self.ag_in, self.fond_account,
                        fond.account_id):
            self.assertEqual(self._balance(account), 0.0, account.code)
        self.assertEqual(entry.state, 'todo')
        self.assertFalse(entry.statement_line_id)
        self.assertTrue(entry.statement_id.exists(), "Le relevé n'est jamais supprimé.")
        # le fonds reste, ses contributions / partages / allocations ont disparu, les écritures sont conservées
        self.assertTrue(fond.exists())
        self.assertFalse(self.env['microfinance.fond.contribution'].sudo().search([('fond_id', '=', fond.id)]))
        self.assertFalse(self.env['microfinance.fond.partage'].sudo().search([('fond_id', '=', fond.id)]))
        self.assertFalse(self.env['microfinance.fond.allocation'].sudo().search([('fond_id', '=', fond.id)]))
        self.assertTrue(moves.exists() == moves)
        self.assertEqual(set(moves.mapped('state')), {'posted'})
        self.assertFalse(moves.mapped('microfinance_fond_partage_id'))
        self.assertEqual(fond.total_contributions, 0.0)
        self.assertEqual(fond.reste_partageable, 0.0)
        log = self._audit()
        self.assertEqual((log.state, log.user_id), ('done', self.admin))
        self.assertTrue(log.counts and log.balances_before and log.balances_after and log.kept_moves)
        self.assertFalse(log.anomalies)

    def test_simulation_changes_nothing_and_lists_companies_models_and_balances(self):
        fond, partage, entry = self._credit_scenario()
        before = self._snapshot()
        wizard = self._run(fond, execute=False)
        self.assertTrue(wizard.can_execute, wizard.log)
        self.assertSnapshotEqual(before)
        self.assertEqual(entry.state, 'done')
        items = {(line.company_name, line.item): line.count for line in wizard.line_ids}
        self.assertEqual(items[(self.hq.name, 'Contributions')], 1)
        self.assertEqual(items[(self.agency.name, 'Lignes de relevé délettrées (remises à traiter)')], 1)
        self.assertEqual(items[(self.agency2.name, 'Parts de partage')], 1)
        self.assertTrue(wizard.balance_ids)
        self.assertFalse(wizard.balance_ids.filtered(lambda b: b.flag.startswith('ANOMALIE')))
        self.assertFalse(self.env['microfinance.fond.purge.log'].sudo().search([]))

    # ------------------------------------------------------------------ (2) fonds d'exploitation, mode A
    def test_exploitation_funds_mode_a_zero_balances(self):
        subvention, avance = self._exploitation_scenario()
        funds = subvention | avance
        moves = self._fund_moves(funds)
        self.assertEqual(len(moves), 3)
        self.assertEqual(self._balance(self.ex_produit), -7000.0)
        self.assertEqual(self._balance(avance.account_id), -3000.0)
        wizard = self._run(funds)
        self.assertNotIn('ERREUR', wizard.log)
        for account in (self.ex_in, self.ex_out, self.ex_produit, avance.account_id):
            self.assertEqual(self._balance(account), 0.0, account.code)
        self.assertTrue(funds.exists() == funds)
        self.assertEqual((avance.exploitation_recu, avance.exploitation_du), (0.0, 0.0))

    # ------------------------------------------------------------------ (3) mode B
    def test_mode_b_deletes_moves_when_test_environment_parameter_is_true(self):
        self.env['ir.config_parameter'].sudo().set_param(self.TEST_ENV, 'True')
        zero = self._snapshot()
        fond, partage, entry = self._credit_scenario()
        subvention, avance = self._exploitation_scenario()
        funds = fond | subvention | avance
        moves = self._fund_moves(funds)
        wizard = self._run(funds, move_mode='delete')
        self.assertNotIn('ERREUR', wizard.log)
        self.assertFalse(moves.exists())
        self.assertSnapshotEqual(zero)
        self.assertEqual(entry.state, 'todo')

    def test_mode_b_refused_without_test_environment_parameter(self):
        subvention, avance = self._exploitation_scenario()
        funds = subvention | avance
        moves = self._fund_moves(funds)
        wizard = self._run(funds, execute=False, move_mode='delete')
        self.assertTrue(wizard.has_blockers)
        self.assertFalse(wizard.can_execute)
        self.assertIn(self.TEST_ENV, wizard.log)
        wizard.confirm_text = 'PURGER'
        with self.assertRaises(UserError):
            wizard.action_execute()
        self.assertTrue(moves.exists() == moves)
        self.assertEqual(self._balance(self.ex_produit), -7000.0)

    # ------------------------------------------------------------------ (4) reset / suppression du fonds
    def test_reset_keeps_the_fund_and_delete_removes_it_and_archives_its_account(self):
        subvention, avance = self._exploitation_scenario()
        account = avance.account_id
        self.assertTrue(avance.account_auto and account.code.startswith('240'))
        self._run(avance, mode_raz='reset')
        self.assertTrue(avance.exists())
        self.assertFalse(account.deprecated)
        self.assertEqual(avance.exploitation_recu, 0.0)
        # un second fonds, supprimé en une seule opération : son compte d'origine est archivé, jamais supprimé
        autre = self._expl_fond('avance')
        self._expl_contribution(autre, 900.0, 'VIR-B')
        autre_account, autre_id = autre.account_id, autre.id
        wizard = self._run(autre, mode_raz='delete_fund')
        self.assertNotIn('ERREUR', wizard.log)
        self.assertFalse(self.env['microfinance.fond.credit'].sudo().with_context(active_test=False).search(
            [('id', '=', autre_id)]))
        self.assertTrue(autre_account.exists(), "Le compte d'origine n'est jamais supprimé.")
        self.assertTrue(autre_account.deprecated)
        self.assertEqual(self._balance(autre_account), 0.0)
        self.assertTrue(subvention.exists() and avance.exists())
        # le fonds remis à zéro avant : son compte garde l'historique d'une purge précédente, il n'est pas archivé
        self._run(avance, mode_raz='delete_fund')
        self.assertFalse(avance.exists())
        self.assertFalse(account.deprecated)

    def test_non_automatic_account_is_never_archived(self):
        fond = self._expl_fond('avance', account_id=self.fond_account.id)
        self.assertFalse(fond.account_auto)
        self._run(fond, mode_raz='delete_fund')
        self.assertFalse(fond.exists())
        self.assertFalse(self.fond_account.deprecated)

    # ------------------------------------------------------------------ (5) dépendance inconnue
    def test_unknown_foreign_key_stops_before_any_deletion(self):
        subvention, avance = self._exploitation_scenario()
        self.env.cr.execute("CREATE TABLE test_purge_dep (id serial PRIMARY KEY, "
                            "fond_id integer REFERENCES microfinance_fond_credit(id))")
        self.env.cr.execute("INSERT INTO test_purge_dep (fond_id) VALUES (%s)", (avance.id,))
        moves = self._fund_moves(avance)
        wizard = self._run(avance, execute=False)
        self.assertTrue(wizard.has_blockers)
        self.assertIn('test_purge_dep', wizard.log)
        wizard.confirm_text = 'PURGER'
        with self.assertRaises(UserError):
            wizard.action_execute()
        self.assertTrue(moves.exists() == moves)
        self.assertEqual(len(avance.contribution_ids), 2)

    # ------------------------------------------------------------------ (6) garde-fous
    def test_guards_parameter_phrase_and_simulation(self):
        subvention, avance = self._exploitation_scenario()
        moves = self._fund_moves(avance)
        wizard = self.Wizard.create({'scope': 'selection', 'fond_ids': [(6, 0, avance.ids)]})
        wizard.confirm_text = 'PURGER'
        with self.assertRaises(UserError):  # pas de simulation
            wizard.action_execute()
        wizard.action_simulate()
        wizard.confirm_text = 'purger'
        with self.assertRaises(UserError):  # mot incorrect
            wizard.action_execute()
        wizard.confirm_text = False
        with self.assertRaises(UserError):  # mot absent
            wizard.action_execute()
        wizard.confirm_text = 'PURGER'
        wizard.fond_ids = [(6, 0, (avance | subvention).ids)]
        self.assertFalse(wizard.can_execute)
        with self.assertRaises(UserError):  # sélection modifiée depuis la simulation
            wizard.action_execute()
        wizard.fond_ids = [(6, 0, avance.ids)]
        wizard.move_mode = 'reverse'
        wizard.action_simulate()
        self.env['ir.config_parameter'].sudo().set_param(self.APPLY, 'False')
        wizard.confirm_text = 'PURGER'
        with self.assertRaises(UserError):  # paramètre d'exécution absent
            wizard.action_execute()
        self.assertTrue(moves.exists() == moves)
        self.assertEqual(len(avance.contribution_ids), 2)
        self.assertFalse(self.env['microfinance.fond.purge.log'].sudo().search([]))

    def test_mirror_moves_are_left_in_place_when_the_option_is_unchecked(self):
        fond, partage, entry = self._credit_scenario()
        mirrors = self._fund_moves(fond).filtered(lambda m: m.microfinance_partage_side == 'agency')
        self.assertEqual(len(mirrors), 2)
        wizard = self._run(fond, include_mirror=False)
        self.assertNotIn('ERREUR', wizard.log)
        self.assertFalse(self.env['account.move'].sudo().search([('reversed_entry_id', 'in', mirrors.ids)]))
        self.assertEqual(set(mirrors.mapped('state')), {'posted'})
        self.assertFalse(mirrors.mapped('microfinance_fond_partage_id'))
        self.assertEqual(self._balance(self.ag_liaison), -300.0)
        self.assertEqual(self._balance(self.hq_out), 0.0)
        self.assertEqual(entry.state, 'done')  # le miroir rapproché n'est pas touché

    def test_unchecked_bank_option_blocks_reconciled_lines(self):
        fond, partage, entry = self._credit_scenario()
        wizard = self._run(fond, execute=False, undo_bank=False)
        self.assertTrue(wizard.has_blockers)
        self.assertIn('rapproch', wizard.log)
        self.assertEqual(entry.state, 'done')

    # ------------------------------------------------------------------ (7) rollback complet
    def test_error_in_the_middle_rolls_everything_back(self):
        fond, partage, entry = self._credit_scenario()
        moves = self._fund_moves(fond)
        move_count = self.env['account.move'].sudo().search_count([])
        wizard = self.Wizard.create({'scope': 'selection', 'fond_ids': [(6, 0, fond.ids)]})
        wizard.action_simulate()
        wizard.confirm_text = 'PURGER'
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

    # ------------------------------------------------------------------ (8) droits
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
        with self.assertRaises(AccessError):
            self.env['microfinance.fond.purge.wizard'].with_user(manager).create({'scope': 'both'})
        with self.assertRaises(AccessError):
            self.env['microfinance.fond.purge.log'].with_user(manager).search([])
        legacy_menu = self.env.ref('microfinance_data_reset_wizard.menu_microfinance_fond_credit_purge_wizard',
                                   raise_if_not_found=False)
        self.assertFalse(legacy_menu)

    # ------------------------------------------------------------------ (9) fonds non sélectionnés intacts
    def test_unselected_funds_and_unrelated_moves_stay_untouched(self):
        subvention, avance = self._exploitation_scenario()
        other_moves = self._fund_moves(subvention)
        other_balance = self._balance(self.ex_produit)
        # écriture hors fonds, sur les mêmes comptes de suspens
        free = self.env['account.move'].sudo().with_company(self.hq).create({
            'move_type': 'entry', 'journal_id': self.ex_journal.id, 'date': '2026-10-08', 'ref': 'Hors fonds',
            'line_ids': [(0, 0, {'name': 'x', 'account_id': self.ex_in.id, 'debit': 123.0, 'credit': 0.0}),
                         (0, 0, {'name': 'x', 'account_id': self.ex_produit.id, 'debit': 0.0, 'credit': 123.0})]})
        free.action_post()
        wizard = self._run(avance, mode_raz='delete_fund')
        self.assertNotIn('ERREUR', wizard.log)
        self.assertTrue(subvention.exists())
        self.assertEqual(len(subvention.contribution_ids), 1)
        self.assertEqual(subvention.contribution_ids.move_id, other_moves)
        self.assertEqual(other_moves.state, 'posted')
        self.assertFalse(self.env['account.move'].sudo().search([('reversed_entry_id', 'in', (other_moves | free).ids)]))
        self.assertEqual(free.state, 'posted')
        self.assertEqual(self._balance(self.ex_produit), other_balance - 123.0)
