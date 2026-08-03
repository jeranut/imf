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
    microfinance_savings_default_product_id = fields.Many2one(
        'microfinance.savings.product', string="Produit d'épargne par défaut",
        domain="[('company_id', '=', id), ('product_type', '=', 'voluntary')]",
        help="Produit utilisé pour ouvrir automatiquement le compte d'épargne principal d'un "
             "client à la création de son premier dossier d'instruction de crédit (cf. "
             "res.partner._get_or_create_microfinance_savings_principal_account(), module "
             "Gestion de l'épargne). Symétrique à microfinance_fond_credit_default_id (crédit). "
             "Si laissé vide, aucun compte n'est ouvert automatiquement — l'agence n'a "
             "simplement pas encore configuré de produit d'épargne par défaut.",
    )

    def _compute_savings_product_code_locked(self):
        Product = self.env['microfinance.savings.product']
        for company in self:
            company.savings_product_code_locked = bool(Product.search_count([('company_id', '=', company.id)]))

    def write(self, vals):
        if 'savings_product_code_prefix' in vals:
            Product = self.env['microfinance.savings.product']
            locked = self.filtered(lambda c: Product.search_count([('company_id', '=', c.id)]))
            if locked:
                raise UserError(_(
                    "Le préfixe de code produit épargne ne peut plus être modifié : des "
                    "produits d'épargne existent déjà pour %s (numérotation déjà initiée)."
                ) % ', '.join(locked.mapped('name')))
        return super().write(vals)
