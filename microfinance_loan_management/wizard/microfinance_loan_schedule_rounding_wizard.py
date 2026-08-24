# -*- coding: utf-8 -*-
from odoo import fields, models


class MicrofinanceLoanScheduleRoundingWizard(models.TransientModel):
    _name = 'microfinance.loan.schedule.rounding.wizard'
    _description = "Choix du mode de répartition du reliquat d'arrondi de l'échéancier"

    loan_id = fields.Many2one('microfinance.loan', string='Crédit', required=True, ondelete='cascade')
    rounding_mode = fields.Selection([
        ('last_installment', 'Absorption sur la dernière tranche'),
        ('distributed', 'Répartition sur les dernières tranches'),
    ], string="Mode de répartition du reliquat d'arrondi", required=True, default='last_installment')

    def action_confirm(self):
        self.ensure_one()
        self.loan_id.action_generate_schedule(rounding_mode=self.rounding_mode)
        return {'type': 'ir.actions.act_window_close'}
