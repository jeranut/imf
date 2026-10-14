# -*- coding: utf-8 -*-
"""Décaissement par virement via un compte d'attente : le nouveau champ account_virements_emis_attente_id n'est
rempli par son défaut que pour la société courante. Les produits existants reprennent leur compte d'attente chèques
émis (même 219000). Idempotent ; aucune écriture existante n'est modifiée."""


def migrate(cr, version):
    cr.execute(
        "UPDATE microfinance_loan_product SET account_virements_emis_attente_id = account_cheques_emis_attente_id "
        "WHERE account_virements_emis_attente_id IS NULL AND account_cheques_emis_attente_id IS NOT NULL")
