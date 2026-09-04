# Audit — Badges payé/non-payé + lien vers l'écriture (frais de dossier & épargne garantie)

Audit **lecture seule** (Lot 0). Aucune modification de code.

> ## ✅ Décision Micka — 2026-09-04
>
> | Volet | Décision |
> |---|---|
> | **1 — frais** | Badge `fee_payment_state` (`Selection` calqué sur `risk_level`) + liens `fee_move_id` / `fee_receivable_move_id` existants. Tout dans `microfinance_loan_management`. |
> | **2 — épargne garantie** | **Option (b)** : le badge `guarantee_savings_state` pointe vers **`savings_account_id`** (le compte épargne de prélèvement du crédit). Rendu dans `microfinance_savings_management` (vue héritée `view_microfinance_loan_form_inherit_savings`). |
>
> **Réserve actée sur (b)** : `savings_account_id` est le compte de *prélèvement automatique / cible progressive*, pas strictement la somme des comptes qui composent `guarantee_savings_balance`, et il peut être **vide**. Le Lot 1 devra : (i) n'afficher le lien que si `savings_account_id` est renseigné ; (ii) garder le bouton statistique « Épargne » existant comme accès à l'ensemble des comptes épargne du client.
>
> **Périmètre Lot 1 :**
> 1. `microfinance_loan_management` : champ calculé `fee_payment_state` sur `microfinance.loan` + badge dans `microfinance_loan_views.xml` (groupe Résumé financier), `fee_paid` passé en `invisible="1"`.
> 2. `microfinance_savings_management` : champ calculé `guarantee_savings_state` sur l'extension `microfinance.loan` + badge dans `microfinance_loan_views_inherit.xml`, à côté un lien vers `savings_account_id` (visible seulement si renseigné). `guarantee_savings_verified` passé en `invisible="1"` (ou conservé, à préciser).
> 3. Pas de nouveau modèle, pas de migration, pas de champ stocké (les deux `Selection` dérivent de champs déjà présents/stockés).

Le reste de ce document est le rapport d'audit d'origine.

---

## Volet 1 — `fee_amount_due` (« Frais de dossier dus »)

### 1. État actuel de l'affichage

`microfinance_loan_management/views/microfinance_loan_views.xml`, groupe « Résumé
financier » (lignes **192-196**) :

```xml
<field name="fee_amount_due" readonly="1"/>
<field name="fee_paid" readonly="1"/>
<field name="fee_receivable_move_id" readonly="1" invisible="not fee_receivable_move_id"/>
<field name="fee_move_id" readonly="1"/>
```

- `fee_amount_due` : `Monetary`, affiché brut (montant).
- `fee_paid` : `Boolean`, affiché en **checkbox** grise readonly.
- `fee_receivable_move_id` / `fee_move_id` : `Many2one('account.move')`, affichés en
  champ readonly. **En vue formulaire readonly, un Many2one se rend déjà comme un lien
  interne cliquable** vers la fiche de l'`account.move` (comportement Odoo natif, aucun
  widget requis). `fee_move_id` porte le libellé « Écriture de frais » ;
  `fee_receivable_move_id` « Écriture engagement frais » (masqué tant que vide).

Aucun `widget=` n'est posé sur ces champs aujourd'hui. Pas de badge, pas de couleur.

### 2. Un `widget="badge"` standard suffit-il ?

**Partiellement.** `widget="badge"` (Odoo 17, `web/static/src/views/fields/badge/`) rend
la **valeur d'un champ** sous forme de pastille colorée via `decoration-success` /
`decoration-warning` / `decoration-danger`. Il fonctionne sur `Selection`, `Char`,
`Many2one` — **pas sur `Boolean`**. Il est en **lecture seule** et **ne fournit pas de
lien** vers un autre enregistrement (une pastille n'est pas cliquable).

Donc « badge coloré payé/non-payé » **+** « lien cliquable vers le move » = **deux
éléments distincts**, pas un widget unique :

| Besoin | Élément |
|---|---|
| Badge vert/rouge payé/non-payé | **nouveau champ calculé `Selection`** rendu en `widget="badge"` (voir §3, calqué sur `risk_level`) |
| Lien vers l'écriture | **le champ `fee_move_id` existant**, déjà rendu en lien interne cliquable en vue readonly — rien à faire, juste le garder visible (et `fee_receivable_move_id` pour l'engagement) |

Un **widget custom** combinant les deux dans un seul contrôle est *possible* mais non
nécessaire et non idiomatique ici : le module n'a aucun widget OWL custom de ce type
aujourd'hui, ce serait le premier. **Non recommandé.**

### 3. Pattern badge existant réutilisable — `risk_level`

`microfinance_loan_management/views/microfinance_scoring_views.xml` — vue **héritée**
`view_microfinance_loan_form_scoring_inherit` (ligne **189**), ajoutée après le groupe de
`internal_score` :

