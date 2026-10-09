# -*- coding: utf-8 -*-
"""Rattache à son agent de crédit (res.partner.microfinance_officer_id) tout client qui n'en a pas,
uniquement quand ses crédits le désignent sans ambiguïté : TOUS ses crédits portent le même
officer_id et la même agence, celle du client. Les autres cas sont listés, jamais devinés.

Dry-run par défaut : paramètre système ``microfinance_loan_management.backfill_client_officer_dry_run``
(absent => créé à « True »). Trace CSV dans ``<dossier du log Odoo>/microfinance_migrations/``.
Idempotent : un client déjà rattaché n'est jamais relu ni modifié.

Exécution réelle après le dry-run (odoo-bin shell) :
    env['ir.config_parameter'].set_param(PARAM_DRY_RUN, 'False')
    from odoo.addons.microfinance_loan_management.client_officer_backfill import backfill_client_officer
    backfill_client_officer(env); env.cr.commit()
"""
import csv
import logging
import os
from datetime import datetime

from odoo import _, tools
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

PARAM_DRY_RUN = 'microfinance_loan_management.backfill_client_officer_dry_run'
_FALSE_VALUES = ('false', '0', 'no', 'non', 'f')
CSV_HEADER = ['partner_id', 'client', 'agence_client', 'nb_credits', 'agents_credits',
              'agences_credits', 'statut']


def is_dry_run(env):
    params = env['ir.config_parameter'].sudo()
    raw = params.get_param(PARAM_DRY_RUN)
    if raw is False or raw is None:
        params.set_param(PARAM_DRY_RUN, 'True')
        return True
    return str(raw).strip().lower() not in _FALSE_VALUES


def _default_log_dir():
    logfile = tools.config['logfile']
    base = os.path.dirname(logfile) if logfile else tools.config['data_dir']
    return os.path.join(base, 'microfinance_migrations')


def _classify(partner, loans):
    if not loans:
        return 'SANS_CREDIT', False
    officers = loans.mapped('officer_id')
    if len(officers) != 1 or any(not loan.officer_id for loan in loans):
        return 'AMBIGU_AGENTS', False
    if set(loans.mapped('company_id').ids) != {partner.company_id.id}:
        return 'AMBIGU_AGENCES', False
    return 'A_POSER', officers


def backfill_client_officer(env, dry_run=None, log_dir=None):
    """Retourne la liste des lignes du rapport (dict CSV_HEADER)."""
    if dry_run is None:
        dry_run = is_dry_run(env)
    env = env(su=True, context={'active_test': False})
    csv_path = _prepare_csv(env, dry_run, log_dir or _default_log_dir())
    clients = env['res.partner'].search([
        ('microfinance_partner_type', '=', 'client'), ('microfinance_officer_id', '=', False),
    ], order='id')
    Loan = env['microfinance.loan']
    rows = []
    for partner in clients:
        loans = Loan.search([('partner_id', '=', partner.id)])
        status, officer = _classify(partner, loans)
        if status == 'A_POSER' and not dry_run:
            partner.write({'microfinance_officer_id': officer.id})
            status = 'POSE'
        rows.append({
            'partner_id': partner.id,
            'client': partner.display_name,
            'agence_client': partner.company_id.display_name or '',
            'nb_credits': len(loans),
            'agents_credits': ', '.join(sorted(set(loans.mapped('officer_id.login')))),
            'agences_credits': ', '.join(sorted(set(loans.mapped('company_id.name')))),
            'statut': status,
        })

    if csv_path:
        with open(csv_path, 'a', encoding='utf-8', newline='') as handle:
            csv.DictWriter(handle, fieldnames=CSV_HEADER, delimiter=';').writerows(rows)
    counts = {}
    for row in rows:
        counts[row['statut']] = counts.get(row['statut'], 0) + 1
    _logger.info("Rattachement client -> agent (%s) : %s client(s) sans agent, %s, trace : %s",
                 'DRY-RUN (rien modifié)' if dry_run else 'RÉEL', len(rows), counts or '{}',
                 csv_path or 'non écrite')
    return rows


def _prepare_csv(env, dry_run, directory):
    """Fichier créé (en-tête) AVANT toute écriture : pas de run réel sans trace. Création exclusive
    (mode 'x') pour que deux exécutions dans la même seconde ne s'écrasent pas."""
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    base = 'rattachement_agent_clients_%s_%s_%s' % (
        env.cr.dbname, stamp, 'dryrun' if dry_run else 'reel')
    try:
        os.makedirs(directory, exist_ok=True)
        counter = 0
        while True:
            path = os.path.join(directory, '%s%s.csv' % (base, '_%d' % counter if counter else ''))
            try:
                with open(path, 'x', encoding='utf-8', newline='') as handle:
                    csv.DictWriter(handle, fieldnames=CSV_HEADER, delimiter=';').writeheader()
                return path
            except FileExistsError:
                counter += 1
    except OSError as exc:
        if not dry_run:
            raise UserError(_(
                "Rattachement réel annulé : impossible d'écrire le fichier de traçabilité dans "
                "%(path)s (%(error)s).") % {'path': directory, 'error': exc})
        _logger.warning("Rattachement client -> agent : CSV non écrit (%s) : %s", directory, exc)
        return None
