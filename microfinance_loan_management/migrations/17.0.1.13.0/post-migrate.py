# -*- coding: utf-8 -*-
"""Propage sur les données déjà en base la correction de compte PCEC par défaut apportée à
microfinance.loan.product.account_surpaiement_id (voir synthese_audit_pcec.md §2.3) :

315000 ("Créditeurs divers", générique tiers) -> 219001, sous-compte dédié du poste 219
"Autres sommes dues à la clientèle", plus proche sémantiquement d'un surpaiement client
(219000 déjà utilisé par account_cheques_emis_attente_id, cf. LOAN_NEW_SUBACCOUNTS).

Changer le default= d'un champ Many2one ne modifie que les enregistrements créés après coup ;
les produits déjà en base gardent l'ancienne valeur (315000). Ce script rattrape les produits
existants.

219001 peut ne pas encore exister sur une instance déjà installée : post_init_hook ne se
redéclenche pas sur un -u d'un module déjà installé (cf. odoo/modules/loading.py) — le compte
n'a donc pas encore été créé pour les sociétés existantes. Ce script le crée d'abord
(idempotent, comme provision_company_pcec), avant de réassigner les produits.

Idempotent : rejouer ce script ne recrée pas de compte en double (recherche par code + société
avant création, comme _get_or_create_account) et ne modifie plus les produits déjà migrés (un
champ déjà sur 219001 n'est pas retouché) ni ceux portant une valeur personnalisée différente de
315000 (loggés comme ignorés, jamais écrasés).
"""
import logging

from odoo import SUPERUSER_ID, api

from odoo.addons.microfinance_loan_management.hooks import (
    LOAN_NEW_SUBACCOUNTS,
    _get_or_create_account,
)

_logger = logging.getLogger(__name__)

OLD_CODE = '315000'
NEW_CODE = '219001'
FIELD_NAME = 'account_surpaiement_id'


def _account_code(record):
    return record.code if record else False


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Product = env['microfinance.loan.product'].with_context(active_test=False)

    name, account_type, reconcile = LOAN_NEW_SUBACCOUNTS[NEW_CODE]

    migrated = 0
    ignored = 0
    left_empty = 0

    for company in env['res.company'].search([]):
        if company.chart_template != 'mg_pcec':
            continue

        _get_or_create_account(env, company, NEW_CODE, name, account_type, reconcile)

        products = Product.search([('company_id', '=', company.id)])
        for product in products:
            current_code = _account_code(product[FIELD_NAME])

            if current_code == NEW_CODE:
                continue  # déjà migré (rejeu idempotent)

            if current_code != OLD_CODE:
                if current_code:
                    ignored += 1
                    _logger.info(
                        "Migration PCEC crédit : produit %s (%s), société %s — %s ignoré "
                        "(valeur personnalisée détectée : compte %s), non modifié.",
                        product.name, product.code, company.name, FIELD_NAME, current_code,
                    )
                else:
                    left_empty += 1
                    _logger.info(
                        "Migration PCEC crédit : produit %s (%s), société %s — %s laissé vide "
                        "(mécanisme non configuré, pas de bascule automatique).",
                        product.name, product.code, company.name, FIELD_NAME,
                    )
                continue

            new_account = env['account.account'].search([
                ('code', '=', NEW_CODE), ('company_id', '=', company.id),
            ], limit=1)
            if not new_account:
                _logger.warning(
                    "Migration PCEC crédit : compte %s introuvable pour la société %s, "
                    "produit %s (%s) — %s non modifié.",
                    NEW_CODE, company.name, product.name, product.code, FIELD_NAME,
                )
                continue

            product[FIELD_NAME] = new_account.id
            migrated += 1
            _logger.info(
                "Migration PCEC crédit : produit %s (%s), société %s — %s : %s -> %s.",
                product.name, product.code, company.name, FIELD_NAME, current_code, NEW_CODE,
            )

    _logger.info(
        "Migration PCEC crédit terminée : %d champ(s) migré(s), %d ignoré(s) (valeur "
        "personnalisée), %d laissé(s) vide (mécanisme non configuré).",
        migrated, ignored, left_empty,
    )
