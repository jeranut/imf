# Fonds de crédit rotatifs bailleurs — synchronisation vs Loan Performer (LPF)

Périmètre : `microfinance_loan_management` uniquement. Aucune modification de
`microfinance_savings_management`, `microfinance_mowgli_assistant`, `plan_compta_pcec`,
`res.partner` ni `microfinance.loan.application` (hors-périmètre, voir écart 1 ci-dessous).

## Ce qui a été ajouté

- **Référentiel Bailleurs** (`microfinance.bailleur.fonds`) : fichier de support global, sans
  `company_id`, partagé par toutes les agences (comme "Professions" ou "Périodicités de
  remboursement").
- **Fonds de crédit** (`microfinance.fond.credit`) : code auto-généré (séquence globale
  `FND/%(year)s/`), `scope` (`single_company`/`multi_company`, figé après la première
  sauvegarde ainsi que `company_id`), compte GL (`account_id`, domaine `account_type` — voir
  écart 2), `date_debut`/`date_cloture`, `passer_gl`, `verification_disponibilite`
  (`never`/`at_request`/`at_disbursement`), `solde_disponible` + `total_contributions`/
  `total_decaisse`/`total_rembourse` (champs calculés stockés, agrégation en `sudo()` pour rester
  identique quelle que soit l'agence consultante sur un fonds `multi_company`).
- **Contributions** (`microfinance.fond.contribution`) : dépôts/retraits, mode de paiement,
  `saisie_company_id` (traçabilité de l'agence de saisie, indépendante et toujours renseignée,
  y compris sur un fonds `single_company`), `state` (`draft`/`posted`), comptabilisation optionnelle
  via `_prepare_contribution_move()` + `action_post()` (squelette identique à
  `_prepare_disbursement_move()` du crédit).
- **Rattachement** : `fond_credit_id` sur `microfinance.loan`, domaine limitant aux fonds actifs
  non clôturés de la société courante ou partagés (`multi_company`).
- **Vérification de disponibilité** : `_check_fond_disponibilite()`, méthode réutilisable avec un
  seul point d'ancrage réel (`action_disburse()`, valeur `at_disbursement`). Ordre des contrôles :
  `date_debut` → `date_cloture` → fonds vide → solde insuffisant, messages en français avec
  valeurs réelles interpolées.
- **Sécurité** : `ir.model.access.csv` complété selon le pattern existant ; nouveau fichier
  `security/microfinance_fond_bailleur_rules.xml` avec la règle de partage optionnel
  (`'|', ('company_id', 'in', company_ids), ('company_id', '=', False)`) — première occurrence de
  ce pattern dans le module, documentée en commentaire pour ne pas être signalée à tort comme un
  oubli d'isolation lors d'un futur audit multi-société.
- **Vues/menus** : "Bailleurs de fonds" et "Fonds de crédit" sous Configuration ; "Contributions
  bailleurs" sous Crédits ; rapport "Utilisation des fonds" (liste + pivot) sous Analyse.
- **Tests** : 17 tests automatisés (`tests/test_fond_bailleur.py`), exécutés réellement sur une
  base Odoo jetable (pas seulement écrits/relus). Deux bugs réels détectés et corrigés en cours de
  route :
  - la vue crédit ne se chargeait plus (`ParseError` à l'installation) car le domaine de
    `fond_credit_id` référence `company_id`, restreint par `groups="base.group_multi_company"` —
    corrigé à l'identique du précédent déjà documenté dans `microfinance_loan_product_views.xml` ;
  - la vérification de disponibilité confondait "fonds vide" et "solde insuffisant" car le crédit
    en cours de décaissement (déjà à l'état `approved`) était déjà déduit de son propre solde —
    corrigé via une méthode partagée `_get_principal_outstanding()`.
  - Suite complète du module rejouée (125 tests) : un seul échec,
    `TestFee.test_disburse_nets_fee_in_single_move`, confirmé **pré-existant et sans rapport** avec
    ce chantier (reproduit sur une base neuve, module fraîchement installé, sans aucun fichier de
    ce chantier impliqué dans l'exécution).

## Lot 6 — Tuile dashboard "Fonds bailleurs"

**Audit ciblé préalable** : l'audit du dashboard révèle un écart avec l'hypothèse du prompt — la
section "Vue d'ensemble" comptait **5 tuiles KPI sur une grille à 5 colonnes** (`credits`,
`decaisse`, `encours`, `impayes`, `defaut`), pas 7. La 6ᵉ tuile ajoutée se place donc naturellement
en ligne 2, colonne 1 (CSS Grid gère l'auto-wrap), sans modifier `grid-template-columns`.

**Tuile ajoutée** (`o_microfinance_kpi--fonds`, icône `fa-university`) : libellé "Fonds bailleurs
(N actifs)", valeur = somme de `solde_disponible` de tous les `microfinance.fond.credit` actifs
visibles pour la société courante (fonds `single_company` de cette société + tous les fonds
`multi_company`). Clic → liste des fonds actifs, réutilise le mécanisme générique `openKpiAction`
déjà en place pour les autres tuiles.

**Mécanisme de calcul** : trois nouvelles méthodes `@api.model` sur `microfinance.fond.credit`
(`get_dashboard_kpi`, `get_multi_company_usage_chart`, `get_single_company_chart`), appelées
depuis `MicrofinanceDashboardController.dashboard_data()` — même convention que les méthodes
dashboard existantes (`Loan.get_par_buckets`, `Loan.get_recent_loans`), ce qui les rend testables
directement sans contexte HTTP, comme fait dans `tests/test_fond_bailleur_dashboard.py` (6 tests,
exécutés réellement, aucune régression sur les 131 tests du module hormis l'échec pré-existant
déjà documenté ci-dessus).

- `get_dashboard_kpi(company_id)` : recherche ORM standard (pas de `sudo()`), domaine explicite
  `company_id = company_id OR scope = multi_company`, redondant avec l'`ir.rule` déjà en place
  mais qui rend la méthode testable indépendamment du contexte de session (même convention que
  `get_recent_loans`/`get_par_buckets`).
- `get_multi_company_usage_chart()` : agrège les fonds `multi_company` par agence (contributions
  nettes par `saisie_company_id`, décaissements par `company_id` du crédit). **Bug réel trouvé à
  l'exécution des tests** : `group_microfinance_user` (groupe de base du dashboard) n'a *aucun*
  droit `ir.model.access` sur `microfinance.fond.contribution` (choix volontaire du Lot 1) — sans
  correctif, un simple agent crédit consultant son dashboard aurait obtenu un `AccessError` dès
  qu'un fonds partagé existe. Corrigé par un `sudo()` ciblé sur cette recherche (comme déjà fait
  sur `microfinance.loan` dans la même méthode pour la consolidation inter-agences) : ce `sudo()`
  n'expose que des montants agrégés par agence, jamais les enregistrements individuels.
- `get_single_company_chart(company_id)` : liste chaque fonds `single_company` de l'agence
  (pas d'agrégat unique), filtré par domaine explicite sur `company_id`.

**Compromis de layout** : aucun redesign de la grille KPI (5→6 tuiles gérées par le flow naturel
de CSS Grid). La nouvelle sous-section "Fonds bailleurs" (Analyses) réutilise telle quelle la
grille 2-colonnes existante (`.o_microfinance_dashboard__grid`), insérée après la ligne PAR et
avant le tableau "Crédits les plus en retard" ; le Graphique A ("Utilisation des fonds partagés
par agence") est masqué proprement (`t-if`) s'il n'existe aucun fonds `multi_company` visible ; le
Graphique B ("Fonds propres à l'agence") affiche un état vide texte si l'agence n'a aucun fonds
`single_company`, cohérent avec le pattern déjà utilisé ailleurs sur ce dashboard
("Aucun crédit en retard.").

**Limitation assumée (signalée, pas résolue)** : le Graphique A agrège tous les fonds
`multi_company` confondus, sans ventilation par fonds individuel — si plusieurs fonds partagés
existent un jour, leurs contributions/décaissements sont additionnés ensemble par agence. Une
version future pourrait ajouter un filtre par fonds si le besoin se présente.

**Non testé en navigateur (au moment du Lot 6)** : le clic sur la tuile et le rendu visuel réel des
deux graphiques n'avaient pas été vérifiés dans un navigateur à ce stade — seule la couche de
données avait été testée par des tests automatisés. **Mis à jour au Lot 7** : le clic sur la tuile
"Fonds bailleurs" a depuis été vérifié dans un navigateur réel (Playwright/Chromium headless,
voir Lot 7 ci-dessous) et navigue correctement vers la liste filtrée. Le rendu visuel des deux
graphiques fonds bailleurs eux-mêmes (avec des fonds `multi_company`/`single_company` réels) n'a
en revanche pas encore été exercé en navigateur (la base de test utilisée pour la vérification du
Lot 7 ne contenait aucun fonds), seulement leurs états vides.

## Lot 7 — Panneau latéral de navigation (onglets)

**Audit ciblé** : confirmé que le dashboard est un client action OWL (`MicrofinanceLoanDashboard`,
`static/src/js/microfinance_loan_dashboard.js`), alimenté par une route JSON contrôleur
(`/microfinance/dashboard/data`), avec les graphiques rendus par **ApexCharts** (SVG, pas canvas)
via `new ApexCharts(ref.el, options); chart.render();`. Le point d'attention du prompt est donc
bien réel : un graphique monté dans un conteneur à largeur nulle (masqué) se serait retrouvé
cassé.

**Structure retenue** : exactement les 3 onglets posés en hypothèse, aucune 4ᵉ section
"Fonds bailleurs" séparée — son contenu (tuile + les deux graphiques du Lot 6) reste réparti dans
"Vue d'ensemble" et "Analyses", tel quel. Un seul topic rendu à la fois via `t-if` dans le template
(pas juste masqué en CSS) : les topics inactifs sont réellement retirés du DOM par OWL.

**Stratégie retenue pour les graphiques masqués/affichés : (a) lazy render**, pas de
`resize()`/redraw. Puisque les topics inactifs sont retirés du DOM (pas juste `display:none`), les
refs des graphiques de l'onglet "Analyses" (le seul à contenir des graphiques) sont `null` tant
qu'il n'est pas actif ; `mountChart()` (qui vérifiait déjà `if (!ref.el) return`) les ignore donc
silencieusement sans jamais monter de graphique dans un conteneur cassé. `setActiveTopic()`
redéclenche `shouldRenderCharts = true` à chaque fois que "analyses" redevient actif (même
mécanisme `onPatched` que le chargement initial), et détruit les instances ApexCharts existantes
en quittant cet onglet (sinon elles pointeraient vers des nœuds DOM déjà retirés par le `t-if`).

**Vérifié réellement dans un navigateur** (pas seulement lu/relu) : Odoo lancé sur une base jetable
dédiée (port 8071, distinct de l'instance déjà en service), piloté par Playwright/Chromium headless
(module Python `playwright`, installé pour l'occasion). Résultats observés :
- Au chargement, seul "Vue d'ensemble" est visible (les 6 tuiles KPI, dont la tuile "Fonds
  bailleurs" du Lot 6) ; "Analyses" et "Activité récente" sont bien absents du DOM.
- Clic sur "Analyses" : les 5 graphiques du portefeuille se rendent avec des tailles réelles non
  nulles (ex. 408×300, 632×320 — mesuré via `bounding_box()` sur chaque `<svg>`), pas de graphique
  écrasé à largeur nulle.
- 4 allers-retours rapides "Vue d'ensemble" ↔ "Analyses" : toujours exactement 5 `<svg>` avec les
  mêmes tailles correctes après coup, aucune erreur console capturée.
- Clic sur "Activité récente" : affiche "Derniers prêts"/"Échéances du jour", masque bien les deux
  autres onglets.
- Clic sur le lien "Voir les fonds actifs" de la tuile "Fonds bailleurs" (depuis "Vue d'ensemble") :
  navigue correctement vers la liste `microfinance.fond.credit`, breadcrumb "Dashboard > Fonds de
  crédit actifs" correct, aucune erreur console — confirme que la restructuration en onglets n'a
  cassé aucun lien existant.
- Aucune régression sur la suite de tests Python (131 tests, seul l'échec pré-existant déjà
  documenté persiste) : le Lot 7 ne touche que JS/XML/SCSS, aucun modèle Python modifié.

**Non vérifié en navigateur** : le rendu des deux graphiques fonds bailleurs eux-mêmes avec des
données réelles (base de test vide, sans fonds), et le changement de société active en cours de
session (nécessiterait une configuration multi-société complète dans le navigateur de test) — ce
dernier point repose sur le mécanisme déjà en place (remount du client action + refetch RPC complet
à chaque montage, aucune donnée mise en cache côté client au-delà de `state.data`), inchangé par ce
lot, mais pas exercé "en live" avec un changement de société réel.

**Responsive** : sous 992px (seuil déjà utilisé pour la grille KPI, repris par cohérence), le
panneau latéral se réduit à une colonne d'icônes seules de 56px, libellé accessible via l'attribut
`title` natif du bouton (tooltip navigateur, pas de librairie JS supplémentaire) — non vérifié en
navigateur à cette largeur précise (fait par ajustement CSS raisonné, pas testé visuellement).

## Écarts vs LPF (à confirmer)

1. **`verification_disponibilite='at_request'` sans effet observable.** Son point d'ancrage naturel
   (transition de `microfinance.loan.application` vers un état "soumis") n'existe pas : ce modèle
   est absent de `models/__init__.py` (hors registre Odoo), et sa méthode de transformation
   demande→crédit référence un wizard inexistant. Câbler ce modèle est un chantier séparé,
   identifié deux fois maintenant (audit initial du module + ce travail), hors périmètre ici.
2. **Comptes GL classe 2/3.** Le PCEC Madagascar 2005 ne suit pas la convention
   classe 2 = Dettes / classe 3 = Fonds propres supposée au départ (classe 2 = opérations
   clientèle mixtes actif/passif, classe 3 = comptes divers mixtes ; les vrais fonds propres sont
   en classe 5). Le domaine de `account_id` est donc basé sur `account_type`
   (`liability_current`/`liability_non_current`/`equity`), conformément à la convention déjà
   utilisée dans `microfinance_loan_product.py`, et non sur un préfixe de code.
3. **Rapports consolidés multi-agences.** Le rapport "Utilisation des fonds" agrège au niveau du
   fonds (une ligne par fonds) ; le filtre "période" ne porte donc que sur `date_debut` du fonds,
   pas sur la date des transactions individuelles. Un filtrage transactionnel réel par période
   nécessiterait un pivot dédié sur les contributions/échéances elles-mêmes.
4. **Import Excel "Branch Planning Model" (LPF) non repris** : jugé hors périmètre (non demandé
   explicitement, et hors du périmètre strict `microfinance_loan_management` défini au départ) —
   à confirmer que ce n'est effectivement pas un besoin actuel.
5. **Pas de QWeb PDF** pour le rapport "Utilisation des fonds" dans cette itération (liste + pivot
   seulement), comme spécifié dès le départ.
6. **Résolution du compte GL pour un fonds `multi_company`** : `account_id` reste un Many2one vers
   un compte d'une société précise même quand `scope='multi_company'` ; la question de savoir dans
   quelle société une écriture de contribution doit être postée quand le fonds est partagé entre
   agences n'est pas résolue (voir point de décision 2 ci-dessous).
7. **Pas de contrainte serveur dure** empêchant `microfinance.loan.fond_credit_id` de pointer vers
   un fonds `single_company` d'une autre société via l'API — seul le domaine de la vue (soft) l'en
   empêche dans l'usage normal de l'interface.

## Points de décision explicite laissés à Micka

1. **Option A/B bailleurs partagés** : déjà tranchée en amont (Option B, `multi_company` partagé,
   `ir.rule` avec clause `company_id` vide) — à reconfirmer maintenant que le code est en place et
   testé.
2. **Compte GL d'un fonds `multi_company`** : quand une contribution est saisie depuis l'agence B
   sur un fonds partagé dont `account_id` appartient à l'agence A, dans quelle société l'écriture
   comptable doit-elle être postée ? `action_post()` utilise actuellement tel quel `fond.account_id`
   et le `journal_id` choisi par l'utilisateur, sans validation de cohérence société. Arbitrage
   métier nécessaire avant un usage réel multi-agences avec `passer_gl=True` sur un fonds partagé.
3. **Emplacement des menus** : "Bailleurs de fonds"/"Fonds de crédit" sous Configuration,
   "Contributions bailleurs" sous Crédits, "Utilisation des fonds" sous Analyse — à valider ou
   ajuster.
4. **Tuile dashboard "Fonds bailleurs"** : non ajoutée (aurait sa place dans la section "Vue
   d'ensemble" du dashboard KPI existant) — à confirmer si souhaitée ; toucherait le contrôleur JS
   du dashboard, hors du périmètre initial de ce chantier.
5. **Formule du solde disponible** : calculée sur le principal restant dû uniquement (intérêts et
   pénalités exclus), interprétation retenue comme la plus sûre en l'absence de précision LPF — à
   confirmer que c'est la lecture métier voulue.
6. **Visibilité de `verification_disponibilite='at_request'`** : la valeur reste sélectionnable
   dans l'interface bien qu'elle n'ait aucun effet réel tant que `microfinance.loan.application`
   n'est pas câblé. Faut-il la masquer/désactiver temporairement dans la vue pour éviter une
   fausse impression de contrôle actif, ou la garder telle quelle (docstring + ce document suffisent
   à la documenter) ?
7. **Câblage de `microfinance.loan.application`** : chantier séparé, identifié à deux reprises —
   à prioriser ou non.

## Lot 8 — Fonds obligatoire si actif + verrouillage anti-contournement post-décaissement

**Bug réel signalé (test manuel), corrigé en priorité** : un crédit décaissé avec `fond_credit_id`
renseigné pouvait ensuite se voir vider ce champ via `write()`. Le `solde_disponible` du fonds,
étant un champ calculé à partir des crédits qui le référencent encore, remontait alors
artificiellement comme si le crédit n'avait jamais consommé le fonds — **sans que l'écriture
comptable de décaissement, elle, ne soit annulée** : elle restait posée sur le compte GL de
l'ancien fonds. Incohérence directe entre comptabilité et solde affiché, qui aurait permis de
contourner silencieusement `_check_fond_disponibilite()` (Lot 2) en déchargeant un crédit d'un
fonds a posteriori pour en libérer artificiellement le solde au profit d'un autre décaissement.

**Correctif** : `_check_fond_credit_id_locked_after_disbursement()`, `@api.constrains('fond_credit_id')`
sur `microfinance.loan` — dès que `disbursement_date` est renseigné (couvre `active` et tout état
ultérieur : `closed`, `defaulted`, `written_off`, ce champ n'étant jamais réinitialisé après le
premier décaissement), toute modification de `fond_credit_id` (vidage ou réattribution vers un
autre fonds) lève une `ValidationError`. Contrôle serveur, pas seulement vue — un `write()` direct
via ORM/API/import est bloqué exactement comme depuis le formulaire (même raisonnement que pour
les contrôles déjà en place sur `scope`/`company_id` de `microfinance.fond.credit`, cf.
`TestFondScopeReadonly`). Complété côté vue par `readonly="disbursement_date != False"` sur le
champ (confort UX uniquement, pas la vraie protection).

**Correction complémentaire (oubli, pas sécurité) : `fond_credit_id` obligatoire si un fonds actif
existe.** Avant ce lot, rien n'empêchait de décaisser un crédit sans le rattacher à un fonds
bailleur alors même que l'agence en a un actif — probablement un oubli plutôt qu'un choix, dans une
agence qui n'est pas purement mutualiste. Nouveau champ non stocké `has_active_fond` (calculé sur
`company_id`, mêmes critères que le domaine de `fond_credit_id` : fonds actif non clôturé,
`single_company` de cette société ou `multi_company`) : si vrai et `fond_credit_id` vide,
`_check_fond_disponibilite()` lève une `UserError` avant même de regarder
`verification_disponibilite`. Une agence sans aucun fonds actif (cas mutualiste pur, déjà validé au
Lot 2) continue de décaisser sans rattachement — non-régression volontaire, `has_active_fond` sert
aussi côté vue à rendre `fond_credit_id` visuellement obligatoire (`required="has_active_fond"`)
avant même d'atteindre le blocage serveur.

**Tests** (`tests/test_fond_bailleur.py`, classes `TestFondCreditIdMandatoryIfActiveFond` et
`TestFondCreditIdLockedAfterDisbursement`) : reproduction exacte du bug signalé (décaissement avec
fonds rattaché → `solde_disponible` diminue → tentative d'effacer le fonds après décaissement →
désormais bloquée, `solde_disponible` reste diminué), blocage du vidage et de la réattribution à un
autre fonds après décaissement, non-régression de la modification libre avant décaissement, et les
deux cas société avec/sans fonds actif pour le caractère obligatoire. Suite complète rejouée (186
tests) : seul échec `TestFee.test_disburse_nets_fee_in_single_move`, déjà documenté ci-dessus comme
pré-existant et sans rapport.
