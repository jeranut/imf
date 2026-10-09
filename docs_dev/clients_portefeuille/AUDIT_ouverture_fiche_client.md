# AUDIT — Ouverture de la fiche client (res.partner) depuis microfinance_*

Date : 2026-10-07. Code : `custom_addons` (diff du lot « clients portefeuille » non commité, inclus).

## Cause du symptôme (confirmée)
Mon portefeuille > Mes clients > clic : `openPortfolioTabRow` ([microfinance_loan_dashboard.js:554](../../microfinance_loan_management/static/src/js/microfinance_loan_dashboard.js#L554)), surchargée par le patch payroll ([microfinance_loan_dashboard_patch.js:27](../../microfinance_payroll_loan/static/src/js/microfinance_loan_dashboard_patch.js#L27)), fait un `doAction` avec `views: [[false, 'form']]` et `context: tab.context || {}`.
- L'onglet `my_clients` n'a pas de `context` : la fiche s'ouvre **sans** `microfinance_context`, donc les sections microfinance sont masquées et les onglets natifs visibles. La vue est celle par défaut (`base.view_partner_form`), avec Nouveau et Dupliquer.
- L'onglet `clients_a_traiter` passe `microfinance_context` : les sections sont visibles, mais la vue reste celle par défaut, avec Nouveau et Dupliquer.

## Points d'ouverture d'une fiche res.partner

| # | Point | Contexte passé | view_id | Domaine | Statut |
|---|---|---|---|---|---|
| 1 | Dashboard, onglet « Mes clients » (`openPortfolioTabRow`) | aucun | défaut (base) | — | **à corriger** |
| 2 | Dashboard, onglet « Clients à traiter » (patch payroll) | `microfinance_context` | défaut (base) | — | **à corriger** |
| 3 | Dashboard, « Nouveau client » (`get_portfolio_new_client_action`) | complet + flag | form verrouillée | — | déjà correct (lot précédent) |
| 4 | Wizard Avance spéciale, retour de `action_validate()` ([wizard.py:186-193](../../microfinance_payroll_loan/wizard/microfinance_payroll_advance_wizard.py#L186-L193)) | aucun | défaut (base) | — | **à corriger** (même symptôme) |
| 5 | Wizard Avance spéciale, `_open_partner_prefill_form()` (nouvelle fiche) | `microfinance_context` + flag + defaults | défaut (base) | — | **à corriger** : la form de base affiche « Nouveau », qui crée un **autre** client avec le flag encore en contexte (contournement du garde) |
| 6 | Menu Clients (`action_microfinance_client`) | `microfinance_context` | form verrouillée (`view_ids`) | clients | correct |
| 7 | Clic sur un Many2one partner (`Many2OneField.openAction` → `res.partner.get_formview_action`) | contexte du champ : clés non-`default_*` du contexte de l'enregistrement + `context=` du champ | `get_formview_id()` = form par défaut | — | **à corriger** : sur les vues crédit, dossier, épargne, garantie, compte crédit, échéance, remboursement, visite et liste noire, aucun `microfinance_context` → fiche native |
| 8 | Smart buttons de la fiche client (Crédit, Compte crédit, Épargne) | `default_partner_id` | — | — | n'ouvrent pas de res.partner |
| 9 | Guichet caisse (JS `search_caisse_clients`, `get_client_accounts_summary`) | — | — | — | lecture seule, n'ouvre pas de fiche |
| 10 | Transfert inter-agences (JS, `searchRead` coursiers) | — | — | — | lecture seule ; module non installé |
| 11 | Onglet Fonds, lignes (`openFundsRow`) | — | — | — | ouvre crédit/allocation, jamais res.partner |
| 12 | Tuiles KPI, listes du dashboard | — | — | — | ouvrent crédits/échéances/fonds |

Aucun bouton XML `name="%(…)d"` ne cible une action res.partner hors du menu Clients. Aucun tableau de bord épargne n'a de JS propre.

## Correctif retenu
- `res.partner.action_open_microfinance_client_form()` : vérifie l'accès en lecture, puis ouvre la form verrouillée du menu Clients avec `microfinance_context` + `default_microfinance_partner_type='client'`, **sans** le flag de création.
- Points 1 et 2 : `openPortfolioTabRow` appelle cette méthode pour les onglets res.partner ; la surcharge du patch payroll est supprimée (elle ne servait qu'à passer le contexte).
- Point 4 : le wizard renvoie cette méthode.
- Point 5 : la fiche préremplie s'ouvre sur la form verrouillée (pas de « Nouveau »), en gardant le flag puisque c'est une création légitime.
- Point 7 : `context="{'microfinance_context': True}"` sur les Many2one partner des vues microfinance, et surcharge de `res.partner.get_formview_action()` : sous `microfinance_context` et pour un client, elle renvoie l'action ci-dessus. On obtient la bonne vue, et le flag de création éventuellement hérité du contexte de l'enregistrement est retiré.
- Hors `microfinance_context` (Contacts, Discuss, EAT/MIIA) : rien ne change, `get_formview_action` reste le standard.

## Écart avec le prompt
« Sans context, les champs CIN/état civil/conjoint sont absents de get_view » : c'est faux en Odoo 17. `get_view` renvoie toujours ces champs ; leur masquage est évalué côté client (`invisible="not context.get('microfinance_context')"`). Le test vérifie donc que ces champs portent bien cette condition, et que hors contexte `get_formview_action` renvoie la form standard.
