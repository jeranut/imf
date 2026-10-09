# AUDIT — Clients : suppression de la création + filtre « Portefeuille »

Date : 2026-10-07 — Base auditée : **MOWGLI** (lecture seule) — Code : `custom_addons` (branche `main`, `a134741`).
Modules installés : `microfinance_loan_management` 17.0.1.25.0, `microfinance_savings_management` 17.0.1.6.0,
`microfinance_payroll_loan` 17.0.1.0.0, `microfinance_load_test`, `microfinance_data_reset_wizard`,
`microfinance_mowgli_assistant`, `mowgli_payroll_pcec`. `microfinance_transfert_inter_agence` : **non installé**.

Aucune modification de code n'a été faite. Les décisions à trancher sont regroupées en **§ 6**.

---

## a) Action et menu « Clients »

| Élément | xml_id | id MOWGLI |
|---|---|---|
| Menu | `microfinance_loan_management.menu_microfinance_client_list` (parent `menu_clients_root`) | 557 |
| Action | `microfinance_loan_management.action_microfinance_client` | 702 |
| Vue recherche | `microfinance_loan_management.view_microfinance_client_search` | 2959 |
| Extension form | `microfinance_loan_management.view_microfinance_partner_form` (inherit `base.view_partner_form`, mode extension) | 2467 |

