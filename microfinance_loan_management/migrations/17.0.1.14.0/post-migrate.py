# -*- coding: utf-8 -*-
"""Restriction du journal sélectionnable à l'ouverture d'une session de caisse guichet : à
partir de cette version, microfinance.caisse.session.journal_id est verrouillé sur le journal
de caisse unique configuré par agence (res.company.cash_journal_id, nouveau champ).

post_init_hook ne se redéclenche pas sur un -u d'un module déjà installé (cf.
odoo/modules/loading.py - précédent documenté dans migrations/17.0.1.5.0, .6.0, .7.0, .11.0,
.12.0) : ce script initialise donc cash_journal_id, pour chaque société déjà en base, à partir
de son journal de code 'CAI' et de type 'cash' (journal caisse standard provisionné par
provision_company_pcec/JOURNALS). Idempotent : une société qui a déjà cash_journal_id n'est pas
touchée. Les agences sans journal CAI (pas encore provisionnées) sont journalisées mais ne font
pas planter le script - cash_journal_id y reste vide jusqu'à provisioning, et
microfinance.caisse.session._check_journal_matches_company_cash_journal bloquera alors toute
ouverture de session tant qu'un manager n'aura pas configuré le journal (Sociétés > Caisse
guichet)."""
import logging

from odoo import SUPERUSER_ID, api

from odoo.addons.microfinance_loan_management.hooks import _backfill_cash_journal_id

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    backfilled, missing = _backfill_cash_journal_id(env)

    if backfilled:
        _logger.info(
            "Microfinance caisse guichet : journal CAI affecté à cash_journal_id pour %s.",
            ", ".join(backfilled),
        )
    if missing:
        _logger.warning(
            "Microfinance caisse guichet : aucun journal CAI (type cash) trouvé pour %s - "
            "cash_journal_id laissé vide, ouverture de session de caisse bloquée pour ces "
            "agences tant qu'un manager n'aura pas configuré le journal "
            "(Paramètres > Sociétés > Caisse guichet).",
            ", ".join(missing),
        )
    if not backfilled and not missing:
        _logger.info(
            "Microfinance caisse guichet : toutes les sociétés ont déjà cash_journal_id, "
            "rien à faire.",
        )
