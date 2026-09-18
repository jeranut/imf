# -*- coding: utf-8 -*-
"""Rattrapage de 5 traitements de post_init_hook qui n'avaient jamais eu de script de
migration dédié (post_init_hook ne se redéclenche pas sur un -u d'un module déjà installé,
cf. odoo/modules/loading.py — précédent documenté dans migrations/17.0.1.5.0, .6.0, .7.0,
.11.0, .12.0, .14.0 de ce module) :

1) _seed_known_agency_codes : agency_code des 11 agences CEFOR déjà identifiées
   (KNOWN_AGENCY_CODES), jamais rattrapé jusqu'ici sur une instance déjà installée.
2) _load_geo_reference_data : référentiel géo (communes, fokontany, codes postaux, régions,
   districts, liens commune<->district) — chargé uniquement par ce hook, absent de la clé
   'data' du manifeste : sans ce script, aucune instance déjà installée avant l'ajout de ce
   référentiel ne l'aurait jamais reçu.
3) _load_activity_reference_data : référentiel Catégorie d'activité / Activité (Bloc IV).
4) _load_financial_reference_data : désignations par défaut Section V (revenus, dépenses
   d'activité, dépenses familiales) et fréquences de montant.
5) _cleanup_existing_financial_lines : nettoyage des lignes financières historiques
   (doublons, lignes sans désignation ou liées à une désignation inactive) — doit tourner
   APRÈS _load_financial_reference_data, dont elle dépend (désignations actives).

Toutes idempotentes : 1) filtre agency_code vide avant écriture ; 2)-4) passent par
_load_records(update=True) avec xml_id noupdate=True forcé (_force_geo_noupdate) et des
write() conditionnels qui ne touchent jamais une valeur déjà renseignée en base ; 5) est
documentée et vérifiée idempotente dans hooks.py (un second passage ne modifie plus rien).
Un rejeu de ce script sur une instance déjà à jour ne duplique donc aucune donnée.
"""
import logging

from odoo import SUPERUSER_ID, api

from odoo.addons.microfinance_loan_management.hooks import (
    KNOWN_AGENCY_CODES,
    _seed_known_agency_codes,
    _load_geo_reference_data,
    _load_activity_reference_data,
    _load_financial_reference_data,
    _cleanup_existing_financial_lines,
)

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    Company = env['res.company']
    before = Company.search([
        ('name', 'in', list(KNOWN_AGENCY_CODES.keys())),
        ('agency_code', '=', False),
    ]).mapped('name')
    _seed_known_agency_codes(env)
    after_missing = Company.search([
        ('name', 'in', list(KNOWN_AGENCY_CODES.keys())),
        ('agency_code', '=', False),
    ]).mapped('name')
    backfilled = sorted(set(before) - set(after_missing))
    _logger.info(
        "Microfinance rattrapage post_init_hook : agency_code renseigné pour %s (agences "
        "déjà codées ou absentes de la base, ignorées : %s).",
        backfilled or '—', sorted(set(KNOWN_AGENCY_CODES) - set(before)) or '—',
    )

    _load_geo_reference_data(env)
    _load_activity_reference_data(env)
    _load_financial_reference_data(env)
    _cleanup_existing_financial_lines(env)

    _logger.info(
        "Microfinance rattrapage post_init_hook : référentiels géo/activités/financier "
        "chargés et lignes financières historiques nettoyées (détails ci-dessus, loggés par "
        "chaque fonction)."
    )
