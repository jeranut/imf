# -*- coding: utf-8 -*-
from odoo import _, api, models


class MicrofinanceLoan(models.Model):
    """Tuiles épargne de la « Vue d'ensemble » du tableau de bord Microfinance, ajoutées depuis le
    module épargne (dépendance à sens unique : le module crédit n'importe jamais le module épargne).
    """
    _inherit = 'microfinance.loan'

    @api.model
    def _get_overview_tiles(self):
        tiles = super()._get_overview_tiles()
        env = self.env
        company_id = env.company.id
        Holder = env['microfinance.savings.holder.account']
        Product = env['microfinance.savings.account']
        if Holder.check_access_rights('read', raise_exception=False):
            holder_domain = [('company_id', '=', company_id), ('state', '=', 'active')]
            tile = self._overview_tile(
                'active_savings_holder_count', _('Comptes épargne actifs'), 'count', 'fa-bank', 'savings-count',
                lambda: Holder.search_count(holder_domain), 'microfinance.savings.holder.account', holder_domain,
                _('Voir les comptes épargne'))
            tile['views'] = [
                [env.ref('microfinance_savings_management.view_microfinance_savings_holder_account_tree').id, 'list'],
                [env.ref('microfinance_savings_management.view_microfinance_savings_holder_account_form').id, 'form'],
            ]
            tiles.append(tile)
        if Product.check_access_rights('read', raise_exception=False):
            product_domain = [('company_id', '=', company_id), ('state', '=', 'active'), ('account_id', '!=', False)]
            views = [
                [env.ref('microfinance_savings_management.view_microfinance_savings_account_tree_menu').id, 'list'],
                [env.ref('microfinance_savings_management.view_microfinance_savings_account_form_menu').id, 'form'],
            ]
            for tile in (
                self._overview_tile(
                    'active_savings_account_count', _("Produits d'épargne actifs"), 'count', 'fa-list',
                    'savings-count', lambda: Product.search_count(product_domain), 'microfinance.savings.account',
                    product_domain, _('Voir les produits')),
                self._overview_tile(
                    'savings_outstanding_total', _('Encours épargne'), 'money', 'fa-google-wallet',
                    'savings-outstanding', lambda: sum(Product.search(product_domain).mapped('balance')),
                    'microfinance.savings.account', product_domain, _("Voir l'encours épargne")),
            ):
                tile['views'] = views
                tiles.append(tile)
        return tiles
