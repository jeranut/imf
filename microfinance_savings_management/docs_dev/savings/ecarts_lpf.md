# Écarts fonctionnels — `microfinance_savings_management` vs LPF (épargne)

Audit statique, lecture seule. Périmètre : `microfinance_savings_management` et ses points
d'intégration avec `microfinance_loan_management` (comptes, groupes de sécurité). Référentiel :
manuel fonctionnel LPF (Loan Performer), module épargne.

Convention des tableaux : **Existant** (implémenté et branché dans la logique), **Partiel**
(champ/mécanisme présent mais incomplet ou non appliqué), **Manquant** (absent du code).

---

## Correctifs appliqués (2026-07-11, session 1)

Suite à cet audit, deux écarts bloquants ont été corrigés (voir tableaux ci-dessous pour le détail,
mis à jour en conséquence) :

- **Contrôle chronologique des transactions** (§2) : implémenté via
  `_check_transaction_date_order` sur `microfinance.savings.transaction`, scopé par compte.
- **Plafond de retrait** (§2/§5) et **pénalité de retrait anticipé** (§5/§6/§7) : implémentés
  (`_check_withdrawal_limit` et `_compute_early_withdrawal_penalty`), avec ligne comptable
  séparée pour la pénalité.
- **Frais de tenue de compte** et **comptes papeterie/retenue de taxe/chèques rejetés** :
  restent non implémentés (nécessitent une refonte hors périmètre de ce correctif — nouveau
  mécanisme de prélèvement périodique pour le premier, nouveaux types de transaction pour les
  seconds). Les champs correspondants ont été **grisés en configuration** (`readonly=True` +
  `help=` explicite "Non implémenté — sans effet actuellement") pour ne plus induire un testeur
  en erreur.
- Le point garantie/apport (`upfront_apport` vs `microfinance.loan.guarantee`) n'a **pas** été
  touché en session 1 — décision métier prise depuis, traitée en session 3 (voir plus bas).

## Correctifs appliqués (2026-07-11, session 2)

Révision des deux mécanismes ajoutés en session 1, suite à relecture métier :

- **Plafond de retrait simplifié** : le cumul mensuel civil a été retiré (règle non demandée,
  absente du manuel LPF) — un seul comportement subsiste, le blocage par transaction
  individuelle (`withdrawal_limit_amount`). Le champ `withdrawal_limit_period` a donc été
  supprimé du produit (n'aurait plus eu qu'une valeur possible, ce qui aurait recréé une
  config morte). La dérogation utilise désormais son propre champ `bypass_withdrawal_limit`,
  indépendant de `bypass_min_balance` (les deux dérogations sont désormais séparées, y compris
  sur la transaction de clôture de compte qui active les deux).
- **Pénalité de retrait anticipé généralisée** : ne dépend plus uniquement de `maturity_date`
  (produit à terme). Un nouveau champ produit `min_retention_days` (délai minimum de rétention
  en jours, calculé depuis `account.opening_date`) déclenche la même pénalité sur **tout type de
  produit**, y compris l'épargne libre — conforme au manuel LPF. Si les deux échéances
  (`maturity_date` et `min_retention_days`) sont atteintes en même temps, la pénalité n'est
  jamais cumulée (un seul taux, une seule ligne comptable).
- Non traité (hors périmètre explicite de cette session) : case "pénalité obligatoire par
  défaut" au niveau institution — seulement évoquée en référence LPF dans la demande, pas dans
  la liste d'actions.
- Un **bug de test préexistant** a été localisé et corrigé à la demande, dans
  `microfinance_savings_management/tests/test_auto_debit.py`
  (`test_cron_isolates_failures_across_loans`, aucune modification de
  `microfinance_loan_management`) : le test réutilisait le même partenaire pour deux crédits
  actifs simultanément, ce que `_check_eligibility` interdit à raison (règle métier existante,
  pas un bug) sans `allow_second_loan`. Une fois corrigé (partenaires distincts), un second
  problème est apparu : le journal "cassé" du test n'avait en réalité aucun effet, Odoo
  provisionnant automatiquement un `default_account_id` pour tout journal cash/bank créé sans
  en préciser un — corrigé en utilisant `withdrawal_journal_id = False` plutôt qu'un journal
  incomplet.