```xml
<field name="risk_level" widget="badge" readonly="1"
       decoration-success="risk_level == 'low'"
       decoration-warning="risk_level == 'medium'"
       decoration-danger="risk_level in ('high','critical')"/>
```

(idem `scoring_decision` juste en dessous, et en tree/kanban lignes 151-152.) Autres
badges du module, tous sur des `Selection` d'état : `state` sur crédit, échéance,
paiement, session caisse, fiche journée, contribution fonds, dossier d'instruction.
**Aucun badge sur un `Boolean`** — c'est toujours un `Selection` derrière.

### 4. Proposition Volet 1 (pour le Lot 1)

1. **Nouveau champ calculé** sur `microfinance.loan` (dans
   `microfinance_loan_management`, le mécanisme frais y vit déjà) :

   ```python
   fee_payment_state = fields.Selection(
       [('none', 'Sans frais'), ('unpaid', 'Non payé'), ('paid', 'Payé')],
       string='État frais de dossier', compute='_compute_fee_payment_state')
   ```
   `_compute_fee_payment_state` : `'none'` si `fee_amount_due <= 0`, sinon `'paid'` si
   `fee_paid` else `'unpaid'`. Non stocké (dérive de `fee_paid` + `fee_amount_due`, déjà
   stockés).

2. **Vue** (`microfinance_loan_views.xml`, groupe Résumé financier) — remplacer la
   checkbox `fee_paid` par le badge, garder les liens :
   ```xml
   <field name="fee_amount_due" readonly="1"/>
   <field name="fee_payment_state" widget="badge" readonly="1"
          decoration-success="fee_payment_state == 'paid'"
          decoration-danger="fee_payment_state == 'unpaid'"
          decoration-muted="fee_payment_state == 'none'"
          invisible="fee_payment_state == 'none'"/>
   <field name="fee_paid" invisible="1"/>   <!-- gardé pour les domaines/автrewriteoff éventuels -->
   <field name="fee_receivable_move_id" readonly="1" invisible="not fee_receivable_move_id"/>
   <field name="fee_move_id" readonly="1"/>
   ```
   Style identique à `risk_level`. Le lien vers l'`account.move` reste les champs
   `fee_move_id` (règlement) et `fee_receivable_move_id` (engagement), déjà cliquables.

3. **Module cible : `microfinance_loan_management`** (champ + vue de base). Le badge frais
   n'a aucune dépendance épargne.

*Option plus légère si Micka ne veut pas d'un nouveau champ* : `widget="badge"` directement
sur `fee_payment_state`… nécessite quand même le champ. Il n'y a pas de moyen propre de
mettre un badge sur le `Boolean` `fee_paid` sans champ Selection intermédiaire.

---

## Volet 2 — `guarantee_savings_required` (« Épargne garantie requise »)

### 4. Déclarations (base vs extension)

**Base — `microfinance_loan_management/models/microfinance_loan.py:164-171` :**

```python
guarantee_savings_required = fields.Monetary(
    string='Épargne garantie requise',
    help="Saisie libre par défaut - ce module seul n'a aucune notion d'épargne garantie de "
         "crédit. Redéclaré en champ calculé (compute+store, lecture seule) par "
         "microfinance_savings_management s'il est installé.")
guarantee_savings_balance = fields.Monetary(
    string='Solde épargne garantie du client',
    help="Saisie libre par défaut, mêmes règles que guarantee_savings_required ci-dessus.")
```

Déclarés dans le module de base **uniquement** parce que
`microfinance.loan.application.required_savings` / `available_savings` y sont `related=` et
qu'un `related=` vers une cible inexistante casse le chargement (cf. commentaire
`microfinance_loan.py:152-163`). Sans le module épargne : champs `Monetary` inertes, jamais
calculés.

**Extension — `microfinance_savings_management/models/microfinance_loan_extension.py:28-38` :**

```python
guarantee_savings_required = fields.Monetary(
    compute='_compute_guarantee_savings_required', store=True, string='Épargne garantie requise',
)
guarantee_savings_balance = fields.Monetary(
    compute='_compute_guarantee_savings_balance', string='Solde épargne garantie du client',
    help="Somme des soldes des comptes actifs du client sur le produit d'épargne garantie de "
         "crédit configuré sur le produit de crédit.",
)
guarantee_savings_verified = fields.Boolean(
    compute='_compute_guarantee_savings_verified', string='Épargne garantie vérifiée',
)
```

Computes (`microfinance_loan_extension.py:101-121`) :

