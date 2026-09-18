# -*- coding: utf-8 -*-
"""Reprend le snapshot de pre-migrate.py (ancien caisse_ecart_waiting_account_id) comme valeur
de microfinance_account_ecart_caisse_deficit_id.

Corrige aussi, pour TOUTES les sociétés (pas seulement celles ayant un ancien compte à migrer),
un défaut connu du backfill natif d'Odoo pour une colonne nouvellement ajoutée : `_init_column`
évalue le `default=` UNE SEULE FOIS pour toute la table (pas par ligne), puis fait un simple
`UPDATE ... SET col = <cette-valeur-unique>` sur toutes les lignes existantes. Comme
_pcec_default('code') dépend de la société (recherche `company_id = env.company.id`), le
résultat de ce calcul unique - celui de la société de l'environnement utilisé pour la mise à
jour - se retrouve appliqué à TOUTES les sociétés, y voir une agence poser une écriture d'écart
de caisse sur le compte d'une AUTRE agence si on ne corrigeait pas ceci explicitement ici,
société par société."""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

FIELD_TO_CODE = {
    'microfinance_account_ecart_caisse_deficit_id': '324000',
    'microfinance_account_ecart_caisse_excedent_id': '329100',
}


def _fix_cross_company_leak(env, _logger):
    """Recale chaque société sur SON PROPRE compte (par code), quand la valeur actuellement
    posée par le backfill natif d'Odoo appartient en réalité à une autre société."""
    Account = env['account.account']
    fixed = {field: [] for field in FIELD_TO_CODE}
    for company in env['res.company'].search([]):
        for field, code in FIELD_TO_CODE.items():
            current = company[field]
            if current and current.company_id == company:
                continue  # déjà correct (bonne société) : ne rien toucher
            own_account = Account.search([
                ('code', '=', code), ('company_id', '=', company.id),
            ], limit=1)
            if own_account:
                company[field] = own_account.id
                fixed[field].append(company.id)
            elif current:
                # Valeur erronée (autre société) mais aucun compte de remplacement disponible
                # pour cette société (chart PCEC non chargé) : on vide plutôt que de laisser un
                # compte appartenant à une autre agence.
                company[field] = False
                fixed[field].append(company.id)
    _logger.info(
        "Microfinance : correction de la fuite inter-société du backfill natif Odoo — "
        "sociétés recalées par champ : %s.", fixed,
    )


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    _fix_cross_company_leak(env, _logger)

    cr.execute("SELECT to_regclass('_microfinance_migrate_caisse_ecart_waiting_account')")
    if not cr.fetchone()[0]:
        _logger.info(
            "Microfinance : aucune valeur historique de compte d'attente écart de caisse à "
            "migrer (table snapshot absente)."
        )
        return

    cr.execute("SELECT company_id, caisse_ecart_waiting_account_id FROM _microfinance_migrate_caisse_ecart_waiting_account")
    rows = cr.fetchall()

    migrated = []
    for company_id, old_account_id in rows:
        company = env['res.company'].browse(company_id)
        if not company.exists():
            continue
        # L'ancienne valeur, saisie à la main par un manager, prime toujours sur le compte
        # PCEC standard posé ci-dessus par _fix_cross_company_leak.
        company.microfinance_account_ecart_caisse_deficit_id = old_account_id
        migrated.append(company_id)

    cr.execute("DROP TABLE IF EXISTS _microfinance_migrate_caisse_ecart_waiting_account")
    _logger.info(
        "Microfinance : migration compte d'attente écart de caisse -> deficit_id terminée. "
        "Sociétés migrées depuis l'ancien champ : %s.", migrated,
    )
