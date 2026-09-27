# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MicrofinanceFondParentMixin(models.AbstractModel):
    """Garde « société mère uniquement » partagée par les modèles de fonds bailleurs.

    Sans société mère désignée dans les paramètres (microfinance.parent_company_id), aucune
    restriction n'est appliquée : comportement d'origine."""
    _name = 'microfinance.fond.parent.mixin'
    _description = 'Garde société mère (fonds bailleurs)'

    can_manage_funds = fields.Boolean(
        string='Peut configurer les fonds', compute='_compute_can_manage_funds',
        help="Vrai si aucune société mère n'est désignée ou si la société courante est la mère. "
             "Non stocké : sert uniquement à rendre les vues en lecture seule dans les agences.",
    )

    @api.depends_context('company')
    def _compute_can_manage_funds(self):
        parent = self.env['res.company']._get_microfinance_parent()
        allowed = not parent or self.env.company.id == parent.id
        for record in self:
            record.can_manage_funds = allowed

    def _check_parent_only(self):
        # Contournement technique (hooks, migrations) : jamais posé depuis une saisie utilisateur.
        if self.env.context.get('microfinance_skip_parent_check'):
            return
        self.env['res.company']._check_microfinance_parent_only()
