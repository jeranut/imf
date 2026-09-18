# -*- coding: utf-8 -*-
"""caisse_ecart_waiting_account_id (res.company) est scindé en deux champs
(microfinance_account_ecart_caisse_deficit_id / ..._excedent_id). Le champ retiré du modèle
Python sera purement et simplement dropé par l'ORM au chargement du module (comme pour tout
champ supprimé, cf. migrations/17.0.1.3.0/pre-migrate.py pour le même risque de perte
silencieuse) : on snapshote donc sa valeur ici, avant que le nouveau schéma ne soit posé, pour
la reprendre en post-migrate comme valeur du champ deficit (l'usage historique du compte
unique était presque exclusivement le manquant en caisse)."""


def migrate(cr, version):
    cr.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'res_company' AND column_name = 'caisse_ecart_waiting_account_id'
    """)
    if not cr.fetchone():
        return  # champ déjà absent (première installation) : rien à sauvegarder

    cr.execute("DROP TABLE IF EXISTS _microfinance_migrate_caisse_ecart_waiting_account")
    cr.execute("""
        CREATE TABLE _microfinance_migrate_caisse_ecart_waiting_account AS
        SELECT id AS company_id, caisse_ecart_waiting_account_id
        FROM res_company
        WHERE caisse_ecart_waiting_account_id IS NOT NULL
    """)
