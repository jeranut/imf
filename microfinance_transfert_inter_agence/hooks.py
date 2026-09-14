# -*- coding: utf-8 -*-
import logging

# Réutilise la création idempotente des journaux du module crédit (source unique
# de la liste JOURNALS, où le journal TRANSIT vient d'être ajouté) plutôt que de
# dupliquer la logique ici.
from odoo.addons.microfinance_loan_management.hooks import _create_journals

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """À l'installation du module sur une instance existante : s'assure que le
    journal « Transit inter-agences » (code TRANSIT, default_account_id = 302000)
    existe sur chaque agence utilisant le plan PCEC.

    _create_journals est idempotent (il saute tout journal déjà présent pour la
    société) : sur une agence qui a déjà ses 7 journaux standards, seul TRANSIT
    est créé ; sur une nouvelle agence, tout est créé — mais dans ce cas c'est le
    post_init_hook du module crédit qui a déjà fait le travail.
    """
    companies = env['res.company'].search([])
    for company in companies:
        if company.chart_template != 'mg_pcec':
            continue
        _create_journals(env, company)
    _logger.info(
        "microfinance_transfert_inter_agence : journal TRANSIT vérifié/créé sur "
        "les agences PCEC.")
