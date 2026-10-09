# -*- coding: utf-8 -*-
"""Rattachement client -> agent de crédit (docs_dev/clients_portefeuille/) : dry-run par défaut,
cf. client_officer_backfill.py pour la règle, le paramètre système et le run réel."""
from odoo import SUPERUSER_ID, api

from odoo.addons.microfinance_loan_management.client_officer_backfill import backfill_client_officer


def migrate(cr, version):
    backfill_client_officer(api.Environment(cr, SUPERUSER_ID, {}))
