# Statut dev — par_reporting
Dernière inspection : 2026-07-11

## Fait
- [x] Calcul automatique de l'état des échéances (`pending`/`partial`/`paid`/`overdue`) et application quotidienne des pénalités de retard via cron actif — `microfinance_loan_management/models/microfinance_loan_installment.py` (`_compute_state`, `_compute_amounts`), `microfinance_loan_management/data/cron.xml:1-12` (`cron_update_overdue_and_penalties`, `active=True`).
- [x] Répartition du portefeuille par tranches d'ancienneté de retard pour le tableau de bord PAR — `microfinance_loan_management/models/microfinance_loan.py` (`get_par_buckets`).

## À faire / incomplet
- [ ] `microfinance_loan_installment.py` et `microfinance_collection_visit.py` ne définissent aucune contrainte `@api.constrains` ni `UserError`/`ValidationError` : aucun contrôle serveur propre à ces deux modèles (validation de montants, cohérence de dates de visite, etc.) — `microfinance_loan_management/models/microfinance_loan_installment.py`, `microfinance_loan_management/models/microfinance_collection_visit.py` (absence confirmée par recherche des deux motifs sur les deux fichiers).
- [ ] `action_mark_default` (`microfinance_loan_management/models/microfinance_loan.py:440-441`) exécute uniquement `self.write({'state': 'defaulted'})`, sans revérifier l'état `active` côté serveur ; seul le bouton du formulaire est conditionné par `invisible="state != 'active'"` (`microfinance_loan_management/views/microfinance_loan_views.xml:73`) — la contrainte n'existe qu'à l'affichage, pas en écriture directe (ex. via un appel externe au modèle).
- [ ] `microfinance.collection.visit.status` n'est piloté par aucune méthode `action_*` : aucune automatisation (ex. passage à `done` déclenché par un événement) n'existe, la transition reste entièrement manuelle — `microfinance_loan_management/models/microfinance_collection_visit.py` (aucune méthode d'action définie sur ce modèle).

## Incohérences relevées
- Groupe Auditeur (`group_microfinance_auditor`) sans aucune ligne d'accès sur `microfinance.loan.installment` ni sur `microfinance.collection.visit`, alors qu'il est explicitement inclus dans `groups=` de `menu_microfinance_root` (menu visible) : un utilisateur n'ayant que ce groupe ne peut pas ouvrir les vues Échéances/Visites (accès refusé) — impact: moyen. Sources : `microfinance_loan_management/security/ir.model.access.csv` (lignes `installment.*` et `visit.*` : groupes `group_microfinance_user`/`_finance`/`_manager`/`_collection_agent` uniquement, aucune ligne `group_microfinance_auditor`), `microfinance_loan_management/views/microfinance_menus.xml:3`.
