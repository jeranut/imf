# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MicrofinanceLoanApplication(models.Model):
    _inherit = 'microfinance.loan.application'

    savings_amount = fields.Monetary(
        string='Épargne (montant)', compute='_compute_savings_amount', store=True, readonly=True,
        help="Somme des soldes des comptes épargne actifs du client — calculée automatiquement "
             "depuis microfinance_savings_management (remplace la saisie manuelle du module "
             "crédit seul).",
    )

    @api.depends('partner_id.microfinance_savings_account_ids.balance',
                 'partner_id.microfinance_savings_account_ids.state')
    def _compute_savings_amount(self):
        for application in self:
            accounts = application.partner_id.microfinance_savings_account_ids.filtered(
                lambda a: a.state == 'active')
            application.savings_amount = sum(accounts.mapped('balance'))
