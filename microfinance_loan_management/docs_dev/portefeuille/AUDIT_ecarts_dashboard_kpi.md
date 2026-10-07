# Audit — écarts dashboard portefeuille (Mahitsy et transverse)

Base auditée : `MOWGLI` (lecture seule, aucune écriture effectuée). Date du jour système : 2026-10-04.

## 1. Domaines de filtrage recensés

| Méthode (microfinance_loan.py) | Usage | Domaine clé |
|---|---|---|
| `_compute_dashboard` (microfinance_dashboard.py, widget agence générique) | KPI agence simple | `company_id=company`, `state='active'`, `disbursement_date != False` pour l'encours ; `state in (active,closed,defaulted)` pour le décaissé |
| `get_dashboard_data` (onglet « Vue d'ensemble ») | KPI agence complets + graphiques | `company_domain` + `disbursed_only` (`disbursement_date != False`) ; `active_domain`, `defaulted_domain`, `portfolio_domain` (`state in (active,defaulted)` + décaissé) |
| `_agent_portfolio_domain` (onglet **« Mon portefeuille »**, `get_agent_portfolio_kpis`) | KPI par agent (ou agrégés agence si vue manager/auditeur) | `company_id in company_ids`, `state in ('active','defaulted')`, **`disbursement_date != False`**, **`officer_id != False`** |
| `_agent_portfolio_upcoming_domain` (« Décaissements à venir ») | Crédits activés pas encore décaissés | `state='active'`, `disbursement_date = False`, `disbursement_release_ready = False`, `officer_id != False` |
| `_resolve_agent_request` / `_get_agent_portfolio_scope` | Scope serveur (company_ids, officer) | auditeur → `user.company_ids`, `officer=None` ; manager/gestionnaire → `[env.company.id]`, `officer=None` ; agent → `[env.company.id]`, `officer=user.id` |

Le dashboard concerné par le signalement (« dashboard portefeuille », onglet **Mon portefeuille**) est servi par `get_agent_portfolio_kpis` / `_agent_portfolio_domain`.

## 2. Requête SQL — crédits Mahitsy (company_id=6)

```sql
select id, name, state, officer_id, company_id, disbursement_date, balance_total
from microfinance_loan where company_id=6;
```

| id | name | state | officer_id | disbursement_date | balance_total |
|---|---|---|---|---|---|
| 1546 | MS/000001 | active | 394 | **(vide)** | 583 076,92 |
| 1547 | MS/000002 | active | 394 | **(vide)** | 466 461,54 |

Détail décaissement :

| id | activation_date | disbursement_date | disbursement_date_planned | disbursement_date_confirmed | disbursement_release_ready |
|---|---|---|---|---|---|
| 1546 | 2026-10-04 | (vide) | 2026-10-06 | true | **false** |
| 1547 | 2026-10-04 | (vide) | 2026-10-06 | true | **false** |

**Cause exacte pour les 2 crédits** : `disbursement_date` est vide. Les deux dossiers sont `state='active'` (activés) mais **pas encore réellement décaissés** — le décaissement provisoire est planifié au 2026-10-06 et n'a pas encore été libéré au guichet (`disbursement_release_ready=false`). `officer_id=394` est bien renseigné, `company_id=6` est cohérent partout : ce n'est donc ni un agent manquant, ni une incohérence de société.

`_agent_portfolio_domain` exige explicitement `disbursement_date != False` (règle documentée dans le code : un crédit `active` peut ne pas être encore décaissé depuis le découplage activation/décaissement — cf. `docs_dev/guichet_caisse/AUDIT_decaissement.md`). Ces 2 crédits sont donc **exclus par construction** des KPI encours/PAR/nb crédits de « Mon portefeuille », exactement comme prévu par la règle métier actuelle.

Ils remplissent en revanche le domaine de `_agent_portfolio_upcoming_domain` (« Décaissements à venir ») : `state='active'`, `disbursement_date=False`, `disbursement_release_ready=False`, `officer_id=394 != False`. Ils devraient donc apparaître dans ce panneau, pas dans les KPI principaux.

## 3. Comparaison toutes agences (base en l'état)

Seules 3 sociétés ont au moins un crédit `active`/`defaulted` dans la base ; les 8 autres sont à 0 partout.

| Agence | Crédits actifs/défaut (SQL) | ... dont réellement décaissés (`disbursement_date` renseigné) | ... dont en attente de décaissement | ... dont sans `officer_id` | Encours (décaissés) |
|---|---|---|---|---|---|
| CEFOR Mahitsy | 2 | 0 | 2 | 0 | 0 |
| CEFOR Ampitatafika | 1 | 0 | 1 | 0 | 0 |
| CEFOR Andoharanofotsy | 4 | 1 | 3 | 0 | 533 076,92 |
| (8 autres agences) | 0 | 0 | 0 | 0 | 0 |

Détail des 6 crédits « en attente » (toutes agences confondues) :

| id | name | agence | officer_id | disbursement_date_planned | disbursement_release_ready |
|---|---|---|---|---|---|
| 782 | SY/000004 | Ampitatafika | 8 | 2026-10-06 | false |
| 773 | AD/000003 | Andoharanofotsy | 2 | 2026-10-05 | false |
| 774 | AD/000004 | Andoharanofotsy | 2 | 2026-10-05 | false |
| 775 | AD/000005 | Andoharanofotsy | 2 | 2026-10-15 | false |
| 1546 | MS/000001 | Mahitsy | 394 | 2026-10-06 | false |
| 1547 | MS/000002 | Mahitsy | 394 | 2026-10-06 | false |

Toutes les dates planifiées sont **dans le futur** par rapport à aujourd'hui (2026-10-04) : aucun de ces 6 crédits n'est en retard de décaissement, aucun `officer_id` n'est vide, aucune incohérence `company_id` détectée nulle part dans la base.

## 4. Cause racine

**Il n'y a pas de bug de domaine/filtrage dans le code pour ces 2 crédits.** Les 2 crédits Mahitsy (et les 4 autres crédits "orphelins" des autres agences) n'apparaissent pas dans les KPI de « Mon portefeuille » parce qu'ils sont **légitimement pas encore décaissés** (`disbursement_date` vide, décaissement provisoire planifié, pas encore libéré au guichet) — exactement le cas que la règle métier documentée dans le code (découplage activation/décaissement) exclut volontairement des agrégats « encours/PAR/nb crédits actifs », puisque ceux-ci ne doivent compter que les crédits **réellement décaissés**.

Ce n'est donc **pas** un bug transverse de domaine (pas de `officer_id` vide, pas d'incohérence `company_id`, pas de fuite multi-société, pas de `state` hors périmètre) mais un **état de données transitoire attendu** : ces dossiers sont en attente de passage au guichet de décaissement. Le vrai manque constaté est plutôt **ergonomique** : rien dans le tableau de bord n'indique clairement à l'utilisateur « 2 crédits actifs à Mahitsy sont en attente de décaissement, c'est pour ça que l'encours affiché est à 0 » — l'écran « Mon portefeuille » affiche simplement 0 partout sans explication, ce qui est perçu comme une absence/bug.

**→ Point data (pas uniquement code) : avant de corriger quoi que ce soit, confirmer avec l'utilisateur** si :
(a) ces 6 crédits (dont les 2 de Mahitsy) sont bien légitimement en attente de décaissement au guichet (dans ce cas, aucune correction de données n'est nécessaire, seulement une amélioration d'affichage côté dashboard — ex. afficher le panneau « Décaissements à venir » ou un badge « X crédits en attente de décaissement » à côté des KPI) ; ou
(b) ces crédits auraient dû être décaissés et `disbursement_release_ready`/`disbursement_date` est resté bloqué à tort (dans ce cas, c'est un problème de workflow guichet/caisse, hors du dashboard portefeuille, à investiguer dans le module caisse).

Aucune correction de code n'a été appliquée à ce stade (étape 1 = diagnostic seul, lecture uniquement).
