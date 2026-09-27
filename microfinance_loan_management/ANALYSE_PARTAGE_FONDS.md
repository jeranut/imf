# Analyse : partage des fonds bailleurs par la société mère (v17.0.1.18.0, base MOWGLI)

## 1. Structure actuelle
| Modèle | Champs clés | Disponible | company_id |
|---|---|---|---|
| `microfinance.bailleur.fonds` (models/microfinance_bailleur_fonds.py:5) | partner_id (req.), name (related stocké), code, active. Pas de mail.thread, pas d'état, aucune contrainte SQL | sans objet | **non** : référentiel global, sans ir.rule (rules.xml:3-5) ; create() crée le partner en sudo (:34) |
| `microfinance.fond.credit` (models/microfinance_fond_credit.py:8) | mail.thread ; bailleur_id, code (séquence `FND/%(year)s/`, unique :96), scope single/multi (:24), passer_gl, account_id, verification_disponibilite, date_debut/cloture, active. Pas de champ d'état | `solde_disponible` stocké, compute `_compute_fond_totals` (:179-218) = contributions posted (dépôts − retraits) − principal restant dû des crédits `approved`/`active` (`loan._get_principal_outstanding`, loan.py:2499) ; sudo sur loan_ids (:202) | **oui**, défaut env.company (:32) ; vide si multi_company ; figé après création (write :106-117, constrains :138-148) |
| `microfinance.fond.contribution` (models/microfinance_fond_contribution.py:6) | fond_id, type depot/retrait, amount, journal_id, move_id, state draft/posted | alimente total_contributions | `company_id` related fond (:44) + `saisie_company_id` (:50) |

Droits (ir.model.access.csv:105-115) : bailleur/fond en lecture pour user, finance, auditor ; CRUD pour `group_microfinance_manager` ; contribution sans droit pour user. Groupes (groups.xml:8-48) : manager, finance, gestionnaire (implique manager+finance), tous impliquent user. ir.rule fond/contribution : `company_id in company_ids OR False` (fond_bailleur_rules.xml:16-31). Menus : `menu_microfinance_bailleur_fonds` / `_fond_credit` sous Configuration > Financement (menus.xml:95-96, manager), contributions menus.xml:56, rapport :63.

## 2. Points de consommation (aucun décrément/incrément manuel : tout passe par le compute stocké)
| fichier:ligne | rôle | changement requis |
|---|---|---|
| loan.py:28-36 | `fond_credit_id`, domaine sur scope/company | domaine sur fonds alloués à la société du crédit |
| loan.py:2665 → 2550-2595 | contrôle au décaissement (`at_disbursement`) sur `fond.solde_disponible` global | comparer à l'allocation de `loan.company_id` |
| loan.py:2511-2529 | `has_active_fond` (scope) | idem : allocation active pour la société |
| loan.py:2531-2548 | fond verrouillé après décaissement | inchangé |
| loan.py:572-581, res_company.py:80-96, res_company_views.xml:24 | fonds par défaut de l'agence (domaine scope) | domaine sur fonds alloués |
| fond_credit.py:179-218 | agrégat global (montant utilisé/remboursé/disponible) | ajouter agrégat par allocation (mêmes dépendances) |
| fond_credit.py:241-384, loan.py:803-890 | KPI, graphes, matrice du dashboard (scope/company, sudo) | réécrire sur allocations |
| loan_views.xml:184-196, report/…repayment_schedule_report.xml:126 | affichage `fond_credit_id` | lecture par agence : impose la règle visibilité |
| microfinance_fond_credit_views.xml (tree 15-18, form 59-62, pivot 103-129), menus.xml:63 | totaux et rapport d'utilisation | colonne/onglet allocations |
Société utilisée : celle du crédit (`loan.company_id`) pour le domaine et `has_active_fond`, mais le solde est **global** au fonds (aucune société). Le remboursement libère le principal via `paid_principal` (dépend :181) ; un crédit `closed` n'est plus compté (rotatif).

