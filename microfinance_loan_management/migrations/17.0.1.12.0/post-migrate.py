# -*- coding: utf-8 -*-
"""Provisioning automatique des comptes/journaux microfinance à l'onboarding d'une agence.

À partir de cette version, le chargement du plan PCEC 2005 sur une société
(AccountChartTemplate._load, models/account_chart_template.py) crée automatiquement les
sous-comptes dédiés (LOAN_NEW_SUBACCOUNTS) et les journaux standards (JOURNALS).

post_init_hook ne se redéclenche pas sur un -u d'un module déjà installé (cf.
odoo/modules/loading.py — précédent documenté dans migrations/17.0.1.5.0, .6.0, .7.0, .11.0) :
ce script rejoue donc le provisioning sur toutes les sociétés déjà en base qui sont sur le
plan PCEC mais à qui il manque tout ou partie de ces comptes/journaux (typiquement une agence
créée manuellement après la première installation du module). Idempotent : les sociétés déjà
complètes ne sont pas modifiées, aucun compte/journal existant n'est réécrit.
"""
import logging

from odoo import SUPERUSER_ID, api

from odoo.addons.microfinance_loan_management.hooks import provision_company_pcec

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Account = env['account.account']
    Journal = env['account.journal']
    provisioned = []
    for company in env['res.company'].search([]):
        if company.chart_template != 'mg_pcec':
            continue
        accounts_before = Account.search_count([('company_id', '=', company.id)])
        journals_before = Journal.search_count([('company_id', '=', company.id)])
        provision_company_pcec(env, company)
        created_accounts = Account.search_count([('company_id', '=', company.id)]) - accounts_before
        created_journals = Journal.search_count([('company_id', '=', company.id)]) - journals_before
        if created_accounts or created_journals:
            provisioned.append((company.name, created_accounts, created_journals))

    if provisioned:
        _logger.info(
            "Microfinance PCEC : provisioning rétroactif — %s",
            "; ".join(
                "%s (+%d compte(s), +%d journal/journaux)" % row for row in provisioned
            ),
        )
    else:
        _logger.info(
            "Microfinance PCEC : toutes les sociétés sur plan PCEC sont déjà provisionnées, "
            "rien à faire."
        )
