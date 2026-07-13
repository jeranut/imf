# -*- coding: utf-8 -*-
import uuid
from datetime import timedelta

from odoo import fields

from .common import MicrofinanceCommon


class TestCaisseFicheJournee(MicrofinanceCommon):
    """Modèle de la fiche journalière de caisse (Lot 1 du prompt « Menu Caisse »). Les totaux
    sont un instantané figé (champs stockés, calculés depuis account.move.line sans dupliquer de
    montant, mais écrits une seule fois par _refresh_amounts() — pas de champ `compute=` réactif)
    — voir action_refresh()/_refresh_amounts()."""

    def _post_move(self, account, debit, credit, date):
        journal = self.env['account.journal'].create({
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
        move.action_post()
        return move

    def test_opening_balance_falls_back_to_account_balance_before_date(self):
        day1 = fields.Date.today() - timedelta(days=2)
        day2 = fields.Date.today() - timedelta(days=1)
        self._post_move(self.bank_account, 500.0, 0.0, day1)
        fiche = self.env['microfinance.caisse.fiche.journee'].create({
            'journal_id': self.disbursement_journal.id, 'date': day2,
        })
        self.assertEqual(fiche.opening_balance, 500.0)

    def test_totals_and_closing_balance(self):
        today = fields.Date.today()
        self._post_move(self.bank_account, 200.0, 0.0, today)
        self._post_move(self.bank_account, 0.0, 50.0, today)
        fiche = self.env['microfinance.caisse.fiche.journee'].create({
            'journal_id': self.disbursement_journal.id, 'date': today,
        })
        self.assertEqual(fiche.total_debit, 200.0)
        self.assertEqual(fiche.total_credit, 50.0)
        self.assertEqual(fiche.closing_balance, fiche.opening_balance + 150.0)

    def test_opening_balance_chains_from_previous_closed_fiche(self):
        day1 = fields.Date.today() - timedelta(days=1)
        day2 = fields.Date.today()
        self._post_move(self.bank_account, 300.0, 0.0, day1)
        fiche1 = self.env['microfinance.caisse.fiche.journee'].create({
            'journal_id': self.disbursement_journal.id, 'date': day1,
        })
        self.assertEqual(fiche1.closing_balance, 300.0)
        # action_close_day() n'est pas encore codée (Lot 2, séparé) : on simule directement
        # l'état pour tester le chaînage lui-même, indépendamment du workflow de clôture.
        fiche1.state = 'closed'
        self._post_move(self.bank_account, 100.0, 0.0, day2)
        fiche2 = self.env['microfinance.caisse.fiche.journee'].create({
            'journal_id': self.disbursement_journal.id, 'date': day2,
        })
        self.assertEqual(fiche2.opening_balance, 300.0)
        self.assertEqual(fiche2.closing_balance, 400.0)

    def test_open_previous_fiche_not_used_as_opening_reference(self):
        # Une fiche non clôturée n'est jamais utilisée comme référence de chaînage : le solde
        # d'ouverture du jour suivant retombe sur le solde comptable réel avant cette date, qui
        # reflète TOUJOURS l'intégralité des mouvements réels (même postérieurs à la création de
        # la fiche non close) — pas une valeur figée arbitrairement par une fiche encore 'open'.
        day1 = fields.Date.today() - timedelta(days=1)
        day2 = fields.Date.today()
        self._post_move(self.bank_account, 300.0, 0.0, day1)
        open_fiche = self.env['microfinance.caisse.fiche.journee'].create({
            'journal_id': self.disbursement_journal.id, 'date': day1,
        })
        self.assertEqual(open_fiche.state, 'open')
        self._post_move(self.bank_account, 150.0, 0.0, day1)
        fiche2 = self.env['microfinance.caisse.fiche.journee'].create({
            'journal_id': self.disbursement_journal.id, 'date': day2,
        })
        self.assertEqual(fiche2.opening_balance, 450.0)

    def test_unique_constraint_journal_date(self):
        today = fields.Date.today()
        self.env['microfinance.caisse.fiche.journee'].create({
            'journal_id': self.disbursement_journal.id, 'date': today,
        })
        with self.assertRaises(Exception):
            self.env['microfinance.caisse.fiche.journee'].create({
                'journal_id': self.disbursement_journal.id, 'date': today,
            })

    def test_no_moves_gives_zero_totals_and_same_opening_closing(self):
        today = fields.Date.today()
        fiche = self.env['microfinance.caisse.fiche.journee'].create({
            'journal_id': self.disbursement_journal.id, 'date': today,
        })
        self.assertEqual(fiche.total_debit, 0.0)
        self.assertEqual(fiche.total_credit, 0.0)
        self.assertEqual(fiche.closing_balance, fiche.opening_balance)

    def test_snapshot_frozen_until_explicit_refresh(self):
        # Instantané figé : un mouvement posté APRÈS la création de la fiche ne modifie pas ses
        # montants tant qu'action_refresh() n'est pas explicitement appelée (pas de champ
        # `compute=` réactif recalculant à la volée).
        today = fields.Date.today()
        fiche = self.env['microfinance.caisse.fiche.journee'].create({
            'journal_id': self.disbursement_journal.id, 'date': today,
        })
        self.assertEqual(fiche.total_debit, 0.0)
        self._post_move(self.bank_account, 200.0, 0.0, today)
        self.assertEqual(fiche.total_debit, 0.0, "L'instantané ne doit pas bouger sans rafraîchissement explicite")
        fiche.action_refresh()
        self.assertEqual(fiche.total_debit, 200.0)

    def test_refresh_blocked_once_closed(self):
        today = fields.Date.today()
        fiche = self.env['microfinance.caisse.fiche.journee'].create({
            'journal_id': self.disbursement_journal.id, 'date': today,
        })
        fiche.state = 'closed'  # action_close_day() pas encore codée (Lot 2) : état simulé
        self._post_move(self.bank_account, 200.0, 0.0, today)
        with self.assertRaises(Exception):
            fiche.action_refresh()
        self.assertEqual(fiche.total_debit, 0.0, "Le solde figé à la clôture ne doit pas bouger")
