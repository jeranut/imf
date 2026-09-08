# -*- coding: utf-8 -*-
"""Sous-lot D du découplage activation / décaissement (docs_dev/guichet_caisse/
AUDIT_decaissement.md) : remboursement, rééchelonnement et radiation refusés sur un crédit
'active' pas encore décaissé ; le cron arriérés/pénalités ignore ces crédits."""
from odoo import fields
from odoo.exceptions import UserError

from .common import MicrofinanceCommon


class TestDecoupleGuards(MicrofinanceCommon):

    def setUp(self):
        super().setUp()
        # Neutralise les fonds bailleurs actifs (cf. test_guichet_backend_lists) : sinon
        # action_activate() lève « Un fonds de crédit rotatif actif existe ».
        self.env['microfinance.fond.credit'].sudo().search([('active', '=', True)]).write({'active': False})

    def test_repayment_blocked_before_disbursement(self):
        loan = self._activate_loan_without_disbursement(loan_amount=900.0, term=3)
        payment = self.env['microfinance.loan.payment'].create({
            'loan_id': loan.id,
            'amount': 100.0,
            'payment_date': fields.Date.context_today(loan),
            'journal_id': self.payment_journal.id,
        })
        with self.assertRaises(UserError):
            payment.action_post()

        # Après décaissement, le même remboursement passe.
        loan.action_process_disbursement()
        payment.action_post()
        self.assertEqual(payment.state, 'posted')

    def test_reschedule_blocked_before_disbursement(self):
        loan = self._activate_loan_without_disbursement(loan_amount=900.0, term=3)
        with self.assertRaises(UserError):
            loan.action_reschedule()

    def test_write_off_blocked_before_disbursement(self):
        loan = self._activate_loan_without_disbursement(loan_amount=900.0, term=3)
        with self.assertRaises(UserError):
            loan.action_write_off()
        with self.assertRaises(UserError):
            loan.action_confirm_write_off('motif test', fields.Date.context_today(loan))

    def test_cron_penalties_ignores_active_not_disbursed(self):
        loan = self._activate_loan_without_disbursement(loan_amount=1000.0, term=4)
        today = fields.Date.context_today(loan)
        for inst in loan.installment_ids:
            inst.due_date = fields.Date.subtract(today, days=20)

        self.env['microfinance.loan'].cron_update_overdue_and_penalties()

        loan.invalidate_recordset()
        self.assertFalse(any(loan.installment_ids.mapped('penalty_applied')),
                         "Aucune pénalité sur un crédit non décaissé.")
        self.assertFalse(any(loan.installment_ids.mapped('arrears_onset_date')),
                         "Aucun épisode d'arriéré ouvert sur un crédit non décaissé.")

        # Une fois décaissé (échéancier recalé), le cron traite bien le crédit.
        loan.action_process_disbursement()
        for inst in loan.installment_ids:
            inst.due_date = fields.Date.subtract(today, days=20)
        self.env['microfinance.loan'].cron_update_overdue_and_penalties()
        loan.invalidate_recordset()
        self.assertTrue(any(loan.installment_ids.mapped('arrears_onset_date')),
                        "Après décaissement, les échéances échues ouvrent un épisode d'arriéré.")