Tests (session 1) : suite complète rejouée sur une copie jetable de la base SEFOR
(`sefor_test_scratch`, détruite après coup).
Tests (session 2) : suite complète rejouée sur **`savings_synthetic_test`**, une base
entièrement vierge et synthétique (créée par `createdb` puis installation fraîche des modules
via `-i`, sans copie d'aucune base réelle même jetable), détruite après coup — **0 échec, 0
erreur sur 54 tests**.

## Correctifs appliqués (2026-07-12, session 4)

Correction du point bloquant #6 (numérotation de compte non conforme au format agence+type+série,
cf. liste priorisée ci-dessous) : introduction de `res.company.agency_code`
(`microfinance_loan_management/models/res_company.py`) et bascule des séquences globales
`EP/%(year)s/NNNNN` (épargne) et `CR/%(year)s/NNNNN` (crédit) vers un format `AGENCE/TYPE/SÉRIE`
(épargne) / `AGENCE/SÉRIE` (crédit), scopé par société via une `ir.sequence` créée à la demande
par société (+ par type pour l'épargne) plutôt que pré-déclarée en XML — les agences restantes
(jusqu'à 25 au total) sont ajoutées manuellement au fil de l'eau par formulaire société, une
liste figée en XML n'aurait pas pu les couvrir à l'avance.

- **`agency_code` rendu obligatoire sans condition** (pas de gate `microfinance_context` comme
  sur `res.partner`) : vérifié concrètement avant implémentation que la base contenant les
  modules microfinance (MOWGLI) ne contient que des agences CEFOR (11/11 sociétés au moment de
  l'audit) — EAT/immobilier tournent sur des bases Postgres entièrement séparées sur cette
  instance, aucun `res.company` n'y est donc réellement partagé avec un usage non-microfinance.
  Une contrainte conditionnée au contexte aurait par ailleurs été inopérante en pratique : aucun
  écran dédié "création d'agence" n'existe côté microfinance, les sociétés se créent via le
  formulaire standard Réglages > Sociétés, qui ne transporte jamais `microfinance_context`.
  Implémenté via `required=True` sur le champ (seul mécanisme qui bloque de façon fiable une
  société jamais mentionnant `agency_code` du tout — un `@api.constrains` ne se déclenche que
  pour les champs présents dans les `vals` d'écriture, donc jamais pour un champ simplement
  omis) + un `create()`/`write()` explicites pour un message métier clair avant la contrainte
  SQL brute.
- **`microfinance.loan.application` ("dossier d'instruction de crédit") : tentative de
  numérotation abandonnée, modèle non fonctionnel découvert en cours de session.** Deux
  problèmes distincts trouvés en creusant l'écart de numérotation de ce modèle :
  1. Il appelait déjà `ir.sequence.next_by_code('microfinance.loan.application')` sans qu'aucune
     `ir.sequence` de ce code n'existe dans le module — son `name` restait donc en permanence à
     `'Nouveau'`.
  2. Plus grave : le fichier `models/microfinance_loan_application.py` (549 lignes, ajouté par
     le commit `6546bb2`) n'a **jamais** été importé dans `models/__init__.py` — le modèle n'a
     donc jamais existé dans le registre Odoo de cette instance. En tentant de l'enregistrer
     pour pouvoir tester la numérotation, la base MOWGLI a refusé de charger : le modèle
     référence 6 sous-modèles inexistants (`microfinance.loan.application.dependent`,
     `.guarantor.line`, `.document.line`, `.income.line`, `.field.visit`, `.social.score`),
     aucun n'étant défini nulle part dans le code. Remise en état hors périmètre de cette
     session (numérotation) — l'import a été **annulé** pour ne pas casser la base. Le code de
     numérotation reste présent dans `create()` de ce fichier (correct et prêt à l'emploi) mais
     **inerte et non testé** tant que ce modèle n'est pas réellement remis en état (créer les 6
     sous-modèles ou retirer les champs qui les référencent).
  Seul `microfinance.loan` (le crédit actif, modèle qui fonctionne) a donc reçu la numérotation
  `AGENCE/SÉRIE` en pratique.
- **Code de type de compte épargne (I/G/E/T)** dérivé du type de client
  (`res.partner.microfinance_client_type` : individuel/groupe/entreprise), sauf pour un produit
  à terme (`product_type = 'term_deposit'`) qui reçoit toujours le code T quel que soit le
  titulaire. Les 4 codes sont implémentés pour rester fidèle à la convention LPF, bien que CEFOR
  n'utilise aujourd'hui que Individuel/Entreprise (Groupe non activé).
- **Pas de garde-fou séparé au niveau de la numérotation** : `agency_code` étant `required=True`
  (contrainte `NOT NULL` en base), une société sans code est structurellement impossible —
  vérifié qu'un `UPDATE` SQL direct pour simuler ce cas échoue lui aussi sur la contrainte NOT
  NULL. Un `UserError` de repli dans `create()` aurait donc été du code mort.
- **Aucun conflit avec le préfixe de code produit** (`loan_product_code_prefix`/
  `savings_product_code_prefix`, `EP00001`/`CR00001`) : mécanisme entièrement disjoint, sur un
  modèle différent (`microfinance.loan.product`/`microfinance.savings.product`, pas
  `microfinance.loan`/`microfinance.savings.account`), vérifié avant implémentation.

Tests (session 4) : nouveaux fichiers `test_agency_code.py` (crédit) et `test_agency_numbering.py`
dans les deux modules ; 12 créations de société existantes dans la suite de tests (hors périmètre
de cette session) ont dû être mises à jour pour fournir un `agency_code`, la contrainte étant
désormais inconditionnelle. Suite complète rejouée sur **MOWGLI** (base réelle, seule base avec
les modules microfinance installés) : **178 tests, 0 erreur**, 3 échecs préexistants et
**sans lien avec cette session** (`test_fee.test_disburse_nets_fee_in_single_move`,
`test_provision.test_post_provisions_requires_product_accounts_configured`,
`test_write_off.test_write_off_requires_product_account_configured`) — confirmés identiques en
rejouant la suite sur le code d'avant session (via `git stash`) avant de conclure qu'ils étaient
hors périmètre.

## Correctifs appliqués (2026-07-11, session 3)

Décision métier actée : remplacement complet du mécanisme `upfront_apport` par le mécanisme
LPF « épargne garantie de crédit ». `microfinance.loan.guarantee` (garanties physiques, ratios
de valorisation) n'a **pas** été touché — reste le circuit séparé pour les garanties physiques.

- **Localisation préalable** : `upfront_apport` et tous les champs associés
  (`savings_apport_ratio`, `savings_apport_required`, `savings_apport_verified`) vivaient
  entièrement dans `microfinance_savings_management` (extensions `_inherit` de
  `microfinance.loan.product` et `microfinance.loan`), **pas** dans
  `microfinance_loan_management` comme le supposait le brief initial — correction de périmètre
  du même type que celle déjà faite sur les groupes de sécurité (cf. plus bas).
- **Dépendance de module** : `microfinance_loan_management` ne doit **pas** dépendre de
  `microfinance_savings_management` — ce serait une dépendance circulaire (c'est déjà l'inverse).
  Comme le mécanisme était déjà porté par une extension côté module épargne, aucune dépendance
  supplémentaire n'était nécessaire ; l'architecture existante gère déjà correctement cette
  vérification croisée. Le point 4 de la demande ne s'appliquait donc pas tel que formulé.
- **Nouveaux champs produit crédit** (`models/microfinance_loan_product_extension.py`) :
  `guarantee_savings_percent` (%, remplace `savings_apport_ratio`) et
  `guarantee_savings_product_id` (Many2one produit épargne dédié, indépendant de
  `savings_product_id` qui reste réservé à `target_during_loan`), avec contrainte de
  cohérence (pourcentage renseigné ⇒ produit requis).
- **Vérification au moment de la demande** (`models/microfinance_loan_extension.py`,
  `_check_guarantee_savings_eligibility`, appelée depuis `_check_eligibility` donc dès
  `action_submit`) : solde réel du client recalculé comme la somme de ses comptes **actifs**
  sur le produit d'épargne garantie configuré (pas un compte unique présélectionné à l'avance,
  contrairement à l'ancien mécanisme) ; réutilise le champ `balance` déjà calculé sur
  `microfinance.savings.account`, sans recalcul depuis les transactions. `UserError` explicite
  (requis / solde / manquant) si insuffisant. Exemption des clients `microfinance_client_type
  == 'company'`.
- **Migration de données** : vérifiée avant modification (pas devinée) — requête sur SEFOR,
  seule base réelle avec le module installé, confirmant **aucun enregistrement** avec
  `savings_requirement_type = 'upfront_apport'`. Aucun script de migration nécessaire.
- **Suppression** : sélection `upfront_apport` retirée de `savings_requirement_type` (ne
  garde que `none`/`target_during_loan`, mécanisme LPF distinct non concerné par ce
  correctif) ; champs `savings_apport_ratio`, `savings_apport_required`,
  `savings_apport_verified` supprimés ; `test_upfront_apport.py` remplacé par
  `test_guarantee_savings.py` (5 tests : garantie suffisante, insuffisante avec message de
  montant manquant, pourcentage à 0 = pas de contrôle, client Société exempté, contrainte de
  configuration).
- Non traité (hors liste d'actions de la demande, seulement évoqué en référence LPF) : case
  "pénalité obligatoire par défaut" au niveau institution — cf. session 1/2, toujours en
  attente.

Tests (session 3) : suite complète rejouée sur **`guarantee_synthetic_test`**, base à nouveau
entièrement vierge et synthétique (même protocole que session 2 : `createdb` + installation
fraîche `-i`, détruite après coup) — **0 échec, 0 erreur sur 56 tests**.

---

## Correction préalable sur le périmètre sécurité

Le brief de cet audit partait de l'hypothèse que le module « réutilise les groupes de
`microfinance_loan_management`, sans groupe épargne dédié ». Ce n'est **pas** ce que montre le
code : le module crée deux groupes dédiés `group_savings_agent` et `group_savings_manager`
([security/savings_security.xml:3-11](../../security/savings_security.xml#L3-L11)), en plus de
donner un accès lecture seule aux groupes `microfinance_loan_management.group_microfinance_manager`
et `.group_microfinance_auditor`. Voir détail en section 9. Le reste de l'audit part donc de l'état
réel du code, pas de l'hypothèse initiale.

---

## 1. Produits d'épargne

| Point LPF | État | Référence |
|---|---|---|
| Modèle produit configurable (taux, soldes min, etc.) | **Existant** | `microfinance.savings.product` — taux d'intérêt, méthode de solde, fréquence de capitalisation, montants min, plafonds, frais, pénalité, durée : [models/microfinance_savings_product.py:29-74](../../models/microfinance_savings_product.py#L29-L74) |
| 2 produits par défaut (épargne libre / épargne garantie de crédit) | **Manquant** | `product_type` a bien 2 valeurs pertinentes (`voluntary`, `compulsory`) + `term_deposit` ([microfinance_savings_product.py:37-41](../../models/microfinance_savings_product.py#L37-L41)), mais aucun enregistrement `data/*.xml` ne crée de produit : à créer manuellement à l'installation, pour chaque société. |
| Produit marquable "par défaut" pour préremplir les écrans | **Manquant** | Aucun champ `is_default`/équivalent sur `microfinance.savings.product`, ni logique de préremplissage à la création d'un compte (`product_id` reste un champ obligatoire sans défaut dans [models/microfinance_savings_account.py:16](../../models/microfinance_savings_account.py#L16)). |

## 2. Dépôts et retraits

| Point LPF | État | Référence |
|---|---|---|
| Ordre chronologique des transactions (pas de saisie antidatée) | **Existant (corrigé le 2026-07-11)** | `_check_transaction_date_order` refuse toute transaction dont la date est strictement antérieure à la date maximale des autres transactions déjà comptabilisées sur le même compte (scopé par `account_id`, une date égale reste acceptée) : [models/microfinance_savings_transaction.py:77-95](../../models/microfinance_savings_transaction.py#L77-L95). |
| Numérotation de compte (agence + type I/G/B + série) | **Manquant** | Séquence générique unique, non ventilée par agence ni par type de client : `EP/%(year)s/00001`, `company_id` vide (séquence globale, pas par société) — [data/ir_sequence_data.xml:3-9](../../data/ir_sequence_data.xml#L3-L9). Aucun `res.partner`/agence dans le format. |
| Distinction D / W / I / T et mode cash/chèque/autre | **Partiel** | `transaction_type` couvre `deposit`/`withdrawal`/`interest_credit`/`fee_debit`/`auto_debit`/`transfer` ([microfinance_savings_transaction.py:16-23](../../models/microfinance_savings_transaction.py#L16-L23)) — plus fin que LPF sur D/W/I. `payment_method` couvre cash/virement/mobile money mais **pas de "chèque"** explicite ([microfinance_savings_transaction.py:26-30](../../models/microfinance_savings_transaction.py#L26-L30)), alors que le produit expose un compte dédié aux chèques rejetés (`account_commission_cheques_rejetes_id`, voir ci-dessous). Le type `transfer` existe dans la sélection mais n'a **pas** de champ "compte destinataire" et sa comptabilisation retombe sur la même branche que `withdrawal` ([microfinance_savings_transaction.py:106-119](../../models/microfinance_savings_transaction.py#L106-L119)) : ce n'est donc pas un vrai virement entre deux comptes épargne, seulement un retrait libellé différemment. |
| Papeterie/commission/pénalité ventilées sur des comptes distincts du compte épargne | **Partiel / Manquant** | Les comptes `account_papeterie_id`, `account_retenue_taxe_id`, `account_commission_cheques_rejetes_id` sont configurables sur le produit ([microfinance_savings_product.py:161-180](../../models/microfinance_savings_product.py#L161-L180), exposés en vue [views/microfinance_savings_product_views.xml:82-86](../../views/microfinance_savings_product_views.xml#L82-L86)) mais **ne sont référencés nulle part** dans `_prepare_transaction_move` (confirmé par grep sur tout le module) : ce sont des champs de configuration morts, sans effet. Seul `account_commission_id` (frais de tenue de compte, type `fee_debit`) est réellement utilisé ([microfinance_savings_transaction.py:107-110](../../models/microfinance_savings_transaction.py#L107-L110)). |
| Retrait = papeterie + commission + pénalité + montant déduits ensemble ; dépôt = épargne seule | **Partiel** | Le dépôt est bien une écriture à 2 lignes qui ne mouvemente que le compte épargne ([microfinance_savings_transaction.py:102-105](../../models/microfinance_savings_transaction.py#L102-L105)), conforme à LPF. Côté retrait, il n'existe **pas** de transaction composée : chaque frais/pénalité/retrait est une transaction séparée (`withdrawal` puis `fee_debit` manuel), donc plusieurs écritures indépendantes plutôt qu'une ventilation en une seule opération. |
| Plafond de retrait (`withdrawal_limit_amount`) | **Existant (corrigé le 2026-07-11, simplifié en session 2)** | `_check_withdrawal_limit` bloque un retrait (type `withdrawal` uniquement) dont le montant dépasse le plafond configuré, transaction par transaction — le cumul mensuel civil envisagé en session 1 a été retiré (non demandé, absent du manuel LPF) et le champ `withdrawal_limit_period` supprimé du produit. Dérogation via son propre champ `bypass_withdrawal_limit`, indépendant de `bypass_min_balance` : [models/microfinance_savings_transaction.py:103-118](../../models/microfinance_savings_transaction.py#L103-L118). |
| Frais de tenue de compte périodiques (`maintenance_fee_amount`/`_frequency`) | **Manquant (config grisée)** | Champs passés en `readonly=True` avec `help="Non implémenté — sans effet actuellement"` ([microfinance_savings_product.py:64-72](../../models/microfinance_savings_product.py#L64-L72)) : aucun cron ni méthode ne les applique (contrairement aux intérêts, qui ont bien un cron de capitalisation). Implémenter un vrai prélèvement périodique est hors périmètre du correctif du 2026-07-11 (nécessite un nouveau mécanisme de cron dédié). |

## 3. Comptes de garantie

| Point LPF | État | Référence |
|---|---|---|
| Blocage de la demande si solde de garantie < x % du montant demandé | **Existant (corrigé le 2026-07-11, session 3)** | `upfront_apport` a été retiré et remplacé par le mécanisme LPF exact : `guarantee_savings_percent` + `guarantee_savings_product_id` sur `microfinance.loan.product` ([models/microfinance_loan_product_extension.py](../../models/microfinance_loan_product_extension.py)), vérifiés dans `_check_guarantee_savings_eligibility`, appelée depuis `_check_eligibility` (donc dès `action_submit`, *au moment de la demande*, plus seulement à l'approbation) : [models/microfinance_loan_extension.py](../../models/microfinance_loan_extension.py). Le solde vérifié est la somme des comptes actifs du client sur le produit d'épargne garantie configuré (pas un compte unique présélectionné), recalculée à chaque évaluation — donc plus de fenêtre "approuvé puis solde baissé avant décaissement" non détectée comme avec l'ancien mécanisme. |
| Ce mécanisme est-il rattaché au modèle "garantie" de LPF ? | **Clarifié** | Le modèle physique `microfinance.loan.guarantee` ([microfinance_loan_management/models/microfinance_loan_guarantee.py:16-65](../../../microfinance_loan_management/models/microfinance_loan_guarantee.py#L16-L65), non modifié) reste le mécanisme séparé pour les garanties physiques (terrain/véhicule/maison/meuble/salaire/caution), avec ses ratios de valorisation. L'épargne garantie de crédit est un second circuit, désormais nommé explicitement comme tel (`guarantee_savings_*`, plus `upfront_apport`) — les deux mécanismes restent disjoints par conception (l'un porte sur un bien/une caution, l'autre sur un solde d'épargne), mais la terminologie ne prête plus à confusion. |
| Champ garantie masqué/inaccessible pour comptes entreprise/institution | **Existant (corrigé le 2026-07-11, session 3)** | `_check_guarantee_savings_eligibility` ne s'applique pas si `partner_id.microfinance_client_type == 'company'` (skip explicite) : [models/microfinance_loan_extension.py](../../models/microfinance_loan_extension.py). |
| Épargne obligatoire liée à un crédit actif : protection à la clôture | **Existant** | `action_close` refuse de clôturer un compte épargne `compulsory` tant que le crédit lié est `active` : [models/microfinance_savings_account.py:114-123](../../models/microfinance_savings_account.py#L114-L123). |

## 4. Calcul des intérêts sur épargne

| Point LPF | État | Référence |
|---|---|---|
| Solde minimum mensuel vs soldes courants au jour le jour | **Existant, et plus complet** | `balance_method` propose 3 méthodes (min / moyenne pondérée par jours / clôture), pas seulement 2 : sélection [microfinance_savings_product.py:43-47](../../models/microfinance_savings_product.py#L43-L47), calcul [models/microfinance_savings_account.py:150-178](../../models/microfinance_savings_account.py#L150-L178). |
| Période d'intérêt configurable 1 à 12 mois | **Partiel** | `capitalization_frequency` est un choix fermé (mensuel/trimestriel/annuel), pas une durée libre 1-12 mois : [microfinance_savings_product.py:48-52](../../models/microfinance_savings_product.py#L48-L52). Suffisant pour la majorité des cas LPF standards, mais moins souple. |
| Montant minimum ne portant pas intérêt, par type de compte | **Manquant** | Aucun seuil de franchise dans `cron_capitalize_interest` : le taux s'applique dès que `reference_balance > 0` ([models/microfinance_savings_account.py:186-192](../../models/microfinance_savings_account.py#L186-L192)). |
| Compte "inactif" exclu de l'intérêt | **Existant** | `cron_capitalize_interest` ne traite que les comptes `state = 'active'` ([microfinance_savings_account.py:183](../../models/microfinance_savings_account.py#L183)) ; un compte devenu `dormant` via `cron_detect_dormant_accounts` ([microfinance_savings_account.py:204-214](../../models/microfinance_savings_account.py#L204-L214)) est donc naturellement exclu de la capitalisation suivante. |
| Ventilation de l'intérêt par catégorie client (individuel/groupe/institution) | **Existant** | `_get_account('interet_paye', partner)` sélectionne le bon compte selon `microfinance_client_type` : [microfinance_savings_product.py:215-223](../../models/microfinance_savings_product.py#L215-L223), utilisé dans [microfinance_savings_transaction.py:92-96](../../models/microfinance_savings_transaction.py#L92-L96). |
| Mode simulation (calcul sans mise à jour) | **Manquant** | `cron_capitalize_interest` crée et comptabilise directement la transaction ([microfinance_savings_account.py:193](../../models/microfinance_savings_account.py#L193)) ; pas de mode "dry-run" pour prévisualiser un lot d'intérêts avant validation. |

## 5. Configuration épargne (paramétrage)

| Point LPF | État | Référence |
|---|---|---|
| Soldes minima par produit, blocage des retraits en dessous | **Existant** | `min_balance` + `_check_minimum_balance` : [microfinance_savings_transaction.py:59-73](../../models/microfinance_savings_transaction.py#L59-L73), avec dérogation explicite via `bypass_min_balance`. |
| Protection contre le découvert (on/off) | **Manquant** | Aucune mention dans le code (recherche exhaustive "découvert"/"overdraft" sans résultat). Le solde ne peut de fait pas devenir négatif grâce à `min_balance` (par défaut 0), mais il n'y a pas de paramètre dédié ni de distinction conceptuelle. |
| Pénalité de retrait anticipé, "obligatoire par défaut" | **Existant (corrigé le 2026-07-11, généralisé en session 2), sans l'option "obligatoire par défaut"** | `_compute_early_withdrawal_penalty` applique automatiquement la pénalité configurée sur tout retrait comptabilisé avant l'une ou l'autre de deux échéances (jamais cumulées) : `maturity_date` (produit à terme uniquement) **ou** `min_retention_days` depuis `account.opening_date` (n'importe quel produit, y compris épargne libre — ajout de session 2, conforme au manuel LPF). Ligne comptable séparée sur `account_penalites_id` : [models/microfinance_savings_transaction.py:120-144,187-201](../../models/microfinance_savings_transaction.py#L120-L201). Il n'y a en revanche toujours pas de notion "obligatoire par défaut" au niveau institution (le taux à 0 désactive simplement la pénalité) — évoqué en référence dans la demande de session 2 mais absent de sa liste d'actions, donc non traité. |
| Désactiver la passation automatique au grand livre (épargne gérée en banque externe) | **Manquant** | `action_post` génère systématiquement un `account.move` pour toute transaction ([microfinance_savings_transaction.py:135-152](../../models/microfinance_savings_transaction.py#L135-L152)) ; pas d'option produit pour découpler suivi épargne et comptabilisation. |
| Suivi de l'épargne au niveau des membres de groupe, non réversible | **Manquant** | `partner_id` sur `microfinance.savings.account` accepte n'importe quel partenaire, y compris un membre individuel d'un groupe (le modèle `microfinance.client.group.member` existe côté crédit), donc l'usage est *possible* en configurant les comptes un par un — mais il n'y a ni bascule dédiée au niveau du groupe, ni page séparée, ni garde applicative rendant le choix non réversible comme le décrit LPF. |

## 6. Dépôts à terme

| Point LPF | État | Référence |
|---|---|---|
| Modèle dédié avec bornes min/max (montant, taux, durée) par produit | **Partiel — hors scope confirmé ?** | `product_type = 'term_deposit'` existe avec `term_months` (valeur unique, pas une plage min/max) : [microfinance_savings_product.py:37-41](../../models/microfinance_savings_product.py#L37-L41). `maturity_date` est calculée sur le compte ([microfinance_savings_account.py:60-66](../../models/microfinance_savings_account.py#L60-L66)) et un filtre "échéance sous 30 jours" existe en vue ([views/microfinance_savings_account_views.xml:27](../../views/microfinance_savings_account_views.xml#L27)). Depuis le correctif du 2026-07-11, la pénalité de retrait anticipé (`early_withdrawal_penalty_rate`) est bien appliquée automatiquement avant échéance (cf. section 5). Il n'y a en revanche toujours aucune borne min/max amount/rate/duration configurable par produit, ni de blocage strict du retrait avant échéance (le retrait reste possible, juste pénalisé) — le comportement métier du dépôt à terme est donc plus avancé qu'avant mais reste incomplet. **À faire trancher avec Micka** : traiter comme MVP suffisant ou le déclarer explicitement hors périmètre pour les bornes min/max restantes. |

## 7. Comptabilisation automatique

| Point LPF | État | Référence |
|---|---|---|
| Dépôt : Caisse/Banque (débit) → Épargne (crédit), lignes papeterie/commission séparées | **Partiel** | Écriture à 2 lignes générée correctement (caisse/banque vs épargne, [microfinance_savings_transaction.py:102-105](../../models/microfinance_savings_transaction.py#L102-L105)) mais sans ventilation papeterie/commission (cf. section 2 — comptes configurés mais non utilisés). |
| Retrait : Épargne (débit) → Papeterie + Pénalité + Caisse (crédit) | **Partiel (amélioré le 2026-07-11)** | Depuis le correctif, un retrait avant `maturity_date` (produit à terme) ou avant `min_retention_days` (tout produit, ajout de session 2) génère une écriture à 3 lignes (épargne débit / pénalité crédit / caisse crédit du net) : [microfinance_savings_transaction.py:187-206](../../models/microfinance_savings_transaction.py#L187-L206). Il manque toujours la ligne papeterie (compte configuré mais non utilisé, cf. section 2) — celle-ci nécessiterait toujours une transaction `fee_debit` séparée. |
| Intérêt : Intérêt sur épargne (débit) → Épargne (crédit) | **Existant** | [microfinance_savings_transaction.py:92-105](../../models/microfinance_savings_transaction.py#L92-L105). |
| Utilisation de `_get_account(poste, partner)` plutôt que comptes en dur | **Existant** | Confirmé : tous les comptes sont résolus via `product._get_account(kind, partner)` ([microfinance_savings_product.py:215-223](../../models/microfinance_savings_product.py#L215-L223)) ou directement les `Many2one` du produit — aucun ID de compte en dur dans `_prepare_transaction_move`. **Flag pour revue manuelle** conservé : la sélection par `partner.microfinance_client_type` mérite un test live pour confirmer le bon compte est pris pour un partenaire "group" vs "individual" vs "company". |
| Filtrage `company_id`/agence sur les comptes | **Existant** | Domaine `[('company_id', '=', company_id)]` sur tous les champs `account.account`/`account.journal` du produit ([microfinance_savings_product.py:79,84,89,...](../../models/microfinance_savings_product.py#L79)) + règles de cloisonnement multi-société ([security/microfinance_company_rules.xml](../../security/microfinance_company_rules.xml)) + tests dédiés `test_multi_company.py`. Cohérent avec l'audit multi-société déjà fait côté crédit. |

## 8. Rapports

Aucun rapport d'analyse n'existe au-delà d'un reçu de transaction imprimable
([report/savings_receipt_report.xml](../../report/savings_receipt_report.xml)). Le menu "Balance
épargne" ([views/microfinance_savings_menus.xml:13-17](../../views/microfinance_savings_menus.xml#L13-L17))
n'est **pas** un rapport dédié : c'est la vue liste standard des comptes filtrée/groupée par
produit, sans calcul de solde à une date antérieure ni de relevé détaillé. Manquent, comme
attendu :
- Soldes à date (autre que la date du jour, puisque `balance` est un champ calculé stocké sur l'état courant, pas historisé).
- Soldes de période (variation sur intervalle).
- Relevé de compte (extrait chronologique avec solde courant après chaque ligne).
- Totaux par lot/agence.

## 9. Sécurité

| Point | État | Référence |
|---|---|---|
| Groupes dédiés `group_microfinance_savings_*` créés par erreur ? | **Correction du périmètre** — le module crée volontairement `group_savings_agent`/`group_savings_manager` (nommés sans le préfixe `microfinance_savings_`), ce n'est pas une erreur mais un choix explicite non documenté dans le brief initial. | [security/savings_security.xml:3-11](../../security/savings_security.xml#L3-L11) |
| Cohérence `ir.model.access.csv` avec ces groupes | **Existant, avec une incohérence mineure** | `group_savings_agent` : lecture/écriture/création sur compte et transaction, pas de suppression ; `group_savings_manager` : CRUD complet ; `microfinance_loan_management.group_microfinance_manager`/`.group_microfinance_auditor` : lecture seule sur produit/compte/transaction. **Incohérence** : `group_microfinance_finance` a un accès lecture au modèle compte ([security/ir.model.access.csv:9](../../security/ir.model.access.csv#L9)) mais **aucune** ligne équivalente pour le modèle transaction — un utilisateur "Finance" côté crédit peut voir les comptes épargne mais pas leur détail de transactions. À confirmer si volontaire. |
| Cloisonnement multi-société | **Existant** | `ir.rule` avec `groups=[]` (s'applique à tout le monde, y compris managers/auditeurs) sur produit/compte/transaction : [security/microfinance_company_rules.xml](../../security/microfinance_company_rules.xml), testé dans `test_multi_company.py`. |

---

## Liste priorisée des écarts bloquants avant test live

1. ~~**Config produit trompeuse (« morte »)**~~ — **Corrigé le 2026-07-11** pour
   `withdrawal_limit_amount` (simplifié en session 2 : plafond par transaction uniquement,
   `withdrawal_limit_period` supprimé) et `early_withdrawal_penalty_rate` (désormais appliqué
   sur tout produit via `maturity_date` et/ou le nouveau `min_retention_days`, ajouté en session
   2). `maintenance_fee_amount`/`_frequency`, `account_papeterie_id`, `account_retenue_taxe_id`,
   `account_commission_cheques_rejetes_id` restent sans effet mais sont maintenant **grisés en
   configuration** avec un `help=` explicite ("Non implémenté — sans effet actuellement") : plus
   de risque de confusion silencieuse pour un testeur, reste à trancher/planifier leur
   implémentation complète (hors périmètre de ces correctifs).
2. **`transfer` n'est pas un virement** — le type de transaction existe dans la sélection UI mais
   se comporte comme un retrait simple (pas de compte destinataire, pas de double écriture entre
   deux comptes épargne). Risque de mauvaise utilisation en test live si un agent s'attend à un
   vrai virement entre comptes.
3. ~~**Absence de contrôle chronologique des transactions**~~ — **Corrigé le 2026-07-11** :
   toute transaction antidatée par rapport à la dernière transaction comptabilisée du même compte
   est désormais bloquée (`_check_transaction_date_order`).
4. ~~**Terminologie "garantie" ambiguë entre les deux modules**~~ — **Corrigé le 2026-07-11
   (session 3)** : `upfront_apport` a été retiré et remplacé par le mécanisme LPF exact,
   nommé explicitement `guarantee_savings_percent`/`guarantee_savings_product_id`, avec
   vérification dès la demande de crédit (pas seulement au décaissement) et exemption des
   clients de type Société. `microfinance.loan.guarantee` (garanties physiques) reste le
   mécanisme séparé, non modifié.
5. **Aucun produit d'épargne pré-créé** — sans les 2 produits par défaut, le premier testeur ne
   pourra rien saisir tant qu'un produit n'aura pas été configuré manuellement (comptes PCEC,
   journaux, taux). À préparer en amont du test live plutôt qu'à découvrir en live.
6. ~~**Numérotation de compte non conforme au format agence+type+série**~~ — **Corrigé le
   2026-07-12 (session 4) pour l'épargne (`microfinance.savings.account`) et le crédit actif
   (`microfinance.loan`)** : `res.company.agency_code` + format `AGENCE/TYPE/SÉRIE` (épargne) et
   `AGENCE/SÉRIE` (crédit), scopé par société. **`microfinance.loan.application` (dossier
   d'instruction) non couvert** : modèle jamais enregistré dans le registre Odoo de cette
   instance (jamais importé dans `models/__init__.py`) et référençant 6 sous-modèles inexistants
   — remise en état hors périmètre, voir détail en tête de document.
7. **Dépôts à terme incomplets** — la pénalité de retrait anticipé est désormais appliquée
   (2026-07-11), mais les bornes min/max (montant, taux, durée) par produit restent absentes ; à
   trancher explicitement "MVP suffisant" vs "hors scope" pour ce qui reste.

## Points jugés hors scope confirmé (déjà couverts correctement)

- Ventilation comptable par catégorie client (individuel/groupe/entreprise), multi-société : bien
  implémentée et testée, pas d'écart.
- Calcul d'intérêt par solde minimum/moyen/clôture : plus complet que le strict minimum LPF.
- Sécurité/cloisonnement multi-société : conforme au pattern déjà audité côté crédit.
