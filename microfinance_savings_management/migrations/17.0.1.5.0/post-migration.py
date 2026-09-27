# -*- coding: utf-8 -*-
"""Correctif du 2026-09-24 (docs_dev/epargne_auto/AUDIT_doublons_creation_client.md §13) : abroge
l'« Option A » du 21/09 (conteneur AGENCE/IC/<numéro du compte crédit>, compte principal réel
distinct). Nouvelle règle : conteneur AGENCE/I/N (N = numéro de compte permanent du client, même
N que le compte crédit), seul compte épargne créé automatiquement à l'enregistrement du client.

Deux actions, l'une en écriture contrôlée, l'autre strictement en lecture :

1. Renommage des conteneurs existants (AGENCE/IC/... -> AGENCE/I/N), respectant le paramètre
   système ``microfinance_savings.migration_dry_run`` (True par défaut, créé ici si absent) :
   en dry-run, seul un CSV liste ce qui serait renommé, rien n'est modifié.
2. Liste (CSV, jamais d'écriture sur les comptes) des clients ayant plusieurs comptes épargne
   pour une société (ancien « compte principal » + conteneur) - à traiter à la main par Micka
   (colonne ``decision``, aucune fusion automatique).

Idempotent : rejouer ce script n'a aucun effet une fois les conteneurs conformes. Ne touche à
aucun compte réel, montant, journal ni écriture comptable.
"""
import logging

from odoo import SUPERUSER_ID, api

from odoo.addons.microfinance_savings_management.container_migration import (
    align_savings_number_sequences,
    is_dry_run,
    list_savings_duplicates,
    rename_misnumbered_containers,
)

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    dry_run = is_dry_run(env)
    if dry_run:
        # Un dry-run ne doit jamais bloquer la mise à jour du module : savepoint + journal de
        # l'erreur. En mode réel, l'erreur remonte (mieux vaut arrêter la mise à jour que
        # laisser des renommages/alignements à moitié faits sans trace).
        try:
            with cr.savepoint():
                align_savings_number_sequences(env, dry_run=True)
        except Exception:
            _logger.exception("Dry-run de l'alignement des séquences épargne en échec (ignoré).")
        try:
            with cr.savepoint():
                rename_misnumbered_containers(env, dry_run=True)
        except Exception:
            _logger.exception("Dry-run du renommage des conteneurs épargne en échec (ignoré).")
    else:
        # Aligner AVANT de renommer : le renommage des conteneurs ne dépend pas de la séquence
        # (il dérive du numéro déjà attribué), mais tout nouveau compte réel de type I créé
        # entre les deux étapes doit voir la séquence déjà à jour.
        align_savings_number_sequences(env, dry_run=False)
        rename_misnumbered_containers(env, dry_run=False)

    # Lecture seule : peut s'exécuter même si le renommage ci-dessus est en dry-run ou a échoué.
    try:
        with cr.savepoint():
            list_savings_duplicates(env)
    except Exception:
        _logger.exception("Listage des doublons de comptes épargne en échec (ignoré).")
