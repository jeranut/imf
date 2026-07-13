# -*- coding: utf-8 -*-
import uuid
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError

from .common import MicrofinanceCommon


class TestCaisseCloture(MicrofinanceCommon):
    """Clôture du Jour (Lot 2 du prompt « Menu Caisse ») : blocage dur des nouvelles écritures
    sur un (journal, jour) clôturé, réouverture réservée manager avec motif tracé,
    séquentialité stricte façon LPF (jour N+1 ne peut être clôturé avant le jour N, s'il existe
    une fiche pour le jour N)."""

    def _post_move(self, account, debit, credit, date, journal=None):
        journal = journal or self.env['account.journal'].create({
            'name': 'Journal mouvement test', 'code': uuid.uuid4().hex[:5].upper(),
            'type': 'general', 'company_id': self.env.company.id,
        })
        counterpart = self.env['account.account'].create({
            'name': 'Contrepartie mouvement test',
            'code': uuid.uuid4().hex[:6].upper(),
            'account_type': 'equity', 'company_id': self.env.company.id,
        })
        move = self.env['account.move'].create({
            'date': date,
            'journal_id': journal.id,
            'line_ids': [
                (0, 0, {'account_id': account.id, 'debit': debit, 'credit': credit}),
                (0, 0, {'account_id': counterpart.id, 'debit': credit, 'credit': debit}),
            ],
        })
        return move

    def _make_manager(self):
        self.env.user.write({
            'groups_id': [(4, self.env.ref('microfinance_loan_management.group_microfinance_manager').id)],
        })

    def test_close_day_succeeds_with_no_previous_fiche(self):
        today = fields.Date.today()
        fiche = self.env['microfinance.caisse.fiche.journee'].create({
            'journal_id': self.disbursement_journal.id, 'date': today,
        })
        fiche.action_close_day()
        self.assertEqual(fiche.state, 'closed')

    def test_close_day_blocked_if_previous_day_still_open(self):
        day1 = fields.Date.today() - timedelta(days=1)
        day2 = fields.Date.today()
        self.env['microfinance.caisse.fiche.journee'].create({
            'journal_id': self.disbursement_journal.id, 'date': day1,
        })  # reste 'open'
        fiche2 = self.env['microfinance.caisse.fiche.journee'].create({
            'journal_id': self.disbursement_journal.id, 'date': day2,
        })
        with self.assertRaises(UserError):
            fiche2.action_close_day()
        self.assertEqual(fiche2.state, 'open')

    def test_close_day_allowed_once_previous_day_closed(self):
        day1 = fields.Date.today() - timedelta(days=1)
        day2 = fields.Date.today()
        fiche1 = self.env['microfinance.caisse.fiche.journee'].create({
            'journal_id': self.disbursement_journal.id, 'date': day1,
        })
        fiche1.action_close_day()
        fiche2 = self.env['microfinance.caisse.fiche.journee'].create({
            'journal_id': self.disbursement_journal.id, 'date': day2,
        })
        fiche2.action_close_day()
        self.assertEqual(fiche2.state, 'closed')

    def test_close_day_allowed_when_no_fiche_at_all_for_previous_day(self):
        # Aucune fiche créée pour la veille (jamais ouverte) : absence de fiche n'est pas traitée
        # comme "non clôturée", rien ne bloque.
        today = fields.Date.today()
        fiche = self.env['microfinance.caisse.fiche.journee'].create({
            'journal_id': self.disbursement_journal.id, 'date': today,
        })
        fiche.action_close_day()
        self.assertEqual(fiche.state, 'closed')

    def test_close_day_detects_variance_against_real_balance(self):
        # Simule une dérive : le solde de clôture "figé" de la fiche précédente ne correspond
        # plus au solde comptable réel (ex. correction manuelle directe, hors workflow normal).
        # La clôture du jour suivant doit détecter l'écart et refuser.
        day1 = fields.Date.today() - timedelta(days=1)
        day2 = fields.Date.today()
        self._post_move(self.bank_account, 300.0, 0.0, day1).action_post()
        fiche1 = self.env['microfinance.caisse.fiche.journee'].create({
            'journal_id': self.disbursement_journal.id, 'date': day1,
        })
        fiche1.action_close_day()
        fiche1.sudo().write({'closing_balance': 9999.0})  # dérive simulée
        fiche2 = self.env['microfinance.caisse.fiche.journee'].create({
            'journal_id': self.disbursement_journal.id, 'date': day2,
        })
        self.assertEqual(fiche2.opening_balance, 9999.0)  # chaînage reprend la valeur dérivée
        with self.assertRaises(UserError):
            fiche2.action_close_day()

    def test_reopen_requires_manager_group(self):
        today = fields.Date.today()
        fiche = self.env['microfinance.caisse.fiche.journee'].create({
            'journal_id': self.disbursement_journal.id, 'date': today,
        })
        fiche.action_close_day()
        non_manager = self.env['res.users'].create({
            'name': 'Caissier non manager (test)', 'login': 'caissier_non_manager_test',
            'groups_id': [(6, 0, [self.env.ref('microfinance_loan_management.group_microfinance_cashier').id])],
        })
        with self.assertRaises(AccessError):
            fiche.with_user(non_manager).action_reopen_day()
        self.assertEqual(fiche.state, 'closed')

    def test_reopen_requires_reason(self):
        self._make_manager()
        today = fields.Date.today()
        fiche = self.env['microfinance.caisse.fiche.journee'].create({
            'journal_id': self.disbursement_journal.id, 'date': today,
        })
        fiche.action_close_day()
        with self.assertRaises(UserError):
            fiche.action_reopen_day()
        self.assertEqual(fiche.state, 'closed')

    def test_reopen_succeeds_with_reason_and_clears_it(self):
        self._make_manager()
        today = fields.Date.today()
        fiche = self.env['microfinance.caisse.fiche.journee'].create({
            'journal_id': self.disbursement_journal.id, 'date': today,
        })
        fiche.action_close_day()
        fiche.reopen_reason = 'Erreur de saisie constatée après clôture'
        fiche.action_reopen_day()
        self.assertEqual(fiche.state, 'open')
        self.assertFalse(fiche.reopen_reason)

    def test_post_move_blocked_on_closed_day(self):
        today = fields.Date.today()
        fiche = self.env['microfinance.caisse.fiche.journee'].create({
            'journal_id': self.disbursement_journal.id, 'date': today,
        })
        fiche.action_close_day()
        move = self._post_move(self.bank_account, 100.0, 0.0, today, journal=self.disbursement_journal)
        with self.assertRaises(UserError):
            move.action_post()

    def test_post_move_allowed_after_reopen(self):
        self._make_manager()
        today = fields.Date.today()
        fiche = self.env['microfinance.caisse.fiche.journee'].create({
            'journal_id': self.disbursement_journal.id, 'date': today,
        })
        fiche.action_close_day()
        move = self._post_move(self.bank_account, 100.0, 0.0, today, journal=self.disbursement_journal)
        fiche.reopen_reason = 'Correction nécessaire'
        fiche.action_reopen_day()
        move.action_post()
        self.assertEqual(move.state, 'posted')

    def test_post_move_unaffected_on_other_journal(self):
        # Le blocage est scopé au journal de la fiche clôturée : un mouvement sur un AUTRE
        # journal (même date) n'est pas concerné.
        today = fields.Date.today()
        fiche = self.env['microfinance.caisse.fiche.journee'].create({
            'journal_id': self.disbursement_journal.id, 'date': today,
        })
        fiche.action_close_day()
        move = self.env['account.move'].create({
            'date': today,
            'journal_id': self.payment_journal.id,
            'line_ids': [
                (0, 0, {'account_id': self.bank_account.id, 'debit': 100.0, 'credit': 0.0}),
                (0, 0, {'account_id': self.loan_account.id, 'debit': 0.0, 'credit': 100.0}),
            ],
        })
        move.action_post()
        self.assertEqual(move.state, 'posted')
