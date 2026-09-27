# Audit partage des fonds + faits pour le niveau portefeuille (lecture seule, 2026-09-21)
Chemins relatifs au module. Base MOWGLI lue en SELECT uniquement. Aucun test relancé (0 écriture de code).

## 1. Audit de l'existant
| # | Point | Statut | fichier:ligne | Correctif court |
|---|---|---|---|---|
| 1 | Dépendances `montant_utilise`/`solde_disponible` | OK (état, société, montant, échéances, `loan_ids` inverse de `fond_credit_id`) ; calcul sudo par défaut (compute_sudo) donc crédits d'autres sociétés couverts | models/microfinance_fond_allocation.py:47-59 | — |
| 1b | Crédit `defaulted` sorti de l'utilisé (principal dû, argent non rentré) | ANOMALIE moyen (même définition que le fonds) | allocation.py:53 ; fond_credit.py:226 | Trancher (Q2) |
| 2 | Écriture allocation hors partage | OK : contexte posé seulement en partage.py:221,253 ; aucune vue ne le pose ; ACL sans create/write/unlink (csv:229-232) donc pas de contournement RPC | allocation.py:61-78 | — |
| 3 | Validation/annulation | OK : rejeu → UserError (partage.py:223), cumul :236-244, règle d'annulation :263-264, verrou :166-167, chatter :248,281. ANOMALIE moyen : aucun `FOR UPDATE`, deux validations concurrentes passent | partage.py:219-249 | verrou `SELECT … FOR UPDATE` sur partage + fonds |
| 3b | Validation ne contrôle que le total en % ; couple % / montant incohérent accepté (API) | ANOMALIE moyen | partage.py:211-217,230 ; partage.py:319-353 | contrôler aussi Σ montants ≈ base, dériver l'autre valeur si les deux fournis |
| 4 | Équilibrage | OK : pas de boucle d'onchange, reliquat sur la dernière ligne, plafonds 0-100 %, base = 0, négatif (CHECK SQL partage.py:306-307) | partage.py:84-135,137-151 | — |
| 5 | Fonds multi : défaut `company_id` | ANOMALIE moyen : `create` écrase aussi un `company_id` explicite, la contrainte ne peut plus se déclencher ; test obsolète (échoue) | fond_credit.py:125-127 ; tests/test_fond_bailleur.py:184-186 | n'écraser que si `'company_id' not in vals` (défauts posés dans super) ; mettre à jour le test |
| 6a | **`allocation_required` vrai par défaut même pour un fonds agence unique** → décaissement toujours refusé (« aucune allocation ») ; aucun partage possible (domaine multi seulement). Réel : fonds 138 BBM2 (société 1) | **CRITIQUE** | fond_credit.py:93-94 ; loan.py:2593-2600 ; partage.py:21 | défaut/garde limités à `scope='multi_company'` ; remettre 138 à faux |
| 6b | Contrôle posé seulement à l'activation ; `fond_credit_id` verrouillé seulement après `disbursement_date` ; `action_process_disbursement` ne rejoue rien → changement de fonds entre activation et décaissement sans contrôle | **ÉLEVÉ** | loan.py:2681,2535-2552,2695 | verrouiller `fond_credit_id` dès `active` ou rejouer le contrôle |
| 6c | Retrait de contribution après partage non contrôlé : allocations > fonds réel, `reste_partageable` < 0 | **ÉLEVÉ** | contribution.py:137-149 ; fond_credit.py:251-255 | refuser un retrait > `reste_partageable` |
| 6d | `has_active_fond`, domaine `fond_credit_id`, fonds par défaut : allocation de `loan.company_id` | OK | loan.py:28-40,2515-2533 ; res_company.py:86 | — |
| 6e | Dashboards : KPI/graphes lisent l'allocation ; autres chemins (rapports, wizards, contrôleurs) : aucun | OK | fond_credit.py:293-301,352,443-448 | — |
| 6f | Une agence lit le solde/contributions globaux du fonds partagé (tuile, liste, form) | ANOMALIE moyen (confidentialité/confusion) | views/microfinance_fond_credit_views.xml:18,62,143 | masquer pour non-mère si `allocation_required` |
| 6g | Concurrence : verrou existant sur la ligne crédit seulement, pas sur allocation | ANOMALIE faible (réservation à l'approbation limite le risque) | loan.py:2463,2698 | verrou allocation à l'activation |
| 7 | Sécurité société : agence lit sa seule allocation, fonds partagé, contributions (rules `company_id False`) sans AccessError ; gardes mère : partage/lignes/fonds/contributions/bailleur couverts | OK. ANOMALIE moyen : `microfinance_skip_parent_check` est lisible dans le contexte RPC → garde contournable par un manager ; `unlink` fonds sans exemption legacy (write, lui, exempte) | parent_mixin.py:28 ; fond_credit.py:131-133,146-148 | ignorer la clé hors hooks ; aligner unlink |
| 8 | Données : fonds 1 (AID) et 91 (MFS) agence unique, `allocation_required` NULL, soldes = contributions ; prêt 388 clos inchangé ; 11 allocations = 80 000 000 = partage PFD/2026/00001 | OK (write_date du 20/09 : recalcul stocké probable, non prouvé) | SQL MOWGLI | — |
| 8b | Manifest 1.19.0 mais migrations s'arrêtent à 1.17.0 ; ACL des 3 modèles présents, règles avant CSV | OK/à surveiller : sur une autre base avec mère déjà désignée, défaut de colonne non vérifié | __manifest__.py:4,12-15,37 ; ir.model.access.csv:229-238 | test sur copie avant tout autre déploiement |
| 9 | Tests | `test_fond_partage.py` : 9 classes, ~50 tests (allocation, partage, gardes mère, consommation, dashboard/accès, rééquilibrage). Non couverts : fonds agence unique + mère (6a), changement de fonds après activation (6b), retrait post-partage, double validation, `defaulted`, `company_id` explicite. 5 tests de fonds échouent sur la base de test TEST_BLOCAGE_TMP (dont celui du point 5), cause non investiguée pour les 4 autres | tests/test_fond_partage.py | — |

**Ordre de correction avant portefeuille : 6a (critique) ; 6b, 6c (élevés) ; puis 5, 3, 3b, 1b (moyens).**

## 2. Faits portefeuille
| Élément | modèle.champ | fichier:ligne |
|---|---|---|
| Agent du crédit | `microfinance.loan.officer_id` → **res.users**, non requis, défaut = utilisateur courant, sans domaine ni lien société, modifiable à tout état (absent de `_LOCKED_DOSSIER_FIELDS`) | loan.py:151,438 ; views/microfinance_loan_views.xml:205 |
| « manager_id » du crédit | res.users = celui qui passe en avis_ca, **pas** le manager d'agence | loan.py:152,1576 |
| Client / dossier | aucun champ agent sur res.partner ni loan.application (seulement `agent_id` de visite) | grep models |
| Portefeuille existant | dashboard « Mon portefeuille » (PAR par agent) ; snapshot `officer_id` res.users ; `officer_id` related stocké sur paiement et échéance | loan.py:1013-1023 ; menus.xml:51 ; portfolio_snapshot.py:15 ; loan_payment.py:45 ; loan_installment.py:45 |
| Qui est agent | groupe `group_microfinance_user` (« Agent crédit »), impliqué par manager, finance, caissier, comité… : pas de liste ni de flag ; agence = `res.users.company_ids` ; utilisateur archivé : `officer_id` conservé | groups.xml:8-49 |
| Manager d'agence | groupe `group_microfinance_manager` (+ gestionnaire) ; aucune méthode « manager de la société » ; test `has_group` déjà utilisé | groups.xml:12-16,45-49 ; loan.py:1021 ; caisse_session.py:208 |
| ir.rule crédit | par société uniquement : un agent voit tout le portefeuille de l'agence (restriction par agent = dashboard seulement) | security/microfinance_company_rules.xml:16-21 ; loan.py:1013-1023 |
| Point d'insertion | `_check_fond_disponibilite`, branche allocation, juste après le solde d'allocation ; appelé **à l'activation** (`at_disbursement` ≈ activation) ; lire `loan.officer_id` à ce moment | loan.py:2554,2593-2614,2681 |
| Utilisé par (fonds, agence, agent) | calculable sans donnée nouvelle : mêmes crédits `approved`/`active`, `_get_principal_outstanding`, regroupés par `officer_id` ; sans agent → seau « non attribué » | loan.py:2502-2512 ; allocation.py:53-57 |
| Point d'extension | commentaire posé ; rien ne s'y oppose (compute stocké n'appelle pas `write`) ; à adapter : règle d'annulation du partage | allocation.py:13-14 ; partage.py:263-264 |
| Écran de partage | `line.company_id` requis, domaine `agency_code`, unique(partage, société), mixin « mère », rule sur `partage_id.company_id` | partage.py:292-308,15 ; security/microfinance_fond_bailleur_rules.xml:51-56 |
| À adapter | KPI/graphes fonds, `get_agent_portfolio_kpis`, onglet Allocations ; tests consommation (382-407) et agent dashboard | fond_credit.py:279-303,430-448 ; loan.py:1084 ; fond_credit_views.xml:67-73 |

## 3. Décisions recommandées
- **Modèle** : `microfinance.fond.portefeuille` (allocation_id, officer_id, montant_attribue, montant_utilise, solde_disponible), unique(allocation_id, officer_id), écriture par contexte technique comme l'allocation. Éviter la confusion avec « Mon portefeuille » (PAR) : libellé « Attribution agent ».
- **Écran** : second modèle en-tête/lignes (`microfinance.fond.attribution` + lignes `officer_id`) en extrayant la logique d'équilibrage % ↔ montant dans un mixin abstrait ; base = solde non attribué de l'allocation. Le modèle de partage lui-même n'est pas réutilisable tel quel (colonne société, garde mère).
- **Agent sans portefeuille** : bloqué dès que l'allocation a au moins une attribution ; libre (plafond allocation seul) tant qu'elle n'en a aucune — rétro-compatible.
- **Sécurité** : manager de l'agence crée/valide ; agent lit uniquement la ligne où `officer_id = user` (rule dédiée) ; mère lit tout ; pas d'ACL d'écriture directe.
- **Changement d'agent / de fonds** : `officer_id` verrouillé dès `active` (comme 6b) sauf manager ; réaffectation d'un `approved` contrôlée sur le solde du nouvel agent ; annulation d'attribution refusée si `restant < montant_utilise`.
- **Utilisé** : dépendance `fond_id.loan_ids.officer_id` en plus de celles de l'allocation.

## 4. Plan d'implémentation (chaque étape testable seule)
1. Corriger 6a, 6b, 6c, puis 5, 3, 3b (+ tests). 2. `models/microfinance_fond_portefeuille.py` + ACL + rule (lecture seule). 3. Champ `montant_attribue`/`reste_a_attribuer` sur l'allocation (stocké). 4. Contrôle dans `_check_fond_disponibilite` + verrou `officer_id`. 5. Mixin d'équilibrage extrait du partage (tests existants inchangés). 6. Modèle attribution + vues + menu manager. 7. Règle d'annulation du partage étendue. 8. KPI « Mon portefeuille » par agent + onglet allocation. 9. Tests.

## 5. Questions bloquantes
1. Agent sans attribution alors que l'allocation est distribuée : bloqué ou libre sur le non attribué ?
2. Les crédits `defaulted` comptent-ils dans l'utilisé (allocation et portefeuille) ?
3. Qui est « agent » : tout utilisateur du groupe Agent crédit de l'agence, ou un groupe/flag dédié (caissier, comité exclus) ?
4. Réduire une attribution déjà utilisée : refusé, ou autorisé avec solde négatif ?
5. Le manager d'agence porte-t-il aussi un portefeuille (crédits à son nom) ?
