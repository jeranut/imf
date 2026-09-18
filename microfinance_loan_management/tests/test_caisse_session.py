# -*- coding: utf-8 -*-
from datetime import timedelta

from psycopg2 import IntegrityError

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
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


class TestCaisseSessionCashJournalRestriction(MicrofinanceCommon):
    """Restriction du journal sélectionnable à l'ouverture d'une session de caisse guichet à
    company_id.cash_journal_id (nouveau champ res.company) : le domain de vue ne fait que guider
    l'UI, c'est la contrainte serveur ci-dessous qui bloque réellement un journal différent, y
    compris par RPC/API. self.disbursement_journal est le cash_journal_id de la société de test
    (cf. tests/common.py) ; self.payment_journal (type cash, même société) sert de journal
    « faux » pour déclencher la contrainte."""

    def test_create_session_with_wrong_journal_raises(self):
        with self.assertRaises(ValidationError):
            self.env['microfinance.caisse.session'].create({
                'journal_id': self.payment_journal.id, 'date': fields.Date.today(),
            })

    def test_write_session_to_wrong_journal_raises(self):
        session = self.env['microfinance.caisse.session'].create({
            'journal_id': self.disbursement_journal.id, 'date': fields.Date.today(),
        })
        with self.assertRaises(ValidationError):
            session.journal_id = self.payment_journal.id

    def test_create_session_with_correct_journal_succeeds(self):
        session = self.env['microfinance.caisse.session'].create({
            'journal_id': self.disbursement_journal.id, 'date': fields.Date.today(),
        })
        self.assertEqual(session.journal_id, self.disbursement_journal)

    def test_default_journal_id_matches_company_cash_journal(self):
        session = self.env['microfinance.caisse.session'].create({'date': fields.Date.today()})
        self.assertEqual(session.journal_id, self.env.company.cash_journal_id)
        self.assertEqual(session.journal_id, self.disbursement_journal)

    def test_onchange_company_id_reassigns_journal(self):
        company_b = self.env['res.company'].create({
            'name': 'Agence B restriction caisse (test)', 'agency_code': 'CJ1',
        })
        journal_b = self.env['account.journal'].create({
            'name': 'Caisse agence B restriction (test)', 'code': 'CJB1', 'type': 'cash',
            'company_id': company_b.id,
        })
        company_b.cash_journal_id = journal_b.id

        session = self.env['microfinance.caisse.session'].new({
            'journal_id': self.disbursement_journal.id,
        })
        session.company_id = company_b
        session._onchange_company_id_journal()
        self.assertEqual(session.journal_id, journal_b)


class TestCaisseSessionReopen(MicrofinanceCommon):
    """action_reopen_session() : même garde-fou que fiche_journee.action_reopen_day() (manager
    uniquement, motif obligatoire), et resynchronise la fiche journalière liée si elle est
    encore clôturée pour ne pas laisser action_open_session() bloquée juste après (cf.
    AUDIT_session_zigzag §5 point 7)."""

    def _manager_user(self):
        # email requis : action_reopen_session() déclenche message_post (session ET fiche),
        # qui échoue avec UserError si l'auteur n'a pas d'adresse configurée.
        return self.env['res.users'].create({
            'name': 'Manager reopen session (test)', 'login': 'manager_reopen_session_test',
            'email': 'manager_reopen_session_test@example.com',
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('microfinance_loan_management.group_microfinance_manager').id,
            ])],
        })

    def _cashier_user(self):
        return self.env['res.users'].create({
            'name': 'Cashier reopen session (test)', 'login': 'cashier_reopen_session_test',
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('microfinance_loan_management.group_microfinance_cashier').id,
            ])],
        })

    def _closed_session(self):
        session = self.env['microfinance.caisse.session'].create({
            'journal_id': self.disbursement_journal.id, 'date': fields.Date.today(),
        })
        session.action_open_session()
        session.action_close_session()
        return session

    def test_reopen_requires_manager_group(self):
        session = self._closed_session()
        cashier = self._cashier_user()
        session.with_user(cashier).reopen_reason = 'Correction nécessaire'
        with self.assertRaises(AccessError):
            session.with_user(cashier).action_reopen_session()
        self.assertEqual(session.state, 'closed')

    def test_reopen_requires_reason(self):
        session = self._closed_session()
        manager = self._manager_user()
        with self.assertRaises(UserError):
            session.with_user(manager).action_reopen_session()
        self.assertEqual(session.state, 'closed')

    def test_reopen_reopens_session_and_linked_fiche(self):
        session = self._closed_session()
        self.assertEqual(session.fiche_journee_id.state, 'closed')
        manager = self._manager_user()
        session.reopen_reason = 'Erreur de comptage détectée après clôture'
        session.with_user(manager).action_reopen_session()
        self.assertEqual(session.state, 'open')
        self.assertEqual(session.fiche_journee_id.state, 'open')
        self.assertFalse(session.reopen_reason)

    def test_reopen_noop_when_not_closed(self):
        today = fields.Date.today()
        session = self.env['microfinance.caisse.session'].create({
            'journal_id': self.disbursement_journal.id, 'date': today,
        })
        session.action_open_session()
        manager = self._manager_user()
        session.with_user(manager).action_reopen_session()
        self.assertEqual(session.state, 'open')

    def test_open_session_after_reopen_reuses_same_session(self):
        session = self._closed_session()
        manager = self._manager_user()
        session.reopen_reason = 'Correction'
        session.with_user(manager).action_reopen_session()
        wizard = self.env['microfinance.caisse.open.session.wizard'].with_user(manager).create({})
        wizard.action_confirm()
        self.assertEqual(
            self.env['microfinance.caisse.session'].search_count([
                ('journal_id', '=', self.disbursement_journal.id), ('date', '=', fields.Date.today()),
            ]), 1,
        )
        self.assertEqual(session.state, 'open')