## 3. Risques de régression
- **Critique** : un fonds appartenant à la mère devient invisible aux agences (rule :16-21 exige company_id ∈ company_ids ou vide) → AccessError sur `fond_credit_id`, rapport échéancier, dashboard.
- **Critique** : sans allocation par agence, une agence peut consommer tout le solde global du fonds (loan.py:2589).
- **Critique** : `scope`/`company_id` immuables (write :106-117) et contrainte scope↔société (:138-148) bloquent tout transfert de propriété par l'ORM.
- **Élevé** : données MOWGLI : 2 fonds propres aux agences (id 91 Ambanidia 100 000 000, id 1 Isotry 10 000 000, même bailleur BFM), 1 seul crédit (388, closed, 500 000, fonds 91), comptes GL `account_id` propres à chaque société ; aucun fonds par défaut configuré ; 0 crédit sans fonds.
- **Élevé** : aucune notion de mère : 11 sociétés plates (`parent_id` vide), `agency_code` obligatoire/unique (res_company.py:23) pour toute société.
- **Élevé** : le partage n'est qu'analytique : les contributions génèrent des écritures dans le journal de `saisie_company_id` (contribution.py:30,119) ; l'allocation n'en crée aucune.
- **Moyen** : tests sur scope (test_fond_bailleur 387 l., _dashboard 252 l., _default_company 93 l.) à adapter ; contrôle de disponibilité sans verrou (concurrence : test_disbursement_concurrent_guard existe).
- **Moyen** : le module n'a pas de dossier `i18n/` (aucun fr.po à maintenir) ; migrations existantes jusqu'à 17.0.1.17.0, manifest en 1.18.0 sans dossier.

## 4. Décisions de conception recommandées
- **Société mère** : Many2one `res.company` dans `res.config.settings` (`config_parameter`, comme `microfinance_product_policy`, res_config_settings.py:8) : global, sans nouvelle table ; `parent_id` natif inutilisable (vide partout, sémantique consolidation).
- **Agences** : toute `res.company` ayant un `agency_code`, mère incluse ; helper `res.company._get_microfinance_parent()` + booléen calculé `is_microfinance_parent`.
- **Contrôle « mère uniquement »** : garde Python (create/write/unlink) sur bailleur, fonds, contribution, partage ; une ir.rule ne peut pas lire un paramètre. Vues : `create/edit` masqués via le booléen calculé. Sans mère configurée : comportement actuel inchangé (non-régression).
- **`microfinance.fond.partage`** : fond_id, date, base_amount, state draft/validated/cancelled, line_ids, mail.thread ; séquence dédiée data/sequence.xml ; à la validation, crée/met à jour les allocations.
- **`microfinance.fond.partage.line`** : partage_id, company_id, percent, amount (compute+inverse bidirectionnel %↔montant, unique(partage, société), somme ≤ base).
- **`microfinance.fond.allocation`** : fond_id, company_id, amount_allocated, montant_utilise, solde_disponible (stockés), unique(fond, société), ir.rule `company_id in company_ids` ; le futur niveau portefeuille se greffe dessous, par `officer_id`.
- **Visibilité fonds** : rule `company_id ∈ company_ids OR False OR allocation_ids.company_id ∈ company_ids`, écriture bloquée côté Python.
- **Migration** : post-migrate 17.0.1.19.0 : une allocation à 100 % pour chaque fonds `single_company` existant, aucune mère imposée (à désigner dans les paramètres). `scope` conservé (legacy).

## 5. Plan d'implémentation (chaque étape testable seule)
1. res_config_settings.py + res_config_settings_views.xml (bloc après :17) + res_company.py : paramètre mère, helper, booléen. Test : lecture/écriture du paramètre.
2. Nouveaux models/microfinance_fond_allocation.py (+ import models/__init__.py après :33) + lignes ir.model.access.csv + rule. Test : unicité, cloisonnement par société.
3. microfinance_fond_partage.py (+ .line), vues, séquence, action, menu dans Financement ; manifest : vues **avant** microfinance_menus.xml. Test : % ↔ montant, somme, validation.
4. microfinance_fond_credit.py : allocation_ids, agrégats par allocation, gardes « mère », rule fonds/contributions (rules.xml:16-31).
5. microfinance_loan.py :28-36, :2511-2529, :2550-2595, :572-581 et res_company.py:82-84 : passer sur l'allocation. Test : décaissement limité à l'allocation de l'agence.
6. Dashboard (fond_credit.py:241-384, loan.py:803-890) et vues fonds/rapport d'utilisation.
7. migrations/17.0.1.19.0/post-migrate.py (idempotent, style des précédentes) + bump manifest.
8. tests/test_fond_partage.py (+ tests/__init__.py) ; adapter test_fond_bailleur*.py, test_fond_default_company.py.

## 6. Ambiguïtés bloquantes
1. Base du partage : le fonds total (dépôts nets, variable) ou un montant saisi et figé par partage ? Un re-partage après validation, avec crédits en cours, est-il permis ?
2. Fonds 91 et 1 (propres aux agences, comptes GL de leur société) : transférés à la mère avec allocation 100 % à l'agence d'origine, ou laissés en legacy ?
3. Qui saisit les contributions (mère seule, journal de la mère) ? L'allocation doit-elle créer une écriture inter-agences ou rester analytique ?
4. Mère : laquelle des 11 sociétés existantes (aucune n'est désignée) ou une société « siège » à créer ? Le code agence est obligatoire pour elle.
