# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class MicrofinanceLoanAccount(models.Model):
    _inherit = 'microfinance.loan.account'

    savings_holder_account_id = fields.Many2one(
        'microfinance.savings.holder.account', string='Compte épargne',
        compute='_compute_savings_holder_account_id')
    savings_account_count = fields.Integer(string="Produits d'épargne", compute='_compute_savings_holder_account_id')

    @api.depends('partner_id', 'company_id')
    def _compute_savings_holder_account_id(self):
        Holder = self.env['microfinance.savings.holder.account']
        for account in self:
            holder = Holder.search([
                ('partner_id', '=', account.partner_id.id), ('company_id', '=', account.company_id.id),
            ], limit=1) if account.partner_id else Holder
            account.savings_holder_account_id = holder
            account.savings_account_count = holder.product_count

    def action_view_savings_accounts(self):
        self.ensure_one()
        holder = self.savings_holder_account_id
        if not holder:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': _('Compte épargne'),
            'res_model': 'microfinance.savings.holder.account',
            'view_mode': 'form',
            'res_id': holder.id,
        }
