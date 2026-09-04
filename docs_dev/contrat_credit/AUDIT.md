# AUDIT — Impression du « Contrat de Crédit » (Lot 0, lecture seule)

Date : 2026-09-01
Périmètre : `microfinance_loan_management`, modèle `microfinance.loan`.
Objectif : confronter chaque hypothèse du template brouillon
(`report_contrat_credit.draft.xml`) à la réalité du code, avant correction au Lot 1.

Légende statut :
- ✅ champ/méthode confirmé, utilisable tel quel
- ⚠️ existe mais nom/usage à corriger dans le template
- ❌ n'existe pas — à créer (méthode) ou décision Micka requise
- ❓ décision fonctionnelle Micka requise

---

## 1. État « Approuvé »

| Élément | Hypothèse template | Réalité | Statut |
|---|---|---|---|
| Valeur technique état « Approuvé » | `state == 'approuve'` | **`state == 'approved'`** | ⚠️ |

`microfinance_loan.py:71-82` — `state = fields.Selection([...])` :

```
draft      Brouillon
enquete    Enquête
avis_ca    Avis CA
avis_cdag  Avis CDAG
approved   Approuvé      <-- étape métier "Approuvé"
active     Actif
closed     Clôturé
defaulted  Défaut
written_off Radié
cancelled  Annulé
```

- Transition posée par `action_approve()` (`microfinance_loan.py:825-828`), qui écrit
  `state='approved'` **et** `approval_date = fields.Date.context_today(self)`.
- `action_approve` est précédée de `_check_committee_octroi_accepted()` (blocage
  Comité d'Octroi) — sans incidence sur le rapport.
- Passage suivant : `action_disburse()` → `state='active'` + `disbursement_date`.

➡️ **Lot 1** : `invisible="state != 'approved'"` dans le bouton hérité.

---

## 2. Vue formulaire à hériter

| Élément | Hypothèse | Réalité | Statut |
|---|---|---|---|
| id XML vue formulaire | `microfinance_loan_management.view_microfinance_loan_form` | identique | ✅ |
| Balise `<header>` exploitable pour xpath | oui | oui, `microfinance_loan_views.xml:63` | ✅ |

- `microfinance_loan_views.xml:58` — `<record id="view_microfinance_loan_form" model="ir.ui.view">`,
  `name` = `microfinance.loan.form`.
- `<header>` ouvert L63, contient déjà ~15 boutons + `<field name="state" widget="statusbar"/>`.
- `xpath expr="//header" position="inside"` : valide, ajoute le bouton en fin de
  header sans toucher aux boutons existants. Non-régression OK.
- ⚠️ Le bouton `%(action_report_contrat_credit)d` doit être **défini dans le même
  fichier** (ou chargé avant) — c'est le cas dans le brouillon (record juste
  au-dessus). Ordre de chargement manifest : la vue héritée et l'action seront dans
  `report/report_contrat_credit.xml`, chargé **avant** `views/microfinance_loan_views.xml`
  (section 3 du manifest, cf. §8) — l'`inherit_id ref` vers `view_microfinance_loan_form`
  impose au contraire un chargement **après**. ➡️ **Lot 1** : séparer — laisser
  l'action + le template dans `report/…xml`, mais placer la **vue héritée** (bouton)
  soit dans `views/microfinance_loan_views.xml` directement, soit dans un fichier vue
  chargé après lui. À trancher à l'implémentation (le plus simple : ajouter le bouton
  directement dans `microfinance_loan_views.xml`, à côté de « Imprimer le reçu »
  L75).

---

## 3. Champs du dossier de prêt (`microfinance.loan`)

### 3.1 Compte crédit conteneur

| Hypothèse | Réalité | Statut |
|---|---|---|
| `loan_account_id` → `microfinance.loan.account`, `.name` format `IS/NNNNNN` | `loan_account_id` Many2one `microfinance.loan.account` (`microfinance_loan.py:39`) | ✅ (avec réserve) |

