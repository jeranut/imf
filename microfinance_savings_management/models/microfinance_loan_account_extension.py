# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class MicrofinanceLoanAccount(models.Model):
    _inherit = 'microfinance.loan.account'

    savings_account_count = fields.Integer(compute='_compute_savings_account_count')

    @api.depends('partner_id')
    def _compute_savings_account_count(self):
        for account in self:
            account.savings_account_count = self.env['microfinance.savings.account'].search_count(
                [('partner_id', '=', account.partner_id.id)]
            ) if account.partner_id else 0

    def action_view_savings_accounts(self):
        self.ensure_one()
        accounts = self.env['microfinance.savings.account'].search([('partner_id', '=', self.partner_id.id)])
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Comptes épargne'),
            'res_model': 'microfinance.savings.account',
        }
        if len(accounts) == 1:
            action.update({'view_mode': 'form', 'res_id': accounts.id})
        else:
            action.update({'view_mode': 'tree,form', 'domain': [('id', 'in', accounts.ids)]})
        return action
