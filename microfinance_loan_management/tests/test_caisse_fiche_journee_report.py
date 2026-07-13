# -*- coding: utf-8 -*-
from odoo import fields

from .common import MicrofinanceCommon


class TestCaisseFicheJourneeReport(MicrofinanceCommon):
    """Rapport imprimable QWeb (Lot 5, optionnel, du prompt « Menu Caisse »)."""

    def test_report_renders_with_movements(self):
        today = fields.Date.today()
        move = self.env['account.move'].create({
            'date': today,
            'journal_id': self.disbursement_journal.id,
            'line_ids': [
                (0, 0, {'account_id': self.bank_account.id, 'debit': 100.0, 'credit': 0.0}),
                (0, 0, {'account_id': self.loan_account.id, 'debit': 0.0, 'credit': 100.0}),
            ],
        })
        move.action_post()
        fiche = self.env['microfinance.caisse.fiche.journee'].create({
            'journal_id': self.disbursement_journal.id, 'date': today,
        })
        html, _report_type = self.env['ir.actions.report']._render_qweb_html(
            'microfinance_loan_management.report_microfinance_caisse_fiche_journee_document', fiche.ids
        )
        self.assertIn(self.disbursement_journal.name.encode(), html)
        self.assertIn(move.name.encode(), html)

    def test_report_renders_with_no_movements(self):
        today = fields.Date.today()
        fiche = self.env['microfinance.caisse.fiche.journee'].create({
            'journal_id': self.disbursement_journal.id, 'date': today,
        })
        html, _report_type = self.env['ir.actions.report']._render_qweb_html(
            'microfinance_loan_management.report_microfinance_caisse_fiche_journee_document', fiche.ids
        )
        self.assertIn(self.disbursement_journal.name.encode(), html)
