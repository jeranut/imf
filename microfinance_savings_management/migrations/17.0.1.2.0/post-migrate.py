# -*- coding: utf-8 -*-
"""Rejoue le provisioning des sous-comptes épargne dédiés (SAVINGS_NEW_SUBACCOUNTS) sur les
sociétés déjà en base utilisant le plan PCEC.

post_init_hook ne se redéclenche pas sur un -u d'un module déjà installé (cf.
odoo/modules/loading.py). Ce script rattrape donc les agences créées manuellement après la
première installation du module, dont le formulaire produit d'épargne affiche les comptes
Épargne Individuel/Groupe/Entreprise et Intérêts vides (en rouge) parce que les comptes
213001/2/3, 607301/2/3, 325005/6/7… n'ont jamais été créés pour leur société.

À partir de cette version, ces comptes sont créés automatiquement au chargement du plan PCEC
sur une société (AccountChartTemplate._load, models/account_chart_template.py). Idempotent
(_get_or_create_account : search par code + société avant création) — aucune société déjà
complète n'est modifiée.
"""
import logging

from odoo import SUPERUSER_ID, api

from odoo.addons.microfinance_savings_management.hooks import provision_company_savings_accounts

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Account = env['account.account']
    provisioned = []
    for company in env['res.company'].search([]):
        if company.chart_template != 'mg_pcec':
            continue
        before = Account.search_count([('company_id', '=', company.id)])
        provision_company_savings_accounts(env, company)
        created = Account.search_count([('company_id', '=', company.id)]) - before
        if created:
            provisioned.append((company.name, created))

    if provisioned:
        _logger.info(
            "Microfinance épargne PCEC : provisioning rétroactif — %s",
            "; ".join("%s (+%d compte(s))" % row for row in provisioned),
        )
    else:
        _logger.info(
            "Microfinance épargne PCEC : toutes les sociétés sur plan PCEC sont déjà "
            "provisionnées, rien à faire."
        )
