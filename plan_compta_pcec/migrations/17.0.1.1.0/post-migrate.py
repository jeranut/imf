# -*- coding: utf-8 -*-
"""Propage sur les sociétés déjà en base la correction apportée au template mg_pcec (voir
synthese_audit_pcec.md §1.2) :

- account_journal_suspense_account_id : pcec_335 ("Virements internes", 335000) -> pcec_301
  ("Opérations entre siège et succursales/agences", 301000).
- transfer_account_code_prefix : '335' -> '301' (n'affecte que la création de nouveaux comptes
  de virement ; le compte de virement déjà attribué à une société existante, auto-créé sous le
  préfixe 335 lors de l'installation, n'est pas mis à jour par le seul changement de préfixe).

Changer ces valeurs de template ne modifie que ce qui est calculé au chargement initial du plan
comptable (account.chart.template._post_load_data / _setup_utility_bank_accounts) : une société
déjà installée avec l'ancien compte de suspens/virement garde l'ancienne valeur. Ce script
rattrape les sociétés existantes sur le plan PCEC.

Idempotent : ne retouche pas une société dont le compte de suspens de journal ou de virement a
déjà été migré vers 301, ni une société portant une valeur personnalisée différente de l'ancien
compte 335 (loggée comme ignorée, jamais écrasée). Les comptes bancaire/caisse dont le
suspense_account_id pointe encore vers l'ancien compte de suspens de la société sont également
corrigés (même règle de non-écrasement pour une valeur personnalisée).
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

SUSPENSE_OLD_CODE = '335000'
SUSPENSE_NEW_CODE = '301000'
TRANSFER_OLD_PREFIX = '335'
TRANSFER_NEW_PREFIX = '301'
CODE_DIGITS = 6


def _account_code(record):
    return record.code if record else False


def _get_new_suspense_account(env, company):
    return env['account.account'].search([
        ('code', '=', SUSPENSE_NEW_CODE), ('company_id', '=', company.id),
    ], limit=1)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    suspense_migrated = 0
    suspense_ignored = 0
    journal_migrated = 0
    journal_ignored = 0
    transfer_migrated = 0
    transfer_ignored = 0

    for company in env['res.company'].search([]):
        if company.chart_template != 'mg_pcec':
            continue

        new_suspense_account = _get_new_suspense_account(env, company)
        if not new_suspense_account:
            _logger.warning(
                "Migration PCEC compta : compte %s introuvable pour la société %s — comptes "
                "de suspens de journal non migrés pour cette société.",
                SUSPENSE_NEW_CODE, company.name,
            )
        else:
            old_suspense_code = _account_code(company.account_journal_suspense_account_id)
            if old_suspense_code == SUSPENSE_NEW_CODE:
                pass  # déjà migré (rejeu idempotent)
            elif old_suspense_code in (SUSPENSE_OLD_CODE, False):
                previous = old_suspense_code or '(vide)'
                company.account_journal_suspense_account_id = new_suspense_account.id
                suspense_migrated += 1
                _logger.info(
                    "Migration PCEC compta : société %s — account_journal_suspense_account_id "
                    ": %s -> %s.",
                    company.name, previous, SUSPENSE_NEW_CODE,
                )
            else:
                suspense_ignored += 1
                _logger.info(
                    "Migration PCEC compta : société %s — account_journal_suspense_account_id "
                    "ignoré (valeur personnalisée détectée : compte %s), non modifié.",
                    company.name, old_suspense_code,
                )

            # Les journaux banque/caisse dont le suspense_account_id pointe encore vers
            # l'ancien compte de suspens de la société sont corrigés en cohérence.
            journals = env['account.journal'].search([
                ('company_id', '=', company.id),
                ('type', 'in', ('bank', 'cash')),
            ])
            for journal in journals:
                journal_code = _account_code(journal.suspense_account_id)
                if journal_code == SUSPENSE_NEW_CODE:
                    continue
                if journal_code in (SUSPENSE_OLD_CODE, False):
                    previous = journal_code or '(vide)'
                    journal.suspense_account_id = new_suspense_account.id
                    journal_migrated += 1
                    _logger.info(
                        "Migration PCEC compta : société %s, journal %s — suspense_account_id "
                        ": %s -> %s.",
                        company.name, journal.name, previous, SUSPENSE_NEW_CODE,
                    )
                else:
                    journal_ignored += 1
                    _logger.info(
                        "Migration PCEC compta : société %s, journal %s — suspense_account_id "
                        "ignoré (valeur personnalisée détectée : compte %s), non modifié.",
                        company.name, journal.name, journal_code,
                    )

        transfer_code = _account_code(company.transfer_account_id)
        if transfer_code and transfer_code.startswith(TRANSFER_NEW_PREFIX):
            pass  # déjà migré (rejeu idempotent)
        elif transfer_code and transfer_code.startswith(TRANSFER_OLD_PREFIX):
            new_code = env['account.account']._search_new_account_code(
                company, CODE_DIGITS, TRANSFER_NEW_PREFIX,
            )
            new_transfer_account = env['account.account'].create({
                'name': company.transfer_account_id.name,
                'code': new_code,
                'account_type': 'asset_current',
                'reconcile': True,
                'company_id': company.id,
            })
            old_transfer_code = transfer_code
            company.transfer_account_id = new_transfer_account.id
            transfer_migrated += 1
            _logger.info(
                "Migration PCEC compta : société %s — transfer_account_id : %s -> %s "
                "(nouveau compte créé, ancien compte %s conservé mais déréférencé).",
                company.name, old_transfer_code, new_code, old_transfer_code,
            )
        elif transfer_code:
            transfer_ignored += 1
            _logger.info(
                "Migration PCEC compta : société %s — transfer_account_id ignoré (valeur "
                "personnalisée détectée : compte %s), non modifié.",
                company.name, transfer_code,
            )

    _logger.info(
        "Migration PCEC compta terminée : suspens société %d migré(s)/%d ignoré(s), suspens "
        "journal %d migré(s)/%d ignoré(s), virement %d migré(s)/%d ignoré(s).",
        suspense_migrated, suspense_ignored, journal_migrated, journal_ignored,
        transfer_migrated, transfer_ignored,
    )