- `.name` = référence du conteneur, format **`AGENCE/NNNNNN`** (ex. `IS/000289`),
  dérivée du numéro de compte permanent du client
  (`microfinance_loan_account.py:40-58`). **Pas** de segment TYPE (contrairement à
  l'épargne). Donc `IS/000289`, pas `IS/I/000289`.
- ⚠️ `loan_account_id` **non `required`** : d'anciens crédits peuvent l'avoir vide.
  Le template doit garder un `t-if` / valeur par défaut (cf. critères de
  non-régression). Sur un crédit récent à l'état `approved` il est toujours
  renseigné (posé au `create()`, `microfinance_loan.py:264-270`).
- ❓ Micka : dans l'en-tête, « Mpindrana laharana » doit-il afficher
  `loan_account_id.name` (n° de compte crédit) ou plutôt
  `partner_id.microfinance_account_number` (n° de compte permanent du client) ?
  Les deux coïncident dans le cas normal.

### 3.2 Agent de crédit

| Hypothèse | Réalité | Statut |
|---|---|---|
| `officer_id` (agent crédit) | `officer_id` Many2one **`res.users`** « Agent crédit », défaut `env.user` (`microfinance_loan.py:83`) | ⚠️ |

- `o.officer_id.name` fonctionne mais renvoie le **nom de l'utilisateur Odoo**, pas
  un partenaire « agent ». Acceptable pour « CA mpikarakara ».
- Autres pistes si besoin : `manager_id`, `finance_user_id`, `collection_agent_id`
  (tous `res.users`).
- ❓ Micka : `officer_id` est-il le bon champ pour « CA mpikarakara » (conseiller
  en charge) ? « Agent BL » reste vide dans le contrat de référence → laissé vide.

### 3.3 Garant / caution — CORRIGÉ (Micka, debug Odoo)

| Hypothèse | Réalité | Statut |
|---|---|---|
| `guarantor_id` Many2one `res.partner` **sur `microfinance.loan`** | **n'existe pas sur le crédit** | ⚠️ |
| `res.partner.microfinance_guarantor_id` (1re piste, décision initiale) | existe (`res_partner.py:468`) mais **jamais renseigné** dans les données réelles SEFOR (vide sur tous les emprunteurs testés) | ❌ écarté |
| **`microfinance.loan.application.guarantor_partner_id`** | **✅ c'est la vraie source** — Many2one `res.partner` « Nom et prénom » (`microfinance_loan_application.py:265`), effectivement peuplé sur les dossiers réels | ✅ |

Vérification données SEFOR :
- `res_partner.microfinance_guarantor_id` : **vide** sur les emprunteurs 235 et
  7056 (les 2 dossiers `approved`).
- `microfinance_loan_application.guarantor_partner_id` : **peuplé** — dossier
  d'instruction 2616 (crédit 4778 / IS/003363) → partenaire **7 « RAKOTONDRASOA »**
  (correspond au « Garant principal : RAKOTONDRASOA » du debug fourni par Micka).
  Dossier 1319 (crédit 2327 / IS/001076) → pas de garant.

**Lien crédit → dossier d'instruction** : `microfinance.loan.application_ids`
One2many (`'microfinance.loan.application', 'loan_id'`, `microfinance_loan.py:168`).
Convention déjà établie dans le module : `application_ids[:1]`
(`action_view_applications()` `:1853`, `_check_committee_octroi_accepted()` `:837`
— « aucun cas réel à plusieurs dossiers observé »). → **Question ouverte 1
résolue** : chemin = `o.application_ids[:1].guarantor_partner_id`.

**Nombre de garants** : `microfinance.loan.application.guarantor_count` est un
compute = `1 if guarantor_partner_id else 0` (`microfinance_loan_application.py:1224`),
`primary_guarantor_name` = `guarantor_partner_id.name` (`:1225`). Il n'y a **pas**
de One2many de garants — un dossier d'instruction n'a **qu'un seul garant**. →
**Question ouverte 2 résolue** : un seul bloc « Ny mpiantoka », pas de boucle.
Les champs KYC dénormalisés du garant sur l'application
(`guarantor_fokontany` Char `:278`, `guarantor_id_card_number` Char `:266`, …) sont
`compute='_compute_guarantor_kyc_from_partner'` synchronisés depuis
`guarantor_partner_id` — mais en Char brut (pas le format « display » en blocs de
3 pour le CIN). → passer par `guarantor_partner_id.microfinance_fokontany_id.name`
et `guarantor_partner_id.microfinance_id_number_display` directement.

➡️ **Lot 1 (implémenté)** : méthode **`get_contrat_guarantor()`** sur
`microfinance.loan` → `self.application_ids[:1].guarantor_partner_id` (res.partner
vide si aucun). Template : `t-set="guarantor" t-value="o.get_contrat_guarantor()"`,
bloc « Ny mpiantoka » entier sous `t-if="guarantor"`, fokontany et CIN chacun sous
leur propre `t-if`.

### 3.4 Périodicité de remboursement

| Hypothèse | Réalité | Statut |
|---|---|---|
| `repayment_frequency_id` Many2one, comparaison sur `.name` (`'Mensuel'` / `'Hebdomadaire'` / `'Journalier'`) | `repayment_frequency_id` Many2one `microfinance.repayment.frequency` (`microfinance_loan.py:63`) | ⚠️ |

- `name` est **`translate=True`** (`microfinance_repayment_frequency.py:11`) →
  **ne jamais** comparer dessus. Utiliser **`code`** (stable, `unique`) :

  | code | name (fr) |
  |---|---|
  | `daily` | Journalier |
  | `weekly` | Hebdomadaire |
  | `biweekly` | Quinzaine (15 jours) |
  | `four_weekly` | Toutes les 4 semaines |
  | `monthly` | Mensuel |
  | `bimonthly` | Bimestriel (2 mois) |
  | `quarterly` | Trimestriel |
  | `four_monthly` | Tous les 4 mois |
  | `semiannual` | Semestriel |
  | `annual` | Annuel |

  (source : `data/repayment_frequency_data.xml`)

➡️ **Lot 1** : `t-if="o.repayment_frequency_id.code == 'monthly'"` → `isam-bolana`,
  `'weekly'` → `isan-kerinandro`, `'daily'` → `isan'andro`. Prévoir un `t-else`
  générique (ex. « isaky ny fe-potoana ») pour les 7 autres périodicités, sinon le
  mot manque à l'impression.

### 3.5 Montants / solde

| Hypothèse template | Réalité | Statut |
|---|---|---|
| `o.loan_amount` | `loan_amount` Monetary « Montant crédit » (`:49`) | ✅ |
| `o.balance_total` | `balance_total` Monetary compute+store « Solde restant » (`:173`) | ✅ |
| `o.installement_amount` | **FAUTE** — champ réel = **`installment_amount`** Monetary « Échéance » (`:87`) | ⚠️ |

- `balance_total` (`_compute_totals`, `:458-470`) = somme des `residual_amount` des
  échéances si `installment_ids` existe, sinon repli sur `loan_amount`. À l'état
  `approved`, l'échéancier est déjà généré automatiquement (write() /
  `_SCHEDULE_TRIGGER_FIELDS`, `:298-300` + `:347-359`) → `balance_total` = capital +
  intérêts totaux non payés. Cohérent avec « totalin'ny renivola sy ny zana-bola ».
- `installment_amount` : montant de la tranche périodique (aperçu), calculé par
  `_compute_installment_target` (formule interest-first arrondie). ✅ champ correct
  après correction de la faute de frappe.

### 3.6 Dates première / dernière échéance

| Hypothèse | Réalité | Statut |
|---|---|---|
| méthode `get_first_installment_date()` / `get_last_installment_date()` | **n'existent pas** | ❌ à créer |

- Source : `installment_ids` One2many `microfinance.loan.installment`.
  Champ date = **`due_date`** Date « Date d'échéance » (`microfinance_loan_installment.py:12`).
  `_order = 'loan_id, sequence, due_date'`.
