# AUDIT — Ajout `product_fee` sur `microfinance.loan.product` (Lot 0, 2026-09-03)

Lecture seule. Objectif : cadrer l'ajout d'un taux de frais de dossier (%) par
produit, défaut 5 %, dans l'onglet « Calcul crédit ».

---

## 1. Frais de dossier — état actuel

### 1.1 Champs déjà présents sur `microfinance.loan.product`

`microfinance_loan_management/models/microfinance_loan_product.py`

| Champ | Type | Défaut | Rôle | Ligne |
|---|---|---|---|---|
| `fee_type` | Selection `fixed` / `percentage` | `'fixed'` (required) | montant fixe **ou** % du montant du crédit | 340-343 |
| `fee_amount` | Monetary « Frais fixes » | `0.0` | montant si `fee_type == 'fixed'` | 344 |
| **`fee_rate`** | **Float « Taux de frais (%) »** | **`0.0`** | **% du montant du crédit si `fee_type == 'percentage'`** — **c'est exactement le `product_fee` demandé** | 345 |
| `fee_journal_id` | Many2one `account.journal` | journal `CRE` | encaissement des frais | 346-352 |
| `fee_charged_before_disbursement` | Boolean | `True` | si vrai, `action_disburse()` bloque tant que les frais ne sont pas encaissés | 353-356 |
| `account_commission_credit_id` | Many2one `account.account` | **PCEC `717003`** « Commission sur crédit » | compte de comptabilisation des frais de dossier | 315-319 |

Contrainte `_check_values` (L400-417) : `fee_amount >= 0` et `fee_rate >= 0`.

### 1.2 Emplacement dans la vue produit

`microfinance_loan_management/views/microfinance_loan_product_views.xml`

- **Onglet « Calcul crédit »** (L51-62) : `interest_rate`, `interest_method`,
  `repayment_frequency_mode`, `repayment_frequency_id`,
  `allowed_repayment_frequency_ids`, `grace_period_days`,
  `installment_rounding_unit`, `installment_rounding_mode`. **Aucun champ de frais
  ici aujourd'hui.**
- **Onglet « Comptabilité » > groupe « Journaux et frais »** (L81-91) :
  `disbursement_journal_id`, `disbursement_limit_amount`,
  `check_cash_balance_at_disbursement`, `payment_journal_id`, **`fee_type`**,
  **`fee_amount`** (`invisible="fee_type != 'fixed'"`), **`fee_rate`**
  (`invisible="fee_type != 'percentage'"`), `fee_journal_id`,
  `fee_charged_before_disbursement`.
- Compte des frais : onglet « Comptabilité » > groupe « Pénalités et commissions »
  (L114-120) → `account_commission_credit_id`.

### 1.3 « Frais de dossier dus » sur `microfinance.loan` — **déjà calculé, jamais saisi**

`microfinance_loan.py`

- `fee_amount_due = fields.Monetary(compute='_compute_fee_amount', store=True, string='Frais de dossier dus')` (L229)
  — **stored compute, sans inverse, sans `readonly=False`** → strictement calculé,
  non modifiable à la main. Affiché `readonly="1"` sur le form loan (groupe
  « Résumé financier »), avec `fee_paid` (readonly) et `fee_move_id` (readonly).
- `_compute_fee_amount` (L505-514) :
  ```python
  @api.depends('loan_amount', 'product_id.fee_type', 'product_id.fee_amount', 'product_id.fee_rate')
  def _compute_fee_amount(self):
      for loan in self:
          product = loan.product_id
          if not product:            loan.fee_amount_due = 0.0
          elif product.fee_type == 'fixed':  loan.fee_amount_due = product.fee_amount
          else:                      loan.fee_amount_due = loan.loan_amount * product.fee_rate / 100.0
  ```
  → **quand `fee_type == 'percentage'`, `fee_amount_due = loan_amount × product.fee_rate / 100`.**

  ⚠️ `@api.depends('product_id.fee_rate')` + `store=True` → **modifier `fee_rate`
  sur un produit recalcule `fee_amount_due` sur TOUS les crédits liés, y compris
  déjà approuvés / actifs.** (Point de décision 5 ci-dessous.)

