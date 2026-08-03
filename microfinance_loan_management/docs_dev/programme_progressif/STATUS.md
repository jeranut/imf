# Statut dev — programme_progressif
Dernière inspection : 2026-07-21

## Correctif : ligne de total Montant mensuel non calculée ("—"), 2026-07-21

### Cause précise
Confirmé dans le code source du renderer Odoo (`list_renderer.js:726`) : un champ `Monetary`
ne peut afficher son agrégat (`sum=`) que si son champ de devise (`currency_id` par défaut)
fait partie des champs chargés par CE tableau embarqué précis — sinon Odoo affiche "—" ("No
currency provided") au lieu de calculer la somme. Les 6 tableaux de la Section V n'avaient
jamais ce champ dans leur `<tree>` (même invisible). Corrigé : `<field name="currency_id"
column_invisible="1"/>` ajouté aux 6 tableaux.

Point volontaire, pas un oubli : la colonne "Montant" (brut, avant conversion mensuelle) n'a
délibérément pas de `sum=` — additionner des montants saisis à des fréquences différentes
(quotidien, hebdomadaire, mensuel) donnerait un total sans signification. Seule "Montant
mensuel" (déjà normalisé) est sommée.

### Point relevé en vérifiant (sans rapport avec ce correctif)
La valeur "5 000 / Quotidien" visible sur la capture d'écran de Micka pour "Bénéfices autre
activité" n'était pas présente en base (`write_date` = date de création, jamais modifiée
depuis) — cohérent avec une saisie faite dans le formulaire mais pas encore enregistrée
(bouton Sauvegarder), pas une perte de données côté serveur.

## Correctif définitif Section V : champs dédiés par tableau + fiabilisation du nettoyage, 2026-07-21

### Cause réelle des tableaux non éditables (Symptôme 2, non résolu jusqu'ici)
Comparaison avec `document_line_ids` (Section III, qui fonctionne) : la vraie différence
structurelle n'était pas un `readonly` — c'était le fait qu'`income_line_ids` (un seul champ
`One2many`) était **réutilisé 6 fois** dans la même vue avec un `domain`/`context` différent à
chaque occurrence, alors que `document_line_ids` est un champ à usage unique. **Corrigé** en
créant 6 champs `One2many` dédiés sur `microfinance.loan.application`
(`income_line_family_income_current_ids`, etc.), chacun avec son `domain` intégré **dans la
définition Python du champ** (pas seulement dans la vue) — même méthodologie exacte que
`document_line_ids`. `income_line_ids` (sans domaine) reste l'unique source de vérité pour les
calculs de totaux et le pré-remplissage ; les 6 nouveaux champs ne sont que des vues filtrées
de la même table, jamais une duplication de données.

### Fiabilisation de `_cleanup_existing_financial_lines`
En ajoutant un test de bout en bout pour cette fonction (déjà présente mais pas totalement
fiable), un bug de départage a été détecté : `_financial_line_keep_key` utilisait `-line.id`
comme dernier critère de départage entre deux lignes en doublon — au sein d'une même
transaction, `write_date`/`create_date` peuvent être strictement identiques (valeur mise en
cache par le curseur), auquel cas ce critère décidait, et `-line.id` favorisait à tort la ligne
la **plus ancienne** plutôt que la plus récente. Corrigé (`line.id`, sans le signe négatif).

### Recomptage réel effectué sur SEFOR (IS/000003)
Contrairement à un state signalé "propre" à tort dans un prompt précédent, un recomptage
précis catégorie × situation a révélé un vrai écart (`family_expense`/`current` à 13 lignes au
lieu de 21, puis plus tard `family_income`/`current` à 6 au lieu de 7) — corrigés au fil de
l'eau. `_cleanup_existing_financial_lines` exécutée manuellement (le hook post_init ne
s'exécute qu'à l'installation initiale, cf. correctifs précédents) : état final vérifié par
SQL direct, indépendant de tout cache ORM : **7/7/21/21/7/7 = 70, stable après upgrade complet
+ suite de tests (14/14)**.

## Correctif : nettoyage réel des lignes financières (IS/000003), 2026-07-20

### Ce qui a été trouvé, précisément, en recomptant chaque tableau/situation
Contrairement à la conclusion du prompt précédent ("70 lignes, déjà propre"), un recomptage
précis par catégorie ET situation a révélé un **vrai écart**, mais dans le sens inverse de ce
qui était supposé : **aucun doublon nulle part** (vérifié par désignation, 0 partout), mais
`family_expense`/`current` n'avait que **13 lignes au lieu de 21** (8 désignations sans ligne
créée — "Sigara (cigarettes)" à "Participation familiale" dans l'ordre du catalogue). Total
réel avant correctif : 62 lignes (7+7+13+21+7+7), pas 70.

**Point méthodologique important, à retenir pour la suite** : `with registry.cursor() as cr:`
en shell Odoo **commit automatiquement à la sortie du bloc si aucune exception ne survient**
(cf. `odoo/sql_db.py`, `TestCursor.__exit__`/`Cursor.__exit__` : `if exc_type is None:
self.commit()`) — un `cr.rollback()` explicite est nécessaire pour un script de vérification
non destructif, sinon toute modification (y compris des recalculs de champs `store=True`
déclenchés par une simple lecture) est committée pour de vrai. Explique vraisemblablement
l'écart entre les comptages successifs au fil des prompts précédents.

### Correctif appliqué
Rappel de `_ensure_default_financial_lines()` (idempotente, n'ajoute que ce qui manque) sur
IS/000003 : `family_expense`/`current` passé de 13 à 21 lignes. État final vérifié par SQL
direct (indépendant de tout cache ORM) : 7/7/21/21/7/7 par catégorie/situation, 70 au total,
0 ligne sans désignation, 0 doublon — stable après un upgrade complet du module + suite de
tests.

### Symptôme 2 (Montant/Fréquence non éditables)
Toujours aucune cause trouvée dans le code. Test ORM de bout en bout : écriture réelle sur
`amount`/`frequency_id` réussie, `monthly_amount` recalculé correctement (12345 × 4 = 49380).
Ceci confirme l'absence de blocage côté modèle, mais **ne remplace pas un test au clic réel
dans le navigateur** (hors de portée sans outil de navigateur) — à confirmer par Micka
directement sur le tableau "Dépenses d'activité" maintenant propre (7 lignes nommées).

## Correctif : retrait du hook read() (duplication) + audit champs non éditables, 2026-07-20

### Symptôme 1 — duplication massive des lignes par défaut
Le hook `read()` introduit au prompt précédent (pour pré-remplir les dossiers existants sans
lignes) était un **anti-pattern confirmé** : une lecture peut être appelée plusieurs fois/en
parallèle par le client web (un appel par bloc `<field domain="...">` imbriqué, notamment) —
une écriture déclenchée dessus n'est pas protégée contre cette concurrence. Constaté en usage
réel par Micka : jusqu'à 70 lignes pour un catalogue de 7 désignations, dont une majorité sans
`designation_id` assigné. **Retiré entièrement.** `_ensure_default_financial_lines()` n'est
plus appelée qu'à `create()` — les dossiers créés avant ce mécanisme doivent être corrigés au
cas par cas (script one-shot), jamais via un hook de lecture.

**État constaté sur SEFOR au moment de l'audit** : la base était en réalité déjà propre (70
lignes exactement, 7/7/21/21/7/7 par catégorie/situation, aucune ligne sans désignation) —
aucun nettoyage de données n'a donc été nécessaire sur ce dossier précis ; le problème avait
dû se produire dans un état/session distinct de celui audité. Vérifié après correctif : 5
lectures répétées du même dossier ne changent plus le nombre de lignes (70 → 70).

### Symptôme 2 — Montant/Fréquence non éditables
Audit exhaustif (modèle + vue) : **aucun `readonly` trouvé** sur `amount`/`frequency_id`, ni
dans la définition Python, ni dans le XML, ni sur un conteneur englobant — les 6 tableaux sont
bien tous `editable="bottom"`, droits d'écriture corrects. Aucune cause identifiée dans le
code ; probablement une conséquence de la confusion causée par la duplication massive du
Symptôme 1 au moment du constat. À revérifier par Micka maintenant que ce dernier est corrigé.

## Correctif Section V — pré-remplissage à l'ouverture + confirmation ligne de total, 2026-07-20

### Problème 1 — lignes par défaut absentes sur les dossiers existants
`_ensure_default_financial_lines()` existait déjà et fonctionnait, mais n'était appelée qu'à
la création du dossier (`create()`). Sans wizard "Modifier" (architecture abandonnée), aucun
déclencheur "à l'ouverture de la section" ne subsistait — les dossiers créés avant
l'introduction du mécanisme (ex. IS/000003, confirmé à 0 ligne) restaient vides pour toujours.

**Correctif** : surcharge de `read()` sur `microfinance.loan.application`, qui rappelle
`_ensure_default_financial_lines()` **uniquement quand `income_line_ids` est effectivement
demandé** dans les champs lus (`web_read` appelle `read()` en interne, confirmé dans le code
source du module `web`) — jamais d'effet de bord sur une lecture qui ne s'y intéresse pas
(liste, `name_get`). Vérifié sur IS/000003 : 0 → 70 lignes après lecture avec
`income_line_ids` dans les champs demandés (7+7+21 désignations × 2 situations), 0 → 0 sur
une lecture sans ce champ.

**Point relevé, non traité (hors périmètre de ce prompt)** : le même problème affecte en
théorie `_ensure_default_document_lines()` (Section III) — même cause (plus de wizard-open
depuis l'abandon de l'architecture wizard). Non corrigé ici, seul le Problème 1 sur la
Section V était demandé ; à traiter séparément si Micka constate le même symptôme sur les
documents administratifs d'un dossier existant.