- ➡️ **Lot 1** — `get_first_installment_date()` :
  `self.installment_ids.sorted('due_date')[:1].due_date` formaté `%d/%m/%Y`, `''`
  si vide. Idem `[-1:]` pour la dernière. (Attention : une éventuelle ligne de
  délai de grâce est `sequence=1` avec `principal_amount=0` — cf.
  `_build_installment_commands` `:1222-1233` ; à trancher avec Micka si le contrat
  doit l'ignorer. Par défaut : première ligne par `due_date` telle quelle.)

### 3.7 Taux d'intérêt / total des intérêts

| Hypothèse | Réalité | Statut |
|---|---|---|
| méthode `get_total_interest()` | **n'existe pas** ; mais `interest_total` déjà disponible | ❌ méthode à créer (triviale) |
| « 3% isam-bolana » (taux mensuel) codé en dur | pas de champ « taux mensuel » ; `interest_rate` = **taux annuel %** | ❓ |

- **`interest_total`** Monetary compute+store « Total intérêts » (`microfinance_loan.py:170`),
  `_compute_totals` (`:461`) = `sum(installment_ids.mapped('interest_amount'))`.
  → C'est **le** total des intérêts sur toute la durée, produit par le moteur
  interest-first en place. `get_total_interest()` doit simplement retourner
  `self.interest_total` (repli possible : recalcul via
  `loan_amount * interest_rate/100 * _period_interest_factor() * term` si aucun
  échéancier — cf. `_build_installment_commands` `:1249`, mais inutile à l'état
  `approved` où l'échéancier existe). **Ne pas dupliquer un calcul divergent.**
- `interest_rate` Float « Taux intérêt annuel (%) », `related='product_id.interest_rate'`
  (`microfinance_loan.py:55` ; `microfinance_loan_product.py:47`). `interest_method`
  Selection (`flat` en pratique pour CEFOR).
- ❓ Micka : le « 3% isam-bolana » du contrat de référence est un **taux mensuel**.
  Options : (a) laisser le littéral « 3% » en dur (texte de contrat), (b) afficher
  `interest_rate/12` avec 2 décimales, (c) afficher `interest_rate` annuel avec le
  libellé adapté. Aucune régression tant que la décision n'est pas prise → garder
  « 3% » littéral au Lot 1 sauf avis contraire.

### 3.8 Épargne de garantie exigée

| Hypothèse template | Réalité | Statut |
|---|---|---|
| `product_id.guarentee_savings_percent` | **FAUTE** — champ réel = **`guarantee_savings_percent`** Float (`microfinance_savings_management/models/microfinance_loan_product_extension.py:50`) | ⚠️ |
| méthode `get_guarantee_amount()` | **n'existe pas** ; mais `guarantee_savings_required` déjà disponible | ❌ méthode à créer (triviale) |

- Champ prêt à l'emploi sur `microfinance.loan` : **`guarantee_savings_required`**
  Monetary.
  - Déclaré en saisie libre inerte dans le module de base
    (`microfinance_loan.py:156-160`).
  - **Redéclaré compute+store** par le module épargne
    (`microfinance_loan_extension.py:28-30` + `_compute_guarantee_savings_required`
    `:101-104`) : `= loan_amount * product_id.guarantee_savings_percent / 100.0`.
  - `microfinance_savings_management` **est installé** sur SEFOR (cf. mémoires
    projet) → la valeur calculée est disponible.
- Alternatives : `avis_ca_epargne_exigee` / `avis_cdag_epargne_exigee`
  (`microfinance_loan_extension.py:50-66`) = `avis_*_amount * guarantee_savings_percent / 100`
  (basé sur le montant de l'avis, pas `loan_amount`).
- ➡️ **Lot 1** : `get_guarantee_amount()` retourne `self.guarantee_savings_required`.
  ❓ Micka : `guarantee_savings_required` (base `loan_amount`) ou
  `avis_cdag_epargne_exigee` (base montant avis CDAG) ? À l'état `approved`, après
  propagation de l'avis, `loan_amount == avis_cdag_amount` donc les deux
  coïncident — `guarantee_savings_required` est le choix le plus robuste.

### 3.9 Date de signature / octroi

| Hypothèse | Réalité | Statut |
|---|---|---|
| méthode `get_signature_date()` | **n'existe pas** | ❌ à créer |
| date d'approbation existante | **`approval_date`** Date « Date d'approbation » readonly (`microfinance_loan.py:52`), posée par `action_approve()` | ✅ source disponible |

- ➡️ **Lot 1** : `get_signature_date()` = `self.approval_date or fields.Date.context_today(self)`,
  formaté `%d/%m/%Y`. (`disbursement_date` `:53` également disponible si Micka
  préfère la date de décaissement.)

---

## 4. Champs `res.partner`

| Hypothèse template | Réalité | Statut |
|---|---|---|
| `partner_id.fokontany_id.name` | champ réel = **`microfinance_fokontany_id`** Many2one `microfinance.geo.fokontany` (`microfinance_loan_management/models/res_partner.py:505`) | ⚠️ |
| `partner_id.microfinance_id_number_display` | **existe** — Char compute (`res_partner.py:525`) | ✅ |

- `microfinance.geo.fokontany` (`microfinance_geo_fokontany.py`) : `name` Char (`:18`),
  `display_name` Char compute = « Nom (Commune) » (`:31,38-42`), `_rec_name = 'display_name'`.
  ➡️ **Lot 1** : `o.partner_id.microfinance_fokontany_id.name` (ou `.display_name`
  si Micka veut « Fokontany (Commune) »). Aucun champ `fokontany_id` nu.
- `microfinance_id_number_display` : présentation du CIN par blocs de 3 chiffres
  (`_compute_id_number_display` `:534-542`). Valeur brute = `microfinance_id_number`
  (`:417`) ; type = `microfinance_id_type` (`cin` / `passport` / `other`, `:415`).
  Le template utilise déjà le bon nom dans le corps (`microfinance_id_number_display`).
  ⚠️ La faute « microfiance… » mentionnée dans le prompt n'apparaît pas dans le
  brouillon fourni — RAS, mais à surveiller à la recopie.
- Prévoir `t-if` : `microfinance_fokontany_id` et `microfinance_id_number` sont
  facultatifs sur `res.partner`.

---

## 5. Champ agence (`res.company`)

| Hypothèse template | Réalité | Statut |
|---|---|---|
| nom d'agence = `company_id.street` | **incorrect** — pas de champ dédié ; nom d'agence = `company_id.name` | ⚠️ |
| `company_id.logo` renseigné en prod | champ standard Odoo, **à vérifier en base** | ❓ |

- `res.company` (`microfinance_loan_management/models/res_company.py`) :
  - **pas** de champ `agency_display_name`. Le seul identifiant agence dédié est
    **`agency_code`** Char `size=3` (`:9`, ex. `IS`, `IS` pour Isotry).
  - Chaque agence CEFOR = une `res.company` distincte → le **nom de l'agence** est
    `company_id.name`. Confirmé par `_get_microfinance_dashboard_subtitle()`
    (`:111-119`) qui compose `self.name` + `street/street2/city`.
  - `street` = 1re ligne d'adresse postale standard (utilisée comme adresse dans le
    sous-titre dashboard) → **ce n'est pas** le nom de l'agence.
- ➡️ **Lot 1** :
  - En-tête « Agence : … » → `o.company_id.name` (éventuellement +
    `o.company_id.agency_code`).
  - Paragraphe « …ao amin'ny masoivoho **[X]** nahazoana fampindramana » (adresse
    du guichet de perception) → ❓ Micka : `o.company_id.street` (adresse) ou
    `o.company_id.city` ou `o.company_id.name` ? Sémantiquement c'est un lieu →
    `street` ou `city` plausibles.
- ❓ **Audit data à faire sur `rotas`/`srv1092944`** : `res.company.logo` est-il
  renseigné pour chaque agence en production ? Le template a déjà
  `t-if="o.company_id.logo"` (garde OK), mais sans logo l'en-tête sera nu.

---

## 6. Jour de remboursement fixe (« ALATSINAINY » = lundi)

| Hypothèse | Réalité | Statut |
|---|---|---|
| champ « jour de la semaine de remboursement » par dossier/agence | **n'existe pas** | ❌ |

- Aucun champ « jour de la semaine » sur `microfinance.loan`,
  `microfinance.repayment.frequency` (ne stocke que `period_kind` / `period_value` /
  `periods_per_year`), `res.company` ni `microfinance.loan.product`.
- Les `due_date` sont calculées par `_period_delta()` (`microfinance_loan.py:880-889`)
  à partir de `approval_date` / `application_date` + N périodes — le jour de la
  semaine découle de la date de départ, il n'est pas paramétré.
- ➡️ **Lot 1** : garder le **texte fixe « ALATSINAINY »** comme dans le contrat de
  référence, sauf demande explicite de Micka de créer un champ configurable
  (hors périmètre sans validation).

---

## 7. Méthodes Python à créer sur `microfinance.loan` (Lot 1)

Toutes dans `microfinance_loan_management/models/microfinance_loan.py` (le module de
base — aucune ne dépend de l'épargne ; `guarantee_savings_required` est déjà
déclaré côté base, redéclaré calculé côté épargne).

| Méthode | Implémentation prévue | Dépend de |
|---|---|---|
| `get_amount_in_words()` | `num2words(self.loan_amount, lang='fr')`, capitalisé | lib `num2words` (cf. §9) |
| `get_total_interest()` | `return self.interest_total` (repli calcul interest-first si pas d'échéancier) | `interest_total` (`:170`) |
| `get_first_installment_date()` | `self.installment_ids.sorted('due_date')[:1].due_date` → `%d/%m/%Y` | `installment_ids.due_date` |
| `get_last_installment_date()` | `self.installment_ids.sorted('due_date')[-1:].due_date` → `%d/%m/%Y` | idem |
| `get_guarantee_amount()` | `return self.guarantee_savings_required` | `guarantee_savings_required` (`:156` / extension `:101`) |
| `get_signature_date()` | `(self.approval_date or fields.Date.context_today(self))` → `%d/%m/%Y` | `approval_date` (`:52`) |

Formatage dates : **jamais ISO**. Utiliser `strftime('%d/%m/%Y')` (cf. rapport
existant `microfinance_loan_repayment_schedule_report.xml:23`) ou
`babel`/`format_date`. Retourner `''` (pas d'exception) si la source est vide, pour
respecter le critère « aucune erreur QWeb si champ optionnel vide ».

---

## 8. Manifest & déclaration

- `__manifest__.py` — section `'data'` débute L12. Bloc rapports existant L25-27 :
  ```
  'report/microfinance_loan_disbursement_receipt.xml',
  'report/microfinance_loan_repayment_schedule_report.xml',
  'report/microfinance_caisse_fiche_journee_report.xml',
  ```
  ➡️ **Lot 1** : ajouter `'report/report_contrat_credit.xml'` à la suite.
- ⚠️ Ordre de chargement (cf. §2) : `report/*` est chargé **avant**
  `views/microfinance_loan_views.xml`. Si la **vue héritée** (bouton) reste dans
  `report/report_contrat_credit.xml`, son `inherit_id ref="…view_microfinance_loan_form"`
  échoue (vue pas encore chargée). ➡️ Mettre le bouton dans
  `views/microfinance_loan_views.xml` (recommandé) OU créer
  `views/microfinance_loan_contrat_views.xml` chargé après L40, en ne gardant dans
  `report/…` que l'`ir.actions.report` + le `<template>`.
- `binding_model_id ref="model_microfinance_loan"` : l'xmlid `model_microfinance_loan`
  existe (référencé partout dans `security/ir.model.access.csv` et les record rules)
  — ✅.
- `report_name` du brouillon : `…report_contrat_credit_document` dans l'action mais
  le `<template id>` est `report_contrat_credit_document` → cohérent. ✅ (Le prompt
  mentionne `report_contrat_credit_document` comme `report_name` — aligné.)

---

## 9. Dépendance `num2words`

| Serveur | Résultat |
|---|---|
| `python3` système | ❌ `ModuleNotFoundError: No module named 'num2words'` |
| **venv Odoo** `/opt/odoo17/venv/bin/python` | ✅ `num2words 0.5.10` — `num2words(1500000, lang='fr')` → « un million cinq cent mille » |

- `num2words` figure déjà dans `/opt/odoo17/requirements.txt` :
  `num2words==0.5.10 ; python_version < '3.12'` (et `0.5.13` pour ≥ 3.12).
- Odoo tourne sur le venv → **rien à installer**. À revérifier sur `srv1092944`
  (`/opt/odoo17/venv/bin/python -c "import num2words"`) avant mise en prod.
- Import à faire en tête de `microfinance_loan.py` :
  `from num2words import num2words` (déjà utilisé par le core Odoo pour les
  chèques — dépendance sûre).

---

## 10. Points hard-codés dans le template vs. configuration

| Élément contrat | Champ de config existant ? | Décision |
|---|---|---|
| Frais « 5% n'ny vola nindramina » (`loan_amount * 0.05`) | ✅ `product_id.fee_rate` (%) si `fee_type == 'percentage'`, **ou** champ calculé **`fee_amount_due`** (`microfinance_loan.py:221`, gère fixed + percentage) | ⚠️ **Lot 1** : remplacer `o.loan_amount * 0.05` par `o.fee_amount_due`. Garder le libellé « 5% » ❓ (dépend du paramétrage produit réel — à vérifier sur le produit du dossier de test). |
| « vidin'ny karatra tahiry (500 Ar) » | ❌ aucun champ (ni produit crédit, ni produit épargne, ni `res.company`, ni `res.config.settings`) | ❌ **rester en dur « 500 Ar »** au Lot 1 ; signaler à Micka qu'un champ de config serait à créer si le montant varie. |
| « zana-bola 3% isam-bolana » | ❌ pas de taux mensuel (`interest_rate` = annuel) | ❓ cf. §3.7 — littéral « 3% » en dur par défaut. |
| « ONG CEFOR », « AFAFI », « ALATSINAINY », articles de loi 2014-038 / 2017-045 | n/a (texte de contrat) | en dur, OK. |

---

## 11. Droits d'accès du bouton « Imprimer le contrat »

Groupes microfinance existants (`security/groups.xml`) :

| xmlid | rôle |
|---|---|
| `group_microfinance_user` | Utilisateur (socle) |
| `group_microfinance_manager` | Manager |
| `group_microfinance_finance` | Finance |
| `group_microfinance_collection_agent` | Agent recouvrement |
| `group_microfinance_auditor` | Auditeur |
| `group_microfinance_comptable` | Comptable |
| `group_microfinance_cashier` | Caissier |
| `group_microfinance_credit_committee` | Comité de crédit |
| `group_microfinance_gestionnaire` | Gestionnaire (implique manager + finance) |

- Les boutons du header actuel utilisent : `group_microfinance_credit_committee`
  (avis CA/CDAG), `group_microfinance_manager` (approuver, rééchelonner…),
  `group_microfinance_finance` (frais, décaissement). « Imprimer le reçu » et
  « Imprimer le calendrier » : **aucun `groups=`** (visibles par tout
  `group_microfinance_user`).
- ❓ Micka : le bouton « Imprimer le contrat » doit-il être ouvert à tout
  `group_microfinance_user`, ou restreint (a minima
  `group_microfinance_manager,group_microfinance_gestionnaire`, éventuellement
  `group_microfinance_credit_committee`) ? Par cohérence avec les deux autres
  boutons d'impression, **sans `groups=`** semble le défaut naturel — à confirmer.

---

## Synthèse des corrections template (Lot 1)

| Template (brouillon) | Correction |
|---|---|
| `invisible="state != 'approuve'"` | `state != 'approved'` |
| bouton dans `report/…xml` héritant `view_microfinance_loan_form` | déplacer la vue héritée dans `views/microfinance_loan_views.xml` (ordre de chargement) |
| `o.company_id.street` (en-tête « Agence : ») | `o.company_id.name` |
| `o.company_id.street` (« masoivoho … ») | ❓ `street` / `city` — décision Micka |
| `o.partner_id.fokontany_id.name` | `o.partner_id.microfinance_fokontany_id.name` |
| `o.guarantor_id.*` (garant) | `o.get_contrat_guarantor().*` → `o.application_ids[:1].guarantor_partner_id` (dossier d'instruction) ; `name` / `microfinance_fokontany_id.name` / `microfinance_id_number_display`, chacun sous `t-if` |
| `o.installement_amount` | `o.installment_amount` |
| `o.repayment_frequency_id.name == 'Mensuel'` … | `o.repayment_frequency_id.code == 'monthly'` … + `t-else` générique |
| `o.loan_amount * 0.05` | `o.fee_amount_due` |
| `500 Ar` | rester en dur (pas de champ) |
| `3%` mensuel | rester en dur (décision Micka) |
| `o.get_amount_in_words()` | méthode à créer (num2words) |
| `o.get_total_interest()` | méthode à créer → `interest_total` |
| `o.get_first_installment_date()` / `o.get_last_installment_date()` | méthodes à créer → tri `installment_ids` par `due_date`, `%d/%m/%Y` |
| `o.get_guarantee_amount()` | méthode à créer → `guarantee_savings_required` |
| `o.get_signature_date()` | méthode à créer → `approval_date` ou today, `%d/%m/%Y` |
| `image_data_uri(...)` | OK (helper QWeb standard) |

---

## Décisions Micka — 2026-09-01 (audit validé)

| # | Question | Décision |
|---|---|---|
| 1 | Caution / garant (§3.3) | ~~`o.partner_id.microfinance_guarantor_id`~~ **corrigé après debug Micka** → **`o.application_ids[:1].guarantor_partner_id`** via `get_contrat_guarantor()`. Un seul garant (pas de One2many). `t-if` de garde + bloc entier « Ny mpiantoka » conditionné. |
| 2 | Adresse « masoivoho … » (§5) | **`o.company_id.street`**. |
| 3 | Épargne de garantie (§3.8) | **Calcul explicite depuis le pourcentage** : `loan_amount × product_id.guarantee_savings_percent / 100`. `get_guarantee_amount()` calcule directement (equivalent à `guarantee_savings_required`), ne pas figer un montant. |
| 4 | « 3% isam-bolana » (§3.7) | **`interest_rate / 12`** (taux mensuel dérivé du taux annuel produit), affiché à la place du littéral « 3% ». |
| 5 | Droits du bouton (§11) | **Manager + Gestionnaire + Agent de crédit** → `groups="microfinance_loan_management.group_microfinance_user"` (= « Agent crédit », socle implicitement inclus par `group_microfinance_manager` et `group_microfinance_gestionnaire`). |
| 6 | Ligne de délai de grâce (§3.6) | **L'inclure** : « première échéance » = 1re ligne `installment_ids` triée par `due_date`, sans filtrage. |
| 7 | En-tête « Mpindrana laharana » (§3.1) | **`o.partner_id.microfinance_account_number`** (n° de compte permanent du client), pas `loan_account_id.name`. |
| 8 | Audit data `rotas` | **Oui** : à faire au Lot 1 — vérifier `res.company.logo` par agence + choisir un dossier réel à l'état `approved` (IS/000289 ou IS/001076). |

➡️ Ces décisions sont intégrées à la « Synthèse des corrections template » ci-dessus.
Reste, au Lot 1 : `t-else` générique pour les 7 périodicités non citées (§3.4), et
séparation vue héritée / action-template pour l'ordre de chargement manifest (§2, §8).

---

*Fin du Lot 0 — audit validé par Micka le 2026-09-01. Passage au Lot 1.*

---

## Lot 1 — Mise en page (retour Micka 2026-09-01)

Exigence : « le template doit être exactement comme la référence au niveau marge et
taille de police, le contrat doit tenir pile-poil sur une page A4 ».

- **Format papier dédié** : `report.paperformat` `paperformat_contrat_credit`
  (A4 portrait, marges 10/8 mm haut/bas, 22/20 mm gauche/droite, aucune bande
  d'en-tête/pied wkhtmltopdf), liée à l'action via `paperformat_id`. Calquée sur
  les marges du `.doc` Word (~2 cm côtés).
- **Police** : `font-family: 'Times New Roman', 'Liberation Serif', 'Nimbus Roman', serif`
  — « Times New Roman » n'est pas installé sur le serveur ; **Liberation Serif**
  (substitut à métriques identiques, présent) prend le relais, rendu quasi
  identique à Word. `font-size: 11pt`, `line-height: 1.45`, paragraphes
  `margin-bottom: 6pt`, titres `margin: 9pt 0 6pt 0` — réglés pour que le contenu
  remplisse une page A4 pleine (vérifié : `pdfinfo` → `Pages: 1`, 595×842 pts, sur
  IS/003363 et IS/001076).
- **Tableau de signatures** : `margin-top: 30pt`, ligne vierge `height: 120px`,
  `page-break-inside: avoid` — posé en bas de page comme la référence.
- **Logo** : `o.company_id.logo` avec `t-if`. Sur SEFOR l'image de la société
  (`res.company(1).partner_id.image_1920`) est **vide** (ligne `ir_attachment`
  orpheline, binaire absent) → le logo n'apparaît pas sur les PDF de test. À
  renseigner par agence en production pour qu'il s'affiche (aucune action requise
  côté template).

---

## Lot 1 — 3 correctifs (retour Micka 2026-09-01, 2e passe)

1. **Adresse emprunteur & garant** : « monina ao amin'ny … » utilise une
   **concaténation `street` + `microfinance_fokontany_id.name` + `city`** (dans
   cet ordre, correction Micka), segments vides ignorés, séparés par « , ».
   Méthode **`res.partner.get_contrat_address()`**. Template :
   `t-set="borrower_address"` / `t-set="guarantor_address"`, chacun sous `t-if`.
   Mise en forme voulue (non harmonisée) : emprunteur = nom **et** adresse
   surlignés jaune+gras ; garant = **nom seul** surligné, adresse en gras simple
   sans surlignage.
2. **Bouton** : `class="btn-success"` (vert) + `<i class="fa fa-print"/>`,
   `type="object"` → `action_print_contrat_to_chatter` (plus `type="action"` sur
   l'`ir.actions.report`). `invisible="state != 'approved'"` inchangé.
3. **Plus de téléchargement** : nouvelle méthode
   **`microfinance.loan.action_print_contrat_to_chatter()`** — rend le PDF et le
   **poste en pièce jointe dans le chatter** (`message_post`), retourne un
   `display_notification` succès. Attachment scopé `res_model` / `res_id` /
   `company_id = self.company_id.id` (même patron que
   `action_print_repayment_schedule`, anti-fuite inter-agences). L'`ir.actions.report`
   perd `binding_model_id` / `binding_type` → n'apparaît plus dans le menu
   « Imprimer » standard d'Odoo.

Vérifié sur SEFOR (dossiers 4778 / 2327, `rollback` après test — aucune trace) :
1 message ajouté au chatter avec le PDF, attachment
`res_model=microfinance.loan res_id=… company_id=1`, PDF 1 page A4.

**Correctif 3bis** (constaté par Micka en test réel : le PDF partait bien dans le
chatter — attachment + `mail.message` créés — mais n'apparaissait qu'après
rechargement manuel de la fiche). `action_print_contrat_to_chatter()` renvoie
désormais `{'type': 'ir.actions.client', 'tag': 'soft_reload'}` au lieu d'un
`display_notification` (qui ne rafraîchit pas le chatter) → formulaire + chatter
rechargés automatiquement, PDF visible immédiatement.

## Lot 1 — 2 correctifs de mise en page (retour Micka 2026-09-01, 3e passe)

1. **Retour à la ligne avant « kara-panondro laharana »** : le bloc identité
   (emprunteur ET garant) est scindé en **2 paragraphes** — ligne 1 = nom +
   « monina ao amin'ny » + adresse ; ligne 2 = « kara-panondro laharana » + CIN.
   Le CIN passe toujours à la ligne, quelle que soit la longueur de l'adresse
   (le bloc « Ny mpindrana-bola » cassait quand l'adresse concaténée était
   longue). `<p>` du CIN sous `t-if` (masqué si pas de CIN).
2. **Suppression de tous les fonds jaunes** (`background-color:#FFFF00`) — c'était
   un repère de calibrage, pas un choix définitif. `.cc-hl` redéfini en
   `font-weight: bold;` seul (conserve le gras dans l'en-tête et la clause 1
   FEPETRA) ; les blocs emprunteur/garant réécrits en styles inline
   `font-weight:bold` / `text-decoration:underline`. Gras, soulignements (noms,
   titres, ALATSINAINY) conservés — seul le fond jaune disparaît. Vérifié : plus
   aucun `#FFFF00` dans le template, PDF toujours 1 page A4.

---

# AUDIT — 5 évolutions du formulaire `microfinance.loan` (Lot 0, 2026-09-01, 4e passe)

Lecture seule. Fichiers concernés : `views/microfinance_loan_views.xml`,
`models/microfinance_loan.py`, `static/src/js/microfinance_loan_form_view.js`,
`static/src/scss/` (+ manifest `assets`).

## 1. Bouton « Recalculer le score »

| Élément | Réalité |
|---|---|
| Définition | `views/microfinance_loan_views.xml:85` — `<button name="action_recompute_risk" string="Recalculer le score" type="object"/>`, dans le `<header>`, **sans classe**, juste avant `<field name="state">`. |
| Méthode | `action_recompute_risk()` (`microfinance_loan.py`) → appelle `action_calculate_scoring(silent=True)`. Inchangée. |
| Affichage du score | `views/microfinance_loan_views.xml:147` — `<field name="internal_score" widget="progressbar" readonly="1"/>` dans `<group string="Résumé financier">`. |
| Champ technique | **`internal_score`** (Float, `string='Score'`, `microfinance_loan.py:185`). Voisins : `risk_level`, `scoring_decision`, `scoring_line_ids`/`scoring_line_count`. |
| Stat button scoring ? | **Non** — le `button_box` n'a que Échéances / Paiements / Visites / Écritures / Enquête. `action_view_scoring_lines()` existe mais n'est câblé nulle part dans cette vue. |

➡️ **Lot 1** : `xpath` sur `//field[@name='internal_score']`, déplacer le bouton
juste après (dans le groupe « Résumé financier »). `type="object"` / `name`
inchangés. Le bouton disparaît du `<header>`.

## 2. Bouton « Imprimer le calendrier de remboursement »

| Élément | Réalité |
|---|---|
| Définition | `views/microfinance_loan_views.xml:76` — `<button name="action_print_repayment_schedule" string="Imprimer le calendrier de remboursement" type="object" invisible="installment_count == 0"/>`, **sans classe ni icône**. |
| Comportement | `action_print_repayment_schedule()` (`microfinance_loan.py:~1796`) : rend le QWeb PDF, crée un `ir.attachment` (`res_model`/`res_id`/`company_id`), `message_post(attachment_ids=[…])`, **retourne un `display_notification`**. → **déjà chatter, PAS de téléchargement.** Même comportement que le bouton contrat. |
| Rafraîchissement chatter | Géré par `static/src/js/microfinance_loan_form_view.js` (commit `d1e471a`) : `MicrofinanceLoanFormController.afterExecuteActionButton` déclenche `MAIL:RELOAD-THREAD` **si `clickParams.name === 'action_print_repayment_schedule'`** → recharge uniquement le fil, pas le formulaire. |

➡️ **Lot 1** : renommer en **« Imprimer le calendrier »**, ajouter la classe verte
+ icône. Comportement inchangé (déjà chatter).

⚠️ **Écart à signaler** : la classe `btn-cefor-print` / la couleur `#1D9E75`
citées par le prompt **n'existent nulle part** dans le module. Le bouton contrat
utilise aujourd'hui `class="btn-success"` (vert Bootstrap standard), pas une
classe CEFOR dédiée. Pour « réutiliser exactement la même classe », il faut
**créer** `.btn-cefor-print` (`#1D9E75`, texte blanc, hover assombri) dans une
SCSS du module, l'appliquer **aux deux** boutons (contrat + calendrier), et
retirer `btn-success` du bouton contrat. → à confirmer par Micka.

⚠️ **Incohérence de rafraîchissement chatter** : le bouton contrat
(`action_print_contrat_to_chatter`, correctif 3bis de la 3e passe) renvoie
`{'tag': 'soft_reload'}` (recharge tout le formulaire), alors que le calendrier
utilise le JS `MAIL:RELOAD-THREAD` (recharge le fil seul). **Recommandation** :
revenir sur le contrat à `display_notification` et **ajouter
`action_print_contrat_to_chatter` à la condition du JS** `d1e471a` — un seul
mécanisme, pas de rechargement complet du formulaire (préserve une saisie en
cours ailleurs sur la fiche). À valider par Micka (hors périmètre strict des 5
points mais lié).

## 3. Upload du contrat signé

| Élément | Réalité |
|---|---|
| Champ Binary simple sur `microfinance.loan` | **Aucun** — à créer. Patterns existants : `microfinance.loan.guarantee.document` (Binary) + `document_filename` (Char) ; `microfinance.loan.application` gère des `document_line_ids` (One2many, trop lourd ici). |
| État « crédit actif » | **`state == 'active'`** — posé par `action_disburse()` (bouton « Activer / Décaisser »). À ne pas confondre avec `'approved'` (bouton contrat). |
| `message_post` dispo | Oui, `microfinance.loan` hérite `mail.thread` / `mail.activity.mixin`. |
| Modèle `ir.attachment` étendu dans le module ? | **Non** — aucun `_inherit = 'ir.attachment'`. Seul `unlink()` surchargé ailleurs : `microfinance.loan.application:2058` (contrôle de groupe, sans rapport). |

➡️ **Lot 1** : nouveaux champs `signed_contract` (Binary, `attachment=True`) +
`signed_contract_filename` (Char) sur `microfinance.loan`. Vue : `widget="binary"`
libellé « Contrat signé », `invisible="state != 'active'"`. `write()` (ou
`@api.onchange` + `write`) : à l'ajout du fichier, `message_post` avec la pièce
jointe et le corps « Contrat signé téléversé. ». Nouveau fichier
`models/ir_attachment.py` à ajouter dans `models/__init__.py` et le manifest si
besoin (le fichier `.py` est auto-chargé par `__init__`, pas besoin d'entrée
`data`).

## 4. Empêcher la suppression du contrat signé

| Élément | Réalité |
|---|---|
| Règles d'accès `ir.attachment` dans le module | **Aucune** (`security/` ne mentionne pas `ir.attachment`). |
| Règle globale bloquant `unlink()` | **Aucune** — comportement Odoo standard (unlink autorisé si l'utilisateur a le `write` sur l'enregistrement lié). |
| Conflit potentiel | Aucun. |

➡️ **Lot 1** : `models/ir_attachment.py` — `class IrAttachment(models.Model):
_inherit = 'ir.attachment'`, override `unlink()` : lever `UserError` uniquement
si `att.res_model == 'microfinance.loan' and att.res_field == 'signed_contract'`.
Les PDF générés (contrat, calendrier) ont `res_field = False` → non protégés,
restent supprimables. Le **remplacement** du fichier via le champ Binary passe
par `write()` sur `ir.attachment` (pas `unlink()`) → non bloqué. À vérifier en
test : ré-upload d'une nouvelle version = OK.

## 5. Barre d'état (statusbar)

| Élément | Réalité |
|---|---|
| `widget="statusbar"` déjà présent ? | **Oui** — `views/microfinance_loan_views.xml:86` : `<field name="state" widget="statusbar" statusbar_visible="draft,enquete,avis_ca,avis_cdag,approved,active,closed,defaulted,written_off"/>`. |
| Position | **Dernier élément du `<header>`**, après les 12 boutons. |
| `clickable` | **Non spécifié** → défaut Odoo 17 = **cliquable** (un manager peut cliquer une étape pour forcer l'état). Comportement actuel à conserver tel quel (ne pas ajouter/retirer `clickable`). |
| Rendu « menu déroulant » | C'est le **repli responsive** du widget : 9 états + 12 boutons dépassent la largeur du header → Odoo replie les étapes dans un `dropdown-toggle` (`statusbar_field.xml:23,52`). |
| Classes CSS réelles (Odoo 17, `addons/web/.../statusbar/statusbar_field.xml`) | `.o_statusbar_status` (conteneur), `.o_arrow_button` (chaque étape, aussi `.btn.btn-secondary`), `.o_arrow_button_current` (étape courante), `.o_first` / `.o_last` (extrémités). |
| Distinction passé / futur | **Non native** : le widget ne colore que l'étape courante. Les étapes « déjà passées » et « futures » ont le même style par défaut. |
| Assets module | `web.assets_backend` dans le manifest, contient déjà 3 SCSS. Form loan : `js_class="microfinance_loan_form"` (JS enregistré) mais **pas** de `class=` sur `<form>` → pas de racine CSS dédiée pour scoper. |

➡️ **Lot 1** :
- Déplacer `<field name="state" widget="statusbar" …/>` en **1re position** du
  `<header>`, avant tous les `<button>` (rendu Odoo standard : le statusbar
  occupe alors sa propre ligne en haut).
- Ajouter `class="o_microfinance_loan_form"` sur `<form>` (à côté de `js_class`)
  pour pouvoir scoper le SCSS (comme `o_microfinance_loan_application_form`).
- Nouveau `static/src/scss/microfinance_loan_form.scss` (ajouté au manifest
  `assets/web.assets_backend`), scopé `.o_microfinance_loan_form .o_statusbar_status`
  : neutraliser les chevrons (`clip-path`/`::before`/`::after`), segments
  accolés, `border-radius` extrémités seules, `padding: 6px 14px`,
  `font-size: 12px`, couleur étape courante `#714B67` blanc `font-weight:500`,
  étapes futures `#D8D6DD` / `#5B5866`.
- ❓ **Décision Micka** : la coloration **passé `#8B8FA3`** exige de distinguer
  les étapes avant/après l'étape courante — **impossible en CSS pur** (le widget
  ne pose aucune classe « passé »). Deux options :
  1. Petite extension JS du widget `statusbar` (ou du `js_class` déjà présent)
     pour ajouter une classe `o_passed` aux étapes d'index < index courant.
  2. Se contenter du natif : seule l'étape courante colorée (`#714B67`), toutes
     les autres en gris clair `#D8D6DD`. Plus simple, pas de JS.
- ❓ Le repli en dropdown persistera si le header reste trop étroit même après
  avoir sorti « Recalculer le score » (point 1). Le CSS custom peut forcer
  `flex-wrap` / autoriser le retour à la ligne des étapes, mais le rendu
  « une seule ligne propre » de la capture de référence suppose que ça tient.
  À vérifier au rendu réel.

## Points ouverts pour Micka (avant Lot 1)

1. **`btn-cefor-print` (#1D9E75)** : le créer (SCSS module) et l'appliquer aux 2
   boutons verts (contrat + calendrier), en remplaçant `btn-success` sur le
   contrat ? (Recommandé, sinon 2 verts différents.)
2. **Rafraîchissement chatter du bouton contrat** : revenir à
   `display_notification` + étendre le JS `d1e471a` à
   `action_print_contrat_to_chatter` (mécanisme unique, pas de reload complet) ?
3. **Statusbar passé/courant/futur** : extension JS pour la 3e couleur
   (`#8B8FA3` passé), ou natif (courant seul coloré) ?
4. **Statusbar** : capture de référence non fournie dans cette itération — les
   couleurs/formes sont reprises du texte du prompt. À confirmer visuellement au
   Lot 1.

### Décisions Micka (2026-09-01) — passage au Lot 1

1. `.btn-cefor-print` (#1D9E75) : **oui**, créée + appliquée aux 2 boutons verts,
   `btn-success` retiré du contrat.
2. Chatter bouton contrat : **mécanisme unique** — retour `display_notification`,
   `action_print_contrat_to_chatter` ajouté à la condition du JS `d1e471a`.
3. Statusbar passé/courant/futur : **extension JS** (classe `o_passed`).
4. Référence statusbar = la capture fournie (segments accolés : Brouillon/Enquête/
   Avis CA/Avis CDAG en gris moyen, Approuvé en violet, Actif/Clôturé/Défaut en
   gris clair).

---

# LOT 1 — 5 évolutions du formulaire (implémenté, 2026-09-01)

| # | Changement | Fichiers |
|---|---|---|
| 1 | Bouton « Recalculer le score » retiré du `<header>`, replacé dans le groupe « Résumé financier » juste après `<field name="internal_score">` (`class="btn-secondary btn-sm" icon="fa-refresh"`, `name`/`type` inchangés). | `views/microfinance_loan_views.xml` |
| 2 | Bouton renommé **« Imprimer le calendrier »**, `class="btn-cefor-print"` + `<i class="fa fa-print"/>`. Bouton contrat : `btn-success` → `btn-cefor-print`. Comportement inchangé (déjà chatter). | `views/…`, `scss/microfinance_loan_form.scss` (nouvelle classe) |
| 3 | Champs `signed_contract` (Binary, `attachment=True`) + `signed_contract_filename` (Char) sur `microfinance.loan`. Vue : `widget="binary"`, `invisible="state != 'active'"`, dans le groupe « Suivi ». `write()` → `_post_signed_contract_to_chatter()` : à l'ajout du fichier, copie indépendante (res_field vide) postée au chatter avec « Contrat signé téléversé. ». | `models/microfinance_loan.py`, `views/…` |
| 4 | Nouveau `models/ir_attachment.py` : `unlink()` lève `UserError` si `res_model=='microfinance.loan'` **et** `res_field=='signed_contract'`. Contexte `bypass_signed_contract_protection` (posé par `microfinance.loan.unlink()`) pour la suppression du dossier. Vérifié : suppression pièce jointe champ **bloquée**, `write({'signed_contract': False})` **bloqué**, remplacement (`write` nouveau `datas` sur la même pièce jointe, id inchangé) **autorisé**, copie chatter **supprimable**, suppression du crédit **non bloquée**. | `models/ir_attachment.py`, `models/__init__.py`, `models/microfinance_loan.py` |
| 5 | `<field name="state" widget="statusbar">` déplacé en **1re position** du `<header>` (sa propre ligne au-dessus des boutons). `class="o_microfinance_loan_form"` ajoutée sur `<form>`. Nouveau `scss/microfinance_loan_form.scss` : segments plats accolés (chevrons `::before/::after` masqués, `border:0`, `padding:6px 14px`, `font-size:12px`), coins arrondis extrémités seules, `flex-flow: row-reverse nowrap` (empêche le repli en dropdown), couleurs courant `#714B67`/blanc, futures `#D8D6DD`/`#5B5866`. Extension JS : `patch(StatusBarField.prototype.setup)` borné à `microfinance.loan`/`state`, ajoute `.o_passed` (`#8B8FA3`/blanc) aux étapes d'index < index courant. | `views/…`, `scss/microfinance_loan_form.scss`, `js/microfinance_loan_form_view.js`, `__manifest__.py` (assets) |

**Correctif lié** : `action_print_contrat_to_chatter()` renvoie de nouveau
`display_notification` (au lieu du `soft_reload` de la 3e passe) ; le rafraîchissement
du chatter passe par le JS `MicrofinanceLoanFormController` (constante
`CHATTER_REFRESH_BUTTONS` = calendrier + contrat).

**Non testé (nécessite restart + navigateur)** : rendu visuel de la statusbar (SCSS
+ `o_passed`), couleur des boutons verts, position du bouton « Recalculer le
score », visibilité de « Contrat signé ». Logique serveur (upload chatter,
protection unlink, non-régression bouton contrat) vérifiée en `odoo-bin shell` avec
`rollback`.

⚠️ Le champ « Contrat signé » est `invisible="state != 'active'"` (strict, comme
demandé). À confirmer : le laisser visible aussi en `closed` / `defaulted` /
`written_off` ?

**Ajustement statusbar (retour Micka + capture 4e passe)** : la barre était crammée
en haut à droite et en police 12px. Corrigé dans `microfinance_loan_form.scss` :
- wrapper du champ `state` → `flex: 1 1 100%` sur sa propre ligne (double sélecteur
  `.o_field_widget.o_field_statusbar` / `[name="state"]`) ;
- `.o_statusbar_status` → `width: 100%` ;
- chaque segment `.o_arrow_button` → `flex: 1 1 0` (largeur égale, occupe tout le
  sheet), `font-size: inherit` (= police système des boutons), `padding: 0.35em
  0.6em` (proportionnel), `text-overflow: ellipsis`.
Bundle `web.assets_backend` recompilé sans erreur, règles présentes dans le CSS.

### STOP — Validation Micka avant Lot 1 (audit) / avant commit (implémentation)
