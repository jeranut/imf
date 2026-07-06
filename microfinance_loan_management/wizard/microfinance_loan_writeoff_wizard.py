# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError


class MicrofinanceLoanWriteoffWizard(models.TransientModel):
    _name = 'microfinance.loan.writeoff.wizard'
    _description = 'Assistant radiation crédit'

    loan_id = fields.Many2one('microfinance.loan', required=True)
    currency_id = fields.Many2one(related='loan_id.currency_id', readonly=True)
    balance_total = fields.Monetary(related='loan_id.balance_total', readonly=True)
    write_off_date = fields.Date(default=fields.Date.context_today, required=True)
    reason = fields.Text(string='Motif', required=True)

    def action_confirm(self):
        self.ensure_one()
        if not self.reason or not self.reason.strip():
            raise UserError(_('Le motif de radiation est obligatoire.'))
        move = self.loan_id.action_confirm_write_off(self.reason, self.write_off_date)
        return {'type': 'ir.actions.act_window', 'res_model': 'account.move', 'res_id': move.id, 'view_mode': 'form'}
