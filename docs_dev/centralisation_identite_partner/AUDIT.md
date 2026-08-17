# Audit — Centralisation identité sur `res.partner` (Lot 0)

Date : 2026-08-16
Périmètre : lecture seule, aucune modification de modèle/vue/donnée.
Modules concernés : `microfinance_loan_management`, `microfinance_savings_management`.
Base interrogée pour la section 4 : `SEFOR` (seule base avec des données de dossier crédit
exploitables — 1 dossier, 5 contacts avec CIN renseignée ; volume de test/dev, pas de production
à ce stade).

---

## Constat préalable important

L'énoncé du chantier suppose que l'identité est *aujourd'hui* saisie localement sur
`microfinance.loan.application` puis poussée vers `res.partner` via un bouton. La réalité du code
est plus nuancée et change la nature du travail de mapping :

- **`res.partner` porte déjà l'essentiel des champs d'identité cible** (`microfinance_id_number`,
  `microfinance_id_issue_date`, `microfinance_id_issue_place`, `microfinance_fokontany_id`
  en Many2one, `microfinance_profession`, `microfinance_employer`, etc.), ajoutés par
  `microfinance_loan_management/models/res_partner.py`.
- **Le Bloc A (client + conjoint) sur `loan.application` est déjà synchronisé depuis
  `res.partner`**, dans le sens partner → dossier, via des champs `compute + store=True +
  readonly=False` (`_compute_kyc_from_partner`), actifs tant que le dossier est en `draft`/`visite`
  puis gelés. Ce n'est pas un `related` (donc pas de propagation automatique dossier → partner), et
  comme il n'y a pas de méthode `inverse`, une saisie manuelle sur le dossier peut diverger
  silencieusement de la fiche contact sans qu'aucune dépendance ne se déclenche pour la re-synchroniser
  (cf. conflit réel détecté en section 4).
- **Le bouton « Synchroniser vers la fiche contact » (`action_sync_partner`)** ne pousse que
  `phone`, `street` (depuis `partner_current_address`) et `street2` (depuis `partner_fokontany`) —
  jamais la CIN ni les dates de délivrance. Il ne concerne que `partner_id`, jamais le garant ni le
  conjoint.
