# Statut dev — dashboard_creation_bloquee
Dernière inspection : 2026-10-07

Correctif : aucune création possible depuis les listes/formulaires ouverts par les tuiles et
onglets du tableau de bord Microfinance (le dashboard est une vue de consultation). Périmètre :
uniquement les actions ouvertes depuis le dashboard (`openKpiAction` et équivalents côté
`microfinance_loan_dashboard.js`). Les menus Crédits, Épargne, Fonds, Clients et leurs
"Nouveau" ne changent pas. Pas de modification des vues de base ni d'EAT/MIIA.

## Audit (étape 0)

- Vérifié dans les sources Odoo 17 (`web/static/src/views/utils.js:163 getActiveActions`,
  consommé par `list_arch_parser.js`, `kanban_arch_parser.js`, `form_arch_parser.js`) : le
  bouton "Nouveau" (et `duplicate`, qui dépend de `create`) n'est décidé que par l'attribut
  `create` de l'**arch de la vue** (list/kanban/form). Recherché explicitement
  `context.create`/`no_create` dans `views/` et `webclient/actions/` côté `web` : aucune
  occurrence — **il n'existe aucune clé de contexte d'action qui désactive le bouton Nouveau**.
  Le bouton "Importer" (`base_import/static/src/import_records/import_records.js`) est
  conditionné à `create="true" ET import="true"` sur l'arch : `create="false"` le masque donc
  déjà seul, `import="false"` reste ajouté par cohérence/lisibilité mais est redondant.
  **Conclusion : vues dédiées obligatoires**, confirmant la consigne "dans le doute, vues
  dédiées : c'est le mécanisme fiable" — pas de raccourci par contexte possible.
- Le bouton "Nouveau" d'un formulaire (`form_controller.js` : `canCreate = create &&
  !preventCreate`) dépend uniquement de l'arch de la vue **utilisée pour cet open**, pas du fait
  que l'enregistrement soit ouvert directement par `res_id` (sans liste/pager). Un clic de ligne
  qui ouvre un formulaire générique (create=true) affiche donc "Nouveau" même sans liste
  visible — tous les clics de ligne du dashboard sont bien dans le périmètre (confirmé par
  l'étape 1.4 du correctif).
- Le pattern "vues dédiées `mode=primary`, `create=\"0\"`, héritant des vues génériques, câblées
  par id explicite" existait **déjà** dans le code avant ce lot, pour d'autres raisons : menu
  Crédits (`view_microfinance_loan_tree/kanban/form_credits_menu`, décision Micka 2026-09-27,
  création crédit réservée au smart button `res.partner`) et tuiles épargne du dashboard
  (`view_microfinance_savings_account_tree/form_menu`, déjà annotées "listes ouvertes par les
  tuiles du tableau de bord" dans leur commentaire XML). Ce lot applique le même principe aux
  endroits qui n'en bénéficiaient pas encore.
- Conséquence : certains points du dashboard étaient **déjà protégés**, sans lien avec ce lot —
  vérifié avant de les retoucher (cf. tableau ci-dessous).
- Deux points tranchés avec Micka avant correctif (AskUserQuestion) :
  - Le bouton explicite "Nouveau prêt" (`openNewLoan`, onglet Activité récente) reste **hors
    périmètre** : raccourci de création assumé, analogue à "Nouveau client" du portefeuille.
  - Le correctif couvre **toutes** les occurrences trouvées par l'audit (tuiles + onglets Mon
    portefeuille Mes crédits/visites/fonds), pas seulement les tuiles de la Vue d'ensemble.

## Action du dashboard → vues utilisées → create bloqué ?

