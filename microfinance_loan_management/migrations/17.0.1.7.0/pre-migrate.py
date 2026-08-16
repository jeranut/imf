# -*- coding: utf-8 -*-
"""Snapshot des anciennes notes sociales saisies manuellement (assets_score, activity_score,
etc., encore de simples colonnes Integer à ce stade) AVANT que le passage en champs compute
stockés (dérivés d'un bracket_id, cf. modèle microfinance_loan_application.py) ne les
recalcule et les écrase à 0 pour tous les dossiers existants — le compute s'exécute lors du
rechargement du schéma (registry.init_models), qui a lieu APRÈS ce script pre-migrate mais
AVANT post-migrate.py. Ce script tourne sur l'ancien schéma/ancien code encore en mémoire (pas
d'accès ORM aux nouveaux champs), donc uniquement du SQL brut."""


def migrate(cr, version):
    cr.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'microfinance_loan_application'
          AND column_name IN (
            'assets_score', 'activity_score', 'health_score', 'income_score',
            'housing_state_score', 'housing_surface_score',
            'education_borrower_score', 'education_children_score'
          )
    """)
    existing_columns = sorted(row[0] for row in cr.fetchall())
    if not existing_columns:
        return  # colonnes déjà absentes (première installation) : rien à sauvegarder

    cr.execute("DROP TABLE IF EXISTS _microfinance_migrate_social_scores")
    columns_sql = ', '.join(existing_columns)
    cr.execute(f"""
        CREATE TABLE _microfinance_migrate_social_scores AS
        SELECT id AS application_id, company_id, {columns_sql}
        FROM microfinance_loan_application
    """)
