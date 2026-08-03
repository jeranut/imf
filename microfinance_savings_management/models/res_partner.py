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

    def _get_or_create_loan_application(self):
        # Cette logique reste dans microfinance_savings_management (qui dépend de
        # microfinance_loan_management), jamais l'inverse : on étend ici la méthode définie
        # dans le module crédit plutôt que d'y ajouter une dépendance vers l'épargne.
        application = super()._get_or_create_loan_application()
        if application:
            self._get_or_create_microfinance_savings_principal_account()
        return application

    def _get_or_create_microfinance_savings_principal_account(self):
        """Ouvre (ou réutilise) le compte d'épargne principal du client sur le produit
        d'épargne par défaut de son agence (res.company.microfinance_savings_default_product_id),
        à la création de son premier dossier d'instruction de crédit. Sans effet si l'agence n'a
        pas encore configuré de produit d'épargne par défaut (pas une erreur : simple absence de
        configuration) ni si un compte sur ce produit existe déjà pour ce client (idempotent,
        comme _get_or_create_loan_application)."""
        self.ensure_one()
        company = self.company_id or self.env.company
        product = company.microfinance_savings_default_product_id
        if not product:
            return False
        Account = self.env['microfinance.savings.account']
        existing = Account.search([
            ('partner_id', '=', self.id), ('product_id', '=', product.id),
        ], limit=1)
        if existing:
            return existing
        return Account.create({
            'partner_id': self.id,
            'product_id': product.id,
            'company_id': company.id,
        })

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
