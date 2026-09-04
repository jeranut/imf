# Lot 0 — Conteneur épargne auto-créé, synchronisé avec le compte crédit du client

Audit en lecture seule (code + SQL `SELECT` sur SEFOR). **Aucune modification de code, de
séquence, ni de donnée.**

## Correction préalable à un audit précédent - à ne pas manquer

**`docs_dev/epargne_exigee_display/AUDIT_COMPLEMENT_credit_lie.md` (31/08/2026, section 1)
affirmait à tort "aucun `create()` programmatique de ce modèle n'existe dans le code
applicatif" pour `microfinance.savings.account`.** Faux : le grep utilisé
(`savings.account'\].create`) ratait le pattern réel du code, qui sépare la variable du
`.create()` :
```python
Account = self.env['microfinance.savings.account']
...
return Account.create({...})
```
**Il existe bel et bien une création automatique** :
`res.partner._get_or_create_microfinance_savings_principal_account()`
(`microfinance_savings_management/models/res_partner.py:35-58`), déclenchée depuis
`res.partner.create()` (ligne 17-30), **pas depuis un crédit** - dès qu'un contact est créé
avec `microfinance_partner_type == 'client'` (et uniquement dans `microfinance_context`).
Ouvre un compte réel (solde, transactions) sur `company.microfinance_savings_default_product_id`
- silencieux (pas d'erreur) mais notifié à l'utilisateur si aucun produit par défaut n'est
configuré pour l'agence. Un test dédié le confirme explicitement :
`test_dossier_creation_no_longer_opens_principal_savings_account` (l'ancien déclencheur, au 1er
dossier de crédit, a été délibérément retiré lors d'un correctif antérieur - décision déjà
actée par Micka, à ne pas réintroduire par erreur).

**Conséquence directe pour ce chantier : le "conteneur épargne" demandé ici (déclenché au 1er
crédit) et ce mécanisme existant (déclenché à la création du client) se chevauchent
potentiellement et doivent être réconciliés avec Micka avant le Lot 1** - cf. section "Point de
décision critique" plus bas. Le reste de ce rapport traite néanmoins des 6 points demandés tels
que posés.

## 1. Mécanisme existant de `microfinance.loan.account`

**Déclencheur** : `microfinance.loan.create()` (`microfinance_loan.py:224-236`), pas à la
soumission ni à l'approbation - au moment même où le PREMIER (ou n'importe quel) crédit est créé :
```python
if not vals.get('loan_account_id') and vals.get('partner_id'):
    partner = self.env['res.partner'].browse(vals['partner_id'])
    vals['loan_account_id'] = partner._get_or_create_microfinance_loan_account().id
```
`_get_or_create_microfinance_loan_account()` (`res_partner.py:148-160`) est idempotent
(recherche avant création, contrainte SQL `unique(partner_id, company_id)`) - **aucune
condition sur `microfinance_partner_type`**, contrairement au déclencheur savings principal
ci-dessus (asymétrie constatée en réel, cf. section 6).

**Numérotation du conteneur (`microfinance.loan.account.name`)** - **pas une séquence dédiée en
premier lieu** : `_get_loan_account_name()` (`microfinance_loan_account.py:39-58`) réutilise
directement `partner.microfinance_account_number` (le numéro de compte permanent du client,
format `AGENCE/NNNNNN`, attribué une seule fois à la création du client via la séquence
`microfinance.partner.account` - `res_partner.py:108-115`) **tel quel comme nom du conteneur**.
La séquence indépendante `microfinance.loan.account` (via
`_get_next_available_loan_account_name`) n'est qu'un **repli**, pour les cas où le client n'a
pas encore de `microfinance_account_number` (partner pas encore reconnu comme client à ce
moment).

**Numérotation des crédits individuels** : séquence **distincte**, `microfinance.loan.agency`
(`microfinance_loan.py:232`), partagée entre **tous les clients de l'agence** (pas par client) -
confirmé exactement comme supposé dans la demande (IS/000020, 21, 25... suite agence, pas liée
au numéro du client).

