# Statut dev — gestion_utilisateurs
Dernière inspection : 2026-07-11

## Fait
- [x] `res.users` n'est étendu par aucun module Microfinance : aucun champ, bouton `type="object"` ni contrainte `@api.constrains` propres n'y sont ajoutés, la gestion des comptes repose entièrement sur le formulaire standard Odoo — `microfinance_loan_management/models/__init__.py` (aucun import `res_users`), aucune vue héritant de `res.users.form` dans MLM/MSM.
- [x] Hiérarchie des groupes MLM (`implied_ids`) opérationnelle : `group_microfinance_manager`, `group_microfinance_finance`, `group_microfinance_collection_agent`, `group_microfinance_credit_committee`, `group_microfinance_cashier` impliquent `group_microfinance_user` ; `group_microfinance_gestionnaire` implique `group_microfinance_manager` et `group_microfinance_finance` — `microfinance_loan_management/security/groups.xml:12-49`.
- [x] Hiérarchie des groupes MSM opérationnelle : `group_savings_manager` implique `group_savings_agent` — `microfinance_savings_management/security/savings_security.xml:6-11`.
- [x] Menu racine « Microfinance » restreint aux 5 groupes MLM habilités ; menu « Configuration » restreint à `group_microfinance_manager` — `microfinance_loan_management/views/microfinance_menus.xml:3` et `:20`.
- [x] Aucun tableau de bord (`microfinance.dashboard`) n'expose d'indicateur lié à la gestion des utilisateurs ; le dashboard porte uniquement sur le portefeuille de crédit — `microfinance_loan_management/models/microfinance_dashboard.py`.

## À faire / incomplet
Aucune observation à ce jour.

## Incohérences relevées
Aucune observation à ce jour.
