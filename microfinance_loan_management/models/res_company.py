# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class ResCompany(models.Model):
    _inherit = 'res.company'

    loan_product_code_prefix = fields.Char(
        string='Préfixe code produit crédit', default='CR',
        help="Préfixe utilisé pour générer automatiquement le code des nouveaux produits de "
             "crédit de cette société (ex. CR00001). Modifiable uniquement tant qu'aucun "
             "produit de crédit n'a encore été créé pour cette société — dès le premier "
             "produit, le préfixe est verrouillé pour ne jamais mélanger deux styles de code "
             "dans l'historique.",
    )
    loan_product_code_locked = fields.Boolean(
        string='Préfixe crédit verrouillé', compute='_compute_loan_product_code_locked',
        help="Vrai dès qu'au moins un produit de crédit existe pour cette société.",
    )

    def _compute_loan_product_code_locked(self):
        Product = self.env['microfinance.loan.product']
        for company in self:
            company.loan_product_code_locked = bool(Product.search_count([('company_id', '=', company.id)]))

    def _get_microfinance_dashboard_subtitle(self):
        """Nom de la société + adresse (rue, complément, ville) pour le sous-titre de l'en-tête
        du tableau de bord microfinance. Omet proprement les segments d'adresse vides plutôt que
        de laisser des virgules ou un tiret orphelins."""
        self.ensure_one()
        address_parts = [part for part in (self.street, self.street2, self.city) if part]
        if not address_parts:
            return self.name
        return '%s — %s' % (self.name, ', '.join(address_parts))

    def write(self, vals):
        if 'loan_product_code_prefix' in vals:
            Product = self.env['microfinance.loan.product']
            locked = self.filtered(lambda c: Product.search_count([('company_id', '=', c.id)]))
            if locked:
                raise UserError(_(
                    "Le préfixe de code produit crédit ne peut plus être modifié : des produits "
                    "de crédit existent déjà pour %s (numérotation déjà initiée)."
                ) % ', '.join(locked.mapped('name')))
        return super().write(vals)
