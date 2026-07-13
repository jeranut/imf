# -*- coding: utf-8 -*-
"""Corrige le type des journaux CRE/EPG créés par post_init_hook (hooks.py, JOURNALS) : avant
cette version, ils étaient créés en type 'general' alors qu'ils sont utilisés comme valeur par
défaut de disbursement_journal_id/payment_journal_id/fee_journal_id (microfinance.loan.product)
et deposit_journal_id/withdrawal_journal_id (microfinance.savings.product), champs dont le
domaine de vue exige ('type', 'in', ('bank', 'cash')) — cf. docs_dev/gestion_caisse/AUDIT.md §1.3.
Ne retype que les journaux sans aucune écriture comptable (account_move) déjà rattachée : un
journal CRE/EPG déjà utilisé pour des décaissements/dépôts réels n'est pas modifié
automatiquement, pour ne pas changer silencieusement le comportement (rapprochement, séquences)
d'un journal déjà en usage — traitement manuel à faire au cas par cas si l'avertissement est
loggé."""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        SELECT id, code, company_id
        FROM account_journal
        WHERE code IN ('CRE', 'EPG') AND type = 'general'
    """)
    rows = cr.fetchall()
    for journal_id, code, company_id in rows:
        cr.execute("SELECT COUNT(*) FROM account_move WHERE journal_id = %s", (journal_id,))
        move_count = cr.fetchone()[0]
        if move_count:
            _logger.warning(
                "Microfinance : journal %s (id=%s, société id=%s) laissé en type 'general' "
                "malgré la correction de post_init_hook, car %s écriture(s) comptable(s) y "
                "sont déjà rattachée(s). Retypage à traiter manuellement si nécessaire.",
                code, journal_id, company_id, move_count,
            )
            continue
        cr.execute("UPDATE account_journal SET type = 'cash' WHERE id = %s", (journal_id,))
        _logger.info(
            "Microfinance : journal %s (id=%s, société id=%s) retypé de 'general' à 'cash' "
            "(aucune écriture comptable existante).",
            code, journal_id, company_id,
        )
