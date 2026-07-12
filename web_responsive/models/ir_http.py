# Copyright 2023 Taras Shabaranskyi
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html).

from odoo import models


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    def _get_apps_menu_shortcuts(self):
        visible_menu_ids = self.env["ir.ui.menu"]._visible_menu_ids()
        shortcuts = (
            self.env["web.responsive.app.shortcut"]
            .sudo()
            .search(
                [
                    ("active", "=", True),
                    ("menu_id", "in", list(visible_menu_ids)),
                ],
                order="sequence, id",
            )
        )
        return [
            {
                "id": shortcut.id,
                "menu_id": shortcut.menu_id.id,
                "name": shortcut.name,
                "icon": (
                    shortcut.icon.decode()
                    if isinstance(shortcut.icon, bytes)
                    else shortcut.icon
                ),
            }
            for shortcut in shortcuts
        ]

    def session_info(self):
        session = super().session_info()
        user = self.env.user
        return {
            **session,
            "apps_menu": {
                "search_type": user.apps_menu_search_type,
                "theme": user.apps_menu_theme,
                "shortcuts": self._get_apps_menu_shortcuts(),
            },
        }