### Problème 2 — ligne de total
Déjà en place depuis le chantier de refonte de la Section V (`sum="Total"`/`"Sous-total"`
sur `monthly_amount` dans les 6 tableaux) — l'absence de ligne de total observée par Micka
était en réalité une conséquence du Problème 1 (tableaux vides, donc rien à sommer), pas un
oubli séparé. Résolu automatiquement par le correctif du Problème 1.

### Vérification
2 nouveaux tests (`test_prefill_triggered_on_read_for_preexisting_application_without_lines`,
`test_read_without_income_line_ids_does_not_create_lines`) + 22 tests de régression
pertinents, 0 échec.

## Refonte complète Section V (Analyse financière et capacité de remboursement), 2026-07-20

### Décision
La section V est refondue pour coller à la fiche papier CEFOR : 3 tableaux distincts par
situation (Revenus familiaux / Dépenses d'activité / Dépenses familiales), désignations
configurables (plus de libellé texte libre), montant mensuel **calculé** (plus saisi
directement), majoration appliquée **uniquement** aux dépenses familiales, bloc
"Accroissement du revenu", capacité de remboursement mensuelle **et** hebdomadaire.

### Points vérifiés avant de coder (audit + confirmation Micka)
- **Bug confirmé et corrigé** : le diviseur hebdomadaire était `52/12 ≈ 4,333`, pas `÷4`.
  Vérifié sur l'exemple papier (`213890 / 4 = 53472,5` exact, `/4,333` donnait un résultat
  faux) — corrigé vers `÷4` exactement.
- **Multiplicateurs Montant → Montant mensuel** : rendus **configurables** (pas figés en
  dur dans le code) via un nouveau modèle `microfinance.financial.frequency` (nom +
  multiplicateur), sur le même principe que "Périodicités de remboursement" déjà en
  Configuration — Micka peut ajouter/modifier librement les multiplicateurs (30, 4, 1, 2,
  5... whatever) sans intervention développeur. Valeurs de départ : Quotidien ×30,
  Hebdomadaire ×4, Mensuel ×1.
- **Majoration (+X%)** : confirmé qu'elle ne s'applique qu'au sous-total des dépenses
  familiales, jamais aux dépenses d'activité — les champs existants
  `safety_margin_current`/`safety_margin_forecast` gardés tels quels (5%/10% par défaut),
  mais appliqués désormais à des lignes prévisionnelles réellement saisies (plus de
  dérivation "prévisionnel = actuel × marge", cf. ci-dessous).
- **manuel.pdf/client.md** cités dans la demande initiale : introuvables dans ce dépôt,
  aucun barème LPF officiel à confronter — validation faite directement avec Micka.

### Modèles créés (Lot 1, Configuration > Financement)
- `microfinance.financial.designation.income` (7 valeurs par défaut)
- `microfinance.financial.designation.activity.expense` (7 valeurs par défaut)
- `microfinance.financial.designation.family.expense` (21 valeurs par défaut)
- `microfinance.financial.frequency` (nom + multiplicateur, 3 valeurs par défaut)
Chargées via `hooks._load_financial_reference_data`, même mécanisme (xml_ids
`noupdate=True` via `_load_records`) que le référentiel géo/activités. **Rappel** :
`post_init_hook` ne s'exécute qu'à l'installation initiale du module — exécution manuelle
one-shot sur SEFOR après ce chantier (comme pour les référentiels précédents).

### Modèle de ligne (Lot 2) — décision de structure
`microfinance.loan.application.income.line` gardé comme **modèle unique** (plutôt que 3
modèles séparés par catégorie) pour limiter la casse — décision confirmée avec Micka.
`designation_id` unique impossible (Many2one ne peut pointer vers 3 modèles différents) :
remplacé par 3 champs Many2one optionnels (`income_designation_id`,
`activity_expense_designation_id`, `family_expense_designation_id`), un seul rempli selon
`category` — même patron que les champs spécifiques-au-type de
`microfinance.loan.application.field.visit`. Champs retirés : `name` (libellé libre,
remplacé par la désignation configurée), `scenario` (renommé `situation`, conforme au
vocabulaire du prompt). `monthly_amount` : `compute='_compute_monthly_amount', store=True`,
`amount × frequency_id.multiplier` — plus de saisie directe.

**Pré-remplissage** : `_ensure_default_financial_lines()` (appelée à la création du
dossier, cf. `create()`) crée une ligne par désignation configurée × 2 situations × 3
catégories, montant à 0 — 70 lignes au total avec le jeu de données par défaut (7+7+21
désignations × 2 situations). Jamais de doublon si rappelée (vérifié par désignation déjà
présente, même patron que `_ensure_default_document_lines`).

### Vue (Lot 3/4)
6 tableaux éditables en ligne directement sur la fiche (3 catégories × 2 situations,
colonne `monthly_amount` avec `sum="Total"`/`"Sous-total"` — mécanisme natif Odoo pour la
ligne total, pas de champ dédié). Dépenses familiales : sous-total brut (tree `sum`) +
`total_family_expense_current/forecast` (déjà existant, réutilisé tel quel, juste
recalculé sans la dérivation prévisionnelle) affiché à côté du taux de majoration. Capacité
de remboursement (mensuelle + hebdomadaire, déjà existante côté hebdomadaire — juste le
diviseur corrigé) affichée après chaque situation. Bloc "Accroissement du revenu" : nouveau
champ `income_growth_occurred` (Selection Oui/Non, radio, défaut Non) contrôlant la
visibilité de `income_growth_before`/`income_growth_after` (champs déjà existants,
réutilisés). `financial_analysis_comment` renommé "Commentaire de l'enquêteur" et
repositionné en fin de bloc (réutilisé tel quel, pas de doublon). "Plan de financement" et
"Suivi de l'augmentation du capital" : hors périmètre de ce prompt, gardés intacts.

### Vérification
Exemple chiffré de la fiche papier reproduit exactement (revenu 840 000, dépenses
activités 44 200, dépenses familiales majorées 581 910 → capacité 213 890 mensuel /
53 472,5 hebdomadaire) + multiplicateurs (170 000×4=680 000, 10 000×30=300 000). 11
nouveaux tests (`test_application_financial_section.py`), 0 échec ; 47/48 sur la suite de
régression pertinente (1 erreur préexistante sans rapport, `test_application_kyc_sync.py`).

## Ajustements Bloc IV + repagination à 3 pages, 2026-07-19

### Repagination (remplace la mention précédente de 2 pages)
La fiche d'enquête passe de 2 à **3 pages** (`survey_page`, valeurs renommées/étendues) :
- **Page 1** (`partner_identification`) : Section I — inchangée.
- **Page 2** (`guarantor_documents_activity`, ex-`other_sections`) : Sections II (Garant), III
  (Documents), IV (Activité).
- **Page 3** (`financial_visits_ca_cdag`, nouvelle) : Sections V (Analyse financière), VI
  (Grille sociale + Visites terrain), VII (Avis CA/CDAG), VIII (Comité d'octroi — reste
  après VII, pas de mention explicite dans la demande initiale, confirmé avec Micka).

Navigation généralisée à une liste ordonnée (`_SURVEY_PAGES`) plutôt que des allers-retours
figés entre 2 valeurs, pour rester valable si une page supplémentaire est ajoutée un jour.
**Migration nécessaire** : le renommage de la valeur `other_sections` → 
`guarantor_documents_activity` a rendu invalide la valeur déjà stockée sur le dossier réel
IS/000003 (`ValueError` à la navigation) — corrigée par UPDATE SQL direct sur SEFOR avant de
poursuivre les tests.

