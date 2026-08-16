# -*- coding: utf-8 -*-
"""Moteur générique de tranches de notation sociale (microfinance.social.score.bracket) :
1) seed des tranches par défaut pour chaque société (post_init_hook ne s'exécute que sur une
   installation neuve, jamais sur un -u d'un module déjà installé, cf. odoo/modules/loading.py
   — précédent déjà documenté dans migrations/17.0.1.5.0/post-migrate.py de ce module) ;
2) migration des dossiers existants ayant une note saisie manuellement avant ce chantier
   (snapshot capturé par pre-migrate.py, AVANT que le passage en champ compute ne l'écrase) :
   assigne le bracket_id dont sequence == ancienne valeur, pour la catégorie/société du
   dossier."""
import logging

from odoo import api, SUPERUSER_ID

from odoo.addons.microfinance_loan_management.hooks import _seed_social_score_brackets

_logger = logging.getLogger(__name__)

# (colonne snapshot, champ bracket_id, catégorie, séquence 0 valide ?)
SCORE_TO_BRACKET = [
    ('assets_score', 'assets_bracket_id', 'assets', False),
    ('activity_score', 'activity_bracket_id', 'activity', False),
    ('health_score', 'health_bracket_id', 'health', False),
    ('income_score', 'income_bracket_id', 'income', False),
    ('housing_state_score', 'housing_state_bracket_id', 'housing_state', True),
    ('housing_surface_score', 'housing_surface_bracket_id', 'housing_surface', False),
    ('education_borrower_score', 'education_borrower_bracket_id', 'education_borrower', True),
    ('education_children_score', 'education_children_bracket_id', 'education_children', False),
]


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    _seed_social_score_brackets(env)

    cr.execute("SELECT to_regclass('_microfinance_migrate_social_scores')")
    if not cr.fetchone()[0]:
        _logger.info("Microfinance : aucune note sociale historique à migrer (table snapshot absente).")
        return

    cr.execute("SELECT * FROM _microfinance_migrate_social_scores")
    rows = cr.dictfetchall()

    Application = env['microfinance.loan.application']
    Bracket = env['microfinance.social.score.bracket']
    report = {score_field: 0 for score_field, _b, _c, _z in SCORE_TO_BRACKET}
    skipped = []

    for row in rows:
        application = Application.browse(row['application_id'])
        if not application.exists():
            continue
        company_id = row['company_id']
        vals = {}
        for score_field, bracket_field, category, zero_valid in SCORE_TO_BRACKET:
            if score_field not in row:
                continue
            old_value = row[score_field]
            if old_value is None:
                continue
            if old_value == 0 and not zero_valid:
                continue  # 0 = "jamais saisi" pour cette catégorie, rien à migrer
            bracket = Bracket.search([
                ('category', '=', category), ('company_id', '=', company_id),
                ('sequence', '=', old_value),
            ], limit=1)
            if bracket:
                vals[bracket_field] = bracket.id
                report[score_field] += 1
        if not vals:
            continue
        try:
            application.write(vals)
        except Exception:
            # Garde-fou montant/tranche (assets_exact_amount, income_net_benefit_amount) qui
            # ne serait plus respecté avec les seuils actuels — ne bloque pas le reste de la
            # migration, à traiter manuellement au cas par cas.
            skipped.append(application.id)
            _logger.warning(
                "Microfinance : migration tranches sociales impossible pour le dossier %s "
                "(contrainte montant/tranche non respectée) — à traiter manuellement.",
                application.id, exc_info=True,
            )

    cr.execute("DROP TABLE IF EXISTS _microfinance_migrate_social_scores")
    _logger.info(
        "Microfinance : migration tranches sociales terminée — dossiers migrés par catégorie : "
        "%s ; dossiers en échec (garde-fou montant/tranche, à traiter manuellement) : %s",
        report, skipped,
    )
