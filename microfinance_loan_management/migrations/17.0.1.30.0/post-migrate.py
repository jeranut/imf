# -*- coding: utf-8 -*-
"""Relevé bancaire papier : la période devient une plage date + heure. Les relevés existants couvrent leur(s) journée(s)
entière(s) : début à 00:00:00 et fin à 23:59:59, heure locale. Idempotent."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['account.bank.statement']._mf_migrate_period_datetimes()
