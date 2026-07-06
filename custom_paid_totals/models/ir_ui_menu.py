# -*- coding: utf-8 -*-
from copy import deepcopy

from odoo import fields, models
from odoo.tools.safe_eval import safe_eval


SG_EAT_DEPOT_COMPANY_NAME = "SG-EAT DEPOT"


SG_EAT_DEPOT_COMPANY_NAME = "SG-EAT DEPOT"


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    custom_paid_totals_dynamic_journal_menu = fields.Boolean(
        string='Menu journal dynamique Trésorerie',
        copy=False,
    )


    def _paid_totals_synced_menu_context(self, menu):
        action = menu.action
        if not action or action._name != 'ir.actions.act_window':
            return {}
        try:
            return safe_eval(action.context or '{}')
        except Exception:
            return {}

    def _is_paid_totals_synced_journal_menu(self, menu):
        return bool(self._paid_totals_synced_menu_context(menu).get('paid_totals_journal_menu_sync'))

    def _paid_totals_synced_menu_company_id(self, menu):
        return self._paid_totals_synced_menu_context(menu).get('default_company_id')

    def load_menus(self, debug):
        menus = deepcopy(super().load_menus(debug))
        parent_menu = self.env.ref('custom_paid_totals.menu_paid_totals_list')
        hidden_menu_ids = set()
        if self.env.company.name != SG_EAT_DEPOT_COMPANY_NAME:
            for xmlid in (
                'custom_paid_totals.menu_custom_paid_advance_payment',
                'custom_paid_totals.menu_custom_paid_advance_payment_config',
            ):
                advance_menu = self.env.ref(xmlid, raise_if_not_found=False)
                if advance_menu:
                    hidden_menu_ids.add(advance_menu.id)

        if self.env.company.name != SG_EAT_DEPOT_COMPANY_NAME:
            for xmlid in (
                'custom_paid_totals.menu_custom_paid_advance_payment',
                'custom_paid_totals.menu_custom_paid_advance_payment_config',
            ):
                advance_menu = self.env.ref(xmlid, raise_if_not_found=False)
                if advance_menu:
                    hidden_menu_ids.add(advance_menu.id)

        pending_menu_ids = list(hidden_menu_ids)
        while pending_menu_ids:
            menu_id = pending_menu_ids.pop()
            child_ids = set(menus.get(menu_id, {}).get('children', [])) - hidden_menu_ids
            hidden_menu_ids.update(child_ids)
            pending_menu_ids.extend(child_ids)

        for menu_id in hidden_menu_ids:
            menus.pop(menu_id, None)
        for menu in menus.values():
            menu['children'] = [
                child_id for child_id in menu.get('children', [])
                if child_id not in hidden_menu_ids
            ]

        return menus
