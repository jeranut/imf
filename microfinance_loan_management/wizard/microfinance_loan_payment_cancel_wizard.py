# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError


class MicrofinanceLoanPaymentCancelWizard(models.TransientModel):
    _name = 'microfinance.loan.payment.cancel.wizard'
    _description = 'Assistant annulation remboursement comptabilisé'

    payment_id = fields.Many2one('microfinance.loan.payment', required=True)
    reason = fields.Text(string='Motif', required=True)

    def action_confirm(self):
        self.ensure_one()
        if not self.reason or not self.reason.strip():
            raise UserError(_('Le motif d\'annulation est obligatoire.'))
        self.payment_id.action_cancel(reason=self.reason)
        return {'type': 'ir.actions.act_window_close'}
