# -*- coding: utf-8 -*-
"""Menus des fonds d'exploitation : visibles seulement de la société mère.

Les menus ne dépendent que des groupes, et le siège ne se distingue d'une agence que par la société (pas de groupe
« direction du siège »). Un Gestionnaire d'agence a le groupe Manager crédit mais ne doit voir ni le menu des fonds
ni celui des contributions d'exploitation. Le filtre est posé après le cache d'Odoo (calculé par groupes ou par
utilisateur, sans la société) pour suivre le changement de société."""
from odoo import api, models

EXPLOITATION_MENUS = (
    'microfinance_loan_management.menu_microfinance_fond_exploitation',
    'microfinance_loan_management.menu_microfinance_fond_contribution_exploitation',
)


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    def _hidden_exploitation_menu_ids(self):
        if self.env.su:
            return set()
        parent = self.env['res.company']._get_microfinance_parent()
        if not parent or self.env.company == parent:
            return set()
        hidden = set()
        for xmlid in EXPLOITATION_MENUS:
            menu = self.env.ref(xmlid, raise_if_not_found=False)
            if menu:
                hidden.add(menu.id)
        return hidden

    @api.model
    def _visible_menu_ids(self, debug=False):
        visible = super()._visible_menu_ids(debug)
        hidden = self._hidden_exploitation_menu_ids()
        return visible - hidden if hidden else visible

    @api.model
    def load_menus(self, debug):
        menus = super().load_menus(debug)
        hidden = self._hidden_exploitation_menu_ids()
        if not hidden:
            return menus
        # copie : le résultat d'origine est dans le cache d'Odoo
        return {
            key: dict(item, children=[child for child in item.get('children', []) if child not in hidden])
            for key, item in menus.items() if key not in hidden
        }
