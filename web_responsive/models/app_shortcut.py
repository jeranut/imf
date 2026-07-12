# Copyright 2026 PackImmo
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html).

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class WebResponsiveAppShortcut(models.Model):
    _name = "web.responsive.app.shortcut"
    _description = "Apps Menu Shortcut"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    menu_id = fields.Many2one(
        "ir.ui.menu",
        string="Target Menu",
        required=True,
        ondelete="cascade",
        domain=[("action", "!=", False)],
    )
    icon = fields.Image(
        string="Application Icon",
        attachment=True,
        max_width=256,
        max_height=256,
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "menu_id_unique",
            "unique(menu_id)",
            "A shortcut already exists for this menu.",
        ),
    ]

    @api.onchange("menu_id")
    def _onchange_menu_id(self):
        if self.menu_id and not self.name:
            self.name = self.menu_id.name

    @api.constrains("menu_id")
    def _check_menu_has_action(self):
        for shortcut in self:
            if shortcut.menu_id and not shortcut.menu_id.action:
                raise ValidationError(
                    _("The selected menu must open an action directly.")
                )
