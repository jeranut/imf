# -*- coding: utf-8 -*-
from datetime import timedelta

from psycopg2 import IntegrityError

from odoo import fields
from odoo.exceptions import UserError
from odoo.tools import mute_logger

from .common import MicrofinanceCommon


class TestCaisseSession(MicrofinanceCommon):
    """Session de caisse (Lot 1 du prompt « Session caisse + interface POS ») : 1 session = 1
    fiche journalière (même contrainte unique que microfinance.caisse.fiche.journee),
    action_open_session() crée ou réutilise la fiche du jour, action_close_session() délègue
    entièrement à fiche.action_close_day() sans redupliquer ses contrôles."""

    def test_unique_journal_date_constraint(self):
        today = fields.Date.today()
        self.env['microfinance.caisse.session'].create({
            'journal_id': self.disbursement_journal.id, 'date': today,
        })
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.env['microfinance.caisse.session'].create({
                    'journal_id': self.disbursement_journal.id, 'date': today,
                })

    def test_open_session_creates_fiche_and_links(self):
        today = fields.Date.today()
        session = self.env['microfinance.caisse.session'].create({
            'journal_id': self.disbursement_journal.id, 'date': today,
        })
        session.action_open_session()
        self.assertEqual(session.state, 'open')
        self.assertTrue(session.fiche_journee_id)
        self.assertEqual(session.fiche_journee_id.journal_id, self.disbursement_journal)
        self.assertEqual(session.fiche_journee_id.date, today)
        self.assertEqual(session.fiche_journee_id.state, 'open')

    def test_open_session_reuses_existing_open_fiche(self):
        today = fields.Date.today()
        fiche = self.env['microfinance.caisse.fiche.journee'].create({
            'journal_id': self.disbursement_journal.id, 'date': today,
        })
        session = self.env['microfinance.caisse.session'].create({
            'journal_id': self.disbursement_journal.id, 'date': today,
        })
        session.action_open_session()
        self.assertEqual(session.fiche_journee_id, fiche)
        self.assertEqual(
            self.env['microfinance.caisse.fiche.journee'].search_count([
                ('journal_id', '=', self.disbursement_journal.id), ('date', '=', today),
            ]), 1,
        )

    def test_open_session_blocked_if_fiche_already_closed(self):
        today = fields.Date.today()
        fiche = self.env['microfinance.caisse.fiche.journee'].create({
            'journal_id': self.disbursement_journal.id, 'date': today,
        })
        fiche.action_close_day()
        session = self.env['microfinance.caisse.session'].create({
            'journal_id': self.disbursement_journal.id, 'date': today,
        })
        with self.assertRaises(UserError):
            session.action_open_session()
        self.assertEqual(session.state, 'draft')

    def test_close_session_closes_linked_fiche(self):
        today = fields.Date.today()
        session = self.env['microfinance.caisse.session'].create({
            'journal_id': self.disbursement_journal.id, 'date': today,
        })
        session.action_open_session()
        session.action_close_session()
        self.assertEqual(session.state, 'closed')
        self.assertEqual(session.fiche_journee_id.state, 'closed')

    def test_close_session_requires_open_state(self):
        today = fields.Date.today()
        session = self.env['microfinance.caisse.session'].create({
            'journal_id': self.disbursement_journal.id, 'date': today,
        })
        with self.assertRaises(UserError):
            session.action_close_session()

    def test_close_session_fails_on_balance_variance_and_leaves_session_open(self):
        # Reprend le scénario de dérive de test_caisse_cloture.py
        # (test_close_day_detects_variance_against_real_balance), au niveau session : une fois
        # session1/fiche1 clôturées, on corrompt le solde de clôture figé de fiche1 (dérive
        # simulée, hors workflow normal) — session2 (jour suivant) en hérite comme solde
        # d'ouverture via le chaînage habituel, et sa clôture doit détecter l'écart contre le
        # solde comptable réel et échouer. Corrompre directement la fiche d'une session encore
        # 'open' ne fonctionne pas ici : _refresh_amounts() (appelé en tout début de
        # action_close_day()) l'écraserait avant toute comparaison.
        day1 = fields.Date.today() - timedelta(days=1)
        day2 = fields.Date.today()
        session1 = self.env['microfinance.caisse.session'].create({
            'journal_id': self.disbursement_journal.id, 'date': day1,
        })
        session1.action_open_session()
        session1.action_close_session()
        session1.fiche_journee_id.sudo().write({'closing_balance': 9999.0})

        session2 = self.env['microfinance.caisse.session'].create({
            'journal_id': self.disbursement_journal.id, 'date': day2,
        })
        session2.action_open_session()
        self.assertEqual(session2.opening_balance, 9999.0)
        with self.assertRaises(UserError):
            session2.action_close_session()
        self.assertEqual(session2.state, 'open')
        self.assertEqual(session2.fiche_journee_id.state, 'open')

    def test_reopening_closed_session_blocked(self):
        today = fields.Date.today()
        session = self.env['microfinance.caisse.session'].create({
            'journal_id': self.disbursement_journal.id, 'date': today,
        })
        session.action_open_session()
        session.action_close_session()
        with self.assertRaises(UserError):
            session.action_open_session()
