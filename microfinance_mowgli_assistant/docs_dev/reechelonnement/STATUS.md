# Statut dev — reechelonnement
Dernière inspection : 2026-07-11

## Fait
- [x] Bouton `action_reschedule` sur `microfinance.loan` (visible seulement à `state == 'active'`, groupe `group_microfinance_manager`) ouvrant le wizard — `microfinance_loan_management/models/microfinance_loan.py:525`, vue `microfinance_loan_management/views/microfinance_loan_views.xml`
- [x] Wizard `microfinance.loan.reschedule.wizard` (`target: 'new'`, champs `new_term`/`new_first_due_date`/`reason`, bouton `action_apply`) — `microfinance_loan_management/wizard/microfinance_loan_reschedule_wizard.py`, `microfinance_loan_management/wizard/microfinance_loan_reschedule_wizard_views.xml`
- [x] `_reschedule_installments` : snapshot des échéances non payées, recalcul de `remaining_principal`, régénération de l'échéancier, incrément de `reschedule_count`, message chatter — `microfinance_loan_management/models/microfinance_loan.py:540-630`
- [x] Modèle d'historique `microfinance.loan.reschedule.history` / `.history.line` câblé (importé dans `models/__init__.py`, droits déclarés) — `microfinance_loan_management/models/microfinance_loan_reschedule_history.py`, `microfinance_loan_management/security/ir.model.access.csv`
- [x] Cloisonnement multi-société sur l'historique et ses lignes (`ir.rule`, `groups=[]`, appliqué à tous) — `microfinance_loan_management/security/microfinance_company_rules.xml` (records `microfinance_loan_reschedule_history_company_rule`, `microfinance_loan_reschedule_history_line_company_rule`)

## À faire / incomplet
- [ ] Aucun `ir.actions.report` (PDF) lié à `microfinance.loan.reschedule.history` ou au wizard — recherche exhaustive sans résultat dans le module, confirmé absent de `microfinance_loan_management/report/`
- [ ] Aucun indicateur agrégé de rééchelonnement dans le dashboard — `reschedule_count` et `reschedule_history_ids` ne sont exposés qu'au niveau fiche crédit individuelle, absents de `microfinance_loan_management/models/microfinance_dashboard.py`

## Incohérences relevées
Aucune incohérence structurelle relevée pour ce workflow (câblage modèle/vue/droits cohérent de bout en bout).
