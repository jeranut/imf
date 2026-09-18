# -*- coding: utf-8 -*-
"""Confirmation du flux de clôture en 3 temps (Comptage -> Récapitulatif -> Écart) avec un vrai
théorique issu de mouvements de guichet (microfinance.caisse.mouvement) : comptage, écart,
verrou concurrentiel, rollback sur échec de action_close_session, et écriture d'écart en
attente + réconciliation manuelle.

Le théorique n'est calculé qu'au passage temps 2 -> temps 3 (recap.wizard.action_confirm_recap)
et relu une dernière fois, frais, dans variance.wizard.action_confirm_close — jamais une valeur
posée à la main. Le tester exige donc un vrai microfinance.caisse.mouvement, indisponible dans
microfinance_loan_management/tests/ (cf. docstring de test_caisse_close_wizard.py) : ces tests
vivent ici."""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError

from .common import SavingsCommon


class TestCaisseCloseSessionWizardConfirm(SavingsCommon):

    def setUp(self):
        super().setUp()
        self.env['microfinance.caisse.denomination'].search([]).write({'active': False})
        currency = self.env.company.currency_id
        self.d1000 = self.env['microfinance.caisse.denomination'].create({
            'name': 'Wizard confirm test 1000', 'value': 1000.0, 'currency_id': currency.id,
        })
        self.d500 = self.env['microfinance.caisse.denomination'].create({
            'name': 'Wizard confirm test 500', 'value': 500.0, 'currency_id': currency.id,
        })

    def _open_session(self, journal=None, date=None):
        session = self.env['microfinance.caisse.session'].create({
            'journal_id': (journal or self.disbursement_journal).id, 'date': date or fields.Date.today(),
        })
        session.action_open_session()
        return session

    def _register_deposit(self, session, amount):
        """Encaissement guichet réel (dépôt épargne) : alimente session.theoretical_balance via
        les mêmes mécanismes que le guichet en production, sans raccourci."""
        account = self._create_active_account(opening_amount=0.0)
        return self.env['microfinance.caisse.mouvement'].register_operation(
            session.id, 'depot_epargne', self.partner.id, amount, account.id, False,
        )

    def _wizard1(self, session):
        return self.env['microfinance.caisse.close.session.wizard'].with_context(
            default_session_id=session.id).create({})

    def _set_quantities(self, wizard, mapping):
        for line in wizard.line_ids:
            if line.denomination_id in mapping:
                line.quantity = mapping[line.denomination_id]

    def _advance_to_recap(self, wizard1):
        action = wizard1.action_confirm_count()
        return self.env['microfinance.caisse.close.session.recap.wizard'].browse(action['res_id'])

    def _advance_to_variance(self, recap):
        action = recap.action_confirm_recap()
        return self.env['microfinance.caisse.close.session.variance.wizard'].browse(action['res_id'])

    def _close(self, session, amount, mapping):
        """Parcourt les 3 temps jusqu'au bout et renvoie le wizard d'écart (après confirmation)
        pour inspection, sans poser de commentaire d'écart."""
        self._register_deposit(session, amount)
        wizard1 = self._wizard1(session)
        self._set_quantities(wizard1, mapping)
        recap = self._advance_to_recap(wizard1)
        variance = self._advance_to_variance(recap)
        return variance

    # --- Régression : payload de comptage confirmé sur une session à théorique non nul ---
    # (AUDIT_denomination_id_manquant : le bug initialement rapporté se manifestait au clic sur
    # "Confirmer le comptage" avec un solde théorique non nul en jeu côté session réelle.)

    def test_confirm_count_with_real_theoretical_balance_creates_valid_lines(self):
        session = self._open_session()
        self._register_deposit(session, 1500.0)  # théorique non nul pour cette session
        wizard1 = self._wizard1(session)
        self.assertTrue(wizard1.line_ids)
        self.assertTrue(all(wizard1.line_ids.mapped('denomination_id')))
        self._set_quantities(wizard1, {self.d1000: 1, self.d500: 1})
        action = wizard1.action_confirm_count()  # ne doit pas lever
        recap = self.env['microfinance.caisse.close.session.recap.wizard'].browse(action['res_id'])
        self.assertEqual(recap.counted_total, 1500.0)
        variance = self._advance_to_variance(recap)
        self.assertAlmostEqual(variance.theoretical_total, 1500.0, places=2)
        variance.action_confirm_close()  # va jusqu'au bout, ne doit pas lever non plus
        self.assertEqual(session.state, 'closed')

    # --- Le théorique n'apparaît qu'au temps 3 ---

    def test_variance_wizard_theoretical_matches_real_movements(self):
        session = self._open_session()
        self._register_deposit(session, 1500.0)
        wizard1 = self._wizard1(session)
        self._set_quantities(wizard1, {self.d1000: 1, self.d500: 1})
        recap = self._advance_to_recap(wizard1)
        variance = self._advance_to_variance(recap)
        self.assertAlmostEqual(variance.theoretical_total, 1500.0, places=2)
        self.assertAlmostEqual(variance.counted_total, 1500.0, places=2)
        self.assertAlmostEqual(variance.variance, 0.0, places=2)

    def test_variance_action_back_reopens_step1_with_same_quantities(self):
        session = self._open_session()
        self._register_deposit(session, 1500.0)
        wizard1 = self._wizard1(session)
        self._set_quantities(wizard1, {self.d1000: 1, self.d500: 1})
        recap = self._advance_to_recap(wizard1)
        variance = self._advance_to_variance(recap)
        action = variance.action_back()
        self.assertEqual(action['res_id'], wizard1.id)
        self.assertEqual(
            self.env['microfinance.caisse.close.session.wizard'].browse(action['res_id']).counted_total,
            1500.0,
        )

    # --- Clôture exacte ---

    def test_close_exact_no_comment(self):
        variance = self._close(self._open_session(), 1500.0, {self.d1000: 1, self.d500: 1})
        self.assertEqual(variance.variance, 0.0)
        variance.action_confirm_close()
        session = variance.session_id
        self.assertEqual(session.state, 'closed')
        self.assertEqual(session.fiche_journee_id.state, 'closed')
        comptage = self.env['microfinance.caisse.comptage'].search([('session_id', '=', session.id)])
        self.assertEqual(len(comptage), 1)
        self.assertEqual(comptage.counted_total, 1500.0)
        self.assertEqual(comptage.theoretical_total, 1500.0)
        self.assertEqual(comptage.variance, 0.0)
        self.assertEqual(comptage.variance_state, 'none')
        self.assertFalse(comptage.variance_move_id)

    # --- Clôture avec écart ---

    def test_close_with_variance_and_comment_succeeds(self):
        variance = self._close(self._open_session(), 1500.0, {self.d1000: 1})  # 1000 compté, théorique 1500
        variance.variance_comment = 'Écart de caisse constaté à la clôture.'
        variance.action_confirm_close()
        comptage = self.env['microfinance.caisse.comptage'].search([
            ('session_id', '=', variance.session_id.id)])
        self.assertEqual(comptage.variance, -500.0)
        self.assertTrue(comptage.variance_comment)

    def test_close_with_variance_without_comment_blocked(self):
        session = self._open_session()
        variance = self._close(session, 1500.0, {self.d1000: 1})
        with self.assertRaises(UserError):
            with self.env.cr.savepoint():
                variance.action_confirm_close()
        self.assertEqual(session.state, 'open')
        self.assertEqual(
            self.env['microfinance.caisse.comptage'].search_count([('session_id', '=', session.id)]), 0)

    # --- Écriture d'écart en attente + réconciliation ---

    def test_variance_move_posted_in_pending_state_on_shortage(self):
        session = self._open_session()
        variance = self._close(session, 1500.0, {self.d1000: 1})  # 1000 compté, théorique 1500 -> manque 500
        variance.variance_comment = 'Manque constaté.'
        variance.action_confirm_close()
        comptage = self.env['microfinance.caisse.comptage'].search([('session_id', '=', session.id)])
        self.assertEqual(comptage.variance_state, 'en_attente')
        self.assertTrue(comptage.variance_move_id)
        self.assertEqual(comptage.variance_move_id.state, 'posted')
        cash_account = session.journal_id.default_account_id
        waiting_account = session.company_id.microfinance_account_ecart_caisse_deficit_id
        lines = comptage.variance_move_id.line_ids
        cash_line = lines.filtered(lambda l: l.account_id == cash_account)
        waiting_line = lines.filtered(lambda l: l.account_id == waiting_account)
        self.assertAlmostEqual(cash_line.credit, 500.0, places=2)  # manque -> crédite la caisse
        self.assertAlmostEqual(waiting_line.debit, 500.0, places=2)

    def test_variance_move_posted_in_pending_state_on_surplus(self):
        session = self._open_session()
        variance = self._close(session, 1000.0, {self.d1000: 1, self.d500: 1})  # 1500 compté, théorique 1000 -> surplus 500
        variance.variance_comment = 'Surplus constaté.'
        variance.action_confirm_close()
        comptage = self.env['microfinance.caisse.comptage'].search([('session_id', '=', session.id)])
        self.assertEqual(comptage.variance_state, 'en_attente')
        cash_account = session.journal_id.default_account_id
        cash_line = comptage.variance_move_id.line_ids.filtered(lambda l: l.account_id == cash_account)
        self.assertAlmostEqual(cash_line.debit, 500.0, places=2)  # surplus -> débite la caisse
        excedent_account = session.company_id.microfinance_account_ecart_caisse_excedent_id
        excedent_line = comptage.variance_move_id.line_ids.filtered(lambda l: l.account_id == excedent_account)
        self.assertAlmostEqual(excedent_line.credit, 500.0, places=2)  # excédent -> compte excedent, pas deficit

    def test_variance_move_blocked_without_waiting_account_configured(self):
        self.env.company.microfinance_account_ecart_caisse_deficit_id = False
        session = self._open_session()
        variance = self._close(session, 1500.0, {self.d1000: 1})
        variance.variance_comment = 'Manque constaté.'
        with self.assertRaises(UserError):
            with self.env.cr.savepoint():
                variance.action_confirm_close()
        self.assertEqual(session.state, 'open')

    def test_reconcile_variance_requires_manager_group(self):
        session = self._open_session()
        variance = self._close(session, 1500.0, {self.d1000: 1})
        variance.variance_comment = 'Manque constaté.'
        variance.action_confirm_close()
        comptage = self.env['microfinance.caisse.comptage'].search([('session_id', '=', session.id)])
        cashier = self._pure_cashier()
        comptage.with_user(cashier).reconciliation_account_id = self.savings_fee_account.id
        with self.assertRaises(AccessError):
            comptage.with_user(cashier).action_reconcile_variance()

    def test_reconcile_variance_requires_destination_account(self):
        session = self._open_session()
        variance = self._close(session, 1500.0, {self.d1000: 1})
        variance.variance_comment = 'Manque constaté.'
        variance.action_confirm_close()
        comptage = self.env['microfinance.caisse.comptage'].search([('session_id', '=', session.id)])
        manager = self._manager_user()
        with self.assertRaises(UserError):
            comptage.with_user(manager).action_reconcile_variance()

    def test_reconcile_variance_success(self):
        session = self._open_session()
        variance = self._close(session, 1500.0, {self.d1000: 1})  # manque 500
        variance.variance_comment = 'Manque constaté.'
        variance.action_confirm_close()
        comptage = self.env['microfinance.caisse.comptage'].search([('session_id', '=', session.id)])
        manager = self._manager_user()
        comptage.reconciliation_account_id = self.savings_fee_account.id
        comptage.with_user(manager).action_reconcile_variance()
        self.assertEqual(comptage.variance_state, 'reconcilie')
        self.assertTrue(comptage.variance_clearing_move_id)
        self.assertEqual(comptage.variance_clearing_move_id.state, 'posted')
        waiting_account = session.company_id.microfinance_account_ecart_caisse_deficit_id
        waiting_lines = (comptage.variance_move_id | comptage.variance_clearing_move_id).line_ids.filtered(
            lambda l: l.account_id == waiting_account)
        self.assertAlmostEqual(sum(waiting_lines.mapped('debit')) - sum(waiting_lines.mapped('credit')), 0.0, places=2)

    def test_reconcile_variance_blocked_when_not_pending(self):
        session = self._open_session()
        variance = self._close(session, 1500.0, {self.d1000: 1, self.d500: 1})  # exact, aucun écart
        variance.action_confirm_close()
        comptage = self.env['microfinance.caisse.comptage'].search([('session_id', '=', session.id)])
        manager = self._manager_user()
        comptage.reconciliation_account_id = self.savings_fee_account.id
        with self.assertRaises(UserError):
            comptage.with_user(manager).action_reconcile_variance()

    def _manager_user(self):
        return self.env['res.users'].create({
            'name': 'Manager close wizard confirm (test)', 'login': 'manager_close_confirm_test',
            'email': 'manager_close_confirm_test@example.com',
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('microfinance_loan_management.group_microfinance_manager').id,
            ])],
        })

    def _pure_cashier(self):
        return self.env['res.users'].create({
            'name': 'Cashier close wizard confirm (test)', 'login': 'cashier_close_confirm_test',
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('microfinance_loan_management.group_microfinance_cashier').id,
            ])],
        })

    # --- Échec de action_close_session → rollback du comptage ---

    def test_close_session_failure_rolls_back_comptage(self):
        # Fiche de la veille (même journal) laissée ouverte → action_close_day() du jour lève
        # sur la séquentialité chronologique. Le comptage créé juste avant doit être annulé.
        yesterday = fields.Date.today() - timedelta(days=1)
        self.env['microfinance.caisse.fiche.journee'].create({
            'journal_id': self.disbursement_journal.id, 'date': yesterday,
        })
        session = self._open_session()
        variance = self._close(session, 1500.0, {self.d1000: 1, self.d500: 1})  # exact, aucun écart
        with self.assertRaises(UserError):
            with self.env.cr.savepoint():
                variance.action_confirm_close()
        self.assertEqual(session.state, 'open')
        self.assertEqual(session.fiche_journee_id.state, 'open')
        self.assertEqual(
            self.env['microfinance.caisse.comptage'].search_count([('session_id', '=', session.id)]), 0)

    # --- Verrou concurrentiel ---

    def test_second_close_after_confirm_blocked(self):
        session = self._open_session()
        variance = self._close(session, 1000.0, {self.d1000: 1})
        variance.action_confirm_close()
        self.assertEqual(session.state, 'closed')
        with self.assertRaises(UserError):
            session.action_close_session()
        self.assertEqual(
            self.env['microfinance.caisse.comptage'].search_count([('session_id', '=', session.id)]), 1)

    def test_confirming_a_stale_flow_after_close_is_blocked(self):
        # Deux comptages (temps 1) ouverts sur la même session ; le premier va jusqu'au bout et
        # clôture, le second doit échouer à la toute dernière étape sans créer de second comptage.
        session = self._open_session()
        self._register_deposit(session, 1000.0)
        wizard1_a = self._wizard1(session)
        wizard1_b = self._wizard1(session)
        self._set_quantities(wizard1_a, {self.d1000: 1})
        self._set_quantities(wizard1_b, {self.d1000: 1})
        variance_a = self._advance_to_variance(self._advance_to_recap(wizard1_a))
        variance_b = self._advance_to_variance(self._advance_to_recap(wizard1_b))
        variance_a.action_confirm_close()
        with self.assertRaises(UserError):
            with self.env.cr.savepoint():
                variance_b.action_confirm_close()
        self.assertEqual(
            self.env['microfinance.caisse.comptage'].search_count([('session_id', '=', session.id)]), 1)
