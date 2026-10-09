# -*- coding: utf-8 -*-
"""Scission compte épargne / produit d'épargne, passage 1 (dry-run par défaut). Le passage 2
(retrait des anciens conteneurs) n'est jamais lancé ici : cf. savings_split_migration.py."""
from odoo import SUPERUSER_ID, api

from odoo.addons.microfinance_savings_management.savings_split_migration import run_split_pass1


def migrate(cr, version):
    run_split_pass1(api.Environment(cr, SUPERUSER_ID, {}))