```python
@api.depends('loan_amount', 'product_id.guarantee_savings_percent')
def _compute_guarantee_savings_required(self):
    for loan in self:
        loan.guarantee_savings_required = loan.loan_amount * loan.product_id.guarantee_savings_percent / 100.0

def _compute_guarantee_savings_balance(self):
    for loan in self:
        guarantee_product = loan.product_id.guarantee_savings_product_id
        if not guarantee_product or not loan.partner_id:
            loan.guarantee_savings_balance = 0.0
            continue
        accounts = self.env['microfinance.savings.account'].search([
            ('partner_id', '=', loan.partner_id.id),
            ('product_id', '=', guarantee_product.id),
            ('state', '=', 'active'),
        ])
        loan.guarantee_savings_balance = sum(accounts.mapped('balance'))

@api.depends('guarantee_savings_required', 'guarantee_savings_balance')
def _compute_guarantee_savings_verified(self):
    for loan in self:
        loan.guarantee_savings_verified = loan.guarantee_savings_balance >= loan.guarantee_savings_required
```

### 5. Existe-t-il un `account.move` / un enregistrement « compte correspondant » ?

**Non — aucun équivalent de `fee_move_id`.**

- `guarantee_savings_verified` est **une pure comparaison de deux montants**
  (`balance >= required`). Aucun move, aucun enregistrement pivot, aucun lettrage,
  aucun `_move_id`.
- `guarantee_savings_balance` est un **agrégat** :
  `sum(microfinance.savings.account [partner + produit garantie + state='active'].balance)`
  — potentiellement **plusieurs comptes épargne**, pas un.
- Il n'existe pas de champ `guarantee_savings_account_id` (singulier) sur le crédit. Le
  seul Many2one épargne du crédit est `savings_account_id` (« Compte épargne
  (prélèvement) », `microfinance_loan_extension.py:16`) — c'est le compte **source du
  prélèvement automatique / cible de l'épargne progressive**, nullable, et **pas
  nécessairement** le(s) compte(s) qui composent le solde garantie (lequel somme *tous*
  les comptes actifs sur `guarantee_savings_product_id`).
- Les dépôts d'épargne génèrent bien des `account.move` (il y a
  `account.move.microfinance_savings_account_id`, `microfinance_savings_transaction.py:374`),
  mais **aucun n'est "l'écriture de la garantie"** : ce sont N dépôts successifs sur
  N comptes.

Ce qui existe déjà pour "voir le compte" :
- Bouton statistique **« Épargne »** (`action_view_savings_accounts`,
  `microfinance_loan_extension.py`) — ouvre la liste des comptes épargne **du client**
  (domaine `partner_id`, non filtré sur le produit garantie).
- `savings_account_count`.
- Vue héritée `view_microfinance_loan_form_inherit_savings`
  (`microfinance_savings_management/views/microfinance_loan_views_inherit.xml`) qui pose
  déjà `guarantee_savings_required` / `_balance` / `_verified` après `fee_move_id`.

### 6. Constat — absence d'`account.move` dédié à la garantie