- **Le garant est le rôle le plus éloigné de la centralisation aujourd'hui** : bien qu'il soit déjà
  un `res.partner` complet via `guarantor_partner_id`, ses champs CIN/dates/fokontany/employeur sont
  de simples `Char`/`Date` locaux, sans aucun `compute` ni lien vers le partner (contrairement à
  l'adresse et la profession du garant, déjà synchronisées via `_compute_guarantor_kyc_from_partner`).

Le Lot 1 ne consistera donc pas à « créer des champs sur `res.partner` puis un mapping », mais
surtout à : (1) créer les quelques champs réellement manquants (duplicata, essentiellement), (2)
remplacer le mécanisme *compute+store+readonly=False* (qui autorise la divergence silencieuse) par
de vrais `related` sur `partner_id`/`microfinance_spouse_id`/`guarantor_partner_id`, et (3) étendre
au garant la même logique déjà en place pour le client/conjoint.

---

## 1. Inventaire des champs déjà présents sur `res.partner`

### 1.a Champs standards Odoo pertinents

| Champ | Type | Label standard | Utilisé/visible en contexte microfinance ? |
|---|---|---|---|
| `street` | Char | Rue | Oui — vue formulaire, placeholder « Adresse... » |
| `street2` | Char | Rue 2 | Oui — placeholder « Adresse 2... », mais aussi détourné comme cible d'écriture du fokontany par `action_sync_partner` (cf. §Constat) |
| `city` | Char | Ville | Oui — piloté automatiquement par `microfinance_commune_id` (onchange), reste modifiable à la main |
| `zip` | Char | Code postal | Oui — piloté par commune puis fokontany si plus précis |
| `state_id` | Many2one | État/Province | Masqué en contexte microfinance (`invisible`) |
| `country_id` | Many2one | Pays | Masqué en contexte microfinance ; défaut Madagascar (`ir.default`) |
| `phone` | Char | Téléphone | Champ natif, non ré-exposé dans le bloc identité individuel (le contact utilise plutôt `microfinance_spouse_phone`/dossier `partner_phone` — cf. §2), mais bien le champ lu pour le garant (`guarantor_phone` = `phone or mobile`) |
| `mobile` | Char | Mobile | Utilisé en repli pour le garant et le conjoint (`phone or mobile`) |
| `function` | Char | Fonction | Non utilisé par les modules microfinance |
| `comment` | Text (Notes internes) | Notes | Onglet natif « Notes internes » conservé tel quel, non réutilisé pour les commentaires d'enquêteur (voir §3 — recommandation de ne pas le réutiliser) |
| `vat` | Char | N° TVA | Masqué en contexte microfinance (redondant avec `microfinance_nif`/`microfinance_stat`/`microfinance_rcs`) |
| `company_name` | Char | Société | Non utilisé (le nom commercial passe par `microfinance_trade_name`) |
| `is_company` | Boolean | — | Piloté par `microfinance_client_type` (onchange) |

### 1.b Extensions déjà ajoutées sur `res.partner`

**`microfinance_loan_management/models/res_partner.py`** (fichier le plus chargé, ~590 lignes) :

Déjà présents et directement réutilisables pour la centralisation identité :
- `microfinance_id_type` (Selection : cin/passport/other)
- `microfinance_id_number` (Char) + `microfinance_id_number_display` (Char, compute/inverse — présentation groupée par 3 chiffres, widget `microfinance_grouped_digits`)
- `microfinance_id_issue_date` (Date), `microfinance_id_issue_place` (Char)
- `microfinance_fokontany_id` (**Many2one** vers `microfinance.geo.fokontany`) — correspond déjà exactement à la décision #2 du chantier, rien à créer ici
- `microfinance_birthdate` (Date), `microfinance_birth_place` (Char)
- `microfinance_gender`, `microfinance_marital_status`
- `microfinance_profession` (Many2one vers `microfinance.profession`)
- `microfinance_employer` (Char — volontairement générique, déjà réutilisé pour le conjoint via `microfinance_spouse_id.microfinance_employer`)
- `microfinance_spouse_id` (Many2one `res.partner`), `microfinance_spouse_phone` (Char, non-related par choix — repli phone/mobile), `microfinance_spouse_profession` (related vers le conjoint, store, readonly=False)
- `microfinance_next_of_kin_name/address/phone`, `microfinance_housing_status`
- `microfinance_guarantor_id` (Many2one `res.partner`) — champ de désignation du garant *sur la fiche client*, distinct de `guarantor_partner_id` sur le dossier (cf. §2, à clarifier)
- `microfinance_commune_id`, `microfinance_region_id`, `microfinance_district_id` (référentiels géo structurés) + `microfinance_region/district/commune/locality` (Char, dépréciés, conservés pour société uniquement)

**Absents sur `res.partner` (à créer en Lot 1)** :
- Duplicata CIN : ni date ni lieu de délivrance de duplicata n'existent aujourd'hui sur `res.partner`.

**`microfinance_savings_management/models/res_partner.py`** : aucune extension identité — uniquement `microfinance_savings_account_ids`/`microfinance_savings_count` (comptes épargne). Sans impact sur ce chantier.

### 1.c Point d'attention — visibilité conditionnée au rôle « client »

Le bloc identité individuel sur la vue `res.partner` (`microfinance_partner_views.xml`, groupe
« Identification ») n'est visible que si `microfinance_partner_type == 'client'`. Un conjoint ou un
garant qui n'est pas lui-même marqué comme client n'a aujourd'hui **aucun accès** à ces champs
depuis sa propre fiche contact (seulement via le dossier crédit qui les affiche/synchronise). À
trancher en Lot 1 : la nouvelle section identité (décision #6, sous `microfinance_context`) devra
probablement ne pas dépendre de `microfinance_partner_type == 'client'` pour rester utilisable par
tous les rôles.

---

## 2. Inventaire des champs identité dans `microfinance.loan.application`

Trois rôles portent une section identité : **Partenaire** (le client, section « 1. Partenaire »),
**Conjoint(e)** (section « 2. Conjoint(e) »), **Garant** (section « II — Identification du
garant »). Un quatrième modèle proche mais hors périmètre est signalé en note.

### 2.a Partenaire (client) — `partner_*`

| Champ dossier | Type | Mécanisme actuel | Source si compute |
|---|---|---|---|
| `partner_surname` | Char | compute/store/readonly=False, gelé hors draft/visite | `partner.name` |
| `partner_nickname` | Char | 100% local | — (aucun équivalent partner) |
| `partner_id_card_number` | Char | compute/store/readonly=False, gelé | `partner.microfinance_id_number` |
| `partner_id_card_issue_date` | Date | idem | `partner.microfinance_id_issue_date` |
| `partner_id_card_issue_place` | Char | idem | `partner.microfinance_id_issue_place` |
| `partner_id_card_duplicate_date` | Date | 100% local | — (aucun équivalent partner) |
| `partner_id_card_duplicate_place` | Char | 100% local | — (aucun équivalent partner) |
| `partner_address_changed` | Boolean | 100% local (constat d'enquête) | — |
| `partner_current_address` | Char | **jamais gelé**, toujours modifiable | pré-rempli à la création seulement |
| `partner_fokontany` | Char | compute/store/readonly=False, gelé — **texte, pas M2O** | `partner.microfinance_fokontany_id.name` (perd la relation) |
| `partner_address_since` | Date | 100% local | — |
| `partner_housing_status` | Selection | compute/store/readonly=False, gelé | `partner.microfinance_housing_status` |
| `partner_agency_distance_km` | Integer | 100% local (constat d'enquête) | — |
| `partner_phone` | Char | **jamais gelé** | pré-rempli à la création |
| `partner_phone_type` / `_detail` | Selection/Char | 100% local (qualifie `partner_phone`) | — |
| `partner_reference_contact_name/phone` | Char | compute/store/readonly=False, gelé | `partner.microfinance_next_of_kin_name/phone` |
| `partner_birth_date/place` | Date/Char | compute/store/readonly=False, gelé | `partner.microfinance_birthdate/birth_place` |
| `partner_marital_status` | Selection | compute/store/readonly=False, gelé | `partner.microfinance_marital_status` |

### 2.b Conjoint(e) — `spouse_*` (lu via `partner_id.microfinance_spouse_id`)

| Champ dossier | Type | Mécanisme | Source |
|---|---|---|---|
| `spouse_name` | Char | compute/store/readonly=False, gelé | `spouse.name` |
| `spouse_id_card_number` | Char | idem | `spouse.microfinance_id_number` |
| `spouse_id_card_issue_date/place` | Date/Char | idem | `spouse.microfinance_id_issue_date/place` |
| **Pas de champ duplicata pour le conjoint** — incohérence : le client et le garant ont `_duplicate_date`/`_duplicate_place`, pas le conjoint. | — | — | — |
| `spouse_address` | Char | compute, gelé — concat `street`+`street2` | `spouse.street`, `spouse.street2` |
| `spouse_fokontany` | Char | compute, gelé — **texte, pas M2O** | `spouse.microfinance_fokontany_id.name` |
| `spouse_profession` | Char | compute, gelé — **texte, pas M2O** | `spouse.microfinance_spouse_profession.name` (donc déjà `partner.microfinance_profession` en coulisses) |
| `spouse_employer` | Char | compute, gelé | `spouse.microfinance_employer` |
| `spouse_phone` | Char | compute, gelé | `partner.microfinance_spouse_phone` (champ non-related, cf. §1.b) |
| `union_duration` | Char | 100% local | — (aucune date de mariage sur partner) |

### 2.c Garant — `guarantor_*` (lié à `guarantor_partner_id`, Many2one `res.partner`)

| Champ dossier | Type | Mécanisme | Source |
|---|---|---|---|
| `guarantor_partner_id` | Many2one | saisie directe | — |
| `guarantor_id_card_number` | Char | **100% local, aucun lien vers le partner** | — |
| `guarantor_id_card_issue_date/place` | Date/Char | **100% local** | — |
| `guarantor_id_card_duplicate_date/place` | Date/Char | **100% local** | — |
| `guarantor_address` | Char | compute/store/readonly=False, gelé — concat `street`+`street2` | `guarantor.street`, `guarantor.street2` |
| `guarantor_fokontany` | Char | **100% local** (contrairement à `partner_fokontany`/`spouse_fokontany`, pas de compute) | — |
| `guarantor_profession` | Char | compute, gelé — **texte, pas M2O** | `guarantor.microfinance_profession.name` |
| `guarantor_employer` | Char | **100% local** (contrairement à `spouse_employer`) | — |
| `guarantor_phone` | Char | compute, **jamais gelé** | `guarantor.phone or guarantor.mobile` |
| `guarantor_relationship_with_borrower` | Char | 100% local, contextuel au dossier | — |
| `guarantor_surveyor_comment` | Text | 100% local, contextuel à l'enquête | — |

**Note hors périmètre** : `microfinance.loan.guarantee` (garantie/caution, modèle distinct) porte
aussi un `guarantor_partner_id` (« Caution »), mais sans aucun champ d'identité dupliqué — simple
Many2one. Non concerné par ce chantier. De même, `microfinance.client.representative` (Comité
d'une société/groupe) porte un `id_card_number` en Char, mais n'est **pas** relié à un
`res.partner` individuel (juste un nom en texte libre) — hors périmètre technique de ce chantier
(pas de partner à centraliser), à signaler si un chantier similaire est envisagé plus tard.

---

## 3. Proposition de mapping

### Réutilise un champ standard existant

| Champ dossier | → Champ `res.partner` standard |
|---|---|
| `partner_current_address` / `spouse_address` / `guarantor_address` | `street` + `street2` |
| `partner_phone` / `guarantor_phone` | `phone` (repli `mobile`) |
| `spouse_phone` | déjà `microfinance_spouse_phone` (non-related, volontaire — cf. §1.b, à conserver tel quel) |

### Réutilise un champ microfinance déjà existant sur `res.partner` (pas standard Odoo, mais déjà là)

| Champ dossier | → Champ `res.partner` |
|---|---|
| `partner_surname` / `spouse_name` | `name` |
| `partner_id_card_number` / `spouse_id_card_number` / `guarantor_id_card_number` | `microfinance_id_number` |
| `partner_id_card_issue_date` / `spouse_..._issue_date` / `guarantor_..._issue_date` | `microfinance_id_issue_date` |
| `partner_id_card_issue_place` / `spouse_..._issue_place` / `guarantor_..._issue_place` | `microfinance_id_issue_place` |
| `partner_fokontany` / `spouse_fokontany` / `guarantor_fokontany` | `microfinance_fokontany_id` (Many2one — arrêter de dupliquer en Char, lire le nom via le related) |
| `partner_housing_status` | `microfinance_housing_status` |
| `partner_reference_contact_name/phone` | `microfinance_next_of_kin_name/phone` |
| `partner_birth_date/place` | `microfinance_birthdate`/`microfinance_birth_place` |
| `partner_marital_status` | `microfinance_marital_status` |
| `spouse_profession` / `guarantor_profession` | `microfinance_profession` (Many2one — arrêter de dupliquer en Char) |
| `spouse_employer` / `guarantor_employer` | `microfinance_employer` |

### Nouveau champ à créer sur `res.partner`

| Champ dossier actuel | Nouveau champ `res.partner` proposé |
|---|---|
| `partner_id_card_duplicate_date` / `guarantor_id_card_duplicate_date` (+ absent côté conjoint, à ajouter par cohérence) | `microfinance_id_duplicate_date` |
| `partner_id_card_duplicate_place` / `guarantor_id_card_duplicate_place` | `microfinance_id_duplicate_place` |

C'est le **seul ajout de champ réellement nécessaire** — tout le reste de l'identité a déjà son
équivalent sur `res.partner`.

### Reste local à `loan.application` (contextuel au rôle/dossier, ne migre pas)

- `partner_nickname` — surnom usuel pour ce dossier, pas un attribut d'identité officielle.
- `partner_address_changed`, `partner_address_since`, `partner_agency_distance_km` — constats
  d'enquêteur datés, propres à la visite.
- `partner_phone_type` / `partner_phone_type_detail` — qualifie `partner_phone` *à ce moment-là*
  (peut être le téléphone d'un voisin), n'a pas de sens comme attribut permanent du partner.
- `guarantor_relationship_with_borrower` — n'a de sens que dans le contexte de ce dossier précis
  (lien avec CE client, pas un attribut du garant lui-même).
- `guarantor_surveyor_comment` / `surveyor_comment` — commentaires d'enquête horodatés par dossier ;
  **ne pas réutiliser le champ `comment` natif de `res.partner`** (Notes internes) : plusieurs
  dossiers successifs sur le même partner écraseraient ou empileraient des commentaires sans
  contexte, alors que le besoin ici est un instantané par dossier.
- `union_duration` — pas de date de mariage sur `res.partner` pour le calculer/vérifier ; laisser
  local sauf si un chantier ultérieur ajoute une date d'union sur le partner.

### Cas à trancher avec recommandation — Profession et Employeur

Les deux champs (`microfinance_profession` Many2one, `microfinance_employer` Char) existent déjà
sur `res.partner` et sont **déjà réutilisés** pour le conjoint (via `related`) et partiellement pour
le garant (compute non-lié). Recommandation : les traiter comme des **attributs intrinsèques de la
personne** et donc centraliser pleinement (garant inclus), pour deux raisons :
1. C'est déjà le choix fait pour le client et le conjoint — traiter le garant différemment
   introduirait une incohérence sans justification métier.
2. Une profession/un employeur changent rarement d'un dossier à l'autre à quelques mois
   d'intervalle ; et si le changement est réel, c'est une mise à jour de la fiche contact qui a du
   sens (contrairement à une adresse "constatée" à la visite, qui elle reste un fait d'enquête).

Seul point de vigilance : contrairement à l'adresse (jamais gelée aujourd'hui pour le client/garant,
donc déjà considérée "vivante"), la profession *est* actuellement gelée hors draft/visite. Si le
Lot 1 remplace le compute/store par un vrai `related`, la profession/l'employeur redeviendront
"vivants" comme l'adresse — à confirmer que c'est le comportement voulu (Micka a déjà tranché ce
point pour le conjoint via `microfinance_spouse_profession`, donc cohérent de généraliser).

---

## 4. Détection des conflits de données existantes

Base interrogée : `SEFOR`. Volume actuel : **1 seul dossier** (`microfinance.loan.application`,
id 1154, état `visite`) et **5 contacts** avec `microfinance_id_number` renseignée. Ce volume ne
permet pas de valider le scénario « même partner dans plusieurs dossiers avec des rôles différents »
— la méthodologie de requête ci-dessous reste néanmoins valable et à relancer une fois le volume de
données réel disponible (production).

### 4.a Conflit détecté — CIN divergente entre le dossier et la fiche contact

Le dossier 1154 porte `partner_id = 2555` (RANDRIAMISEZA) :
- `res_partner.microfinance_id_number` (2555) = `123123654789`
- `microfinance_loan_application.partner_id_card_number` (1154) = `123 123 654 788` (dernier
  chiffre différent : **8** au lieu de **9**)

Le dossier est en état `visite`, donc théoriquement encore dans la fenêtre de synchronisation
automatique (`_KYC_IN_PROGRESS_STATES`). La divergence s'explique par le mécanisme actuel :
`partner_id_card_number` est un `compute(store=True, readonly=False)` **sans `inverse`** — une
saisie manuelle sur le dossier écrase la valeur calculée sans jamais la resynchroniser tant
qu'aucun champ dépendance ne change côté partner. C'est exactement le type de divergence silencieuse
que la centralisation (Lot 1, `related` au lieu de compute) doit éliminer.

### 4.b Doublon de CIN entre deux partners différents

```
microfinance_id_number = 123654789654
  → id 2211 « RANDRIANAVALONA santatra »
  → id 2247 « RANDRIAMBELOMASINA »
```

Deux fiches contact distinctes partagent aujourd'hui la même CIN. Cas exactement du type que la
contrainte d'unicité (section 5) est censée empêcher à l'avenir — nécessite investigation manuelle
côté métier avant Lot 1 (doublon de saisie ? erreur de frappe sur l'une des deux ? réelle
homonymie avec CIN mal recopiée ?) : à traiter indépendamment du chantier de centralisation,
mais bloquant pour l'activation d'une contrainte unique si non résolu avant.

### 4.c Multi-rôle (même partner sur plusieurs dossiers)

Non observable avec un seul dossier en base. Méthodologie pour relance future :

```sql
-- Partners apparaissant comme client sur un dossier et garant/conjoint sur un autre
SELECT partner_id, count(DISTINCT id) FROM microfinance_loan_application GROUP BY partner_id HAVING count(*) > 1;
SELECT guarantor_partner_id, count(DISTINCT id) FROM microfinance_loan_application
  WHERE guarantor_partner_id IS NOT NULL GROUP BY guarantor_partner_id HAVING count(*) > 1;
-- Un même partner_id apparaissant à la fois comme partner_id et guarantor_partner_id sur des dossiers différents
SELECT a.partner_id FROM microfinance_loan_application a
  JOIN microfinance_loan_application b ON a.partner_id = b.guarantor_partner_id AND a.id != b.id;
```

---

## 5. Question ouverte — portée de la contrainte d'unicité CIN

**(a) Globale sur `res.partner`** (toute la base, toutes sociétés/usages confondus)
- Pour : une CIN est un identifiant national réellement unique par personne — c'est la
  réalité qu'on modélise. Simple à implémenter (`_sql_constraints` ou contrainte Python sans filtre
  de contexte). Détecte aussi les doublons créés par erreur hors contexte microfinance si jamais le
  champ venait à être renseigné ailleurs.
- Contre : `res.partner` est partagé avec EAT et le projet immobilier/MIIA. Si l'un de ces usages
  vient un jour à renseigner `microfinance_id_number` (aujourd'hui il ne le fait pas — champ
  namespacé, non exposé dans leurs vues), la contrainte s'appliquerait aussi à leurs données sans
  distinction.

**(b) Scopée au contexte microfinance** (ex. limitée aux partners avec
`microfinance_partner_type` renseigné, ou `microfinance_client_type` non vide)
- Pour : isole strictement l'effet de bord aux usages microfinance, aucun risque de bloquer un
  scénario EAT/immobilier imprévu.
- Contre : plus complexe à garantir en base (une contrainte SQL `UNIQUE` ne peut pas être
  conditionnelle simplement ; nécessiterait soit une contrainte Python `@api.constrains` avec filtre
  explicite — moins robuste qu'une contrainte SQL en cas d'écriture concurrente/bulk — soit un index
  partiel PostgreSQL `WHERE microfinance_partner_type IS NOT NULL`, faisable mais un cran de
  complexité de plus). Une personne pourrait légitimement avoir un contact EAT/immobilier existant
  avec la même CIN qu'un client microfinance sans que ce soit détecté — potentiellement le vrai cas
  qu'on veut justement détecter (même personne physique, deux fiches).

**Recommandation (à valider, pas tranchée)** : option (a), pour deux raisons concrètes observées
dans le code : le champ `microfinance_id_number` est déjà namespacé et n'est aujourd'hui *jamais*
renseigné hors contexte microfinance (aucune vue EAT/immobilier ne l'expose) — le risque de
« faux positif » cross-usage est donc actuellement nul en pratique. Une contrainte globale reste
aussi la plus simple à implémenter de façon fiable (SQL `UNIQUE` partiel sur valeur non vide) et
colle le mieux à la réalité qu'un CIN identifie une personne unique, indépendamment de son rôle
métier dans l'instance.

---

## Livrables et suite

Ce document répond aux 5 objectifs du Lot 0. Aucune modification de code, modèle, vue ou donnée
n'a été effectuée. En attente de validation de Micka sur :
- le mapping de la section 3 (en particulier Profession/Employeur),
- la portée de la contrainte CIN (section 5),
- le traitement du doublon CIN réel détecté en 4.b avant d'activer toute contrainte.