### 1.4 Où le montant de frais est utilisé

| Emplacement | Usage |
|---|---|
| `microfinance_loan.py:_compute_fee_amount` | le calcul lui-même |
| `microfinance_loan.py:_compute_net_disbursed_amount` (L525-529) | `net_disbursed_amount = loan_amount − fee_amount_due` si `not fee_charged_before_disbursement` |
| `microfinance_loan.py:_prepare_fee_move` / `action_charge_fee` (L1495-1526) | écriture d'encaissement séparée : débit `fee_journal_id.default_account_id`, crédit `account_commission_credit_id`, montant `fee_amount_due` |
| `microfinance_loan.py:_prepare_disbursement_move` (L1478-1483) | si `not fee_charged_before_disbursement` : nette `fee_amount_due` du décaissement, crédit `account_commission_credit_id` |
| `microfinance_loan.py:action_disburse` (L1681) | bloque si `fee_charged_before_disbursement and not fee_paid and fee_amount_due > 0` |
| Vue form loan | `fee_amount_due` / `fee_paid` / `fee_move_id` (readonly) + bouton header « Encaisser les frais de dossier » |
| `report/microfinance_loan_disbursement_receipt.xml:43` | « Frais de dossier prélevés » → `o.fee_amount_due` |
| `report/report_contrat_credit.xml:170` | `o.fee_amount_due` + `(<fee_rate>% n'ny vola nindramina)` si `fee_type == 'percentage'` |
| `tests/test_fee.py` | teste `fee_type` / `fee_amount` / `fee_rate` / `fee_amount_due` / `fee_charged_before_disbursement` (fixed = montant, percentage `fee_rate: 2.0` → `fee_amount_due == 20.0` sur crédit 1000) |

Aucun wizard n'utilise les frais. Dossier `migrations/` présent (jusqu'à
`17.0.1.8.0`) ; version module `17.0.1.10.0`.

---

## 2. `product_fee` existe-t-il déjà sous un autre nom ?

**Oui, à 100 % : c'est `fee_rate`** (Float, « Taux de frais (%) », % du montant du
crédit, déjà branché sur `_compute_fee_amount`). Recherche `product_fee`,
`frais_dossier_percent`, `commission_rate`, `frais_percent` → **aucune autre
occurrence.** Seule différence avec la demande : `default=0.0` (vs 5.0 souhaité) et
`fee_type` par défaut `'fixed'` (donc `fee_rate` non appliqué tant que le produit
n'est pas passé en `'percentage'`).

---

## 3. PCEC 420010

**Introuvable dans le code.** Le seul compte « frais / commission » utilisé pour
les frais de dossier est `product.account_commission_credit_id`, dont le défaut
résout le code PCEC **`717003`** (« Commission sur crédit »). `420010` n'apparaît
que dans des données géographiques (`commune_4420010`, sans rapport). → **à
confirmer avec Micka** : le prompt se trompe-t-il de numéro, ou le plan CEFOR
mappe-t-il `717003` ↔ `420010` ? Le montant porté sur ce compte est toujours
`fee_amount_due` (compute), jamais saisi dossier par dossier.

---

## 4. Impacts d'un changement de source (valeur produit vs valeur saisie)

**Aucun changement de source nécessaire** : la source est **déjà** le produit
(`fee_rate`), et « Frais de dossier dus » est **déjà** un compute pur. Le premier
point de décision du prompt (« si saisi manuellement… onchange vs compute ») est
**sans objet**.

Le seul « impact » réel = choisir comment introduire le 5 % par défaut sans casser
l'existant (« PRET RURAL » est aujourd'hui `fee_type='fixed'`, `fee_amount=10000`,
`fee_rate=0`).

