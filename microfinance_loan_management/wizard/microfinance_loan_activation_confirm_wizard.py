# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError


class MicrofinanceLoanActivationConfirmWizard(models.TransientModel):
    """Chantier décaissement provisoire (docs_dev/decaissement_provisoire/) : ouvert par
    microfinance.loan.action_activate() une fois les contrôles d'éligibilité passés et la date
    provisoire par défaut calculée (_compute_disbursement_date_planned_default). Seul point
    d'entrée qui fait réellement passer le crédit à 'active' (_do_activate(), appelée par
    action_confirm() ci-dessous) - patron repris de microfinance_loan_writeoff_wizard.py (un
    seul écran, un seul bouton de confirmation)."""

    _name = 'microfinance.loan.activation.confirm.wizard'
    _description = 'Assistant confirmation date de décaissement provisoire'

    loan_id = fields.Many2one('microfinance.loan', string='Crédit', required=True)
    disbursement_date_planned = fields.Date(string='Date de décaissement provisoire', required=True)

    def action_confirm(self):
        self.ensure_one()
        if not self.disbursement_date_planned:
            raise UserError(_('La date de décaissement provisoire est obligatoire.'))
        self.loan_id.write({
            'disbursement_date_planned': self.disbursement_date_planned,
            'disbursement_date_confirmed': True,
        })
        self.loan_id._do_activate()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'microfinance.loan',
            'res_id': self.loan_id.id,
            'view_mode': 'form',
        }
