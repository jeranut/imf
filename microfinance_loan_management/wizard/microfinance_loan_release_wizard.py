# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class MicrofinanceLoanReleaseWizard(models.TransientModel):
    """Confirmation de « Envoyer à la caisse » quand la date de décaissement provisoire n'est pas
    confirmée et atteinte : la date demandée est affichée, le motif de l'anticipation est
    obligatoire et tracé dans le chatter par microfinance.loan._release_to_cashier()."""

    _name = 'microfinance.loan.release.wizard'
    _description = "Assistant envoi anticipé d'un crédit à la caisse"

    loan_id = fields.Many2one('microfinance.loan', string='Crédit', required=True, readonly=True)
    disbursement_date_planned = fields.Date(related='loan_id.disbursement_date_planned', string='Date de décaissement provisoire')
    disbursement_date_confirmed = fields.Boolean(related='loan_id.disbursement_date_confirmed', string='Date confirmée')
    reason = fields.Text(string="Motif de l'anticipation")

    def action_confirm(self):
        self.ensure_one()
        if not (self.reason or '').strip():
            raise UserError(_("Le motif de l'anticipation est obligatoire."))
        self.loan_id.action_release_to_cashier_confirmed(self.reason)
        return {'type': 'ir.actions.act_window_close'}