**Confirmé : il n'y a pas d'`account.move` (ni d'enregistrement unique) qui matérialise
« le compte correspondant » à `guarantee_savings_required`.** Le badge vert/rouge est
faisable (comparaison de soldes), mais **le "lien cliquable vers l'écriture" n'a pas de
cible évidente** — contrairement au Volet 1 où `fee_move_id` existe.

Cibles concrètes envisageables (à trancher par Micka, cf. question ouverte) :
| Option | Cible du lien | Remarque |
|---|---|---|
| (a) | Liste des **comptes épargne garantie** du client (action fenêtre filtrée `partner_id` + `product_id = guarantee_savings_product_id` + `state='active'`) | Cohérent avec `guarantee_savings_balance` (mêmes critères). Réutilise le pattern `action_view_savings_accounts`. **Plusieurs** comptes possibles → une liste, pas une fiche. |
| (b) | Le `savings_account_id` du crédit (compte de prélèvement) | Un seul enregistrement, déjà Many2one cliquable. Mais **sémantiquement décalé** : ce n'est pas forcément le compte garantie, et il peut être vide. |
| (c) | Le **dernier dépôt** (`microfinance.savings.transaction` type `deposit`) sur le compte garantie, ou son `account.move` | Aucun champ ne le pointe → nouveau compute à créer. « Dernier » est arbitraire (la garantie = un cumul, pas un dépôt). |
| (d) | **Pas de lien** — seulement le badge couleur | `guarantee_savings_required` / `_balance` / `_verified` + le bouton « Épargne » existant racontent déjà l'histoire. Le plus honnête vu qu'il n'y a pas d'écriture. |

### 7. Module cible & contrainte d'architecture — vérifié

- **Aucun import** de `microfinance_savings_management` dans `microfinance_loan_management`
  (`grep` : seulement des mentions en commentaire). `microfinance_loan_management.depends`
  = `['base', 'mail', 'account', 'base_vat', 'contacts', 'hr', 'calendar',
  'base_accounting_kit']` — pas d'épargne. Dépendance **unidirectionnelle**
  (`microfinance_savings_management.depends` inclut `microfinance_loan_management`).
- Tous les champs `guarantee_savings_*`, `savings_account_id`,
  `action_view_savings_accounts`, et la vue héritée du formulaire crédit vivent dans
  **`microfinance_savings_management`**.
- ➡️ **Le badge + (éventuel) lien pour `guarantee_savings_verified` doit être ajouté dans
  `microfinance_savings_management`**, en étendant la vue héritée existante
  `view_microfinance_loan_form_inherit_savings` (et en y ajoutant le champ calculé
  `Selection` d'état s'il en faut un pour le `widget="badge"`, sur
  `microfinance_loan_extension.py`). **Jamais** dans `microfinance_loan_management`.

### Proposition Volet 2 (sous réserve de la réponse Micka)

1. **`microfinance_loan_extension.py`** : champ calculé
   ```python
   guarantee_savings_state = fields.Selection(
       [('na', 'N/A'), ('insufficient', 'Insuffisante'), ('verified', 'Vérifiée')],
       compute='_compute_guarantee_savings_state')
   ```
   `'na'` si `guarantee_savings_required <= 0`, sinon `'verified'` / `'insufficient'`
   selon `guarantee_savings_verified`.
2. **`microfinance_loan_views_inherit.xml`** : remplacer l'affichage de
   `guarantee_savings_verified` par le badge :
   ```xml
   <field name="guarantee_savings_state" widget="badge" readonly="1"
          decoration-success="guarantee_savings_state == 'verified'"
          decoration-danger="guarantee_savings_state == 'insufficient'"
          invisible="guarantee_savings_state == 'na'"/>
   ```
3. **Lien** : selon décision Micka — le plus cohérent est **(a)** une action fenêtre
   `action_view_guarantee_savings_accounts()` (nouvelle méthode dans l'extension) filtrée
   comme `_compute_guarantee_savings_balance`, exposée en bouton à côté du badge ; ou
   **(d)** pas de lien, le bouton « Épargne » existant suffit.

---

## Question ouverte pour Micka (avant Lot 1)

Pour **`guarantee_savings_verified`** : **aucun `account.move` dédié n'existe** (garantie =
comparaison `solde cumulé des comptes épargne actifs sur le produit garantie` ≥ `montant
requis`). Le lien du badge doit pointer vers :

- **(a)** la **liste des comptes épargne garantie** du client (action filtrée `partner` +
  `produit garantie` + `actif`) — *recommandé si un lien est voulu* ;
- **(b)** le `savings_account_id` (compte de prélèvement) du crédit — un seul
  enregistrement mais sémantiquement décalé et souvent vide ;
- **(c)** le dernier mouvement de dépôt / son `account.move` — nécessite un nouveau
  compute, « dernier » arbitraire ;
- **(d)** **pas de lien**, badge couleur seul (le bloc `required` / `balance` / `verified`
  + le bouton « Épargne » existant suffisent) — *recommandé si on veut rester simple*.

Le **Volet 1 (frais)** n'a pas de question ouverte : badge `Selection` calqué sur
`risk_level` + liens `fee_move_id` / `fee_receivable_move_id` déjà cliquables, tout dans
`microfinance_loan_management`.

---

## Annexe — points d'entrée

| Élément | Emplacement |
|---|---|
| Champs frais en vue | `microfinance_loan_management/views/microfinance_loan_views.xml:192-196` |
| Badge de référence `risk_level` | `microfinance_loan_management/views/microfinance_scoring_views.xml:189` (form hérité), `:151` (tree) |
| Vue héritée scoring (pattern d'ajout au form crédit) | `microfinance_scoring_views.xml`, record `view_microfinance_loan_form_scoring_inherit` |
| `fee_paid` / `fee_move_id` / `fee_receivable_move_id` | `microfinance_loan_management/models/microfinance_loan.py:230-236` |
| `guarantee_savings_*` base | `microfinance_loan.py:164-171` |
| `guarantee_savings_*` extension + computes | `microfinance_savings_management/models/microfinance_loan_extension.py:28-38`, `:101-121` |
| `savings_account_id` (prélèvement) | `microfinance_loan_extension.py:16-21` |
| `action_view_savings_accounts` / `savings_account_count` | `microfinance_loan_extension.py` |
| Vue héritée form crédit (côté épargne) | `microfinance_savings_management/views/microfinance_loan_views_inherit.xml`, record `view_microfinance_loan_form_inherit_savings` |
| `account.move.microfinance_savings_account_id` (dépôts épargne) | `microfinance_savings_management/models/microfinance_savings_transaction.py:374` |
| Absence d'import savings dans loan_management | vérifié par `grep` — que des commentaires |
