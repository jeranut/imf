# -*- coding: utf-8 -*-
"""Une seule balance d'ouverture par société : nettoyage des brouillons vides en doublon (dry-run par défaut), cf.
balance_cleanup.py."""
from odoo import SUPERUSER_ID, api

from odoo.addons.microfinance_loan_management.balance_cleanup import delete_empty_draft_duplicates


def migrate(cr, version):
    delete_empty_draft_duplicates(api.Environment(cr, SUPERUSER_ID, {}))
