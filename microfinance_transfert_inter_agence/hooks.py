# -*- coding: utf-8 -*-
import logging

# Réutilise les helpers du module crédit (recherche de compte par code + société).
from odoo.addons.microfinance_loan_management.hooks import _get_account_or_warn

_logger = logging.getLogger(__name__)

TRANSIT_CODE = 'TRANSIT'
TRANSIT_NAME = 'Transit inter-agences'
TRANSIT_ACCOUNT_CODE = '302000'


def _create_transit_journal(env, company):
    """Crée idempotemment le journal « Transit inter-agences » (type general, compte par défaut
    302000) d'une société. Recherche avec active_test=False : un journal archivé n'est JAMAIS
    recréé (le code est unique par société, archivés compris). Le champ code est limité à
    5 caractères : le journal est stocké sous « TRANS » et retrouvé par la recherche « TRANSIT »."""
    Journal = env['account.journal'].with_context(active_test=False)
    existing = Journal.search([('code', 'in', (TRANSIT_CODE, TRANSIT_CODE[:5])), ('company_id', '=', company.id)], limit=1)
    if existing:
        if not existing.active:
            _logger.warning(
                "microfinance_transfert_inter_agence : le journal %s de %s est archivé ; il n'est pas "
                "recréé. Réactivez-le pour utiliser les transferts inter-agences.",
                existing.code, company.name)
        return existing
    vals = {'name': TRANSIT_NAME, 'code': TRANSIT_CODE, 'type': 'general', 'company_id': company.id}
    account = _get_account_or_warn(env, company, TRANSIT_ACCOUNT_CODE)
    if account:
        vals['default_account_id'] = account.id
    return Journal.create(vals)


def post_init_hook(env):
    """À l'installation du module : s'assure que le journal « Transit inter-agences »
    (code TRANSIT, default_account_id = 302000) existe sur chaque société utilisant le plan PCEC.
    Le module crédit ne le crée plus lui-même (il ne figure plus dans JOURNALS)."""
    for company in env['res.company'].search([]):
        if company.chart_template != 'mg_pcec':
            continue
        _create_transit_journal(env, company)
    _logger.info(
        "microfinance_transfert_inter_agence : journal TRANSIT vérifié/créé sur les agences PCEC.")
