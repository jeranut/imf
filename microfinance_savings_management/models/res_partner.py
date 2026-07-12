# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    microfinance_savings_account_ids = fields.One2many(
        'microfinance.savings.account', 'partner_id', string='Comptes épargne')
    microfinance_savings_count = fields.Integer(compute='_compute_microfinance_savings_count')

    @api.depends('microfinance_savings_account_ids')
    def _compute_microfinance_savings_count(self):
        for partner in self:
            partner.microfinance_savings_count = len(partner.microfinance_savings_account_ids)

    def action_view_microfinance_savings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Épargne',
            'res_model': 'microfinance.savings.account',
            'view_mode': 'tree,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }
