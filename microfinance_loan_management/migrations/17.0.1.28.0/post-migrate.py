# -*- coding: utf-8 -*-
"""Fonds sans compte dédié : crée leur compte passif (240xxx privé par défaut). Les fonds qui ont déjà un
compte (même un ancien compte par défaut) ne sont pas touchés, ni leurs écritures. Idempotent."""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    funds = env['microfinance.fond.credit'].with_context(active_test=False).search(
        [('passer_gl', '=', True), ('account_id', '=', False)])
    funds._ensure_origin_account()