**Mécanisme générique des séquences** (`res.company._get_or_create_numbering_sequence`,
`res_company.py:34-50`) : créées **à la demande**, une par société (`company_id` sur
`ir.sequence`), jamais pré-déclarées en XML - ajouter une nouvelle séquence pour l'épargne
(conteneur et/ou individuel partagé) ne demande aucune migration de structure, juste un nouveau
`code` string réutilisant ce même helper.

## 2. Structure actuelle de `microfinance.savings.account`

**Aucun champ auto-référencé (parent/conteneur) n'existe aujourd'hui.** Champs pertinents déjà
cartographiés (audit précédent) : `partner_id`, `product_id` (chaque compte a TOUJOURS un
produit - pas de notion de compte "sans produit"), `microfinance_loan_id` (jamais alimenté en
pratique, cf. audit `compulsory`), `balance`/`transaction_ids`/`state` (un compte est un objet
métier complet, pas un conteneur léger comme `microfinance.loan.account`).

**Numérotation actuelle, déjà à trois niveaux mais SANS conteneur réel** (`_get_savings_account_
name`, `microfinance_savings_account.py:70-92`) :
- Code type dérivé du produit (`_PRODUCT_TYPE_CODE = {'voluntary': 'I', 'compulsory': 'G',
  'term_deposit': 'T'}`).
- **1er compte d'un type donné pour un client** : réutilise directement
  `AGENCE/TYPE/SUFFIXE_DU_CLIENT` (ex. `IS/000012` → `IS/I/000012`) - **exactement le même
  procédé que le conteneur crédit, mais appliqué au premier COMPTE RÉEL lui-même, pas à un
  conteneur séparé**.
- **Compte supplémentaire du même type** : séquence indépendante **par type de code**
  (`microfinance.savings.account.%s % type_code` - donc déjà 3 séquences distinctes I/G/T,
  partagées entre clients pour ce type).

**Écart structurel important avec la demande** : la demande veut que **même le 1er produit
épargne d'un client** tire son numéro d'une séquence partagée (comme les crédits individuels
dès le premier), le numéro de base (`IS/I/000012`) étant réservé à un **conteneur séparé, sans
produit**. Aujourd'hui, le 1er compte réel EST ce numéro de base - il n'y a pas de conteneur
distinct. Adopter la demande telle quelle change donc le comportement de numérotation du **1er
compte de chaque client**, pas seulement une addition - impact sur les tests existants
(`test_savings_account_number_derivation.py`, 6 tests, tous à revoir) et potentiellement sur des
références déjà communiquées à des clients réels (cf. volumétrie ci-dessous, 3 comptes réels
concernés).

**Volumétrie réelle (SEFOR, lecture seule)** : **3 comptes épargne au total**, un par client/
entité, aucun avec plus d'un compte (`GROUP BY partner_id HAVING count(*) > 1` → 0 résultat).
Compatible avec une restructuration en hiérarchie sans volume à migrer en masse, mais révèle une
incohérence réelle à anticiper (section 6).

## 3. Séquences existantes/à créer pour l'épargne

Confirmé : **3 séquences déjà existantes**, une par type de produit
(`microfinance.savings.account.I`, `.G`, `.T`) - c'est déjà la "séquence épargne (par type)"
demandée au point 4 de la spec métier, **déjà partagée entre clients**, déjà indépendante de la
séquence crédit. **Rien à créer de ce côté.** Ce qui manque réellement :
- Une séquence (ou une dérivation directe, comme pour `microfinance.loan.account`) pour nommer
  le **conteneur** lui-même (`IS/I/000012`), aujourd'hui absent en tant qu'enregistrement.