### Ajustements Bloc IV
- `activity_description` déplacé après `activity_sector_id` (au lieu d'avant).
- `sale_location_status` renommé "Statut du lieu", `sale_location_type` renommé "Type du lieu".
- `sale_location_enclosed` : **déjà un `Selection`** avant ce lot (pas un `Boolean` comme
  supposé dans la demande initiale — vérifié en Lot 0, aucune migration de données requise,
  le seul dossier réel l'ayant vide) — juste réordonné (`open` avant `closed`), ajout de
  `default='open'` et `widget="radio"` dans la vue.
- Nouveau champ `activity_duration` (Char, compute non stocké, `@api.depends
  ('activity_start_date')`) : format "X ans et Y mois" (singulier géré : "1 an", "1 mois"),
  "Y mois" si moins d'un an, "Moins d'un mois" si moins d'un mois, vide si date non renseignée.
  Positionné juste après `activity_start_date`.
- Placeholders ajoutés sur les 9 champs texte/numérique du Bloc IV qui n'en avaient pas encore
  (`activity_description`, `activity_interruption`, `cyclical_period`,
  `supplier_credit_delay_days`, `customer_credit_delay_days`, `other_income_activities`,
  `loan_request_reason`, `debt_purpose`, `debt_amount`) — champs `Selection`/`Boolean`/`Date`
  exclus (pas de placeholder utile), ainsi que les champs `readonly`
  (`activity_sector_id`, `activity_duration`, l'utilisateur n'y saisissant jamais rien).

### Vérification
Testé directement sur SEFOR (dossier IS/000003) à chaque lot : durée d'activité validée sur
l'exemple demandé (5 ans et 7 mois) + cas limites (aujourd'hui, 6 mois, 1 an pile, vide) ;
navigation à 3 pages dans les deux sens avec bornes correctes ; défaut "Ouvert" confirmé sur
un nouveau dossier. 32/33 tests pertinents (1 erreur préexistante sans rapport,
`test_application_kyc_sync.py`).

## Note — réorganisation du menu Configuration, 2026-07-19
Le menu Configuration a été réorganisé en 6 sous-menus thématiques (cf.
`docs_dev/configuration/STATUS.md`). Impact sur les emplacements mentionnés dans ce fichier :
"Programmes progressifs" est désormais sous **Configuration > Crédit** (au lieu de
Configuration directement) ; "Catégories d'activité" et "Activités" sont désormais sous
**Configuration > Profil socio-économique**. Aucun changement d'`id`/action/comportement, la
réorganisation ne touche que le rangement visuel.

## Modèles Catégorie d'activité / Activité + intégration Bloc IV, 2026-07-19

### Décision
Remplacement de la saisie libre `activity_code` (Char) / `activity_sector` (Selection à 4
valeurs génériques) du Bloc IV par deux modèles de configuration :
- `microfinance.loan.application.activity.category` (`code`, `name`, `activity_ids`) —
  configurée **uniquement** dans Configuration (Manager crédit), jamais créable depuis la
  fiche d'enquête.
- `microfinance.loan.application.activity` (`code`, `name`, `category_id` requis) — une
  catégorie peut avoir plusieurs activités (`One2many`/`Many2one`). Contrainte SQL
  `unique(code)` **globale** (pas relative à la catégorie) sur les deux modèles.

Sur le dossier (`microfinance.loan.application`) : `activity_id` (Many2one, création à la
volée via "Créer et modifier..." uniquement — `no_quick_create` empêche la création rapide par
simple saisie de texte, qui aurait échoué de toute façon faute de renseigner `code`/
`category_id`, tous deux requis) ; `activity_sector_id` (`compute='_compute_activity_sector_id',
store=True, readonly=True`, `@api.depends('activity_id.category_id')`) — jamais saisi
manuellement. `activity_description` inchangé.

### Anomalie du jeu de données initial — décision confirmée
2 codes d'activité utilisés deux fois avec des catégories différentes dans le tableau fourni
par Micka (52 lignes, 37 catégories uniques, 50 activités après dédoublonnage) :
- Code `27` "Réparateur à domicile" : 1ʳᵉ occurrence sous **`S9529`** (Réparation d'autres
  articles personnels et ménagers), 2ᵉ sous `C3319` (Réparation d'autres matériels).
- Code `30` "Autres services" : 1ʳᵉ occurrence sous `Q8892` (Autres activités de services aux
  particuliers et aux familles), 2ᵉ sous `S9523` (Réparation de chaussures...).

**Option A confirmée par Micka** : garder la 1ʳᵉ occurrence dans l'ordre du tableau source,
ignorer la 2ᵉ à l'import. Point relevé et confirmé avec Micka pendant l'audit : le texte de
l'anomalie fourni initialement citait "Q8892" pour la première occurrence du code 27, alors
que le tableau montre en réalité `S9529` — coquille dans le texte descriptif, tableau source
faisant foi, aucun impact sur le résultat de l'Option A. `Q8892` garde bien ses 4 activités
restantes après dédoublonnage (Lavanderie, Photos, Tailleur, Autres services).

### Implémentation
- [x] Lot 1 : modèles + vues liste/formulaire + menu **Microfinance > Configuration >
  Catégories d'activité** / **Activités** (séquences 10/11, patron identique à
  `microfinance.profession`/`microfinance.repayment.frequency`). Accès : catégorie en lecture
  seule pour `group_microfinance_user`, écriture réservée à `group_microfinance_manager`
  (implicitement `group_microfinance_gestionnaire`, qui l'inclut) ; activité créable/
  modifiable par `group_microfinance_user` (nécessaire pour la création à la volée depuis la
  fiche d'enquête).
- [x] Lot 2 : chargement via le même mécanisme que le référentiel géographique
  (`hooks._load_activity_reference_data`, `_load_records(update=True)` + xml_ids
  `noupdate=True` via `_force_geo_noupdate`, données en dur dans `hooks.py`
  `ACTIVITY_REFERENCE_DATA` plutôt qu'un fichier CSV séparé, vu le volume modeste et la
  logique de dédoublonnage à appliquer). **Point technique découvert en cours de route** :
  `post_init_hook` ne s'exécute qu'à l'installation initiale du module (`new_install`, cf.
  `odoo/modules/loading.py:244`), jamais sur un simple `-u` d'un module déjà installé —
  exécution manuelle one-shot via shell Odoo sur SEFOR (même principe que la migration
  garant du chantier précédent). Sur une nouvelle installation du module, le chargement se
  fait automatiquement.
- [x] Lot 3/4 : intégration Bloc IV en édition directe (cohérent avec l'abandon de
  l'architecture wizard, cf. section précédente), vue mise à jour dans le même mouvement que
  le Lot 3 (pas de lot séparé nécessaire, la vue ne demandait qu'un remplacement de 2 champs).
- [x] Lot 5 : `tests/test_application_activity.py` (7 tests) — unicité de code (catégorie et
  activité, y compris inter-catégories), une catégorie peut avoir plusieurs activités,
  sélection d'activité existante → secteur dérivé, création avec code déjà utilisé → bloquée,
  création avec code inédit → réussie et immédiatement réutilisable, chargement du référentiel
  (compte + dédoublonnage + idempotence d'un second appel). Vérifié directement sur SEFOR
  (dossier IS/000003) : 0 échec sur les 7 nouveaux tests + les 30/31 tests déjà validés au
  chantier précédent (1 erreur préexistante sans rapport, `test_application_kyc_sync.py`).

## Abandon de l'architecture wizard : édition directe sur la fiche d'enquête, 2026-07-18

### Décision
Les 7 wizards popup de la fiche d'enquête (Section I Partenaire, II Garant, III Documents,
IV Activité, V Financière, VI Grille sociale + Visites terrain, VII CA/CDAG) sont
**définitivement abandonnés** au profit de l'édition directe sur la fiche (champs
`readonly` conditionnés par `state`, tableaux `one2many` en `editable="bottom"` directement
dans le formulaire). **Raison** : les bugs récents (tableau resté en liste au lieu du
formulaire attendu, `wizard_id` non défini sur le wizard Documents, mise en page cassée en
modale flottante) venaient tous de la couche wizard elle-même (modèles `Transient`
séparés, synchronisation manuelle avec les données réelles, code de liaison superflu).
**Si quelqu'un est tenté de réintroduire un wizard sur cette fiche plus tard : ne pas le
faire** — l'édition directe couvre tous les cas déjà rencontrés (y compris les contre-
visites terrain, cf. ci-dessous) avec moins de code et moins de surface de bug.

### Lot 0 — Audit préalable
- [x] Inventaire complet des 7 wizards (modèle, champs, mécanisme de lecture/écriture,
  bouton d'ouverture) avant toute modification. Découverte : contrairement à l'hypothèse
  de départ (seules les sections I/II/III/IV auraient un wizard), **les 7 sections avaient
  déjà un wizard fonctionnel** (confirmé par une inspection précédente, cf. plus bas dans
  ce fichier) — le chantier réel couvrait donc le double du périmètre prévu initialement.
- [x] Confirmé : aucun menu, action statique ni rapport ne référence ces wizards
  (ouverture uniquement via des méthodes Python `action_open_*_wizard()` retournant une
  action à la volée) — suppression sans dépendance externe à gérer.

### Lot 1 — Page 1 (Identification du partenaire)
- [x] Le mécanisme `compute='_compute_kyc_from_partner', store=True, readonly=False` +
  gel par `state` existait déjà sur le **modèle** (`microfinance.loan.application`) ; seule
  la **vue** forçait `readonly="1"` en dur et passait par le wizard. Vue corrigée pour
  reprendre exactement les mêmes conditions `readonly="state not in ('draft',
  'field_survey')"` que l'ancien wizard (adresse/téléphone du partenaire restent hors gel).
  Tableau Enfants/personnes à charge passé en `editable="bottom"` directement sur la fiche.
- [x] Wizard `microfinance.loan.application.partner.wizard` (+ `.dependent.line`) supprimé.

### Lot 2 — Garant (Section II)
- [x] Modèle `microfinance.loan.application.guarantor.line` **supprimé** : ses champs
  migrés en champs directs sur `microfinance.loan.application` (préfixe `guarantor_`,
  cohérent avec `partner_`/`spouse_`) — un seul garant par dossier, pas besoin d'un modèle
  de ligne séparé. `guarantor_address`/`guarantor_profession` suivent le même patron de gel
  que le Bloc A ; `guarantor_phone` reste toujours modifiable (même exception que
  `partner_phone`) ; `guarantor_partner_id` n'est jamais gelé (identité, comme `partner_id`).
- [x] **Migration des données réelles** (script one-shot, lecture SQL directe de l'ancienne
  table + écriture ORM sur les nouveaux champs) exécutée sur SEFOR (dossier IS/000003).
  Point de vigilance découvert et corrigé pendant la migration : `guarantor_address`/
  `guarantor_phone` étant désormais calculés depuis la fiche du contact garant
  (`guarantor_partner_id`) et non plus stockés manuellement, la migration aurait fait
  disparaître l'adresse/téléphone déjà saisis si le contact ne les avait pas encore sur sa
  fiche — corrigé en reportant ces valeurs sur le contact avant bascule (aucune perte).

### Lot 3 — Documents administratifs (Section III)
- [x] Le pré-remplissage des 2 lignes standard (`_ensure_default_document_lines`) écrivait
  déjà directement sur `document_line_ids` (modèle réel) — jamais de bug `wizard_id`
  possible dans ce sens ; le vrai problème était uniquement l'obligation de passer par la
  modale pour éditer. Tableau `document_line_ids` passé en `editable="bottom"` directement
  sur la fiche. Wizard `microfinance.loan.application.document.wizard` (+ `.wizard.line`)
  supprimé.

### Lot 4 — Sections IV, V, VI, VII
- [x] IV (Activité), V (Financière, avec les 2 tableaux revenus/dépenses actuel/
  prévisionnel), VI (scores de catégorisation sociale), VII (Avis CA/CDAG) : tous les
  champs vivaient déjà directement sur `microfinance.loan.application` (les wizards
  n'étaient que des copies génériques champ-à-champ, sans mécanisme de gel). Bascule en
  édition directe sans aucun changement de modèle, seulement la vue. 4 wizards supprimés.
- [x] Visites terrain (VI bis, VAD/VAV + contre-visites) : la logique la plus complexe de
  tout le chantier (résolution des liens `counter_visit_of_id` entre lignes-wizard en deux
  passes, cf. `_resolve_source_counter_visit_links`) s'est révélée être un **artefact du
  modèle `Transient`** — le modèle réel (`microfinance.loan.application.field.visit`) avait
  déjà un `counter_visit_of_id` (Many2one avec domaine) pleinement fonctionnel en édition
  directe native d'un `one2many`, sans aucune bascule à deux passes nécessaire. Confirmé
  par test réel sur SEFOR (visite + contre-visite créées et liées correctement en une
  seule écriture). Point technique : le domaine de `counter_visit_of_id` référence
  `application_id`, qui doit donc être présent (même `column_invisible="1"`) dans les
  sous-vues `<tree>` "Contre-VAD"/"Contre-VAV" — sans quoi Odoo refuse de charger la vue
  ("Field ... must be present in view").
- [x] Wizard `microfinance.loan.application.field.visit.wizard` (+ `.wizard.line`)
  supprimé — dernier des 7 wizards de la fiche d'enquête.

### Lot 5 — Nettoyage et vérification finale
- [x] Recherche exhaustive de toute référence aux 7 modèles/vues wizard supprimés dans
  tout le module (code + XML + CSV) : aucune référence orpheline restante (seules les
  mentions historiques dans ce fichier et dans `docs/workflows/programme_progressif/
  README.md` subsistent, volontairement, en tant que journal).
- [x] `ir.model.access.csv` et `__manifest__.py` nettoyés (entrées des 7 wizards + leurs
  modèles de ligne retirées).
- [x] Vérifié par script (`get_view` + recherche de boutons `action_open_*` dans l'arch) :
  plus aucun bouton n'ouvre de wizard sur la fiche d'enquête.
- [x] Suite de tests ciblée (Page 1, Garant, Documents, workflow, visites terrain, KYC
  sync) exécutée directement sur SEFOR après chaque lot : 0 échec sur l'ensemble, 1 seule
  erreur préexistante et sans rapport (`test_application_kyc_sync.py`, validation
  conjoint/téléphone obligatoire sur un contact marié déjà présent dans les fixtures de
  test — signalé ci-dessous, pas corrigé, hors périmètre de ce chantier).

## Incohérences relevées (complément)
- `tests/test_application_kyc_sync.py::TestApplicationKycSync.setUpClass` échoue sur SEFOR
  (`ValidationError: Le conjoint et son téléphone sont obligatoires pour un client marié`)
  — préexistant, sans rapport avec l'abandon de l'architecture wizard (fichier jamais
  modifié dans ce chantier). À corriger séparément si besoin.

## Correctif formulaire garant : identité Many2one, synchronisation, CIN, mise en page 2 colonnes, 2026-07-18

### Lot 1 — Suppression de champs
- [x] `guarantor_changed` ("Changement de garant") et `address_changed` ("Changement
  d'adresse du garant") retirés du modèle et de la vue.
- [x] Pas de champ `partner_reference_id` distinct à retirer : le champ "Référence"
  (`partner_id`) a été **repurposé** en champ d'identité principal (Lot 2) plutôt que
  supprimé puis recréé à l'identique — même nom de champ conservé, impact minimal.

### Lot 2 — Identité en Many2one + synchronisation
- [x] `partner_id` (déjà Many2one vers `res.partner`, ex-"Référence") devient le champ
  d'identité principal, `required=True`, libellé "Nom et prénom". L'ancien champ `name`
  (Char libre) est supprimé.
- [x] `address`/`phone` : simple pré-remplissage via `@api.onchange('partner_id')` (adresse
  concaténée `street`+`street2`, téléphone `phone` ou repli `mobile`) — **hors mécanisme de
  gel**, exactement comme `partner_current_address`/`partner_phone` sur le Bloc A (jamais
  resynchronisés automatiquement, ne s'écrasent jamais s'ils sont déjà renseignés).
- [x] `profession` : `compute='_compute_profession_from_partner', store=True,
  readonly=False`, synchronisé depuis `partner_id.microfinance_profession.name` tant que
  `application_id.state` est `draft`/`field_survey`, gelé ensuite (réaffectation à soi-même,
  même patron exact que `_compute_kyc_from_partner` sur `microfinance.loan.application`).
  `fokontany` reste volontairement un champ manuel (non listé dans la demande de
  synchronisation), comme `partner_address_since`/`union_duration` sur le Bloc A.
- [x] `_compute_counts()` (primary_guarantor_name) et `action_open_guarantor_wizard()` mis à
  jour pour lire `partner_id.name` au lieu de l'ancien champ `name`. Comme `partner_id` est
  désormais requis, l'ouverture du formulaire sans garant existant n'auto-crée plus de ligne
  vide (impossible sans partenaire) : elle ouvre un formulaire de création vierge standard
  (pas de `res_id`), la ligne n'est créée qu'à l'enregistrement.

### Lot 3 — Widget CIN
- [x] `widget="microfinance_grouped_digits"` appliqué directement sur `id_card_number` (pas
  de champ d'affichage séparé avec compute/inverse comme sur `res.partner.
  microfinance_id_number_display` : ce niveau de complexité existe côté client pour maintenir
  une valeur brute strictement numérique validée par contrainte 12 chiffres, contrainte qui
  n'existe pas sur ce champ garant — le widget seul suffit ici).

### Lot 4 — Deux colonnes uniformes sur la Page 2
- [x] Sections II, III, IV, V, VI, VII, VIII (toutes en une seule colonne auparavant)
  restructurées en groupe englobant + deux `<group>` côte à côte, la seconde restant vide
  (`<group/>`) sans champ artificiel ajouté — même patron que "1. Partenaire" sur la Page 1.

### Tests
- [x] `tests/test_application_guarantor_document_wizards.py` réécrit : formulaire de
  création vierge sans ligne existante, réutilisation sans doublon, sauvegarde de tous les
  champs papier, pré-remplissage adresse/téléphone via `Form` (déclenche réellement
  l'onchange, contrairement à un `.write()` direct), non-écrasement d'une correction
  manuelle, synchronisation et gel de la profession.
- [x] `tests/test_application_survey_pagination.py` : test de non-régression garant mis à
  jour (identité via `res.partner` réel).

### Non vérifié / à faire
- [ ] **Tests non exécutés réellement**, même limitation que les chantiers précédents (pas
  d'accès sudo/DB dans cet environnement) — seule vérification statique effectuée
  (`py_compile`, XML bien formé, correspondance champs vue/modèle vérifiée
  programmatiquement).
- [ ] Rendu visuel (formatage CIN en temps réel, disposition deux colonnes sur toute la Page
  2) non validé.

## Correctif : garant unique (formulaire direct) + pré-remplissage documents réel, 2026-07-18

### Symptôme 1 — le wizard garant affichait toujours une liste
Cause : le lot précédent avait bien retiré `editable="bottom"` du tableau, mais le bouton
"Modifier" ouvrait toujours le wizard **collection** (`microfinance.loan.application.
guarantor.wizard`, un `line_ids` avec tableau + "Ajouter une ligne") — retirer l'édition en
ligne ne suffisait pas tant que l'étape de liste elle-même restait dans le parcours. **Décision
confirmée avec Micka : un seul garant par dossier**, ce qui rend toute l'architecture
wizard-collection obsolète.
- [x] Suppression complète de `microfinance.loan.application.guarantor.wizard` /
  `.wizard.line` (python + vue) — code mort une fois le bouton repointé, vérifié qu'aucune
  autre action/menu n'y référençait avant suppression.
- [x] Nouvelle vue `<form>` **sur le modèle réel** `microfinance.loan.application.guarantor.
  line` (même agencement Identité/Adresse et contact qu'avant) —
  `views/microfinance_loan_application_guarantor_line_views.xml`.
- [x] `action_open_guarantor_wizard()` (même nom de méthode, bouton XML inchangé) : prend la
  première ligne de `guarantor_line_ids`, en crée une vide (`name` requis → "Nouveau garant"
  par défaut) si la collection est vide, puis ouvre directement son formulaire
  (`res_id`/`view_id` ciblés) — plus jamais de liste intermédiaire.

### Symptôme 2 — le wizard documents s'ouvrait vide sur un dossier existant
Cause confirmée : le mécanisme de pré-remplissage n'était câblé que sur `create()` du
dossier — un dossier de test créé **avant** ce lot (`IS/000002`) n'avait donc jamais reçu ses
2 lignes.
- [x] Logique extraite dans `_ensure_default_document_lines()` (vérifie chaque
  `document_type` individuellement via `name`, pas un simple test "collection vide" — ne
  duplique jamais une ligne déjà présente, y compris à côté d'une ligne personnalisée
  existante) — appelée à la fois depuis `create()` **et** depuis
  `action_open_document_wizard()`, pour couvrir aussi les dossiers créés avant ce mécanisme.

### Tests
- [x] `tests/test_application_guarantor_document_wizards.py` : formulaire garant sans liste
  (création à la volée, réutilisation sans doublon au second appel), pré-remplissage
  documents sur un dossier existant sans lignes, non-duplication à l'ouverture répétée,
  ajout des 2 lignes standard sans dupliquer une ligne personnalisée déjà là.
- [x] `tests/test_application_survey_pagination.py` : test de non-régression Page 2 mis à
  jour pour refléter le nouveau mécanisme (formulaire direct au lieu du wizard supprimé).

### Non vérifié / à faire
- [ ] **Tests non exécutés réellement**, même limitation que les chantiers précédents (pas
  d'accès sudo/DB dans cet environnement) — seule vérification statique effectuée
  (`py_compile`, XML bien formé).
- [ ] Rendu visuel (formulaire garant en popup direct, wizard documents pré-rempli sur
  `IS/000002`) non validé.

## Wizard Garant (formulaire détaillé) + matrice Documents administratifs, 2026-07-18

### Audit préalable
- [x] Champs réels confirmés sur `microfinance.loan.application.guarantor.line` :
  `partner_id`/`name`/`id_card_number`/`address`/`phone`/`profession`/`relationship_to_borrower`
  (pas `relationship_with_borrower`). **`partner_id` ("Garant (fiche contact)") remplissait
  déjà le rôle demandé pour "Référence"** — pas de champ `partner_reference_id` séparé créé
  (évite un doublon), juste relabellisé "Référence".
- [x] `microfinance.loan.application.document.line` avait un seul booléen partagé
  `is_provided` + `comment` (Char) — aucune donnée de test ni ligne "Photo d'identité" trouvée
  nulle part (recherche exhaustive), donc aucune migration de données nécessaire pour
  l'éclatement en deux cases à cocher.
- [x] Aucun mécanisme de pré-remplissage de `document_line_ids` n'existait avant ce lot.
- [x] Technique confirmée : tableau `guarantor_line_ids` affiché via `<tree editable="bottom">`
  intégrée au wizard (pas de widget custom) — passage à une vue tree non éditable + vue
  `<form>` dédiée, technique standard Odoo (comportement automatique : ajouter/cliquer une
  ligne d'un one2many dont le tree n'est pas `editable` ouvre le formulaire enregistré du
  modèle).

### Lot 1 — Formulaire détaillé garant
- [x] Nouveaux champs sur `microfinance.loan.application.guarantor.line` **et** son mirroir
  `microfinance.loan.application.guarantor.wizard.line` (même patron dual-modèle que les
  wizards précédents) : `guarantor_changed`, `id_card_issue_date`, `id_card_issue_place`,
  `id_card_duplicate_date`, `id_card_duplicate_place`, `address_changed`, `fokontany`,
  `employer`, `surveyor_comment`.
- [x] Nouvelle vue `<form>` dédiée pour `...guarantor.wizard.line` (Identité / Adresse et
  contact, même style deux colonnes que la Page 1) — enregistrée comme unique vue form de ce
  modèle, donc reprise automatiquement par Odoo à l'ouverture d'une ligne.
- [x] Tableau du wizard "Modifier les garants" : `editable="bottom"` retiré, résumé réduit à
  Nom/Lien de parenté/Téléphone.

### Lot 2 — Matrice Documents administratifs
- [x] `microfinance.loan.application.document.line` (+ mirroir wizard) restructuré :
  `is_provided` remplacé par `provided_by_partner`/`provided_by_guarantor` (deux cases
  distinctes), `comment` renommé `observation`. `name` (type de document) conservé tel quel
  ("garder ce qui existe", pas de renommage en `document_type` sans bénéfice fonctionnel).
- [x] `_compute_counts()` (document_provided_count/missing_count) mis à jour : "fourni" =
  case Partenaire **ou** Garant cochée.
- [x] Pré-remplissage automatique à la création du dossier (`create()` de
  `microfinance.loan.application`) : 2 lignes ("Copie CIN", "Certificat de résidence – 3
  mois"), cases vides. **"Photo d'identité" volontairement absente** de cette liste et de tout
  le mécanisme — déjà couverte par `res.partner.image_1920`, pas suivie une deuxième fois ici.
  L'enquêteur peut ajouter d'autres lignes en plus des 2 par défaut.
- [x] Vue du wizard Documents : reste `editable="bottom"` (contrairement au garant — lignes
  courtes, 2 cases + 1 champ texte, édition directe adaptée).

### Lot 3 — Tests
- [x] `tests/test_application_guarantor_document_wizards.py` (5 tests) : 2 lignes documents
  par défaut sans "Photo d'identité", cases à cocher + observation sauvegardées via le
  wizard, ajout d'une ligne document supplémentaire, ajout d'un garant avec tous les champs
  du papier, réutilisation de `partner_id` comme "Référence" garant.

### Non vérifié / à faire
- [ ] **Tests non exécutés réellement**, même limitation que les chantiers précédents (pas
  d'accès sudo/DB dans cet environnement) — seule vérification statique effectuée
  (`py_compile`, XML bien formé).
- [ ] Rendu visuel du formulaire garant et de la matrice documents non validé.

## Pagination simplifiée de la fiche d'enquête (Page 1 / Page 2), 2026-07-18
- [x] Audit préalable : tous les wizards des sections II à VII **existaient déjà** et
  fonctionnaient (`action_open_guarantor_wizard`, `_document_wizard`, `_activity_wizard`,
  `_financial_wizard`, `_social_grid_wizard`, `_field_visit_wizard`, `_ca_cdag_wizard`) — ce
  chantier est une pure réorganisation de vue, aucun wizard créé ni modifié.
- [x] **Écart trouvé par rapport à la liste des 6 sections du prompt** : la liste omettait deux
  blocs déjà existants — la grille de catégorisation sociale (`social_level_id`/`total_points`,
  bouton "Modifier la grille sociale", jusque-là mélangée avec les visites terrain dans un même
  groupe "VI") et "VIII — Comité d'octroi" (affichage de `state`, sans wizard). Confirmé avec
  Micka : les deux sont inclus sur la Page 2 (cohérent avec "toutes les sections restantes").
- [x] `survey_page` (Selection `partner_identification`/`other_sections`, default
  `partner_identification`, `copy=False`) sur `microfinance.loan.application` — totalement
  indépendant de `state`, navigable à tout moment du workflow.
- [x] `action_survey_next_page()`/`action_survey_previous_page()` : bascule `survey_page`
  uniquement, aucun autre champ touché.
- [x] Vue : les blocs Page 1 (section I existante, inchangée) et Page 2 (II à VIII, y compris
  grille sociale et comité) enveloppés chacun dans un `<div invisible="...">` (pas un
  `<group>` : un group englobant aurait changé la disposition des groupes enfants en colonnes
  côte à côte au lieu de l'empilement vertical actuel) conditionné sur `survey_page` —
  `views/microfinance_loan_application_views.xml`. Bouton "Page suivante" en bas de la Page 1,
  "Page précédente" en haut de la Page 2 — deux boutons de navigation au total, comme demandé.
- [x] Tests écrits (`tests/test_application_survey_pagination.py`, 5 tests) : page par défaut,
  navigation dans les deux sens, `state` jamais modifié par la navigation, navigation possible
  quel que soit l'état du workflow, non-régression d'un wizard de la Page 2 (garant).
- [ ] Un futur découpage plus fin de la Page 2 en plusieurs pages reste possible sans casser ce
  mécanisme : il suffirait d'ajouter de nouvelles valeurs à la sélection `survey_page` et de
  répartir les `<div invisible="survey_page not in (...)">` en conséquence — aucune
  refonte structurelle nécessaire.

### Non vérifié / à faire
- [ ] **Tests non exécutés réellement**, même limitation que les chantiers précédents (pas
  d'accès sudo/DB dans cet environnement) — seule vérification statique effectuée
  (`py_compile`, XML bien formé).
- [ ] Rendu visuel de la navigation (boutons, bascule Page 1 ↔ Page 2) non validé.

## Affichage complet (lecture seule) de la fiche d'enquête sur le dossier, 2026-07-18
- [x] Audit préalable : le marqueur "PP/PS" de la photo papier (à côté de "Heure fin enquête")
  correspond à "Premier Prêt/Prêt Successif", déjà implémenté (`loan_tier_label`, groupe
  "Rang du prêt") — confirmé avec Micka, aucun nouveau champ, aucun déplacement dans
  l'en-tête ; ce lot reste concentré sur la section I/II/III.
- [x] Le résumé de 4 champs (`partner_surname`, `partner_marital_status`, `spouse_name`,
  `dependent_count`) de la section "I — Identification du partenaire" a été remplacé par
  l'affichage complet des 21 + 10 champs Partenaire/Conjoint et du tableau Enfants (6
  colonnes : Nom, Lien de parenté, Age, Classe, École, Remarque), tous en lecture seule,
  organisés en trois sous-groupes "1. Partenaire" / "2. Conjoint(e)" / "3. Enfants et
  personnes à charge" — `views/microfinance_loan_application_views.xml`. Style deux colonnes
  conservé pour la section Partenaire et Conjoint(e), cohérent avec le wizard.
  `dependent_count` (total incl. personnes à charge non-enfants, distinct de
  `children_count`/`children_schooled_count`) n'est plus affiché nulle part dans les vues —
  reste un champ modèle valide, mais volontairement omis de cet affichage papier-conforme
  pour ne pas réintroduire la confusion entre les deux compteurs.
- [x] Bouton "Modifier" (section I) inchangé : ouvre toujours le même wizard, avec les mêmes
  valeurs pré-remplies (aucune régression, ce lot ne touche qu'à l'affichage lecture seule).
- [x] Vérification exhaustive : les 40 références de champs de la nouvelle section ont été
  comparées programmatiquement à la liste réelle des champs du modèle (aucun champ manquant
  ni mal orthographié) — un oubli initial (`partner_id_card_issue_place`) détecté et corrigé
  lors de cette vérification.

### Non vérifié / à faire
- [ ] Pas d'accès à une instance Odoo réelle dans cet environnement (toujours pas de sudo/DB)
  : impossible d'ouvrir un dossier de test rempli via le wizard et de comparer visuellement
  avec la photo papier (Lot 2 du prompt) — seule une vérification statique (XML bien formé,
  correspondance champ par champ avec le modèle) a été faite. À valider visuellement par
  Micka avant de considérer ce lot définitivement clos.

## Mise en conformité du wizard "Identification du partenaire" avec la fiche papier CEFOR,
2026-07-18

Comparaison champ par champ avec la photo du formulaire papier fournie par Micka
("I — IDENTIFICATION DU PARTENAIRE" / "1. PARTENAIRE" / "2. CONJOINT(E)" /
"3. ENFANTS et PERSONNES À CHARGE").

- [x] Section Partenaire — nouveaux champs sur `microfinance.loan.application` :
  `partner_nickname` (Surnom), `partner_id_card_duplicate_date`/`_place` (Duplicata CIN),
  `partner_address_changed` (Changement d'adresse), `partner_agency_distance_km` (distance
  domicile-agence — aucun équivalent trouvé ailleurs dans le module, confirmé par recherche
  exhaustive), `partner_phone_type`/`partner_phone_type_detail` (qualification du téléphone).
  Ces deux derniers suivent le régime d'exception de `partner_phone` (toujours modifiables,
  jamais gelés) car ils le qualifient directement ; les autres suivent le gel normal du Bloc A
  (aucune source sur `res.partner`, comme `union_duration`/`partner_address_since`).
- [x] Section Conjoint — `spouse_id_card_issue_date`/`_place` : contrairement aux autres
  champs "sans source" de ce lot, **ceux-ci sont synchronisés** comme le reste des champs
  conjoint (le conjoint a sa propre fiche `res.partner`, avec ses propres
  `microfinance_id_issue_date`/`_place`) — ajoutés à `_KYC_FIELD_SOURCES`.
- [x] Refonte Enfants et personnes à charge
  (`microfinance.loan.application.dependent`) : `age` (compute, `store=True`, depuis
  `birth_date`, jamais saisi à la main), `school_class`/`school_name` (remplacent l'ancien
  champ combiné `occupation`, aucune donnée de test ne le référençait — vérifié avant
  suppression), `remark`. Deux nouveaux compteurs sur le dossier,
  `children_count`/`children_schooled_count` (compute, `store=True`, depuis `dependent_ids`)
  — **distincts** du `dependent_count` déjà existant (total incl. personnes à charge non-
  enfants, utilisé sur le formulaire principal) : collision de nom évitée en gardant
  `dependent_count` inchangé et en nommant différemment les nouveaux compteurs papier.
- [x] **Point de décision confirmé** : le champ "Lien de parenté" (`relationship`), absent de
  la fiche papier d'origine (qui ne liste que des "enfants et personnes à charge" sans
  distinguer), est **conservé** — ajout non destructif déjà utile pour les personnes à charge
  non-enfants. Note : `docs/ecarts_lpf.md` (référencé dans le prompt) est en réalité dédié à un
  chantier sans rapport (fonds de crédit rotatifs bailleurs vs Loan Performer) ; ce point de
  décision est donc documenté ici plutôt que dans ce fichier.
- [x] Vue du wizard réorganisée dans l'ordre exact du papier (1. Partenaire / 2. Conjoint(e) /
  3. Enfants et personnes à charge), style deux colonnes conservé pour la section Partenaire,
  placeholders ajoutés sur tous les nouveaux champs texte/numérique (Selection/Date/Boolean
  laissés sans placeholder, non pertinent pour ces widgets).
- [x] Tests écrits (`tests/test_application_partner_wizard_cefor_fields.py`, 4 tests) :
  sauvegarde des nouveaux champs via le bouton Valider, recalcul de l'âge au changement de
  date de naissance, cohérence des compteurs avec le détail du tableau, sauvegarde des
  nouvelles colonnes du tableau via le wizard.

### Non vérifié / à faire
- [ ] **Tests non exécutés réellement**, même limitation que les correctifs précédents (pas
  d'accès sudo/DB dans cet environnement) — seule vérification statique effectuée
  (`py_compile`, XML bien formé).
- [ ] Rendu visuel du wizard réorganisé non validé.

## Synchronisation du Bloc A (fiche d'enquête) avec res.partner, 2026-07-18

### Audit préalable (Lot 0, lecture seule)
- [x] Tableau de correspondance exhaustif construit entre les 21 champs du Bloc A
  (`microfinance.loan.application`) et les champs existants sur `res.partner` — voir le
  commentaire au-dessus de `_KYC_FIELD_SOURCES` dans `models/microfinance_loan_application.py`
  pour la correspondance exacte retenue.
- [x] **Découverte majeure** : `microfinance_spouse_id` est un Many2one vers `res.partner` (le
  conjoint est déjà un contact complet), pas un champ texte — confirmé par le commentaire déjà
  présent sur `microfinance_spouse_profession` ("une seule source de vérité"). Conséquence :
  la plupart des champs "spouse_*" proposés initialement (CIN, adresse, fokontany) **n'ont pas
  été dupliqués** sur `res.partner` — lus directement via
  `partner_id.microfinance_spouse_id.<champ>` (décision confirmée avec Micka).
- [x] Écart de valeurs Selection trouvé entre `microfinance_marital_status` (res.partner, 4
  valeurs) et `partner_marital_status` (dossier, 5 valeurs, incluait `cohabiting`/Union libre
  en plus) — `cohabiting` ajouté à `microfinance_marital_status` pour aligner les deux
  (confirmé avec Micka).
- [x] `partner_surname` (dossier) synchronisé depuis `res.partner.name` malgré la
  correspondance approximative (pas de séparation nom/prénom dans ce système) — confirmé avec
  Micka.
- [x] Découverte : le wizard `microfinance.loan.application.partner.wizard` (section I de la
  fiche d'enquête) portait un commentaire explicite affirmant que ces champs étaient "jamais
  liés en live à res.partner" — obsolète, corrigé (docstring mise à jour).

### Lot 1 — Nouveaux champs sur `res.partner`
- [x] `microfinance_birth_place` (Identification), `microfinance_employer` (Identification,
  **générique**, pas "spouse_employer" dédié — réutilisable client/conjoint, symétrique à
  `microfinance_profession`), `microfinance_next_of_kin_phone` (Famille et compte),
  `microfinance_housing_status` (Famille et compte) — `models/res_partner.py` +
  `views/microfinance_partner_views.xml`.
- [x] `'cohabiting'` ajouté à `microfinance_marital_status`.
- [x] Aucun champ dupliqué `microfinance_spouse_id_card_number`/`_address`/`_fokontany` (cf.
  découverte Lot 0).

### Lot 2 — Synchronisation sur `microfinance.loan.application`
- [x] 17 champs du Bloc A convertis en `compute='_compute_kyc_from_partner', store=True,
  readonly=False`, `@api.depends` listant explicitement chaque champ source (client +
  conjoint, via `partner_id.microfinance_spouse_id...`).
- [x] Gel implémenté par réaffectation explicite de chaque champ à sa propre valeur quand
  `state not in ('draft', 'field_survey')` — nécessaire car un compute multi-champs
  `readonly=False` stocké doit fixer une valeur pour chaque champ à chaque appel (sinon l'ORM
  le viderait), cf. `_compute_kyc_from_partner`.
- [x] `partner_current_address`/`partner_phone` **hors** de ce mécanisme (pas de
  `compute=`) : simple pré-remplissage à la création (`create()`, pour les dossiers créés par
  l'ORM comme `res.partner._get_or_create_loan_application()`) et à la sélection du client
  (`@api.onchange('partner_id')`, pour la saisie manuelle) — jamais gelés, jamais
  resynchronisés ensuite.
- [x] `partner_address_since`/`union_duration` : aucune source sur `res.partner` (ni sur le
  conjoint) — restent des champs manuels ordinaires, gelés comme le reste du Bloc A (readonly
  vue conditionnel) mais hors du mécanisme `compute`.
- [x] Wizard section I (`microfinance_loan_application_partner_wizard_views.xml`) : nouveau
  champ `application_state` (related, technique) pilotant un `readonly=` conditionnel sur
  chaque champ gelé, bandeau d'information si le dossier est hors instruction. `dependent_ids`/
  `guarantor_line_ids` non touchés (hors périmètre confirmé).

### Lot 3 — Tests
- [x] `tests/test_application_kyc_sync.py` (6 tests) : pré-remplissage complet à la création
  (client + conjoint), resynchronisation en `draft`, gel confirmé après `analysis`,
  modification manuelle préservée en `field_survey` sans changement source, adresse/téléphone
  modifiables après gel, adresse/téléphone jamais resynchronisés même en cours.

### Non vérifié / à faire
- [ ] **Tests non exécutés réellement**, même limitation que les correctifs précédents (pas
  d'accès sudo/DB dans cet environnement) — seule vérification statique effectuée
  (`py_compile`, XML bien formé).
- [ ] Rendu du wizard (bandeau d'information, readonly conditionnel par champ) non validé
  visuellement.

## Numérotation à trois niveaux (compte client permanent / épargne dérivée / crédit
indépendant), 2026-07-18

### Audit préalable (Lot 0, lecture seule)
- [x] La référence du dossier d'instruction (`IS/000174`) était bien générée par une séquence
  **dédiée au dossier** (`ir.sequence` code `microfinance.loan.application.agency`,
  incrémentée à chaque `create()`), sans aucun lien avec le client — confirme le bug décrit
  par Micka.
- [x] Aucun champ candidat sur `res.partner` pour un numéro de compte permanent
  (`microfinance_registration_number`/`microfinance_internal_reference` sont des Char libres,
  jamais auto-générés).
- [x] Déclencheur "client microfinance" confirmé : `microfinance_partner_type == 'client'`,
  posé uniquement via le contexte par défaut de l'action du menu **Microfinance > Clients**
  (`default_microfinance_partner_type`), jamais modifiable ensuite depuis l'interface — fiable
  comme condition de déclenchement, vérifiée à la création uniquement (jamais sur write, cf.
  décision explicite de Micka).
- [x] `microfinance.loan.name` (crédit accordé) avait **déjà** une séquence dédiée et
  indépendante (`microfinance.loan.agency`), incrémentée à chaque crédit créé tous clients
  confondus de l'agence — **Lot 3 déjà satisfait avant même de commencer**, aucun code changé,
  seul le commentaire obsolète de `tests/test_agency_numbering.py` (qui affirmait à tort que
  `microfinance.loan.application` n'était pas fonctionnel) a été corrigé.
- [x] Padding uniformément 6 chiffres partout (`_get_or_create_numbering_sequence(code,
  padding=6)`), aucune divergence trouvée.
- **Deux points bloquants découverts pendant l'audit, tranchés avec Micka avant de coder :**
  - Le numéro épargne existant (`microfinance_savings_management`) utilisait déjà une séquence
    indépendante **par type** (I/G/E/T), et un test existant (`test_agency_numbering.py`)
    validait explicitement qu'un même client peut avoir plusieurs comptes du même type avec des
    numéros différents — incompatible avec une dérivation stricte à un seul numéro par client.
    **Décision Micka** : un seul compte "principal" par type dérive le numéro client, les
    comptes suivants du même type gardent l'ancienne séquence indépendante (cf. Lot 2).
  - Aucune logique de création/réutilisation automatique du compte épargne à la création du
    dossier n'existait dans le code (contrairement à ce que supposait le prompt) — **Décision
    Micka** : l'ajouter comme prérequis avant le Lot 2, déclenchée à la création du premier
    dossier d'instruction, sur un nouveau produit d'épargne par défaut configurable par agence
    (symétrique à `microfinance_fond_credit_default_id`).

### Lot 1 — Numéro de compte client permanent (`microfinance_loan_management`)
- [x] `res.partner.microfinance_account_number` (Char, readonly, copy=False), format
  `AGENCE/NNNNNN`, séquence dédiée par agence (`microfinance.partner.account`) — attribué une
  seule fois dans `create()`, uniquement si `microfinance_partner_type == 'client'`.
- [x] Verrou double : `create()` ignore toute valeur fournie manuellement dans les vals
  (toujours recalculée), `write()` bloque toute modification hors du mécanisme interne
  (`_assign_microfinance_account_number()`, via un flag de contexte technique
  `microfinance_allow_account_number_write`) — `ValidationError` explicite sinon.
- [x] `microfinance.loan.application.name` devient un `related='partner_id.microfinance_account_number'`
  (stocké) : la référence du dossier reprend désormais le numéro de compte permanent du
  client — la génération par séquence propre au dossier a été retirée de `create()`. La
  séquence `microfinance.loan.application.agency` n'est plus utilisée nulle part (vérifié par
  recherche exhaustive) ; les lignes `ir.sequence` déjà créées dynamiquement pour ce code
  restent en base, orphelines mais inoffensives (pas de script de migration, instance de test
  sans données réelles à préserver, comme pour le correctif précédent).
- [x] `tests/common.py` : `cls.partner` (fixture partagée par toute la suite) marqué
  `microfinance_partner_type='client'` — sans quoi il n'aurait jamais de numéro de compte et
  tous les dossiers créés dans les tests auraient un `name` vide. Un seul test existant
  (`test_automatic_numbering` → renommé `test_numbering_derived_from_client_permanent_account_number`
  dans `test_application_workflow.py`) attendait l'ancien comportement (deux dossiers du même
  client avec des `name` différents) ; corrigé pour attendre le nouveau (même `name`, égal au
  numéro de compte du client). Aucun autre test dans toute la suite ne référençait
  `application.name`.

### Lot 2 — Numéro épargne dérivé (`microfinance_savings_management`)
- [x] Prérequis ajouté : `res.company.microfinance_savings_default_product_id` (Many2one,
  domaine `product_type='voluntary'` de la société), et
  `res.partner._get_or_create_microfinance_savings_principal_account()` câblé via override de
  `_get_or_create_loan_application()` (héritage `res.partner`, jamais l'inverse — le module
  épargne dépend du module crédit). Best-effort : si aucun produit par défaut n'est configuré,
  aucun compte n'est ouvert automatiquement, sans bloquer la création du dossier de crédit.
  Idempotent comme `_get_or_create_loan_application()`.
- [x] `microfinance_savings_account._get_savings_account_name()` : le **premier** compte d'un
  type donné (I/G/E/T) pour un client reprend `AGENCE/TYPE/NNNNNN` avec le même suffixe
  numérique que `partner_id.microfinance_account_number` (`IS/000001` → `IS/I/000001`) ; tout
  compte supplémentaire du même type pour le même client retombe sur l'ancienne séquence
  indépendante par type (`microfinance.savings.account.<TYPE>`), pour ne jamais produire deux
  comptes de même nom.
- [x] `tests/test_agency_numbering.py` (existant, non modifié) continue de passer tel quel :
  ses partenaires de test ne sont jamais marqués `microfinance_partner_type='client'`, donc
  n'ont pas de numéro de compte — la dérivation ne s'applique jamais à eux, ils exercent
  exactement l'ancien chemin (séquence indépendante), qui reste le comportement de repli.

### Lot 3 — Numéro crédit (`microfinance_loan_management`)
- [x] Aucun changement de code : `microfinance.loan.name` était déjà correct (séquence dédiée
  `microfinance.loan.agency`, indépendante du numéro de compte client et du numéro de dossier).
  Déjà couvert par `tests/test_agency_numbering.py` (`test_loan_numbering_per_agency` — deux
  crédits du même client obtiennent des numéros différents ; `test_loan_numbering_independent_per_agency`).

### Lot 4 — Tests et documentation
- [x] `microfinance_loan_management/tests/test_partner_account_number.py` (nouveau, 7 tests) :
  attribution à la création, indépendance par agence, incrémentation, non-attribution hors
  client microfinance, permanence après écritures multiples, verrou de modification manuelle,
  valeur manuelle ignorée à la création.
- [x] `microfinance_savings_management/tests/test_savings_account_number_derivation.py`
  (nouveau, 7 tests) : dérivation du 1er compte d'un type, repli en séquence indépendante pour
  le 2e compte du même type, dérivation indépendante par type, comportement de repli si le
  client n'a pas de numéro de compte, ouverture automatique du compte principal à la création
  du dossier, absence d'erreur si aucun produit par défaut configuré, idempotence du hook.

### Non vérifié / à faire
- [ ] **Tests non exécutés réellement**, même limitation que les correctifs précédents (pas
  d'accès sudo à l'instance Odoo ni identifiants de base de données dans cet environnement) —
  seule vérification statique effectuée (syntaxe Python via `ast.parse`, XML bien formé). À
  exécuter avant mise en production.
- [ ] Le nouveau champ `microfinance_savings_default_product_id` (Microfinance > tableau de
  bord/réglages société) n'a pas été validé visuellement.

## Extension — Section CRÉDIT sur la fiche client (sélection produit + création automatique
du dossier), 2026-07-18 — **corrigée le même jour, voir sous-section Correctif ci-dessous**
- [x] Champs sur `res.partner` : `microfinance_selected_product_id`,
  `microfinance_current_loan_application_id` (Lot 0, champ technique confirmé avec Micka
  plutôt qu'une recherche heuristique), `microfinance_progressive_eligible_product_ids`
  (absent avant ce chantier, ajouté comme prévu au prompt de dépendance) —
  `models/res_partner.py`. Le champ radio `microfinance_credit_selection_mode` initialement
  ajouté ici a été **retiré par le correctif ci-dessous**, remplacé par un réglage global
  unique (`microfinance_product_policy`, calculé/lecture seule).
- [x] `microfinance_progressive_eligible_product_ids` réutilise directement
  `_evaluate_progressive_eligibility()` de `microfinance.loan.application` (instance jetable
  via `.new()`), sans dupliquer la logique d'éligibilité. Inclut systématiquement la 1ère
  étape de chaque programme (aucun prérequis) — confirmé avec Micka, sinon un client ne
  pourrait jamais entrer dans un programme progressif via ce champ — et les étapes
  suivantes dont le statut calculé est `eligible` ou `warning` (confirmé avec Micka : ce
  statut n'a jamais été bloquant côté dossier, cohérent de l'inclure ici aussi).
- [x] `_get_or_create_loan_application()` : recherche un dossier non terminal
  (`state not in ('refused', 'loan_created')`) pour le couple client/produit, le réutilise
  si trouvé, sinon crée un brouillon (`partner_id`/`loan_product_id`/`company_id`
  pré-remplis). Notification via `bus.bus`/`simple_notification` (voir limitation
  technique ci-dessous).
- [x] Verrou de changement de produit (`@api.constrains`) : bloqué tant que le dossier
  courant n'est ni rejeté (`refused`) ni transformé en crédit clôturé (`closed`) ou annulé
  (`cancelled`) — l'inclusion de `cancelled` dans les états déverrouillants a été confirmée
  avec Micka (cohérent avec `PRIOR_LOAN_STATES` qui exclut déjà les crédits annulés des
  prêts antérieurs réalisés).
- [x] Vue : rangée CRÉDIT/ÉPARGNE insérée juste avant `<notebook>` (après le bloc Comité),
  **sans condition de type de client** (contrairement aux blocs Identification/Famille et
  Société) — un client Société peut tout autant souscrire un crédit. Domaine du champ
  produit dupliqué par mode (indépendant/progressif) avec placeholder contextuel distinct.
  Champ `microfinance_product_change_locked`/`microfinance_product_lock_message` ajoutés en
  complément du Lot 1 initial, nécessaires pour piloter le bandeau readonly/message —
  `views/microfinance_partner_views.xml`.
- [x] Tests écrits (`tests/test_partner_credit_selection.py`), sélection indépendante
  (création/réutilisation/aucun produit → aucun dossier), éligibilité progressive (0/1/2
  produits éligibles selon société et historique), verrou (bloqué en cours d'instruction,
  bloqué crédit actif puis débloqué une fois clôturé, débloqué si crédit annulé, débloqué si
  dossier rejeté) — nombre de tests mis à jour par le correctif ci-dessous.

### Correctif — Politique de produit globale (remplace les radios par client), 2026-07-18
Changement de décision confirmé par Micka en cours de test : le mode de sélection
(indépendant/progressif) n'est plus un choix par client (deux radios sur la fiche), mais un
**réglage unique pour tout le système** (les 25 agences), volontairement **non dupliqué par
société** (pas de champ sur `res.company`) et **non rétroactif** (un changement de politique
n'affecte jamais les dossiers/crédits déjà créés, seulement les nouveaux).
- [x] Champ `microfinance_credit_selection_mode` (radio) **retiré** de `res.partner`, ainsi
  que le widget radio dans la vue et toute référence dans les contraintes/domaines qui en
  dépendaient — pas de script de migration nécessaire (instance de test, confirmé par
  Micka).
- [x] Nouveau réglage global : `models/res_config_settings.py` (`ResConfigSettings`,
  `TransientModel` hérité de `res.config.settings`), champ `microfinance_product_policy`
  stocké via `config_parameter='microfinance_loan_management.microfinance_product_policy'`
  (technique standard Odoo — `ir.config_parameter`, jamais par société ; aucun modèle de
  configuration singleton dédié n'existait déjà dans ce module, ni dans les autres modules
  du dépôt à l'exception de `microfinance_mowgli_assistant` dont le patron a été repris à
  l'identique). Accessible via **Microfinance > Configuration > Paramètres** (nouveau,
  n'existait pas encore dans ce module) — `views/res_config_settings_views.xml`,
  `views/microfinance_menus.xml`. Accès en écriture réservé de fait à
  `group_microfinance_manager` (menu `menu_microfinance_config` déjà filtré sur ce groupe ;
  la balise `<app>` porte en plus son propre `groups=` pour bloquer l'accès même en
  passant directement par Réglages généraux).
- [x] Sur `res.partner`, nouveau champ calculé non stocké `microfinance_product_policy`
  (lecture seule, `@api.depends()` sans dépendance de champ — relu depuis
  `ir.config_parameter` à chaque accès) qui remplace `microfinance_credit_selection_mode`
  comme source du domaine du champ Produit et de la contrainte de cohérence
  (`_check_microfinance_product_matches_policy`, renommée). Le reste (verrou de changement
  de produit, création/réutilisation automatique du dossier, champ dossier courant) **non
  retouché**, comme demandé, car indépendant du champ radio supprimé.
- [x] Tests mis à jour (suppression des références au champ radio, ajout d'un helper
  `_set_product_policy()` dans `tests/common.py`) + nouvelle classe
  `TestPartnerCreditSelectionProductPolicy` (politique par défaut, lecture du réglage
  global, absence de duplication par société, non-rétroactivité d'un changement de
  politique en cours de route).
- [ ] **Tests non exécutés réellement**, même limitation que ci-dessus (pas d'accès sudo/DB
  dans cet environnement) — seule vérification statique (`py_compile`, XML bien formé)
  effectuée.

### Limitation technique signalée (pas un écart, un choix documenté)
- Le prompt supposait une notification `display_notification` avec lien cliquable, sur le
  modèle de `action_print_repayment_schedule()`. Ce mécanisme ne fonctionne que comme retour
  d'une action déclenchée par un bouton, jamais depuis `create()`/`write()` appelés par le
  bouton Enregistrer standard d'une fiche. Utilisé à la place :
  `self.env['bus.bus']._sendone(..., 'simple_notification', ...)` (pattern standard Odoo 17,
  cf. `base_geolocalize`), qui affiche un toast mais sans lien cliquable intégré (ce service
  ne supporte que titre/message/type). Le lien réel vers le dossier est assuré par le champ
  `microfinance_current_loan_application_id` affiché en lecture seule (widget Many2one
  natif, cliquable). Compromis validé avec Micka.

### Non vérifié / à faire
- [ ] **Tests non exécutés réellement** : contrairement au chantier initial (9/9 passés sur
  la base SEFOR), cette extension n'a pu être vérifiée que par relecture statique
  (`py_compile`, XML bien formé) — aucun accès sudo à l'instance Odoo (utilisateur système
  `odoo`) ni identifiants de base de données dans cet environnement. À exécuter
  (`-u microfinance_loan_management --test-enable --test-tags
  /microfinance_loan_management:TestPartnerCreditSelection*`) avant mise en production.
- [ ] Rendu de la vue initiale (position, bascule du radio, style) avait été validé
  visuellement par Micka en cours de chantier ; le radio ayant depuis été retiré (cf.
  correctif ci-dessus), **le nouvel écran Microfinance > Configuration > Paramètres et le
  domaine du champ Produit piloté par la politique globale restent à valider visuellement**,
  sans capture ni test navigateur automatisé de notre côté.

## Fait
- [x] Modèles `microfinance.loan.progressive.program` / `.step` (contrainte
  `unique(product_id)`, cf. Lot 0 confirmé avec Micka) —
  `microfinance_loan_management/models/microfinance_loan_progressive_program.py`
- [x] Extension `microfinance.loan.product` : `progressive_step_ids`,
  `progressive_program_id`/`progressive_step_sequence`/`is_progressive_step` (computed,
  `store=True`) — `microfinance_loan_management/models/microfinance_loan_product.py`
- [x] Vue liste + formulaire (sous-liste étapes éditable, `widget="handle"`) sous
  **Microfinance > Configuration > Programmes progressifs** —
  `views/microfinance_loan_progressive_program_views.xml`, menu dans
  `views/microfinance_menus.xml`
- [x] Bandeau lecture seule sur la fiche produit ("Fait partie du programme progressif…")
  — `views/microfinance_loan_product_views.xml`
- [x] Sécurité : 8 lignes `ir.model.access.csv` (lecture pour Agent crédit/Finance/
  Auditeur, écriture pour Manager — Gestionnaire hérite via `implied_ids`, pas de ligne
  dédiée)
- [x] Champ `loan_product_id` (requis, domaine société) sur
  `microfinance.loan.application` — absent avant ce chantier, condition préalable
  nécessaire au calcul (confirmé avec Micka)
- [x] `progressive_eligibility_status`/`progressive_eligibility_message` (computed, non
  stockés) sur `microfinance.loan.application`, recherche cross-agency (`sudo()`, sans
  filtre société, même exception documentée que `microfinance_fond_credit.py`) —
  `models/microfinance_loan_application.py`
- [x] Statut "le plus favorable retenu" en cas de prêts multiples, classement
  `defaulted < prior_active < warning < eligible` — confirmé explicitement avec Micka
- [x] Retard historique reconstitué depuis `arrears_onset_date`/`arrears_cured_date` des
  échéances (pas les métriques de scoring courantes, à 0 sur un prêt clôturé) — formule
  confirmée avec Micka
- [x] Champ `closed_date` ajouté sur `microfinance.loan`, posé par `action_close()` —
  nécessaire pour dater le message d'éligibilité, absent avant ce chantier
- [x] Bandeau `alert` coloré (success/warning/danger selon statut) sur la vue formulaire
  du dossier, mention "Information indicative…", aucun bouton de workflow conditionné —
  `views/microfinance_loan_application_views.xml`
- [x] **Bug préexistant corrigé (hors périmètre initial, mais bloquant)** :
  `action_create_loan()` référençait un wizard inexistant
  (`microfinance.loan.application.create.loan.wizard`) — construit (formulaire minimal :
  produit pré-rempli depuis `loan_product_id`, montant, durée) —
  `wizard/microfinance_loan_application_create_loan_wizard.py` + vue associée. Écart déjà
  identifié à deux reprises dans `docs/ecarts_lpf.md` (chantier fonds bailleurs) avant ce
  chantier, désormais résolu.
- [x] Tests automatisés (`tests/test_loan_progressive_program.py`, 9 tests), **exécutés
  réellement** sur la base de développement SEFOR (`-u microfinance_loan_management
  --test-enable --test-tags`), pas seulement écrits/relus : produit indépendant
  (`not_applicable`), étape 1 (`not_applicable`), aucun prêt antérieur
  (`no_prior_loan`), prêt précédent actif (`prior_active`), prêt clôturé sans retard
  (`eligible`), prêt clôturé avec retard hors tolérance (`warning`), prêt radié
  (`defaulted`), plusieurs prêts — le plus favorable retenu (`eligible` malgré un
  `defaulted` concurrent), cas cross-agency (prêt pris dans une autre société). **9/9
  passent.**
- [x] Mise à jour de 3 sites de test existants (`test_application_workflow.py`,
  `test_field_visit.py`, `test_social_category_grid.py`) pour fournir `loan_product_id`
  désormais requis à la création d'un dossier — vérifiés toujours verts après
  modification.
- [x] `docs/ecarts_lpf.md` mis à jour (item 1 et 7 de "Écarts vs LPF"/"Points de
  décision" marqués résolus, nouvel item 8 sur le rang de prêt global LPF vs chaînage
  produit-à-produit CEFOR).

## À faire / incomplet
- [ ] `verification_disponibilite='at_request'` (chantier fonds bailleurs, sans rapport
  direct) reste sans effet réel : le nouveau wizard de création de crédit ne l'invoque
  pas — hors périmètre de ce câblage minimal, signalé dans `docs/ecarts_lpf.md`.
- [ ] Aucun rapport/PDF ni indicateur de tableau de bord pour le programme progressif —
  non demandé dans ce chantier.
- [ ] Le wizard de création de crédit est volontairement minimal (produit/montant/durée) :
  garanties, périodicité, fonds bailleur, comptes, scoring restent à saisir/calculer
  directement sur `microfinance.loan` après création, jamais dupliqués dans le wizard —
  comportement voulu, pas un manque.

## Incohérences relevées
- La suite de tests `TestEligibility` (`tests/test_eligibility.py`, préexistante, non
  modifiée) échoue actuellement sur la base SEFOR (5/25 tests de la session groupée) à
  cause d'un fonds de crédit rotatif actif réellement configuré pour l'agence CEFOR
  Isotry dans cette base de développement persistante (`_check_fond_disponibilite()`,
  chantier fonds bailleurs) — confirmé sans rapport avec ce chantier (trace d'erreur
  entièrement dans un autre module de code, jamais touché ici). Signalé, pas corrigé
  (hors périmètre).
- `microfinance.loan.progressive.program.step.product_id` référence un produit sans
  contrainte serveur imposant que ce produit appartienne à la même société que le
  programme (`program_id.company_id`) — un programme mono-société pourrait en théorie
  référencer une étape avec un produit d'une autre société via l'API. Pas bloquant en
  usage normal de l'interface (le domaine n'a pas été restreint, volontairement, car un
  programme peut être commun à toutes les sociétés) ; à signaler si Micka souhaite un
  contrôle plus strict.
