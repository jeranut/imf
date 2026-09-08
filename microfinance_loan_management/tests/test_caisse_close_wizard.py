# -*- coding: utf-8 -*-
"""Sous-lot D — assistant de clôture de session avec comptage de billetage
(microfinance.caisse.close.session.wizard). Clôture exacte, clôture avec écart + motif,
blocage sans motif, échec de action_close_session → comptage non persisté, verrou
concurrentiel."""
import uuid
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError

from .common import MicrofinanceCommon


class TestCaisseCloseSessionWizard(MicrofinanceCommon):

    def setUp(self):
        super().setUp()
        # Neutralise les coupures existantes (données par défaut + éventuelles) pour un jeu de
        # dénominations maîtrisé : le wizard pré-remplit une ligne par coupure active de la
        # devise de la session.
        self.env['microfinance.caisse.denomination'].search([]).write({'active': False})
        currency = self.env.company.currency_id
        self.d1000 = self.env['microfinance.caisse.denomination'].create({
            'name': 'Wizard test 1000', 'value': 1000.0, 'currency_id': currency.id,
        })
        self.d500 = self.env['microfinance.caisse.denomination'].create({
            'name': 'Wizard test 500', 'value': 500.0, 'currency_id': currency.id,
        })
        self.d100 = self.env['microfinance.caisse.denomination'].create({
            'name': 'Wizard test 100', 'value': 100.0, 'currency_id': currency.id,
        })

    def _post_cash(self, amount, date=None):
        """Poste une écriture qui débite le compte de caisse (default_account_id des journaux
        de test) : alimente le solde théorique de la fiche du jour."""
        date = date or fields.Date.today()
        journal = self.env['account.journal'].create({
            'name': 'Journal alim. caisse test', 'code': uuid.uuid4().hex[:5].upper(),
            'type': 'general', 'company_id': self.env.company.id,
        })
        counterpart = self.env['account.account'].create({
            'name': 'Contrepartie alim. caisse test', 'code': uuid.uuid4().hex[:6].upper(),
            'account_type': 'equity', 'company_id': self.env.company.id,
        })
        move = self.env['account.move'].create({
            'date': date, 'journal_id': journal.id,
            'line_ids': [
                (0, 0, {'account_id': self.bank_account.id, 'debit': amount, 'credit': 0.0}),
                (0, 0, {'account_id': counterpart.id, 'debit': 0.0, 'credit': amount}),
            ],
        })
        move.action_post()
        return move

    def _open_session(self, date=None):
        session = self.env['microfinance.caisse.session'].create({
            'journal_id': self.disbursement_journal.id,
            'date': date or fields.Date.today(),
        })
        session.action_open_session()
        return session

    def _wizard(self, session):
        return self.env['microfinance.caisse.close.session.wizard'].with_context(
            default_session_id=session.id).create({})

    def _set_quantities(self, wizard, mapping):
        for line in wizard.line_ids:
            if line.denomination_id in mapping:
                line.quantity = mapping[line.denomination_id]

    # --- Pré-remplissage ---

    def test_wizard_prefills_lines_and_theoretical_total(self):
        self._post_cash(1500.0)
        session = self._open_session()
        wizard = self._wizard(session)
        self.assertEqual(wizard.theoretical_total, 1500.0)
        self.assertEqual(len(wizard.line_ids), 3)
        self.assertEqual(set(wizard.line_ids.mapped('denomination_id')),
                         {self.d1000, self.d500, self.d100})

    def test_archived_denomination_not_offered(self):
        self.d100.active = False
        session = self._open_session()
        wizard = self._wizard(session)
        self.assertEqual(len(wizard.line_ids), 2)

    def test_theoretical_total_refreshed_at_open(self):
        # Aucun mouvement au moment de l'ouverture de session, puis une écriture postée : le
        # wizard, ouvert après, doit voir le solde rafraîchi (default_get force le refresh).
        session = self._open_session()
        self.assertEqual(session.closing_balance, 0.0)
        self._post_cash(800.0)
        wizard = self._wizard(session)
        self.assertEqual(wizard.theoretical_total, 800.0)

    # --- Clôture exacte ---

    def test_close_exact_no_comment(self):
        self._post_cash(1500.0)
        session = self._open_session()
        wizard = self._wizard(session)
        self._set_quantities(wizard, {self.d1000: 1, self.d500: 1})
        self.assertEqual(wizard.counted_total, 1500.0)
        self.assertEqual(wizard.variance, 0.0)
        wizard.action_confirm()
        self.assertEqual(session.state, 'closed')
        self.assertEqual(session.fiche_journee_id.state, 'closed')
        comptage = self.env['microfinance.caisse.comptage'].search([('session_id', '=', session.id)])
        self.assertEqual(len(comptage), 1)
        self.assertEqual(comptage.counted_total, 1500.0)
        self.assertEqual(comptage.theoretical_total, 1500.0)
        self.assertEqual(comptage.variance, 0.0)
        self.assertEqual(comptage.line_ids.filtered(lambda l: l.denomination_id == self.d1000).quantity, 1)

    # --- Clôture avec écart ---

    def test_close_with_variance_and_comment_succeeds(self):
        self._post_cash(1500.0)
        session = self._open_session()
        wizard = self._wizard(session)
        self._set_quantities(wizard, {self.d1000: 1})  # 1000 compté, théorique 1500
        wizard.variance_comment = 'Écart de caisse constaté à la clôture.'
        wizard.action_confirm()
        self.assertEqual(session.state, 'closed')
        comptage = self.env['microfinance.caisse.comptage'].search([('session_id', '=', session.id)])
        self.assertEqual(comptage.variance, -500.0)
        self.assertTrue(comptage.variance_comment)

    def test_close_with_variance_without_comment_blocked(self):
        self._post_cash(1500.0)
        session = self._open_session()
        wizard = self._wizard(session)
        self._set_quantities(wizard, {self.d1000: 1})
        with self.assertRaises(ValidationError):
            with self.env.cr.savepoint():
                wizard.action_confirm()
        self.assertEqual(session.state, 'open')
        self.assertEqual(
            self.env['microfinance.caisse.comptage'].search_count([('session_id', '=', session.id)]), 0)

    # --- Échec de action_close_session → rollback du comptage ---

    def test_close_session_failure_rolls_back_comptage(self):
        # Fiche de la veille (même journal) laissée ouverte → action_close_day() du jour lève
        # sur la séquentialité chronologique. Le comptage créé juste avant doit être annulé.
        yesterday = fields.Date.today() - timedelta(days=1)
        self.env['microfinance.caisse.fiche.journee'].create({
            'journal_id': self.disbursement_journal.id, 'date': yesterday,
        })
        self._post_cash(1500.0)
        session = self._open_session()
        wizard = self._wizard(session)
        self._set_quantities(wizard, {self.d1000: 1, self.d500: 1})  # exact, aucun écart
        with self.assertRaises(UserError):
            with self.env.cr.savepoint():
                wizard.action_confirm()
        self.assertEqual(session.state, 'open')
        self.assertEqual(session.fiche_journee_id.state, 'open')
        self.assertEqual(
            self.env['microfinance.caisse.comptage'].search_count([('session_id', '=', session.id)]), 0)

    # --- Bouton d'ouverture ---

    def test_action_open_close_wizard_returns_action(self):
        session = self._open_session()
        action = session.action_open_close_wizard()
        self.assertEqual(action['res_model'], 'microfinance.caisse.close.session.wizard')
        self.assertEqual(action['context']['default_session_id'], session.id)

    def test_action_open_close_wizard_blocked_when_not_open(self):
        session = self.env['microfinance.caisse.session'].create({
            'journal_id': self.disbursement_journal.id,
        })
        with self.assertRaises(UserError):
            session.action_open_close_wizard()

    # --- Verrou concurrentiel ---

    def test_second_close_after_wizard_blocked(self):
        # Un vrai test multi-worker n'est pas réalisable en TransactionCase (un second curseur
        # ne voit pas les données non committées). On verrouille le filet garanti par le
        # FOR UPDATE + invalidate_recordset : une fois la session clôturée par le wizard, tout
        # nouvel appel à action_close_session échoue sur la garde d'état relue sous verrou.
        self._post_cash(1000.0)
        session = self._open_session()
        wizard = self._wizard(session)
        self._set_quantities(wizard, {self.d1000: 1})
        wizard.action_confirm()
        self.assertEqual(session.state, 'closed')
        with self.assertRaises(UserError):
            session.action_close_session()
        self.assertEqual(
            self.env['microfinance.caisse.comptage'].search_count([('session_id', '=', session.id)]), 1)

    def test_confirming_a_stale_wizard_after_close_is_blocked(self):
        # Deux wizards ouverts sur la même session ; le premier clôture, le second doit
        # échouer sans créer de second comptage.
        self._post_cash(1000.0)
        session = self._open_session()
        wizard_a = self._wizard(session)
        wizard_b = self._wizard(session)
        self._set_quantities(wizard_a, {self.d1000: 1})
        self._set_quantities(wizard_b, {self.d1000: 1})
        wizard_a.action_confirm()
        with self.assertRaises(UserError):
            with self.env.cr.savepoint():
                wizard_b.action_confirm()
        self.assertEqual(
            self.env['microfinance.caisse.comptage'].search_count([('session_id', '=', session.id)]), 1)
