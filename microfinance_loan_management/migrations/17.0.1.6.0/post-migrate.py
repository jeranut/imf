# -*- coding: utf-8 -*-
"""Backfill de microfinance_partner_type (Lot 4/5 du typage res.partner bailleur/agence/client) :
post_init_hook (hooks.py) ne s'exécute que sur une installation neuve (new_install, cf.
odoo/modules/loading.py), jamais sur un -u d'un module déjà installé. Cette instance a déjà
microfinance_loan_management installé : sans ce script, les 11 agences existantes, les clients
déjà créés via l'ancien menu Clients (sans domaine) et le bailleur "BFM" déjà en base resteraient
avec microfinance_partner_type vide / partner_id manquant après la mise à jour. Réutilise les
mêmes fonctions que post_init_hook (source unique) pour rester cohérent entre install neuve et
mise à jour."""
from odoo import api, SUPERUSER_ID

from odoo.addons.microfinance_loan_management.hooks import (
    _seed_agency_partner_type,
    _backfill_existing_client_partner_type,
    _backfill_bailleur_partner_ids,
)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    _seed_agency_partner_type(env)
    _backfill_existing_client_partner_type(env)
    _backfill_bailleur_partner_ids(env)
