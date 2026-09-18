# -*- coding: utf-8 -*-
"""Propage sur les données déjà en base les corrections de comptes PCEC par défaut apportées à
microfinance.savings.product (voir synthese_audit_pcec.md) :

- account_cheques_attente_id : vide ou 511200 (code inexistant dans le PCEC officiel, jamais
  réellement créé par ce module) -> 331120 (poste 33112 "Chèques à l'encaissement non
  disponibles", déjà présent dans le plan PCEC de base chargé par plan_compta_pcec).
- account_interets_avance_{individuel,groupe,entreprise}_id : 325005/6/7 ("Produits reçus ou
  constatés d'avance", un revenu différé - mauvaise famille pour une charge d'intérêt épargne)
  -> 218004/5/6 ("Charges à payer", même famille que account_cout_interet_payer_*).

Changer le default= d'un champ Many2one ne modifie que les enregistrements créés après coup ;
les produits déjà en base gardent l'ancienne valeur (ou restent vides). Ce script rattrape les
produits existants.

Les comptes 331120/218004/218005/218006 peuvent ne pas encore exister sur une instance déjà
installée : post_init_hook ne se redéclenche pas sur un -u d'un module déjà installé (cf.
odoo/modules/loading.py) — SAVINGS_NEW_SUBACCOUNTS n'a donc pas encore tourné avec les nouveaux
codes pour ces sociétés. Ce script les crée d'abord (idempotent, comme provision_company_savings_
accounts), avant de réassigner les produits.

Idempotent : rejouer ce script ne recrée pas de compte en double (recherche par code + société
avant création, comme _get_or_create_account) et ne modifie plus les produits déjà migrés (un
champ déjà sur le nouveau code n'est pas retouché) ni ceux portant une valeur personnalisée
différente de l'ancien code (loggés comme ignorés, jamais écrasés).
"""
import logging

from odoo import SUPERUSER_ID, api

from odoo.addons.microfinance_savings_management.hooks import (
    SAVINGS_NEW_SUBACCOUNTS,
    _get_or_create_account,
)

_logger = logging.getLogger(__name__)

# 331120 (poste 33112 "Chèques à l'encaissement non disponibles") appartient au plan PCEC de
# base (plan_compta_pcec/data/template/account.account-mg_pcec.csv, xml_id pcec_33112) : il
# existe donc déjà pour toute société ayant chargé ce plan après l'ajout de cette ligne au
# template. Recréé ici par précaution seulement (idempotent), au cas où une société aurait
# chargé une version antérieure du template.
EXTRA_ACCOUNTS_TO_ENSURE = {
    '331120': ("Chèques à l'encaissement non disponibles", 'asset_current', True),
}

# champ -> (anciens codes acceptés pour bascule automatique, nouveau code)
# account_cheques_attente_id n'avait aucun défaut fonctionnel avant cette correction (511200
# n'a jamais été créé par ce module) : un champ vide y est donc traité comme "à corriger", au
# même titre que 511200 si un compte de ce code a été créé manuellement entre-temps.
# Les 3 champs account_interets_avance_* avaient au contraire un défaut réellement provisionné
# (325005/6/7, créés par SAVINGS_NEW_SUBACCOUNTS depuis l'installation du module) : un champ
# vide sur ces 3 champs signifie que CEFOR a délibérément laissé le mécanisme non configuré
# (cf. l'aide du champ : "Peut rester vide si ce mécanisme n'est pas utilisé") — on ne le
# force donc pas, seule la bascule 325xxx -> 218xxx est appliquée.
FIELD_MIGRATIONS = {
    'account_cheques_attente_id': (['511200', False], '331120'),
    'account_interets_avance_individuel_id': (['325005'], '218004'),
    'account_interets_avance_groupe_id': (['325006'], '218005'),
    'account_interets_avance_entreprise_id': (['325007'], '218006'),
}


def _account_code(record):
    return record.code if record else False


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Product = env['microfinance.savings.product'].with_context(active_test=False)

    migrated = 0
    ignored = 0
    left_empty = 0

    for company in env['res.company'].search([]):
        if company.chart_template != 'mg_pcec':
            continue

        for code, (name, account_type, reconcile) in SAVINGS_NEW_SUBACCOUNTS.items():
            _get_or_create_account(env, company, code, name, account_type, reconcile)
        for code, (name, account_type, reconcile) in EXTRA_ACCOUNTS_TO_ENSURE.items():
            _get_or_create_account(env, company, code, name, account_type, reconcile)

        products = Product.search([('company_id', '=', company.id)])
        for product in products:
            for field_name, (old_codes, new_code) in FIELD_MIGRATIONS.items():
                current_code = _account_code(product[field_name])

                if current_code == new_code:
                    continue  # déjà migré (rejeu idempotent)

                if current_code not in old_codes:
                    if current_code:
                        ignored += 1
                        _logger.info(
                            "Migration PCEC épargne : produit %s (%s), société %s — %s ignoré "
                            "(valeur personnalisée détectée : compte %s), non modifié.",
                            product.name, product.code, company.name, field_name, current_code,
                        )
                    else:
                        left_empty += 1
                        _logger.info(
                            "Migration PCEC épargne : produit %s (%s), société %s — %s laissé "
                            "vide (mécanisme non configuré, pas de bascule automatique).",
                            product.name, product.code, company.name, field_name,
                        )
                    continue

                new_account = env['account.account'].search([
                    ('code', '=', new_code), ('company_id', '=', company.id),
                ], limit=1)
                if not new_account:
                    _logger.warning(
                        "Migration PCEC épargne : compte %s introuvable pour la société %s, "
                        "produit %s (%s) — %s non modifié.",
                        new_code, company.name, product.name, product.code, field_name,
                    )
                    continue

                old_display = current_code or '(vide)'
                product[field_name] = new_account.id
                migrated += 1
                _logger.info(
                    "Migration PCEC épargne : produit %s (%s), société %s — %s : %s -> %s.",
                    product.name, product.code, company.name, field_name, old_display, new_code,
                )

    _logger.info(
        "Migration PCEC épargne terminée : %d champ(s) migré(s), %d ignoré(s) (valeur "
        "personnalisée), %d laissé(s) vide (mécanisme non configuré).",
        migrated, ignored, left_empty,
    )
