# -*- coding: utf-8 -*-
"""Supprime les brouillons de balance d'ouverture VIDES (aucun montant, aucune écriture) qui doublonnent une autre balance de la
même société : une seule balance par société. Dry-run par défaut : paramètre système
``microfinance_loan_management.opening_cleanup_dry_run`` (absent => créé à « True »), journal dans le log Odoo.
Idempotent : sans doublon vide, ne fait rien.

Exécution réelle après le dry-run (odoo-bin shell) :
    env['ir.config_parameter'].set_param(PARAM_DRY_RUN, 'False')
    from odoo.addons.microfinance_loan_management.balance_cleanup import delete_empty_draft_duplicates
    delete_empty_draft_duplicates(env); env.cr.commit()
"""
import logging

_logger = logging.getLogger(__name__)

PARAM_DRY_RUN = 'microfinance_loan_management.opening_cleanup_dry_run'
_FALSE_VALUES = ('false', '0', 'no', 'non', 'f')


def is_dry_run(env):
    params = env['ir.config_parameter'].sudo()
    raw = params.get_param(PARAM_DRY_RUN)
    if raw is False or raw is None:
        params.set_param(PARAM_DRY_RUN, 'True')
        return True
    return str(raw).strip().lower() not in _FALSE_VALUES


def delete_empty_draft_duplicates(env, dry_run=None):
    """Retourne les ids des brouillons vides en doublon (supprimés si ``dry_run`` est faux)."""
    if dry_run is None:
        dry_run = is_dry_run(env)
    Balance = env['microfinance.opening.balance'].sudo()
    found = Balance.browse()
    for balance in Balance.search([('state', '=', 'draft')]):
        empty = not balance.move_id and all(
            balance.company_id.currency_id.is_zero(line.debit) and balance.company_id.currency_id.is_zero(line.credit)
            for line in balance.line_ids)
        others = Balance.search_count([('company_id', '=', balance.company_id.id), ('id', '!=', balance.id)])
        if empty and others:
            found |= balance
            _logger.info("Balance d'ouverture %s (%s, société %s) : brouillon vide en doublon, %s.", balance.id,
                         balance.name, balance.company_id.name, 'serait supprimée (dry-run)' if dry_run else 'supprimée')
    if not found:
        _logger.info("Balances d'ouverture : aucun brouillon vide en doublon.")
    ids = found.ids
    if found and not dry_run:
        found.unlink()
    return ids
