# -*- coding: utf-8 -*-
"""Conteneurs épargne : nouvelle règle de nommage AGENCE/IC/<numéro du compte crédit> (Option A,
docs_dev/epargne_auto/AUDIT_doublons_creation_client.md).

Renomme les conteneurs existants dont le nom ne suit pas la règle, SAUF si le paramètre système
``microfinance_savings.migration_dry_run`` vaut True (valeur par défaut, créée ici si absente) :
dans ce cas, seul un CSV « dry-run » est écrit et aucun nom n'est modifié. Après relecture du CSV,
passer le paramètre à False puis relancer (cf. container_migration.py pour la commande shell).

Idempotent : un conteneur déjà conforme est ignoré, rejouer ce script n'a aucun effet.
Ne touche à aucun compte réel, montant, journal ni écriture comptable.
"""
import logging

from odoo import SUPERUSER_ID, api

from odoo.addons.microfinance_savings_management.container_migration import (
    is_dry_run,
    rename_misnumbered_containers,
)

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    dry_run = is_dry_run(env)
    if dry_run:
        # Un dry-run ne doit jamais bloquer la mise à jour du module : savepoint + journal de
        # l'erreur. En mode réel, l'erreur remonte (mieux vaut arrêter la mise à jour que
        # laisser des renommages à moitié faits sans trace).
        try:
            with cr.savepoint():
                rename_misnumbered_containers(env, dry_run=True)
        except Exception:
            _logger.exception("Dry-run du renommage des conteneurs épargne en échec (ignoré).")
        return
    rename_misnumbered_containers(env, dry_run=False)
