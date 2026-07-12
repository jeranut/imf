# Statut dev — administration
Dernière inspection : 2026-07-11

## Fait
- [x] `post_init_hook` crée les sous-comptes PCEC dédiés (`LOAN_NEW_SUBACCOUNTS`, 29 comptes) puis les 7 journaux (`JOURNALS`) de façon idempotente pour toute société dont `chart_template == 'mg_pcec'` — `microfinance_loan_management/hooks.py:116-125` (`post_init_hook`), `:98-113` (`_create_subaccounts`, `_create_journals`).
- [x] Contraintes de validation opérationnelles sur `microfinance.repayment.frequency` (code unique, `period_value > 0`) — `microfinance_loan_management/models/microfinance_repayment_frequency.py:20-28`.
- [x] Contraintes de validation opérationnelles sur `microfinance.provision.rule` (bornes min/max/taux, non-chevauchement par société) — `microfinance_loan_management/models/microfinance_provision_rule.py:27-48`.
- [x] Cron quotidien de mise à jour des impayés/pénalités actif par défaut — `microfinance_loan_management/data/cron.xml:3-12` (`active` = True sur `ir_cron_microfinance_overdue_penalties`).
- [x] Cloisonnement multi-société non contournable (`ir.rule`, `groups=[]`) opérationnel sur 9 modèles MLM et 3 modèles MSM — `microfinance_loan_management/security/microfinance_company_rules.xml`, `microfinance_savings_management/security/microfinance_company_rules.xml`.

## À faire / incomplet
- [ ] Cron mensuel de comptabilisation des provisions livré inactif par défaut ; nécessite une activation manuelle (Réglages > Technique > Actions planifiées) pour s'exécuter automatiquement — `microfinance_loan_management/data/cron.xml:21` (`active` = False sur `ir_cron_microfinance_post_provisions`).
- [ ] Modèle `microfinance.loan.application` non câblé dans le registre Odoo (absent de `models/__init__.py`, d'`ir.model.access.csv` et de toute vue) ; aucune règle de cloisonnement par société n'est donc définie pour ce modèle — `microfinance_loan_management/security/microfinance_company_rules.xml:23-27` (commentaire signalant l'omission), `microfinance_loan_management/models/__init__.py` (import absent).
- [ ] Aucune tranche de provisionnement n'est préchargée pour les sociétés autres que `base.main_company` ; chaque nouvelle agence doit configurer les siennes manuellement — `microfinance_loan_management/data/provision_rules_data.xml`.

## Incohérences relevées
- Accès du groupe Auditeur microfinance asymétrique entre les deux modèles de configuration transverse : lecture accordée sur `microfinance.repayment.frequency` mais aucun accès sur `microfinance.provision.rule`, alors que ce dernier a un impact comptable plus direct — `microfinance_loan_management/security/ir.model.access.csv:7` (accès accordé) vs absence de ligne `access_microfinance_provision_rule_auditor` (les lignes `:8-10` ne couvrent que user/manager/finance) — impact: faible.