---

## 5. Options pour le Lot 1

### Option A (recommandée) — réutiliser `fee_rate`, sans nouveau champ

- `fee_rate` : `default` `0.0` → **`5.0`** ; `string` « Taux de frais (%) » →
  éventuellement « Frais de dossier (%) ».
- `fee_type` : `default` `'fixed'` → **`'percentage'`** (pour que le 5 %
  s'applique par défaut).
- Vue : afficher `fee_type` + `fee_amount` + `fee_rate` **aussi (ou plutôt) dans
  l'onglet « Calcul crédit »**, près de `interest_rate` — soit par déplacement,
  soit par duplication d'affichage (le champ reste unique en base).
- Aucune modif de `_compute_fee_amount` (déjà branché), aucune migration lourde,
  `test_fee.py` inchangé.
- Rétro-compat : `default` ne touche que les **nouveaux** produits. Produits
  existants inchangés sauf migration explicite (point de décision 4).

### Option B — créer `product_fee` en plus (demande littérale)

- Nouveau `product_fee = fields.Float(string="Frais de dossier (%)", default=5.0)`.
- Rebrancher `_compute_fee_amount` dessus.
- **Doublon fonctionnel avec `fee_rate`** : deux « % de frais » sur le même
  modèle → ambiguïté de config, risque d'incohérence. Impose de déprécier
  `fee_rate` (migration + `test_fee.py` + `report_contrat_credit.xml` +
  `_check_values`). Beaucoup d'effort pour un renommage déguisé.

### Option C — renommer proprement `fee_rate` → `product_fee`

- `ALTER TABLE ... RENAME COLUMN fee_rate TO product_fee` en `pre-migrate`
  (nouvelle version, ex `17.0.1.11.0`) → valeurs existantes préservées.
- Adapter `_compute_fee_amount` (`@api.depends` + formule), `_check_values`,
  `report_contrat_credit.xml:170`, `test_fee.py`, vue produit.
- Propre à terme, mais c'est un chantier de renommage, pas un simple ajout.

---

## 6. Points de décision à trancher avec Micka avant le Lot 1

1. **Calcul « Frais de dossier dus »** : il est **déjà** un compute pur basé sur
   `product.fee_rate`. Confirmer qu'on garde ce comportement (rien à changer côté
   `microfinance.loan`) ?
2. **Nouveau champ `product_fee` (doublon de `fee_rate`)** vs **réutiliser /
   renommer `fee_rate`** ? (reco : Option A — réutiliser.)
3. **`fee_type`** : garder les 2 modes (`fixed` / `percentage`) configurables, ou
   forcer `percentage` par défaut (voire retirer `fixed` si CEFOR ne facture qu'en
   %) ?