- Une décision sur le sort du 1er compte de chaque type : doit-il désormais TOUJOURS passer par
  la séquence par type (comme un 2ème compte aujourd'hui), libérant le numéro de base pour le
  seul conteneur ?

## 4. Point de déclenchement pour la création automatique

**Deux candidats concurrents existent déjà dans le code, avec des sémantiques différentes** (cf.
correction en tête de rapport) :
- **`res.partner.create()`** (mécanisme "compte principal" existant) - déclenché dès la
  reconnaissance du client, indépendamment de tout crédit.
- **`microfinance.loan.create()`** (mécanisme demandé ici, "conteneur épargne") - déclenché au
  1er crédit, symétrique du conteneur crédit.

Techniquement, répliquer exactement le patron `microfinance.loan.account` (lazy, idempotent,
`_get_or_create_...`) dans `microfinance.loan.create()` est direct - le rattrapage paresseux déjà
en place pour `loan_account_id` (`microfinance_loan.py:234-236`, pour un client créé hors
`microfinance_context`) montre le patron exact à réutiliser. **Mais la question n'est pas
technique, elle est fonctionnelle** : cf. section suivante.

## 5. Impact sur le garde-fou de `action_close()`

Le garde-fou (`microfinance_savings_account.py:190-198`, interdiction de clôturer un compte
`compulsory` lié à un crédit actif) **reste valable et nécessaire quelle que soit l'issue de la
restructuration**, à condition qu'il continue de s'appliquer aux enregistrements "produit
individuel" (feuilles de la hiérarchie), jamais à un conteneur - un conteneur n'a par nature pas
de solde/transactions à clôturer au sens propre (même rôle que `microfinance.loan.account`, qui
n'a même pas d'`action_close`). Si le conteneur est représenté par un enregistrement
`microfinance.savings.account` sans produit (option retenue par Micka, pas de nouveau modèle),
il faudra explicitement exclure ce cas de `action_close()`/`action_activate()` (ex. `state`
non pertinent pour un conteneur, ou un champ dédié `is_container` à vérifier avant toute action
métier) - **actuellement aucun champ ne permettrait de distinguer un conteneur d'un compte réel
sans produit défini**, `product_id` étant `required=True` sur le modèle actuel.

## 6. Recensement des données existantes et asymétrie constatée

**3 clients/entités ont un `microfinance.loan.account`, tous les 3 ont aussi un
`microfinance.savings.account`** (coïncidence de ce jeu de données réduit, pas une règle) - mais
**seul 1 des 3 a des numéros de base cohérents entre les deux**, révélant une limite réelle du
mécanisme de dérivation déjà en place :

| Partenaire | Type | N° compte permanent | Conteneur crédit | Compte épargne | Cohérent ? |
|---|---|---|---|---|---|
| RANDRIAMISEZA | `client` | IS/000400 | IS/000400 | IS/I/000400 | **Oui** |
| BM | `bailleur` (pas client !) | *(absent)* | IS/000001 | IS/I/000012 | **Non** - les deux sont tombés sur le repli séquence indépendante, valeurs différentes par coïncidence de compteurs |
| RANDRIANIRINA FERDINAND | *(type vide, ni `client` ni autre)* | *(absent)* | IS/000151 | IS/I/000038 | **Non** - même cause |

**Point critique pour le Lot 1** : le déclencheur du conteneur épargne proposé
(`microfinance.loan.create()`, symétrique du conteneur crédit) **n'a, comme aujourd'hui le
conteneur crédit, aucune condition sur `microfinance_partner_type`** - il fonctionnerait donc
pour BM et RANDRIANIRINA FERDINAND aussi. Mais la **dérivation du numéro** (base = `partner.
microfinance_account_number`) ne fonctionne QUE si ce champ est renseigné, ce qui suppose
`microfinance_partner_type == 'client'` (seul déclencheur de `_assign_microfinance_account_
number`, cf. `res_partner.py:108-115` et logique de `create()` du module crédit) - **exactement
la même limite que celle déjà rencontrée aujourd'hui**, pas une régression nouvelle, mais un
point à anticiper explicitement plutôt qu'à découvrir après coup : un conteneur épargne créé
pour un partenaire sans `microfinance_account_number` retombera nécessairement sur un numéro de
repli non synchronisé avec le conteneur crédit, cassant la promesse "même base numérique" pour
ces cas.

**6 clients au total** (`microfinance_partner_type = 'client'`) sur SEFOR, tous avec un
`microfinance_account_number` sauf un (`RANDRIANATOANDRO Jean Batiste`, id 9, numéro vide -
cause non investiguée, hors périmètre de cet audit). Volume de migration rétroactive à prévoir
en Lot 1 : **au plus 6 conteneurs épargne à créer rétroactivement pour les clients existants**
(probablement moins - seuls les clients ayant déjà au moins un crédit sont concernés si le
déclencheur reste `microfinance.loan.create()` uniquement, jamais rétroactif comme
`microfinance.loan.account` lui-même) - volume négligeable, aucun risque de performance, mais **à
trancher explicitement avec Micka** (rétroactif à tous les clients existants, ou seulement les
futurs, cf. section suivante) plutôt qu'à décider seul.

## Point de décision critique à soumettre à Micka avant le Lot 1

**Le mécanisme "compte principal" existant (`res.partner.create()`, produit par défaut de
l'agence) et le "conteneur épargne" demandé ici (`microfinance.loan.create()`, sans produit) ne
sont PAS la même chose et vont coexister sans intervention.** Trois options, à trancher
explicitement (aucune tranchée dans cet audit, lecture seule) :

**A. Coexistence assumée** : le "compte principal" continue de créer un vrai compte au 1er
client (produit par défaut, s'il est configuré), le nouveau conteneur (sans produit) se
superpose au 1er crédit. Risque : deux entités différentes toutes deux nommées à partir du même
numéro de base, potentiel conflit de nommage (`IS/I/000012` pris par le compte principal ET
visé par le conteneur) - la fonction `_get_savings_account_name` gère déjà ce genre de collision
par repli, mais pas conçue pour un conteneur permanent sans produit en concurrence avec un vrai
compte du même nom.

**B. Fusion** : le conteneur EST le compte principal, simplement renommé "conteneur" et
déclenché plus tôt (dès la création du client, comme aujourd'hui) ou plus tard (au 1er crédit,
comme demandé) - mais alors il n'est plus "sans produit", contredisant l'idée d'un conteneur pur
symétrique à `microfinance.loan.account`.

**C. Retrait du mécanisme "compte principal"** au profit du seul conteneur - mais alors la
question du produit par défaut de l'agence (`microfinance_savings_default_product_id`,
actuellement configuré sur seulement 1 agence sur 11 dans SEFOR) devient sans objet, à moins
qu'un vrai compte "1er produit épargne" continue d'être créé automatiquement sous le nouveau
conteneur - ce qui n'est pas décrit dans la demande.

**Recommandation** (pour discussion, pas une décision) : clarifier avec Micka si "conteneur
épargne" doit être un enregistrement strictement vide (aucun produit, jamais de solde) au sens
propre du terme, auquel cas Option A ou C s'imposent - la coexistence non résolue (Option A par
défaut si rien n'est tranché) est le scénario le plus risqué en silence.

## Effort de restructuration estimé (pour dimensionner le Lot 1, pas un engagement)

- Ajouter un champ conteneur/hiérarchie sur `microfinance.savings.account` (ex.
  `parent_savings_account_id` + `is_container` ou équivalent) : impact vue formulaire (masquer
  produit/solde/transactions pour un conteneur), pas d'impact comptable direct identifié (aucune
  écriture `account.move` ne référence directement ce modèle).
- Revoir `_get_savings_account_name`/`_get_next_available_savings_account_name` pour que le 1er
  compte réel d'un type ne réutilise plus le numéro de base (réservé au conteneur) - **casse
  potentiellement les 3 tests existants qui vérifient explicitement ce comportement**
  (`test_savings_account_number_derivation.py`), à réécrire consciemment, pas à contourner.
- Nouveau code de séquence/dérivation pour le conteneur lui-même, sur le même patron que
  `microfinance.loan.account` (dérivation directe + repli séquence indépendante).
- Adapter `action_close()`/`action_activate()` pour exclure un conteneur (section 5).
- Résoudre la coexistence avec le mécanisme "compte principal" (section précédente) avant
  d'écrire le moindre code - dépendance bloquante pour le Lot 1.
