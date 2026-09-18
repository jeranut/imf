# -*- coding: utf-8 -*-
"""Assistant d'ouverture de session (microfinance.caisse.open.session.wizard) : point d'entrée
unique appelé directement par le bouton « Ouvrir une session » de l'écran guichet (cf.
AUDIT_session_zigzag). Trouve ou crée la session du jour pour l'agence courante et l'ouvre,
sans passer par le formulaire backend générique de microfinance.caisse.session."""
from odoo import fields
from odoo.exceptions import UserError

from .common import MicrofinanceCommon


class TestCaisseOpenSessionWizard(MicrofinanceCommon):

    def _wizard(self, **ctx):
        return self.env['microfinance.caisse.open.session.wizard'].with_context(**ctx).create({})

    def test_wizard_defaults_from_current_company_and_journal(self):
        wizard = self._wizard()
        self.assertEqual(wizard.company_id, self.env.company)
        self.assertEqual(wizard.journal_id, self.disbursement_journal)
        self.assertEqual(wizard.date, fields.Date.today())
        self.assertEqual(wizard.cashier_id, self.env.user)

    def test_confirm_creates_and_opens_session_when_none_exists(self):
        self.assertFalse(self.env['microfinance.caisse.session'].search([
            ('journal_id', '=', self.disbursement_journal.id), ('date', '=', fields.Date.today()),
        ]))
        wizard = self._wizard()
        wizard.action_confirm()
        session = self.env['microfinance.caisse.session'].search([
            ('journal_id', '=', self.disbursement_journal.id), ('date', '=', fields.Date.today()),
        ])
        self.assertEqual(len(session), 1)
        self.assertEqual(session.state, 'open')

    def test_confirm_reuses_existing_draft_session_without_duplicate(self):
        existing = self.env['microfinance.caisse.session'].create({
            'journal_id': self.disbursement_journal.id, 'date': fields.Date.today(),
        })
        wizard = self._wizard()
        wizard.action_confirm()
        self.assertEqual(existing.state, 'open')
        self.assertEqual(
            self.env['microfinance.caisse.session'].search_count([
                ('journal_id', '=', self.disbursement_journal.id), ('date', '=', fields.Date.today()),
            ]), 1,
        )

    def test_confirm_twice_same_day_reopens_same_session_not_a_second_one(self):
        wizard_a = self._wizard()
        wizard_a.action_confirm()
        wizard_b = self._wizard()
        wizard_b.action_confirm()
        self.assertEqual(
            self.env['microfinance.caisse.session'].search_count([
                ('journal_id', '=', self.disbursement_journal.id), ('date', '=', fields.Date.today()),
            ]), 1,
        )

    def test_confirm_blocked_without_company_cash_journal_configured(self):
        self.env.company.cash_journal_id = False
        wizard = self._wizard()
        self.assertFalse(wizard.journal_id)
        with self.assertRaises(UserError):
            wizard.action_confirm()

    def test_confirm_blocked_if_fiche_already_closed(self):
        fiche = self.env['microfinance.caisse.fiche.journee'].create({
            'journal_id': self.disbursement_journal.id, 'date': fields.Date.today(),
        })
        fiche.action_close_day()
        wizard = self._wizard()
        with self.assertRaises(UserError):
            wizard.action_confirm()