4. **Défaut 5 %** : uniquement les nouveaux produits (via `default`), ou migration
   rétroactive sur les produits existants (dont « PRET RURAL » en `fixed`/10000
   aujourd'hui) ?
5. **Recalcul rétroactif** : `_compute_fee_amount` est `@api.depends('product_id.
   fee_rate')` + `store=True` → changer le taux sur un produit **recalcule
   `fee_amount_due` sur les crédits déjà approuvés / actifs**. Souhaité, ou
   faut-il figer les frais au moment de l'approbation/décaissement ?
6. **Verrouillage `_LOCKED_DOSSIER_STATES`** : ce verrou porte sur des champs du
   **dossier** `microfinance.loan` (`loan_amount`, `term`, `product_id`,
   `interest_rate`, `installment_amount`). `fee_rate` / `product_fee` est un champ
   **produit**, hors périmètre de ce verrou. Confirmer qu'on ne l'y ajoute pas
   (le seul risque « rétroactif » est le point 5 ci-dessus).
7. **PCEC** : prompt = `420010`, code = `717003` (`account_commission_credit_id`).
   Quel est le bon compte / le mapping ?

**Ne rien implémenter avant arbitrage de ces 7 points.**

---

## LOT 1 — Implémentation (2026-09-03, décisions Micka appliquées)

Décisions retenues : compute pur conservé ; **réutiliser `fee_rate`** (pas de
`product_fee`) ; `fee_type` reste `fixed`/`percentage` au choix du produit ;
défaut 5 % **nouveaux produits seulement** (pas de migration) ; **frais figés dès
l'approbation** ; `_LOCKED_DOSSIER_STATES` non touché ; PCEC = **717003**
(`account_commission_credit_id`, inchangé).

| Fichier | Changement |
|---|---|
| `models/microfinance_loan_product.py` | `fee_rate` : `default` `0.0` → **`5.0`** + `help` explicite (fr). Aucun autre changement. |
| `models/microfinance_loan.py` | Nouvelle constante `_FEE_FROZEN_STATES = ('approved','active','closed','defaulted','written_off')`. `_compute_fee_amount` : pour un dossier dans ces états, **conserve la valeur en base** (lecture SQL directe de `fee_amount_due`) au lieu de recalculer — un changement ultérieur de `fee_rate`/`fee_amount` sur le produit ne fait plus bouger les frais d'un dossier déjà approuvé. Dossiers avant `approved` : suivent toujours la config produit courante. |
| `views/microfinance_loan_product_views.xml` | `fee_type` / `fee_amount` / `fee_rate` **déplacés** de l'onglet « Comptabilité » > « Journaux et frais » vers l'onglet **« Calcul crédit »**, juste après « Méthode d'intérêt ». `fee_journal_id` + `fee_charged_before_disbursement` restent dans « Comptabilité ». |
| `tests/test_fee.py` | Nouveau `test_fee_frozen_from_approval` : dossier approuvé à 5 % → `fee_amount_due == 50` ; on passe le produit à 3 % → dossier approuvé **inchangé (50)**, dossier encore `draft` → **30**, nouveau dossier → **30**. |
| `tests/common.py` | ⚠️ **Correction d'une régression d'un lot précédent** (contrat signé) : `action_disburse()` exige désormais `signed_contract`. Le helper partagé `_create_loan` pose maintenant un `signed_contract` factice (surchargeable `signed_contract=False`), sinon **tous** les tests de décaissement échouaient. Sans rapport avec `product_fee` mais nécessaire pour que la suite tourne. |

### Vérifications

- `-u microfinance_loan_management -d SEFOR` : **propre** (Modules/Registry loaded, 0 erreur).
- Vue produit : `fee_type`/`fee_amount`/`fee_rate` bien dans « Calcul crédit »,
  absents de « Comptabilité », `fee_journal_id` toujours dans « Comptabilité ».
  `default_get(['fee_rate'])` sur un nouveau produit → **5.0**. `get_views` OK.
- `test_fee_frozen_from_approval` : **PASS**. `test_fee_amount_fixed` /
  `test_fee_amount_percentage` : **PASS** (compute existant intact).

### Limite de validation — suite complète non exécutable sur SEFOR

`--test-enable` sur SEFOR échoue sur ~18 tests de décaissement, **cause
environnementale, pas le code** : SEFOR contient 2 `microfinance.fond.credit`
réels actifs (`BM AID`, `joj`, société 1) → `_check_fond_disponibilite()` bloque
tout `action_disburse()` de dossier de test sans `fond_credit_id`. Ces tests
passent sur une base de test vierge. Un `-i` sur base neuve échoue de son côté
pour une raison distincte (`agency_code` NOT NULL, `microfinance_partner_views.xml`
suppose des sociétés configurées). → **à faire tourner sur une vraie base de CI
propre** ; les erreurs observées ne proviennent ni de `product_fee` ni du fix
`common.py`.

### STOP — relire le diff avant commit