| Action du dashboard | Modèle(s) | Vues utilisées **avant** ce lot | Vues utilisées **après** | create bloqué ? |
|---|---|---|---|---|
| `openAllLoans()` ("Voir tous les prêts", onglet Activité récente) | microfinance.loan | `action_microfinance_loan` (menu Crédits), déjà `*_credits_menu` | inchangé | **Oui, déjà** |
| Tuiles épargne (Comptes/Produits/Encours épargne) | microfinance.savings.holder.account, microfinance.savings.account | `*_menu`/holder dédiées | inchangé | **Oui, déjà** |
| Onglet "Mes clients" (ligne cliquée) | res.partner | `action_open_microfinance_client_form` → `view_microfinance_client_form_clients_menu` | inchangé | **Oui, déjà** |
| Tuiles "Crédits actifs" / "En attente de décaissement" / "En défaut" / "Montant accordé" / "Encours décaissé" / "Impayés" (`openKpiTile`) | microfinance.loan | aucune vue transmise → génériques (create=true) | `view_microfinance_loan_tree_credits_menu` + `view_microfinance_loan_form_credits_menu` (réutilisées, pas dupliquées) | **Oui** |
| Tuile "Fonds accessibles à l'agence" | microfinance.fond.credit | génériques (create=true, aucune vue protégée n'existait nulle part) | `view_microfinance_fond_credit_tree_dashboard` / `_form_dashboard` (nouvelles) | **Oui** |
| "Voir les échéances du jour" (`openTodayInstallments`) | microfinance.loan.installment | génériques (create=true) | `view_microfinance_installment_tree_dashboard` / `_form_dashboard` (nouvelles) | **Oui** |
| Onglet "Mes crédits"/"Mes impayés" + tableau agent "Clients du portefeuille"/"Décaissements à venir" (`openLoanRecord`, `openPortfolioTabRow`) | microfinance.loan | formulaire générique (create=true) | `view_microfinance_loan_form_credits_menu` (réutilisée) | **Oui** |
| Onglet "Mes visites" (ligne cliquée, `openPortfolioTabRow`) | microfinance.collection.visit | formulaire générique (create=true) | `view_microfinance_visit_form_dashboard` (nouvelle) | **Oui** |
| Onglet "Fonds de crédit" (ligne cliquée, `openFundsRow`) | microfinance.loan ou microfinance.portfolio.allocation (selon la ligne) | formulaire générique (create=true) | `view_microfinance_loan_form_credits_menu` ou `view_microfinance_portfolio_allocation_form_dashboard` (nouvelle), selon `res_model` de la ligne | **Oui** |
| "Nouveau prêt" (`openNewLoan`, bouton explicite) | microfinance.loan | formulaire générique (create=true) | inchangé | **Non — volontaire**, hors périmètre (décision Micka) |
| "Nouveau client" (`openAgentShortcut('new_client')`, bouton explicite) | res.partner | action dédiée résolue côté serveur | inchangé | **Non — volontaire**, décision D1 antérieure |

## Fait

- [x] **Audit étape 0** : mécanisme `create` vérifié dans les sources `web`, inventaire complet
  des actions ouvertes par le dashboard, repérage des cas déjà protégés (voir tableau
  ci-dessus). Deux points de périmètre soumis à Micka avant correctif (AskUserQuestion) :
  "Nouveau prêt" hors périmètre, correctif étendu à tous les cas trouvés.
- [x] **Vues XML dédiées créées** (toutes `mode="primary"`, héritant de la vue générique
  correspondante, jamais appliquées aux menus) :
  - `views/microfinance_fond_credit_views.xml` : `view_microfinance_fond_credit_tree_dashboard`
    (`create="0" import="0"`), `view_microfinance_fond_credit_form_dashboard`
    (`create="0" duplicate="0"`).
  - `views/microfinance_loan_installment_views.xml` :
    `view_microfinance_installment_tree_dashboard` (`create="0" import="0"`),
    `view_microfinance_installment_form_dashboard` (`create="0" duplicate="0"`).
  - `views/microfinance_collection_visit_views.xml` :
    `view_microfinance_visit_form_dashboard` (`create="0" duplicate="0"`).
  - `views/microfinance_portfolio_views.xml` :
    `view_microfinance_portfolio_allocation_form_dashboard` (`create="0" duplicate="0"`).
  - Aucune nouvelle vue pour `microfinance.loan` : les vues `*_credits_menu` existantes (déjà
    `create="0"`, déjà utilisées par le menu Crédits lui-même) sont réutilisées telles quelles.
- [x] **Serveur** (`models/microfinance_loan.py`) :
  - `_get_overview_tiles()` : les 6 tuiles crédits reçoivent désormais `tile['views']` pointant
    vers `view_microfinance_loan_tree/form_credits_menu` ; la tuile `fund_count` reçoit
    `tile['views']` pointant vers les 2 nouvelles vues dashboard de `microfinance.fond.credit`.
  - `get_dashboard_data()` : `today_installments_link` reçoit une clé `'views'` (nouvelles vues
    dashboard de `microfinance.loan.installment`) ; ajout de la clé `dashboard_form_views`
    (dict `{res_model: view_id}` pour `microfinance.loan`, `microfinance.collection.visit`,
    `microfinance.portfolio.allocation`) — résolue une seule fois par chargement du dashboard,
    consommée côté client pour tout formulaire ouvert directement par clic de ligne.
- [x] **Client** (`static/src/js/microfinance_loan_dashboard.js`) :
  - `_openDomainList()` recevait déjà un paramètre `views` optionnel (utilisé par les tuiles) —
    inchangé, juste mieux alimenté par le serveur.
  - `openTodayInstallments()` transmet désormais `link.views`.
  - nouvelle méthode `_dashboardFormViewId(model)` : lit `state.data.dashboard_form_views[model]`
    avec repli sur `false` (vue par défaut) si le modèle n'est pas dans la table — filet de
    sécurité, pas un cas attendu avec les modèles actuellement ouverts par le dashboard.
  - `openLoanRecord()`, `openPortfolioTabRow()` (branche générique, après le cas `res.partner`
    déjà dédié), `openFundsRow()` : les 3 utilisent désormais
    `views: [[this._dashboardFormViewId(model), "form"]]` au lieu de `[[false, "form"]]`.
- [x] **Domaine et searchpanel inchangés** : aucune des vues dédiées ne touche au domaine
  (toujours celui calculé serveur, identique à la tuile) ni au searchpanel/recherche (la vue
  search n'est pas héritée par ces vues "list/form only").
- [x] **Aucune garde serveur ajoutée** : les modèles concernés restent créables légitimement
  ailleurs (smart button crédit sur `res.partner`, souscription épargne, circuit allocation de
  fonds) ; le blocage est une règle d'interface du dashboard, documentée ici, pas une contrainte
  de modèle.
- [x] **Déploiement sur MOWGLI** : `pg_dump -Fc` avant action
  (`backups/MOWGLI_before_dashboard_create_block_20261007_184936.dump`), `systemctl restart
  odoo17_2`, puis `odoo-bin -u microfinance_loan_management --stop-after-init` (log
  `backups/MOWGLI_update_dashboard_create_block_20261007_185012.log` + `odoo.log` du même
  horodatage) : "Modules loaded" sans erreur ni traceback après le début de la mise à jour,
  `systemctl restart odoo17_2` final, service actif et répondant (`/web/login` → 303).

## À faire / incomplet

- **Tests fonctionnels dans l'UI non faits** (pas de navigateur disponible dans cette session) :
  - Pour chaque tuile/onglet listé dans le tableau ci-dessus : vérifier que le bouton "Nouveau"
    a bien disparu en liste et en formulaire, que le compteur affiché == nombre de lignes de la
    liste ouverte, que le searchpanel est toujours présent.
  - Vérifier qu'aucun doublon n'est possible par "Dupliquer" depuis ces formulaires.
  - Vérifier la non-régression des menus (Crédits, Échéances, Fonds de crédit, Visites de
    recouvrement, Répartition du fonds d'agence) : "Nouveau" toujours présent, inchangé.
  - Vérifier que l'utilisateur ayant les droits d'édition peut toujours modifier un
    enregistrement ouvert depuis le dashboard (seul `create`/`duplicate`/`import` sont
    désactivés, `edit` reste au défaut).
- Pas de test automatisé (`tests/`) ajouté pour ce correctif — purement une restriction de vue
  côté client, difficilement testable en `TransactionCase` sans un test HOOT/tour ; à envisager
  si une régression UI est redoutée à l'avenir.
- `fond_matrix`/`fond_multi_chart`/`fond_single_chart` (graphiques de l'onglet "Fonds bailleurs")
  n'ouvrent aucune liste au clic (confirmé par grep du template XML, aucun `t-on-click` dessus) :
  rien à corriger, pas dans le tableau ci-dessus.
- `my_payments` et `my_installments` (onglets "Mes remboursements"/"Mes échéances") sont déjà
  `clickable: false` dans `TABS` (JS) : aucune ligne n'ouvre de formulaire, rien à corriger.

## Cas laissés tels quels (avec raison)

- **"Nouveau prêt"** (`openNewLoan`) et **"Nouveau client"** (`openAgentShortcut('new_client')`) :
  raccourcis de création explicites et assumés, hors périmètre du correctif (confirmé par Micka).
  Ce ne sont pas des listes "avec bouton Nouveau" mais des boutons de création directe, cohérent
  avec la décision D1 déjà actée pour "Nouveau client".
- **Menus Crédits, Échéances, Fonds de crédit, Visites de recouvrement, Répartition du fonds
  d'agence** : gardent leurs vues génériques (ou déjà dédiées pour Crédits) — aucune vue
  "dashboard" ne leur est câblée, création inchangée partout.
- **`view_microfinance_loan_form_credits_menu`** réutilisée telle quelle (pas de nouvelle vue
  "dashboard" dupliquée pour `microfinance.loan`) : elle était déjà strictement
  create="0"/duplicate="0" pour une autre raison (menu Crédits), ce qui correspond exactement au
  besoin du dashboard — dupliquer l'aurait rendue redondante sans bénéfice.

## Fichiers touchés (résumé)

- `models/microfinance_loan.py` (`_get_overview_tiles`, `get_dashboard_data`)
- `views/microfinance_fond_credit_views.xml`, `views/microfinance_loan_installment_views.xml`,
  `views/microfinance_collection_visit_views.xml`, `views/microfinance_portfolio_views.xml`
  (nouvelles vues `*_dashboard`)
- `static/src/js/microfinance_loan_dashboard.js` (`_dashboardFormViewId`, `openLoanRecord`,
  `openPortfolioTabRow`, `openFundsRow`, `openTodayInstallments`)
- `docs_dev/dashboard_creation_bloquee/STATUS.md` (ce fichier)
