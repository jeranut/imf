# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class ResCompany(models.Model):
    _inherit = 'res.company'

    savings_dormancy_months = fields.Integer(
        string="Épargne : mois d'inactivité avant dormance", default=6,
    )
    savings_product_code_prefix = fields.Char(
        string='Préfixe code produit épargne', default='EP',
        help="Préfixe utilisé pour générer automatiquement le code des nouveaux produits "
             "d'épargne de cette société (ex. EP00001). Modifiable uniquement tant qu'aucun "
             "produit d'épargne n'a encore été créé pour cette société — dès le premier "
             "produit, le préfixe est verrouillé pour ne jamais mélanger deux styles de code "
             "dans l'historique.",
    )
    savings_product_code_locked = fields.Boolean(
        string='Préfixe épargne verrouillé', compute='_compute_savings_product_code_locked',
        help="Vrai dès qu'au moins un produit d'épargne existe pour cette société.",
    )
    savings_holder_account_prefix = fields.Char(
        string='Préfixe compte épargne', default='CE',
        help="Préfixe des comptes épargne de cette agence : <préfixe>/<numéro du compte crédit>, "
             "ex. CE/AD/000003. Verrouillé dès qu'un compte épargne existe dans l'agence, pour que "
             "tous les comptes gardent le même format.",
    )
    savings_holder_account_prefix_locked = fields.Boolean(
        string='Préfixe compte épargne verrouillé', compute='_compute_savings_holder_account_prefix_locked',
    )
    microfinance_savings_default_product_id = fields.Many2one(
        'microfinance.savings.product', string="Produit d'épargne par défaut",
        domain="[('company_id', '=', id), ('product_type', '=', 'voluntary')]",
        help="Non consommé automatiquement depuis le 2026-09-24 (correctif numérotation, "
             "docs_dev/epargne_auto/AUDIT_doublons_creation_client.md §13) : l'ouverture "
             "automatique d'un compte épargne réel sur ce produit à la création de la fiche "
             "client a été supprimée. Le seul compte épargne créé automatiquement est "
             "désormais le conteneur (AGENCE/I/N, même numéro que le compte crédit), qui "
             "n'utilise aucun produit. Ce champ reste configurable mais n'a plus d'effet "
             "avant qu'un usage manuel (choix par défaut à la création d'un compte épargne "
             "supplémentaire) ne lui soit redonné.",
    )

    def _compute_savings_product_code_locked(self):
        Product = self.env['microfinance.savings.product']
        for company in self:
            company.savings_product_code_locked = bool(Product.search_count([('company_id', '=', company.id)]))

    def _compute_savings_holder_account_prefix_locked(self):
        Holder = self.env['microfinance.savings.holder.account'].sudo()
        for company in self:
            company.savings_holder_account_prefix_locked = bool(
                company.id and Holder.search_count([('company_id', '=', company.id)]))

    def write(self, vals):
        if 'savings_holder_account_prefix' in vals:
            Holder = self.env['microfinance.savings.holder.account'].sudo()
            for company in self:
                if (vals['savings_holder_account_prefix'] != company.savings_holder_account_prefix
                        and Holder.search_count([('company_id', '=', company.id)])):
                    raise UserError(_(
                        "Le préfixe des comptes épargne de %s ne peut plus être modifié : des comptes "
                        "épargne existent déjà dans cette agence."
                    ) % company.display_name)
        if 'savings_product_code_prefix' in vals:
            Product = self.env['microfinance.savings.product']
            locked = self.filtered(lambda c: Product.search_count([('company_id', '=', c.id)]))
            if locked:
                raise UserError(_(
                    "Le préfixe de code produit épargne ne peut plus être modifié : des "
                    "produits d'épargne existent déjà pour %s (numérotation déjà initiée)."
                ) % ', '.join(locked.mapped('name')))
        return super().write(vals)
