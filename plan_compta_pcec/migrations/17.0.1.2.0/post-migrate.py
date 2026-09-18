# -*- coding: utf-8 -*-
"""Propage sur les sociétés déjà en base la correction de libellé/account_type apportée à la
famille "32 Comptes de Régularisation" du template mg_pcec (321, 324, 325, 326+3261/3262,
329+3291/3292/3293 - cf. rapport d'audit famille 32, PCEC p.76-77).

Comme pour migrations/17.0.1.1.0/post-migrate.py (compte de suspens 335->301) : corriger le CSV
du template ne modifie que ce qui sera chargé pour une NOUVELLE société. Les account.account
déjà créés pour les sociétés existantes gardent l'ancien libellé/account_type erronés tant
qu'un script ne les corrige pas explicitement ici.

Idempotent et non-destructif : ne corrige un compte que si son libellé ET son account_type
correspondent encore EXACTEMENT à l'ancien état erroné connu (OLD_NAME, OLD_TYPE) - toute
société où le compte a déjà été modifié manuellement (nom et/ou type différents de l'ancien
état connu, y compris déjà migré) est laissée intacte et journalisée comme ignorée."""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

# code -> (ancien libellé erroné, ancien account_type erroné, nouveau libellé, nouveau account_type)
CORRECTIONS = {
    '321000': (
        "Charges et produits constatés d'avance *", 'asset_current',
        "Charges payées ou constatées d'avance *", 'asset_current',
    ),
    '324000': (
        'Charges à répartir *', 'asset_current',
        "Comptes d'attente à régulariser - actif *", 'asset_current',
    ),
    '326000': (
        "Comptes d'ajustement - passif *", 'liability_current',
        'Produits réservés *', 'liability_current',
    ),
    '326100': (
        'Produits réservés sur échéances de crédit non imputées', 'income',
        'Produits sur échéances de crédit non imputées', 'liability_current',
    ),
    '326200': (
        "Comptes d'ajustement devises - passif *", 'liability_current',
        'Produits sur créances litigieuses douteuses ou contentieuses', 'liability_current',
    ),
    '329000': (
        'Autres comptes de régularisation *', 'asset_current',
        'Autres comptes de régularisation - passif *', 'liability_current',
    ),
    '329100': (
        'Autres comptes de régularisation - actif *', 'asset_current',
        'Écritures créditrices à régulariser', 'liability_current',
    ),
    '329200': (
        'Autres comptes de régularisation - passif *', 'liability_current',
        'Produits réservés sur crédits sains', 'liability_current',
    ),
    '329300': (
        'Autres comptes de régularisation - divers *', 'asset_current',
        'Principal à récupérer sur crédits réintégrés', 'asset_receivable',
    ),
}
# 325000 : libellé et account_type déjà corrects avant ce chantier, rien à propager.


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    migrated = 0
    ignored = 0
    for code, (old_name, old_type, new_name, new_type) in CORRECTIONS.items():
        accounts = env['account.account'].search([('code', '=', code)])
        for account in accounts:
            if account.name == old_name and account.account_type == old_type:
                account.write({'name': new_name, 'account_type': new_type})
                migrated += 1
                _logger.info(
                    "Migration PCEC compta (famille 32) : société %s, compte %s : "
                    "%r/%s -> %r/%s.",
                    account.company_id.name, code, old_name, old_type, new_name, new_type,
                )
            elif account.name != new_name or account.account_type != new_type:
                ignored += 1
                _logger.info(
                    "Migration PCEC compta (famille 32) : société %s, compte %s ignoré "
                    "(valeur personnalisée détectée : %r/%s), non modifié.",
                    account.company_id.name, code, account.name, account.account_type,
                )
            # sinon déjà migré (rejeu idempotent) : rien à faire, rien à journaliser.

    # 3293 (asset_receivable) doit aussi devenir réconciliable, comme le nouveau template.
    accounts_3293 = env['account.account'].search([
        ('code', '=', '329300'), ('account_type', '=', 'asset_receivable'), ('reconcile', '=', False),
    ])
    accounts_3293.write({'reconcile': True})

    _logger.info(
        "Migration PCEC compta (famille 32) terminée : %d compte(s) corrigé(s), "
        "%d compte(s) ignoré(s) (valeur personnalisée).", migrated, ignored,
    )
