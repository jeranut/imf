# -*- coding: utf-8 -*-
"""Chantier décaissement provisoire (docs_dev/decaissement_provisoire/) : get_pending_
disbursements() et action_process_disbursement() exigent désormais disbursement_release_ready
== True (posé par le cron quotidien cron_release_ready_disbursements, une fois disbursement_
date_planned atteinte). Sans rattrapage, tout crédit déjà 'active' sans disbursement_date au
moment de cette montée de version (déjà en file d'attente aujourd'hui) disparaîtrait de l'onglet
« Décaissements en attente » du guichet et serait bloqué à l'action_process_disbursement()
jusqu'au passage du cron - rupture de service sur des dossiers pourtant déjà éligibles avant ce
chantier. On les fait donc passer directement à disbursement_date_confirmed=True et
disbursement_release_ready=True (pas de disbursement_date_planned nécessaire : comportement
identique à avant ce chantier, ils restent immédiatement visibles au guichet).

DRY-RUN PAR DÉFAUT : ce script ne fait qu'un rapport (nombre de dossiers concernés par agence)
et n'écrit rien, sauf si la variable d'environnement
MICROFINANCE_APPLY_DISBURSEMENT_PROVISOIRE_MIGRATION vaut '1' au moment de l'upgrade
(-u microfinance_loan_management). Cf. mémoire déploiement : redémarrer le service, puis lancer
l'upgrade, toujours après backup."""
import logging
import os

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

APPLY_ENV_VAR = 'MICROFINANCE_APPLY_DISBURSEMENT_PROVISOIRE_MIGRATION'


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    loans = env['microfinance.loan'].search([
        ('state', '=', 'active'),
        ('disbursement_date', '=', False),
    ])

    by_company = {}
    for loan in loans:
        by_company.setdefault(loan.company_id.display_name, 0)
        by_company[loan.company_id.display_name] += 1

    if not loans:
        _logger.info(
            "Microfinance (décaissement provisoire) : aucun crédit 'active' non décaissé à "
            "rattraper - rien à faire.")
        return

    report = ", ".join("%s: %d" % (name, count) for name, count in sorted(by_company.items()))
    apply_migration = os.environ.get(APPLY_ENV_VAR) == '1'

    if not apply_migration:
        _logger.warning(
            "Microfinance (décaissement provisoire) : DRY-RUN - %d dossier(s) seraient "
            "marqués disbursement_date_confirmed=True / disbursement_release_ready=True par "
            "agence : %s. Aucune écriture effectuée. Relancer l'upgrade avec la variable "
            "d'environnement %s=1 pour appliquer réellement.",
            len(loans), report, APPLY_ENV_VAR,
        )
        return

    loans.write({
        'disbursement_date_confirmed': True,
        'disbursement_release_ready': True,
    })
    _logger.info(
        "Microfinance (décaissement provisoire) : %d dossier(s) marqués "
        "disbursement_date_confirmed=True / disbursement_release_ready=True par agence : %s.",
        len(loans), report,
    )