Définition : [microfinance_partner_views.xml:314-321](../../microfinance_loan_management/views/microfinance_partner_views.xml#L314-L321)

- `res_model` : `res.partner` — `view_mode` : `tree,form,kanban`
- `domain` : `[('microfinance_partner_type', '=', 'client')]`
- `context` : `{'microfinance_context': True, 'default_microfinance_client_type': 'individual', 'default_microfinance_partner_type': 'client'}`
- `search_view_id` : `view_microfinance_client_search`
- `view_id` : vide, **aucun `view_ids`** (`ir_act_window_view` vide pour 702).

Vues réellement servies (aucune vue dédiée tree/kanban/form n'existe) :

| Type | Vue | Remarque |
|---|---|---|
| tree | `base.view_partner_tree` (id 122, priorité 8) | vue de base |
| kanban | `base.res_partner_kanban_view` (id 128) | vue de base |
| form | `base.view_partner_form` (id 125) + toutes ses extensions, dont `view_microfinance_partner_form` (sections scopées par `context.get('microfinance_context')`) et `microfinance_savings_management.res_partner_views_inherit` | vue de base étendue |
| search | `view_microfinance_client_search` (2959) | **vue autonome** (pas d'`inherit_id`), qui reprend le contenu de `base.view_res_partner_filter` et contient **déjà** un `<searchpanel>` : État civil (`microfinance_marital_status`) et Commune (`microfinance_commune_id`) |

## b) Points d'entrée de création d'un `res.partner`

### b.1 Interface — action Clients
| Entrée | Contexte | Effet |
|---|---|---|
| Bouton « Nouveau » tree/kanban/form | `microfinance_context` | crée un **client** (`default_microfinance_partner_type='client'`) |
| Import (tree/kanban) | `microfinance_context` | idem, en masse |
| Dupliquer (form, `copy()`) | `microfinance_context` | aucun `copy()` surchargé ; `microfinance_account_number` est `copy=False`, mais la CIN est copiée → bloquée par `_check_cin_unique` si renseignée |
| « Nouveau client » du dashboard « Mon portefeuille » | [microfinance_loan_dashboard.js:355-363](../../microfinance_loan_management/static/src/js/microfinance_loan_dashboard.js#L355-L363) | simple `doAction(action_microfinance_client, {viewType: 'form'})` : **même formulaire que le menu Clients**, aucun flag, **aucun rattachement à l'agent** |

### b.2 Many2one vers `res.partner` dans les vues microfinance
Aucune n'a `no_create` / `no_quick_create` / `no_create_edit` aujourd'hui (seul `no_quick_create` existant dans le module porte sur un autre champ, [application_views.xml:283](../../microfinance_loan_management/views/microfinance_loan_application_views.xml#L283)).

| Vue (fichier:ligne) | Champ | `microfinance_context` ? | Type créé si « Créer » |
|---|---|---|---|
| `view_microfinance_partner_form` [partner_views.xml:135](../../microfinance_loan_management/views/microfinance_partner_views.xml#L135) | `microfinance_spouse_id` (conjoint) | **oui** (context du champ) | NULL (Odoo ne propage pas les `default_*` de l'action au Many2one ; vérifié en base : 3 conjoints, tous NULL) |
| idem [partner_views.xml:160](../../microfinance_loan_management/views/microfinance_partner_views.xml#L160) | `microfinance_guarantor_id` (garant) | oui (hérité de l'action) | NULL (10 garants NULL, 1 « client ») |
| `view_microfinance_loan_application_form` [application_views.xml:115](../../microfinance_loan_management/views/microfinance_loan_application_views.xml#L115) | `partner_id` (emprunteur) | non | NULL |
| idem [application_views.xml:235](../../microfinance_loan_management/views/microfinance_loan_application_views.xml#L235) | `guarantor_partner_id` | **oui** | NULL (4 en base) |
| `view_microfinance_loan_form` [loan_views.xml:252](../../microfinance_loan_management/views/microfinance_loan_views.xml#L252) / :277 | `partner_id`, `co_borrower_id` | non | NULL |
| `view_microfinance_guarantee_form` [guarantee_views.xml:31](../../microfinance_loan_management/views/microfinance_loan_guarantee_views.xml#L31) | `guarantor_partner_id` | non | NULL |
| `view_microfinance_loan_account_form` :24 | `partner_id` | non | NULL |
| `view_microfinance_client_blacklist_form` :24 | `partner_id` | non | NULL |
| `view_microfinance_bailleur_fonds_form` :23 | `partner_id` | non | NULL (devrait être `bailleur`) |
| `view_microfinance_savings_account_form` (épargne) :76 | `partner_id` | non | NULL |
| `view_microfinance_payroll_advance_wizard_form` (payroll) :20 | `selected_partner_id` | non | NULL (domaine sur candidats) |
| Arbres (loan, application, payment, installment, account, blacklist, caisse_mouvement, savings_*) | `partner_id` | — | arbres non éditables → pas de création |
| Champs `related` readonly (visit, installment, payment, savings.transaction) | `partner_id` | — | aucune création possible |

Les modèles cibles (`microfinance.loan.partner_id`, `loan.application.partner_id`, `savings.account.partner_id`, `caisse.mouvement.partner_id`) **n'ont aucun domaine** `microfinance_partner_type='client'` : un contact quick-créé depuis ces formulaires (type NULL, hors portefeuille, invisible du menu Clients) peut devenir emprunteur ou titulaire. C'est le vrai trou « clients hors portefeuille », **hors** `microfinance_context`.

### b.3 Créations par code
| Emplacement | Contexte | Type | Impact d'un garde « microfinance_context sans flag » |
|---|---|---|---|
| [res_partner.py:443-470](../../microfinance_loan_management/models/res_partner.py#L443-L470) `create()` (loan_mgmt) | — | — | lieu du garde (contient déjà le blocage inter-agences) |
| `microfinance_savings_management/models/res_partner.py:20` `create()` | — | — | ouvre le conteneur épargne, `super()` |
| `microfinance_payroll_loan` wizard « Avance spéciale » [wizard.py:162-168](../../microfinance_payroll_loan/wizard/microfinance_payroll_advance_wizard.py#L162-L168) | **oui** | client | **bloqué** sans flag |
| idem `_open_partner_prefill_form()` [wizard.py:195-210](../../microfinance_payroll_loan/wizard/microfinance_payroll_advance_wizard.py#L195-L210) (repli si champ obligatoire manquant) | **oui** (formulaire client prérempli, enregistré par l'agent) | client | **bloqué** sans flag ; le formulaire s'ouvre sans `view_id` (form de base), donc les futures vues `create="false"` ne le touchent pas, seul le garde serveur |
| `microfinance_load_test` `_create_fake_partner()` :30 | **oui** | client | **bloqué** sans flag |
| `microfinance_bailleur_fonds.create()` :36 (`sudo()`) | non | bailleur | aucun |
| `hooks.py:240` backfill bailleurs | non | bailleur | aucun |
| `hr.employee` (contact de travail auto) | non | NULL | aucun |
| Controllers | — | — | aucune création de `res.partner` |
| Guichet caisse (JS `search_caisse_clients`, `get_client_accounts_summary`) | — | — | lecture seule |

### b.4 Chemin légitime « Mon portefeuille »
**Il n'existe pas.** Aujourd'hui :
- le bouton « Nouveau client » du dashboard renvoie vers le formulaire de l'action Clients (b.1), sans rattachement à l'agent ;
- `microfinance_loan_management` **n'a aucun champ** reliant un client à un agent/portefeuille ; « Mes clients » est déduit des crédits (`microfinance_loan_ids.officer_id`, [microfinance_loan.py:1448](../../microfinance_loan_management/models/microfinance_loan.py#L1448)) ;
- le **seul** rattachement explicite client → agent est le wizard « Avance spéciale » de `microfinance_payroll_loan` (fiche employé), qui crée ou retrouve le client puis pose `microfinance_officer_id` (jamais réaffecté silencieusement).

➡ Conformément à l'étape 1.3 : **STOP sur le garde serveur** tant que le chemin légitime n'est pas défini (cf. § 6, D1).

## c) Champ client ↔ portefeuille / agent

| Candidat | Modèle / module | Stocké | Index | Remplissage MOWGLI |
|---|---|---|---|---|
| `microfinance_officer_id` (Many2one `res.users`, « Agent crédit (portefeuille) », `tracking`, `copy=False`) | `res.partner` / **`microfinance_payroll_loan`** ([res_partner.py:15](../../microfinance_payroll_loan/models/res_partner.py#L15)) | oui (colonne présente) | **non** (seul `res_partner__company_id_index` existe) | **2 / 36** clients |
| `microfinance_loan_ids.officer_id` | chemin One2many via `microfinance.loan.officer_id` (stocké, indexé) | — | — | 21 clients ont un crédit |
| `microfinance.portfolio` (`agent_id`, `company_id`, unique) | loan_mgmt | — | — | 6 portefeuilles ; **aucun lien vers res.partner** |

Données MOWGLI :
- 36 clients (8 agences) ; 2 avec `microfinance_officer_id` ;
- 20 clients avec crédit mais sans `microfinance_officer_id` ; 14 sans crédit ni agent ;
- 0 client avec des crédits de plusieurs agents ; 0 incohérence entre `microfinance_officer_id` et `loan.officer_id` → un backfill depuis les crédits est **sans ambiguïté** aujourd'hui.

Un « related stocké vers l'agent du portefeuille » n'est **pas possible** : le client n'a pas de `portfolio_id`, il n'y a donc rien à relier. Proposition :
1. **Redéclarer** `microfinance_officer_id` dans `microfinance_loan_management` (même nom, même colonne, `index=True`, libellé « Agent crédit (portefeuille) »). La déclaration de `microfinance_payroll_loan` (qui dépend de loan_mgmt) reste inchangée ; elle ne précise pas `index`, donc l'index est conservé. Aucune donnée déplacée, juste un `CREATE INDEX` à l'update.
2. **Migration post-migrate idempotente** (nouvelle version 17.0.1.26.0) : pour chaque client sans `microfinance_officer_id` dont **tous** les crédits ont un même `officer_id` (même agence que le client), le poser. Dry-run par défaut via `ir.config_parameter` `microfinance_loan_management.backfill_client_officer_dry_run` (absent ⇒ `True`), avec CSV de rapport dans `microfinance_migrations/` comme les migrations épargne. Les clients ambigus ou sans crédit sont listés, jamais devinés.
3. Option : un champ calculé stocké `microfinance_portfolio_id` (Many2one `microfinance.portfolio`, dépend de `microfinance_officer_id` + `company_id`) pour afficher « Agent – Agence » dans le panneau. Ce n'est pas indispensable si le panneau filtre déjà l'agence avant l'agent (cf. D3).

## d) Accès et `ir.rule` sur `res.partner`

En base, sur `res.partner` : uniquement `base.res_partner_rule` (multi-société globale : `partner_share=False` OU `company_id parent_of company_ids` OU sans société) et la règle portail. **Aucune règle microfinance** sur `res.partner`.

Les règles d'isolation par agent ([microfinance_officer_isolation_rules.xml](../../microfinance_loan_management/security/microfinance_officer_isolation_rules.xml), [microfinance_portfolio_rules.xml](../../microfinance_loan_management/security/microfinance_portfolio_rules.xml)) portent sur `microfinance.loan`, `.loan.payment`, `.loan.installment`, `.collection.visit`, `.portfolio`, `.portfolio.allocation.line`.

Conséquences :
- **Un agent voit aujourd'hui tous les clients de son agence** dans le menu Clients (pas seulement les siens).
- Un `<searchpanel>` sur `microfinance_officer_id` afficherait donc à un agent **les noms et compteurs des autres agents de son agence**. Il ne sort pas de l'agence (règle multi-société), mais n'isole pas par agent. Le test demandé « un agent ne voit que son portefeuille » **échouerait** sans nouvelle règle.
- L'auditeur (`group_microfinance_auditor`, groupe autonome, n'implique pas `group_microfinance_user`) voit toutes les agences cochées dans le sélecteur de sociétés : le « cross-agences voit tout » est déjà assuré par la seule règle société.
- Ajouter une règle agent sur `res.partner` est **risqué** (modèle partagé EAT/MIIA, contacts techniques, conjoints, garants, bailleurs, agences) ; il faudrait une règle du type `['|', ('microfinance_partner_type', '!=', 'client'), ('microfinance_officer_id', '=', user.id)]` pour `group_microfinance_user`, plus une règle d'échappement. Or **caissier, comité, enquêteur, CA, CDAG, agent recouvrement impliquent tous `group_microfinance_user`** : sans échappement, ils perdraient la visibilité des clients (guichet, instruction des dossiers). Et les 20 clients sans agent disparaîtraient pour les agents tant que le backfill n'est pas passé. → cf. D2.

## e) Règle inter-agences (à préserver)

Point de vérité unique : `res.partner._check_no_active_loan_elsewhere(cin, company_id)` [res_partner.py:416-441](../../microfinance_loan_management/models/res_partner.py#L416-L441) (`sudo()` limité à la recherche des crédits `active`/`defaulted` des autres agences).
Appelée :
- dans `create()` [res_partner.py:450-456](../../microfinance_loan_management/models/res_partner.py#L450-L456), **avant** `super().create()`, sous `microfinance_context` et `microfinance_id_type == 'cin'` ;
- dans `write()` [res_partner.py:493-503](../../microfinance_loan_management/models/res_partner.py#L493-L503), sur changement de CIN, type ou agence ;
- côté crédit (`microfinance_loan`).
Tests existants : `microfinance_loan_management/tests/test_client_blocage_inter_agences.py`. Doc : `docs_dev/blocage_client_inter_agence/`.

Le futur garde doit se placer **avant** ce contrôle dans la boucle `vals_list` de `create()` (même méthode), sans toucher à `_check_no_active_loan_elsewhere`.

---

## 6. Décisions à trancher avant l'étape 1

**D1. Chemin légitime de création (bloquant pour le garde serveur).** Options :
- **(A, recommandée)** « Nouveau client » de « Mon portefeuille » devient une vraie création : bouton JS → méthode serveur (ou action dédiée) qui ouvre le formulaire client avec `allow_microfinance_partner_create=True` et `default_microfinance_officer_id=<agent du portefeuille résolu côté serveur>` (jamais l'id envoyé par le client), masqué en lecture seule (déjà le cas via `readOnly`). Le wizard « Avance spéciale » passe aussi le flag (création directe + formulaire prérempli). Cela touche `microfinance_payroll_loan` : il faut confirmer que ce module compte comme « nôtre » et peut être modifié.
- (B) Garde serveur reporté ; seulement les verrous UI.

**D2. Isolement par agent dans le menu Clients.**
- **(A, recommandée pour ce lot)** Pas de nouvelle règle `res.partner` : le panneau montre les portefeuilles de l'agence (comme la liste aujourd'hui). Le test devient « un agent ne voit aucun portefeuille d'une autre agence ».
- (B) Nouvelle règle agent sur `res.partner` + échappements (manager, gestionnaire, finance, caissier, comité, enquêteur, CA, CDAG, recouvrement à arbitrer), backfill obligatoire avant. Chantier séparé recommandé.

**D3. Champ du panneau.** `microfinance_officer_id` redéclaré et indexé dans loan_mgmt + backfill depuis les crédits (§ c), ou en plus `microfinance_portfolio_id` calculé stocké. Note : un panneau Many2one en `select="one"` n'affiche pas d'entrée « Non attribué » ; les 14 clients sans agent ne seront visibles que via « Tout ». Faut-il un filtre « Sans portefeuille » ?

**D4. Portée du garde.** Proposé : ne bloquer que les créations qui produisent un **client** (`microfinance_partner_type` = `'client'` dans `vals` ou dans `default_microfinance_partner_type` du contexte) sous `microfinance_context`, et non toute création sous ce contexte. Sinon la création d'un conjoint ou d'un garant depuis la fiche client ou le dossier (types NULL, `microfinance_context` présent) serait bloquée. Confirmer si conjoints et garants doivent rester créables à la volée, ou être eux aussi verrouillés (`no_create` les empêche de toute façon côté UI si l'étape 1.2 s'applique à tous les Many2one).

**D5. Trou hors contexte.** Les formulaires crédit, dossier, épargne, garantie, compte crédit et liste noire créent des contacts **sans** `microfinance_context` : le garde serveur ne les voit pas, seul `no_create` (étape 1.2) les ferme. Faut-il ajouter un domaine `microfinance_partner_type = 'client'` sur `partner_id` emprunteur/titulaire (dossier, crédit, compte épargne, compte crédit) ? Recommandé, mais hors périmètre strict du prompt.

**D6. `microfinance_load_test`.** Son wizard crée des clients sous `microfinance_context` : lui passer le flag (modification d'un autre module), ou accepter qu'il casse ?

**D7. Search view.** Le prompt demande une search `mode="primary"` héritant de `base.view_res_partner_filter`. Elle existe déjà sous forme de vue **autonome** avec un panneau (État civil, Commune). Recommandé : **ajouter** Agence + Portefeuille au `<searchpanel>` existant de `view_microfinance_client_search` (même `search_view_id`, aucune vue de base touchée), plutôt que d'en créer une deuxième qui dupliquerait ou perdrait État civil/Commune. Ordre proposé : Agence, Portefeuille, État civil, Commune.

## 7. Écarts entre le prompt et le code réel

1. « Vues dédiées inherit_id sur **nos vues clients actuelles** » : il n'existe **aucune** vue tree/kanban client propre au module ; l'action utilise `base.view_partner_tree` / `base.res_partner_kanban_view`, et la form est une **extension** (pas primary) de `base.view_partner_form`. Les nouvelles vues seront donc des `mode="primary"` héritant des vues **de base** (sans les modifier), branchées par `view_ids`. Même patron que `view_microfinance_loan_tree_credits_menu`.
2. Search view : déjà dédiée et autonome, avec un searchpanel (cf. D7).
3. Le lien client ↔ agent n'existe pas dans `microfinance_loan_management` ; le seul champ (`microfinance_officer_id`) appartient à `microfinance_payroll_loan`, n'est pas indexé et n'est rempli que pour 2 clients sur 36. Pas de « related stocké » possible (cf. § c).
4. Le chemin légitime « Mon portefeuille » n'existe pas : le bouton redirige vers le formulaire générique (cf. b.4, D1).
5. Pas de règle d'isolement agent sur `res.partner` : le test « un agent ne voit que son portefeuille » est incompatible avec l'existant sans D2-B.
6. « Avance spéciale hr.employee » : c'est le wizard de `microfinance_payroll_loan`, et il **crée** des clients sous `microfinance_context` (direct + formulaire prérempli). Le garde le casserait sans flag.
7. « rotas » dans la commande de mise à jour : aucune base ni instance de ce nom sur ce serveur (bases : MOWGLI, MOWGLI_fondtest, EATDATA…, service `odoo17_2`). À préciser.
8. `microfinance_transfert_inter_agence` n'est pas installé sur MOWGLI : il est hors périmètre de ce lot.
