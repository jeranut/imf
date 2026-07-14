# Statut dev — comptabilite
Dernière inspection : 2026-07-14

## Fait
- [x] Décaissement, frais, remboursement, contre-passation, radiation, provisionnement (manuel via action liste + cron mensuel), comptabilisation des transactions d'épargne — `microfinance_loan_management/models/microfinance_loan.py` (`action_disburse`, `action_charge_fee`, `action_write_off`, `action_confirm_write_off`, `action_post_provisions`), `microfinance_loan_management/models/microfinance_loan_payment.py` (`action_post`, `_reverse_posted_payment`), `microfinance_savings_management/models/microfinance_savings_transaction.py` (`action_post`).
- [x] Génération d'échéancier interest-first (politique CEFOR, taux uniforme uniquement) : la
  cible par tranche (arrondie au plus proche multiple de `installment_rounding_unit`, nouveau
  champ configurable sur `microfinance.loan.product`, défaut 1000 Ar) consomme l'intérêt total du
  crédit en priorité, le principal ne comble que le reste — remplace l'ancienne répartition
  linéaire (montant identique par tranche) — `microfinance_loan_management/models/
  microfinance_loan.py` (`action_generate_schedule`). Détails et écarts vs LPF :
  `microfinance_loan_management/docs/ecarts_lpf_remboursement.md`.
- [x] Ventilation d'un remboursement réordonnée en intérêt → principal → pénalités (politique
  CEFOR, Décision 2), au lieu de l'ordre pénalité → intérêt → principal repris de LPF —
  `microfinance_loan_management/models/microfinance_loan_payment.py`
  (`_allocate_to_installments`). La comptabilisation cash-basis (`_prepare_payment_move`) et le
  mapping de comptes PCEC configurables par produit (principal/intérêt/pénalités,
  `account_type`, pas préfixe de code) existaient déjà avant ce changement et n'ont pas été
  retouchés.
- [x] Action serveur contextuelle « Comptabiliser les provisions » liée à la vue liste de `microfinance.loan`, réservée à Manager/Finance — `microfinance_loan_management/data/provision_server_action.xml` (`action_server_microfinance_post_provisions`, `binding_model_id`/`binding_view_types="list"`).

## À faire / incomplet
- [ ] La valeur `cancelled` de `microfinance.savings.transaction.state` n'est atteinte par aucune méthode `action_*` ni aucun `write()` dans le code actuel (recherche `'cancelled'` limitée à la définition de la sélection) : état mort, jamais accessible depuis l'UI — `microfinance_savings_management/models/microfinance_savings_transaction.py:34` (sélection), pas d'équivalent à `action_cancel` dans ce fichier (seule méthode d'action présente : `action_post`, ligne 135).
- [ ] La tâche planifiée `ir_cron_microfinance_post_provisions` (`cron_post_provisions`, mensuelle) est définie avec `active=False` par défaut : le provisionnement automatique ne s'exécute donc pas tant qu'elle n'est pas activée manuellement — `microfinance_loan_management/data/cron.xml:13-22`.

## Incohérences relevées
- Groupe Comptable (`group_microfinance_comptable`) sans `implied_ids` vers `group_microfinance_user` et absent de la liste `groups=` du menu racine `menu_microfinance_root` : accès technique en lecture (`loan.comptable`, `loan.product.comptable`) mais aucune visibilité menu native pour un utilisateur n'ayant que ce groupe — impact: moyen. Sources : `microfinance_loan_management/security/groups.xml:31-34`, `microfinance_loan_management/views/microfinance_menus.xml:3`, `microfinance_loan_management/security/ir.model.access.csv:71-72`.
- Groupe Auditeur (`group_microfinance_auditor`) explicitement listé dans `groups=` de `menu_microfinance_root` (donc menu visible) mais aucune ligne d'accès sur `microfinance.loan.payment` dans `ir.model.access.csv` : un utilisateur n'ayant que ce groupe voit le menu Remboursements mais l'ouverture de la vue échoue (accès refusé) — impact: moyen. Sources : `microfinance_loan_management/views/microfinance_menus.xml:3`, `microfinance_loan_management/security/ir.model.access.csv` (aucune ligne `*_payment*` avec `group_microfinance_auditor`).
- `microfinance.loan.payment.journal_id` (et les champs comptables équivalents sur `microfinance.loan.product`) n'utilisent nulle part `check_company=True` : le filtre société est un domaine de vue (soft), pas une contrainte serveur — un `write()`/import direct pourrait rattacher un journal/compte d'une autre agence sans être bloqué. Caractéristique uniforme du module (pas spécifique aux remboursements), déjà relevée par ailleurs pour `fond_credit_id` — impact: faible en usage normal (UI), à surveiller si des imports/API externes écrivent sur ces modèles. Sources : `microfinance_loan_management/models/microfinance_loan_payment.py` (`journal_id`), `microfinance_loan_management/docs/ecarts_lpf_remboursement.md`.
