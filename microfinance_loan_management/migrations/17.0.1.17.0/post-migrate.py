# -*- coding: utf-8 -*-
"""provision_company_pcec() pré-remplit désormais aussi microfinance_account_ecart_caisse_
deficit_id/excedent_id (cf. hooks._fill_ecart_caisse_accounts, appelé depuis
provision_company_pcec) - mais uniquement pour les sociétés dont le plan PCEC se charge (ou se
recharge) APRÈS ce correctif. Une société déjà passée sur chart_template == 'mg_pcec' avant ce
correctif (cas réel constaté : une agence existante bascule sur le pack comptable PCEC 2005
depuis Comptabilité > Configuration, longtemps après sa création, sans jamais repasser par
provision_company_pcec) reste avec ces deux champs vides tant qu'on ne rejoue pas le
provisioning explicitement ici - même précédent que les migrations 17.0.1.12.0/.13.0/.14.0 pour
LOAN_NEW_SUBACCOUNTS/JOURNALS/cash_journal_id.

Idempotent : ne touche aucune société dont le champ est déjà renseigné (post-migrate précédent,
ou saisie manuelle)."""
import logging

from odoo import SUPERUSER_ID, api

from odoo.addons.microfinance_loan_management.hooks import provision_company_pcec

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    filled = []
    for company in env['res.company'].search([('chart_template', '=', 'mg_pcec')]):
        before = (
            bool(company.microfinance_account_ecart_caisse_deficit_id),
            bool(company.microfinance_account_ecart_caisse_excedent_id),
        )
        provision_company_pcec(env, company)
        after = (
            bool(company.microfinance_account_ecart_caisse_deficit_id),
            bool(company.microfinance_account_ecart_caisse_excedent_id),
        )
        if after != before:
            filled.append(company.name)

    if filled:
        _logger.info(
            "Microfinance : comptes d'attente écart de caisse pré-remplis rétroactivement "
            "pour %s (plan PCEC déjà chargé avant ce correctif).", ", ".join(filled),
        )
    else:
        _logger.info(
            "Microfinance : aucune société à rattraper pour les comptes d'attente écart de "
            "caisse (déjà renseignés ou plan PCEC non chargé).",
        )
