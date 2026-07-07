# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError


class MicrofinanceLoanRescheduleWizard(models.TransientModel):
    _name = 'microfinance.loan.reschedule.wizard'
    _description = 'Assistant rééchelonnement crédit'

    loan_id = fields.Many2one('microfinance.loan', string='Crédit', required=True)
    currency_id = fields.Many2one(related='loan_id.currency_id', readonly=True)
    new_term = fields.Integer(string='Nouvelle durée restante (échéances)')
    new_first_due_date = fields.Date(string='Nouvelle date de 1ère échéance restante')
    reason = fields.Text(string='Motif du rééchelonnement')

    def action_apply(self):
        self.ensure_one()
        if not self.new_term and not self.new_first_due_date:
            raise UserError(_('Renseignez une nouvelle durée et/ou une nouvelle date de première échéance.'))
        if self.new_term and self.new_term <= 0:
            raise UserError(_('La nouvelle durée doit être un nombre d\'échéances positif.'))
        self.loan_id._reschedule_installments(self.new_term, self.new_first_due_date, reason=self.reason)
        return {'type': 'ir.actions.act_window_close'}
