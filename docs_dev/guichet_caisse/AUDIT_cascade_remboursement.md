# Audit — Cascade de remboursement multi-échéances + wizard

Audit **en lecture seule**. Aucune modification de code, de vue, de données ou de sécurité.
Aucun commit. État des lieux factuel : aucune solution d'implémentation n'est proposée ici.

Fichiers lus :

- `microfinance_loan_management/models/microfinance_loan_payment.py`
- `microfinance_loan_management/models/microfinance_loan_installment.py`
- `microfinance_loan_management/models/microfinance_loan.py` (extraits `_compute_totals`,
  `action_open_payment_wizard`, `_get_scoring_metrics`)
- `microfinance_loan_management/wizard/microfinance_loan_payment_wizard.py`
- `microfinance_loan_management/static/src/js/microfinance_caisse_pos.js`
- `microfinance_loan_management/static/src/js/microfinance_loan_dashboard.js`
- `microfinance_loan_management/models/microfinance_caisse_session.py` (`action_open_close_wizard`)
- `microfinance_savings_management/models/microfinance_caisse_mouvement.py`
- `microfinance_savings_management/models/microfinance_loan_extension.py`
- `microfinance_savings_management/models/microfinance_loan_payment_extension.py`
- `microfinance_savings_management/models/microfinance_savings_account.py` (`_create_transaction`)
- `microfinance_savings_management/models/microfinance_savings_transaction.py` (types)
- `microfinance_loan_management/security/ir.model.access.csv`,
  `microfinance_savings_management/security/savings_security.xml`
- `/opt/odoo17/addons/web/static/src/core/orm_service.js`
- Tests : `test_repayment_allocation.py`, `test_repayment_accounting.py`,
  `test_payment_prefill.py`, `test_payment_cancel.py`, `test_auto_debit.py`,
  `microfinance_savings_management/tests/test_caisse_pos.py`

---

## 1. `_allocate_to_installments` et `action_post` (paiement) — comportement actuel

### 1.1 `_allocate_to_installments()` — corps intégral

`microfinance_loan_payment.py:136-165` :

```python
def _allocate_to_installments(self):
    self.ensure_one()
    if self.loan_id.state not in ('active', 'defaulted'):
        raise UserError(_('Le crédit doit être actif ou en défaut pour enregistrer un remboursement.'))
    if not self.loan_id.disbursement_date:
        raise UserError(_(
            "Ce crédit est activé mais pas encore décaissé : aucun remboursement ne peut "
            "être enregistré avant le décaissement effectif en caisse."))
    if self.amount > self.loan_id.balance_total + 0.01:
        raise UserError(_('Surpaiement interdit. Solde restant : %.2f') % self.loan_id.balance_total)
    installments = self.loan_id.installment_ids.filtered(lambda i: i.residual_amount > 0.01).sorted(lambda i: (i.due_date, i.sequence))
    alloc_interest = alloc_principal = alloc_penalty = 0.0
    touched = self.env['microfinance.loan.installment']
    for inst, interest_pay, principal_pay, penalty_pay in self._allocation_plan(installments, self.amount):
        inst.paid_interest += interest_pay
        inst.paid_principal += principal_pay
        inst.paid_penalty += penalty_pay
        alloc_interest += interest_pay
        alloc_principal += principal_pay
        alloc_penalty += penalty_pay
        touched |= inst
    self.write({
        'allocated_penalty': alloc_penalty,
        'allocated_interest': alloc_interest,
        'allocated_principal': alloc_principal,
        'installment_ids': [(6, 0, touched.ids)],
    })
```

### 1.2 `_allocation_plan()` — le générateur d'allocation (source unique)

`microfinance_loan_payment.py:92-116`, `@api.model` :

```python
def _allocation_plan(self, installments, amount):
    remaining = amount
    for inst in installments:
        if remaining <= 0.01:
            break
        interest_due = max(inst.interest_amount - inst.paid_interest, 0.0)
        interest_pay = min(remaining, interest_due)
        remaining -= interest_pay
        principal_due = max(inst.principal_amount - inst.paid_principal, 0.0)
        principal_pay = min(remaining, principal_due)
        remaining -= principal_pay
        penalty_due = max(inst.penalty_amount - inst.paid_penalty, 0.0)
        penalty_pay = min(remaining, penalty_due)
        remaining -= penalty_pay
        if interest_pay or principal_pay or penalty_pay:
            yield inst, interest_pay, principal_pay, penalty_pay
```

### 1.3 Un paiement s'applique-t-il déjà à plusieurs échéances ?

**Oui, déjà aujourd'hui, automatiquement et sans aucun garde-fou intermédiaire.** Si
`amount` dépasse le montant dû de l'échéance courante, le générateur `_allocation_plan`
**déborde sur l'échéance suivante** dans le même ordre (intérêt → principal → pénalité), puis
la suivante, etc., jusqu'à épuisement de `remaining` (`<= 0.01`).

- **Aucune limitation à une seule échéance.** Pas de rejet, pas de troncature à l'échéance
  courante.
- Seule borne : `if self.amount > self.loan_id.balance_total + 0.01` → `UserError`
  **« Surpaiement interdit »** (`microfinance_loan_payment.py:147-148`). Un montant qui
  dépasse le solde total restant du crédit est **refusé en bloc** (l'écriture n'est pas
  passée).
- Confirmé par le test `test_surplus_payment_overflows_to_next_installment_same_priority`
  (`test_repayment_allocation.py:60-79`) : 150 payés sur deux échéances (P100/I20 puis
  P200/I30) → échéance 1 `paid`, échéance 2 partiellement soldée (`paid_interest=30`,
  `state='partial'`), `allocated_interest=50`.

### 1.4 Ordre de sélection de « l'échéance courante »

`installment_ids.filtered(residual_amount > 0.01).sorted((due_date, sequence))`
(`:149`). Donc :

- **Toutes les échéances non soldées** (résiduel > 0,01) : `overdue`, `partial`, `pending`
  **et les échéances futures non encore dues** — pas seulement les échéances en retard.
- Ordre : **date d'échéance la plus ancienne d'abord, puis `sequence`** en départage. Les
  échéances en retard remontent naturellement en tête (leur `due_date` est passée). Ce n'est
  ni « la plus ancienne en retard » explicitement, ni « la prochaine à échoir » : c'est un
  tri global de toutes les non-soldées.
- `preview_repayment_allocation` (§2) utilise **exactement le même filtre et le même tri**.

### 1.5 Ventilation 3 buckets — par échéance individuelle ?

**Oui.** L'ordre intérêt dû → principal dû → pénalités est appliqué **dans le corps de la
boucle `for inst in installments`** de `_allocation_plan` (`:106-114`), donc **par échéance,
une échéance à la fois**, avant de passer au reliquat sur l'échéance suivante. Réutilisable
tel quel pour chaque échéance d'une cascade : c'est déjà ce que fait le code.

Commentaire du code (`:47`, `:94-95`) : cet ordre est la « ventilation CEFOR (Décision 2) »,
explicitement distincte de LPF (pénalité → intérêt → capital, cité en `:12`).

### 1.6 `action_post()` — corps intégral

`microfinance_loan_payment.py:198-214` :

```python
def action_post(self):
    for payment in self:
        if payment.state != 'draft':
            continue
        payment._allocate_to_installments()
        move = self.env['account.move'].with_context(
            default_loan_id=False,
            default_loan_line_id=False,
        ).create(payment._prepare_payment_move())
        move.action_post()
        payment.write({'move_id': move.id, 'state': 'posted'})
        payment.loan_id.message_post(body=_('Remboursement %s comptabilisé : %s') % (payment.name, move.name))
        if payment.loan_id.balance_total <= 0.01:
            payment.loan_id.action_close()
    return True
```

- Séquence : `_allocate_to_installments()` (écrit `paid_*` sur les échéances + `allocated_*`
  sur le paiement) → création + `action_post()` de l'`account.move` (`_prepare_payment_move`
  ne comptabilise que les buckets réellement alloués : caisse en débit, principal/intérêt/
  pénalité en crédit) → `state = 'posted'` → message sur le crédit → **auto-clôture du crédit
  si `balance_total <= 0.01`** (via `action_close()`, pas un write brut).
- **Ne retourne aucune action** : `return True`.
- **Aucune écriture explicite de `state` sur les échéances** : `microfinance.loan.installment.
  state` est un `compute='_compute_state'` **stocké** (`store=True, readonly=False`,
  `installment.py:21-26`) qui dépend de `residual_amount / total_amount / due_date`. Écrire
  `paid_*` recalcule `residual_amount` (`_compute_amounts`) puis `state` : une échéance
  entièrement couverte devient `paid`, partiellement couverte `partial`, non touchée reste
  `overdue` ou `pending`. La spec (échéance qui passe en `partial` quand le reliquat ne la
  couvre pas — points 1 et 3) est donc **déjà obtenue mécaniquement** par ce recalcul.

### 1.7 Remontée du résultat

`action_post()` renvoie `True`. Les montants alloués sont lus **après coup** sur le
`payment` (`allocated_interest / allocated_principal / allocated_penalty`, champs `readonly`
stockés) par l'appelant — cf. `register_operation` §4.

---

## 2. `preview_repayment_allocation` — réutilisable ou à remplacer ?

### 2.1 Corps intégral

`microfinance_loan_payment.py:118-134`, `@api.model` :

```python
def preview_repayment_allocation(self, loan_id, amount):
    loan = self.env['microfinance.loan'].browse(loan_id)
    installments = loan.installment_ids.filtered(lambda i: i.residual_amount > 0.01).sorted(lambda i: (i.due_date, i.sequence))
    alloc_interest = alloc_principal = alloc_penalty = 0.0
    for _inst, interest_pay, principal_pay, penalty_pay in self._allocation_plan(installments, amount):
        alloc_interest += interest_pay
        alloc_principal += principal_pay
        alloc_penalty += penalty_pay
    return {
        'interest_amount': alloc_interest,
        'principal_amount': alloc_principal,
        'penalty_amount': alloc_penalty,
    }
```

### 2.2 Ce qu'elle retourne aujourd'hui

**Trois scalaires agrégés sur toute la cascade** : `{'interest_amount', 'principal_amount',
'penalty_amount'}`. Elle **ne renvoie pas** :

- le détail par échéance (quelles échéances, combien sur chacune) ;
- la liste des échéances touchées ;
- le reliquat non alloué (surplus au-delà de `balance_total`) ;
- l'état résultant des échéances.

### 2.3 Réutilisable ?

- **Le générateur `_allocation_plan` est déjà « cascade-aware »** : il itère toutes les
  échéances non soldées, dans l'ordre, et **yield par échéance** un tuple
  `(inst, interest_pay, principal_pay, penalty_pay)`. C'est la brique réutilisable pour
  alimenter une liste de wizard.
- `preview_repayment_allocation` ne fait qu'**écraser ce détail** en 3 totaux. Son **shape de
  retour est trop étroit** pour piloter un wizard (pas de lignes par échéance, pas de
  reliquat). Point ouvert §8 : l'étendre (ajout de clés, non destructif pour le JS, cf. §6.4)
  ou créer une méthode sœur.
- Elle **n'a aucun garde-fou** : pas de contrôle `balance_total`, pas de contrôle d'état
  crédit. Un `amount` supérieur au solde y « fonctionne » (la boucle s'arrête faute
  d'échéances) alors que `_allocate_to_installments` lèverait `UserError`. Divergence à
  connaître.
- **Aucun appelant Python** (`grep` : uniquement le JS ci-dessous et le générateur partagé).

### 2.4 Utilisation par `microfinance_caisse_pos.js`

`updateVentilationPreview()` (`microfinance_caisse_pos.js:447-456`) :

```js
async updateVentilationPreview() {
    if (this.state.activeTab !== "remboursement_credit" || !this.state.selectedAccountId || this.amount <= 0) {
        this.state.ventilation = null;
        return;
    }
    this.state.ventilation = await this.orm.call(
        "microfinance.loan.payment", "preview_repayment_allocation",
        [this.state.selectedAccountId, this.amount]
    );
}
```

- **Quand** : appelée à chaque frappe du pavé numérique — `pressDigit()` (`:404`),
  `pressDecimal()` (`:412`), `pressBackspace()` (`:417`) — et à la sélection du crédit
  `selectAccount()` (`:357`, uniquement onglet `remboursement_credit`). `pressClear()`
  (`:419-422`) met `state.ventilation = null` sans rappeler la méthode.
- **Garde** : ne s'exécute que si onglet `remboursement_credit` ET crédit sélectionné ET
  `amount > 0` ; sinon `state.ventilation = null`.
- **Données affichées au caissier** : `microfinance_caisse_pos.xml` (bloc `t-if=
  "state.ventilation"`, colonne pavé numérique) — 3 lignes **Intérêt / Principal / Pénalité**
  formatées `formatMoney`, au-dessus de l'affichage du montant. Rien d'autre (pas de liste
  d'échéances, pas de reliquat, pas d'anticipation).
- Le retour de `preview_repayment_allocation` est stocké tel quel dans `state.ventilation` ;
  le JS lit `state.ventilation.interest_amount / .principal_amount / .penalty_amount`.

---

## 3. Critère « en retard » déjà en usage

### 3.1 États d'une échéance

`microfinance.loan.installment.state` (`microfinance_loan_installment.py:21-26`) :
`pending` (À payer) / `partial` (Partiel) / `paid` (Payé) / `overdue` (En retard).

`_compute_state` (`:54-65`), `@api.depends('residual_amount', 'total_amount', 'due_date')` :

```python
today = fields.Date.context_today(self)
for line in self:
    if line.total_amount and line.residual_amount <= 0.01:
        line.state = 'paid'
    elif line.residual_amount < line.total_amount:
        line.state = 'partial'
    elif line.due_date and line.due_date < today:
        line.state = 'overdue'
    else:
        line.state = 'pending'
```

**Conséquence importante** : une échéance **partiellement payée ET échue** est calculée en
`partial`, **pas** `overdue` (la branche `partial` est testée avant `overdue`). Le critère
strict `state == 'overdue'` **exclut donc les échéances partiellement soldées en retard**.

### 3.2 `state == 'overdue'` strict — sites qui l'emploient

- `default_payment_amount_and_journal` (`microfinance_loan_payment.py:15`) :
  `overdue = loan.installment_ids.filtered(lambda i: i.state == 'overdue')` → préremplissage
  du montant = `sum(overdue.mapped('residual_amount'))` s'il y en a, sinon résiduel de la
  prochaine échéance non soldée (`residual_amount > 0.01`, triée `(due_date, sequence)`).
  **Pas de tri appliqué à la liste `overdue` elle-même.**
- `_compute_totals` → `overdue_amount` (`microfinance_loan.py:585-586`) :
  `filtered(lambda l: l.state == 'overdue')`, somme des résiduels + `overdue_installment_count`.
- `_get_scoring_metrics` (`microfinance_loan.py:1156`) :
  `installments.filtered(lambda line: line.state == 'overdue')`.
- `_get_max_overdue_days()` (`microfinance_loan.py`, cf. `docs_dev/dashboard_portefeuille_
  agent/AUDIT.md §B1.1`) : `filtered(lambda l: l.state == 'overdue')`.
- `cron_process_savings_auto_debit` (`microfinance_loan_extension.py:234`) :
  `search([('state', '=', 'overdue'), ...])`.
- `_process_savings_auto_debit` : `amount = min(self.overdue_amount, withdrawable)`
  (`:205`) — s'appuie donc sur `overdue_amount` (état strict).

### 3.3 Critère élargi `due_date <= today AND state != 'paid'`

`get_pending_or_late(company_id)` (`microfinance_loan_installment.py:97-134`) — utilisé par
l'onglet « Échéances du jour » du guichet :

```python
installments = self.search([
    ('company_id', '=', company_id),
    ('due_date', '<=', today),
    ('state', '!=', 'paid'),
    ('loan_id.state', 'in', ('active', 'defaulted')),
    ('loan_id.disbursement_date', '!=', False),
], order='due_date asc, loan_id asc')
```

Docstring (`:99-115`) : `state != 'paid'` **inclut volontairement les `partial` échues**.
Filtres `loan_id.state in ('active','defaulted')` **et** `disbursement_date != False`
**obligatoires** (exclusion des échéanciers d'aperçu d'un crédit non décaissé — anomalie A1
de `docs_dev/guichet_caisse/AUDIT.md §3.3` et `docs_dev/dashboard_portefeuille_agent/
AUDIT.md`). Référence croisée : `docs_dev/guichet_caisse/AUDIT_decaissement.md §2.1`.

`get_due_today(company_id)` (`:84-95`) : `due_date == today AND state != 'paid'`, **sans**
filtre `loan_id.state` ni `disbursement_date` (plus laxiste, consommé par le dashboard).

### 3.4 Bilan

**Il n'existe aucun helper partagé** renvoyant « la liste ordonnée des échéances en retard
d'un crédit donné ». Chaque site refiltre. Deux définitions coexistent :

| Définition | Inclut `partial` échu ? | Sites |
|---|---|---|
| `state == 'overdue'` strict | **non** | préremplissage montant, `overdue_amount`, scoring, PAR, auto-débit |
| `due_date <= today AND state != 'paid'` | **oui** | `get_pending_or_late` (guichet), `get_due_today` (dashboard) |

L'ordre canonique partout où un tri est fait : `(due_date, sequence)`.

---

## 4. `register_operation` — `remboursement_credit` et autres points de création de paiement

### 4.1 `register_operation`, branche `remboursement_credit` — corps exact

`microfinance_savings_management/models/microfinance_caisse_mouvement.py:84-128` (`@api.model`) :

```python
@api.model
def register_operation(self, session_id, type, partner_id, amount, savings_account_id=False, loan_id=False):
    session = self.env['microfinance.caisse.session'].browse(session_id)
    if not session.exists() or session.state != 'open':
        raise UserError(_("Aucune session de caisse ouverte : impossible d'enregistrer une opération."))
    partner = self.env['res.partner'].browse(partner_id)
    vals = {'session_id': session.id, 'type': type, 'partner_id': partner.id, 'amount': amount}
    ...
    elif type == 'remboursement_credit':
        loan = self.env['microfinance.loan'].browse(loan_id)
        if loan.company_id != session.company_id:
            raise UserError(_("Ce crédit n'appartient pas à l'agence de la session en cours."))
        payment = self.env['microfinance.loan.payment'].create({
            'loan_id': loan.id,
            'amount': amount,
            'journal_id': session.journal_id.id,
        })
        self._run_posting_sudo(payment, session, 'action_post')
        vals.update({
            'loan_id': loan.id,
            'payment_id': payment.id,
            'interest_amount': payment.allocated_interest,
            'principal_amount': payment.allocated_principal,
            'penalty_amount': payment.allocated_penalty,
        })
    ...
    return self.create(vals)
```

- Garde session ouverte ; garde agence (`loan.company_id == session.company_id`).
- `create` du `microfinance.loan.payment` **en identité réelle** (le caissier a `create` sur
  ce modèle : `ir.model.access.csv:99` `access_microfinance_payment_cashier … 1,1,1,0`).
- `_run_posting_sudo(payment, session, 'action_post')` (`:57-82`) : `payment.ensure_one()` ;
  re-vérifie `payment.company_id == session.company_id` (défense en profondeur, `payment.
  company_id` est un `related` stocké de `loan_id.company_id`) ; puis
  `payment.sudo().action_post()`. **Le retour de `action_post` est ignoré.**
- Ventilation recopiée dans le `caisse.mouvement` **après** `action_post`, par lecture de
  `payment.allocated_*` — simple reflet, pas un second calcul (commentaire `:42-44`).
- `register_operation` **retourne un `microfinance.caisse.mouvement`** (recordset), jamais une
  action.

### 4.2 Remontée au guichet OWL

`microfinance_caisse_pos.js:478-513`, `submitOperation()` :

```js
await this.orm.call("microfinance.caisse.mouvement", "register_operation", [
    this.state.session.id, tab, this.state.client.id, this.effectiveAmount,
    isLoanOp ? false : this.state.selectedAccountId,
    isLoanOp ? this.state.selectedAccountId : false,
]);
this.notification.add("Opération enregistrée.", { type: "success" });
...
```

- **Un seul appel RPC** = création + comptabilisation (`action_post` en sudo) en une passe.
- **La valeur de retour est ignorée** (aucune affectation). Succès → notification, reset du
  montant/ventilation, rechargement session + reselection client. Exception →
  `error.data?.message`.
- Aucun signal, aucun `doAction` déclenché depuis cette méthode aujourd'hui.

### 4.3 Tous les points de création de `microfinance.loan.payment` (`grep`)

| # | Point d'entrée | Fichier | Création + post |
|---|---|---|---|
| 1 | **Guichet caisse** — `register_operation` (`remboursement_credit`) | `microfinance_savings_management/models/microfinance_caisse_mouvement.py:113-121` | `create` (identité réelle) + `action_post` **en sudo** via `_run_posting_sudo` |
| 2 | **Assistant** `microfinance.loan.payment.wizard.action_create_payment` | `microfinance_loan_management/wizard/microfinance_loan_payment_wizard.py:40-53` | `create` + `action_post()` si `post_now` (défaut `True`). Ouvert par `microfinance.loan.action_open_payment_wizard` (bouton form crédit, `microfinance_loan_views.xml:78`) **et** réutilisé par le dashboard OWL (`microfinance_loan_dashboard.js:416-419`, cf. §6.2) |
| 3 | **Formulaire direct** `microfinance.loan.payment` | `microfinance_loan_payment_views.xml:17` (bouton header `action_post` `type="object"`) ; menu « Remboursements » `action_microfinance_payment` (`:27`) | `create` manuel + clic `action_post`. Onchange `_onchange_loan_id` préremplit montant/journal |
| 4 | **Cron auto-débit épargne** `_process_savings_auto_debit` | `microfinance_savings_management/models/microfinance_loan_extension.py:212-219` | `create` (`payment_origin='savings_auto_debit'`) + `action_post()`. Déclenché par `cron_process_savings_auto_debit` (`:230`) |
| 5 | Tests | `test_repayment_allocation.py`, `test_repayment_accounting.py`, `test_caisse_pos.py`, `test_auto_debit.py`, `test_payment_cancel.py` | `create` + `action_post()` directs (pas un chemin runtime) |

➡️ `register_operation` **n'est pas la seule voie**. Trois autres chemins runtime
(assistant, formulaire direct, cron auto-débit) créent et comptabilisent des
`microfinance.loan.payment` via le même `action_post` → `_allocate_to_installments` →
`_allocation_plan`. La portée « partout » du prompt (point 6) implique donc au minimum les
points 1 à 4 ; les points 3 et 4 n'ont **aucune UI** susceptible d'afficher un wizard
(point ouvert §8).

---

## 5. Compte épargne lié — dépôt du surplus

### 5.1 Le champ `savings_account_id`

`microfinance_savings_management/models/microfinance_loan_extension.py:16-21` :

```python
savings_account_id = fields.Many2one(
    'microfinance.savings.account', string="Compte épargne (prélèvement)",
    domain="[('partner_id', '=', partner_id)]", tracking=True,
    help='Compte source du prélèvement automatique et/ou compte dans lequel est vérifiée la '
         "cible d'épargne progressive.",
)
```

- **`required=False`** (aucun `required=True` au niveau champ). **Aucune contrainte serveur
  ne force son renseignement** (ni par produit, ni à l'activation, ni au décaissement —
  `grep savings_account_id` sur `microfinance_savings_management` : la seule `@api.constrains`
  est `_check_savings_account_company`, `:124-131`, qui vérifie **seulement** la cohérence
  d'agence *si le champ est renseigné*).
- Le code existant **tolère le champ vide** :
  `_compute_savings_target_reached` (`:93-99`) garde avec `bool(loan.savings_account_id)` ;
  `cron_process_savings_auto_debit` (`:236`) filtre `('loan_id.savings_account_id', '!=',
  False)` dans son domaine ; `_process_savings_auto_debit` n'est jamais atteint sans compte.
- ➡️ **L'hypothèse du prompt (« compte obligatoire déjà existant ») n'est pas vérifiée par le
  code.** Un crédit avec un surplus à placer **peut** n'avoir aucun `savings_account_id`.

### 5.2 Comment déposer un montant sur ce compte

`microfinance_savings_management/models/microfinance_savings_account.py:179-200` :

```python
def _create_transaction(self, transaction_type, amount, note=None, bypass_min_balance=False,
                         bypass_withdrawal_limit=False, bypass_cash_balance=False,
                         related_loan_payment_id=False, date=None, payment_method='cash'):
    self.ensure_one()
    if self.is_container:
        raise UserError(_("Un conteneur épargne (%s) ne peut recevoir aucune transaction.") % self.name)
    transaction = self.env['microfinance.savings.transaction'].create({
        'account_id': self.id, 'transaction_type': transaction_type, 'amount': amount,
        'date': date or fields.Date.context_today(self), 'note': note,
        'bypass_min_balance': bypass_min_balance, 'bypass_withdrawal_limit': bypass_withdrawal_limit,
        'bypass_cash_balance': bypass_cash_balance,
        'related_loan_payment_id': related_loan_payment_id, 'payment_method': payment_method,
    })
    transaction.action_post()
    return transaction
```

- **Réutilisable tel quel** pour un dépôt : `transaction_type='deposit'`
  (`microfinance_savings_transaction.py:19`, type crédit — `CREDIT_TYPES = ('deposit',
  'interest_credit')`). Retourne la transaction, déjà `action_post()`-ée.
- Lève si `account.is_container`.
- **Précédent guichet** : la branche `depot_epargne` de `register_operation`
  (`microfinance_caisse_mouvement.py:106-108`) appelle déjà
  `self._run_posting_sudo(account, session, '_create_transaction', 'deposit', amount,
  payment_method='cash')`.
- Champ `related_loan_payment_id` sur `microfinance.savings.transaction` (`:65-66`) — lien
  transaction épargne → paiement crédit, déjà utilisé par l'auto-débit
  (`microfinance_loan_extension.py:220`).

### 5.3 Comportement si `savings_account_id` vide + surplus

**Le code ne tranche pas.** Aucune logique n'existe aujourd'hui pour router un surplus vers
l'épargne depuis un remboursement (le seul flux crédit↔épargne existant est l'inverse :
auto-débit épargne → remboursement). → **Question bloquante §8.**

---

## 6. Wizard depuis composant OWL — contrainte technique et précédent éventuel

### 6.1 `orm.call` ne traite pas les actions

`/opt/odoo17/addons/web/static/src/core/orm_service.js:118-129` :

```js
call(model, method, args = [], kwargs = {}) {
    ...
    return this.rpc(url, params, { silent: this._silent });
}
```

`orm.call` fait un `rpc()` nu et **retourne le résultat brut**. Il n'effectue **aucun
traitement d'action** (contrairement au clic sur un bouton `type="object"` d'une form view,
géré par le webclient). Une méthode Python qui `return {'type': 'ir.actions.act_window',
...}` appelée via `orm.call` rend au JS **un simple objet** ; c'est au composant OWL de le
détecter et d'appeler lui-même `this.env.services.action.doAction(objet)`.

### 6.2 Précédent CLAIR et réutilisable dans le dépôt

**`microfinance_loan_dashboard.js:410-419`** (composant client action OWL
`microfinance_loan_dashboard`, tag `microfinance_loan_dashboard`) :

```js
async openPaymentWizard(loanId) {
    const action = await this.orm.call("microfinance.loan", "action_open_payment_wizard", [[loanId]]);
    this.actionService.doAction(action);
}
```

où `microfinance.loan.action_open_payment_wizard` (`microfinance_loan.py:2628-2633`) :

```python
def action_open_payment_wizard(self):
    self.ensure_one()
    return {
        'type': 'ir.actions.act_window', 'name': _('Enregistrer remboursement'),
        'res_model': 'microfinance.loan.payment.wizard',
        'view_mode': 'form', 'target': 'new',
        'context': {'default_loan_id': self.id, 'default_journal_id': self.product_id.payment_journal_id.id}
    }
```

➡️ **Ce projet contient déjà exactement le motif recherché** : un composant OWL custom
appelle par `orm.call` une méthode Python qui **retourne un dict `ir.actions.act_window`**
(ouverture d'un `TransientModel` en `target: 'new'`, c.-à-d. en dialog), puis passe ce dict
à `this.actionService.doAction(action)`. **Cela fonctionne.** Le wizard ouvert est
`microfinance.loan.payment.wizard`, celui de la saisie d'un remboursement.

### 6.3 Précédents secondaires

- **`microfinance_caisse_pos.js:91-105`** (`openSessionForm`) : le guichet lui-même ouvre
  déjà un dialog via `this.env.services.action.doAction({... target: "new" ...}, { onClose:
  () => this.loadSession() })`. Établit le motif « ouvrir un dialog depuis le guichet +
  rafraîchir sur `onClose` ». Ici le dict est **construit côté JS**, pas retourné par le
  serveur.
- **`microfinance_caisse_session.py:73-88`** (`action_open_close_wizard`) : même shape de
  retour (`ir.actions.act_window`, `microfinance.caisse.close.session.wizard`, `target:
  'new'`), mais câblé sur un **bouton de formulaire standard** (`microfinance_caisse_
  session_views.xml:26`, `type="object"`), pas sur le guichet OWL. Montre le modèle wizard,
  pas le chemin RPC.

### 6.4 Contraintes factuelles à connaître (pas des solutions)

1. **Un seul RPC = create + post en sudo.** Le remboursement guichet est aujourd'hui
   atomique côté UI : `register_operation` crée le `microfinance.loan.payment` **et** le
   comptabilise (`action_post` sous `_run_posting_sudo`) dans le même appel. Un flux avec
   confirmation intermédiaire (wizard) impose soit un premier appel « aperçu / dry-run »
   puis un second appel « confirmer », soit que le wizard lui-même porte la
   comptabilisation.
2. **Le sudo est volontairement circonscrit à `register_operation`.** `_run_posting_sudo`
   (`microfinance_caisse_mouvement.py:57-82`, docstring `:63-69`) : « Le sudo est strictement
   circonscrit à ce point d'entrée ». Le caissier n'a **pas** `create` sur `account.move`.
   Une méthode « confirmer » portée par le wizard et exécutée en identité caissier ne
   pourrait pas poster l'écriture sans un sudo ciblé équivalent.
3. **`preview_repayment_allocation` renvoie 3 scalaires** (§2.2) — insuffisant pour peupler
   la liste d'un wizard (pas de lignes par échéance, pas de reliquat). Le générateur
   `_allocation_plan` yield le détail par échéance et reste réutilisable.
4. **Extension du retour de `preview_repayment_allocation`** : additive (nouvelles clés) =
   sans risque pour le JS existant (`updateVentilationPreview` ne lit que `interest_amount /
   principal_amount / penalty_amount`) ; modifier/supprimer ces trois clés = régression du
   pavé.
5. **`_allocate_to_installments` interdit `amount > balance_total`** (`:147-148`). Les
   points 4-5 (surplus au-delà de **toutes** les échéances → épargne ou anticipation)
   **ne peuvent pas** être comptabilisés en un seul `microfinance.loan.payment` sous ce
   garde-fou. `_prepare_payment_move` ne connaît que 4 types de lignes (caisse, principal,
   intérêt, pénalité) — un montant routé vers l'épargne n'est pas une ligne de paiement
   crédit.
6. **Un `microfinance.caisse.mouvement` = un `type` + un enregistrement lié.**
   `register_operation` (`remboursement_credit`) ne renseigne que `payment_id`. Un
   « remboursement + dépôt du surplus » produit **deux** enregistrements métier (un
   `microfinance.loan.payment` + une `microfinance.savings.transaction`). Le modèle
   `microfinance.caisse.mouvement` **possède** les deux champs (`payment_id` **et**
   `savings_transaction_id`, `microfinance_caisse_mouvement.py:51-52`) mais le code n'en
   remplit qu'un par `type`.
7. **Droits wizard pour un caissier.** Précédents CSV :
   `access_caisse_close_wizard_cashier` / `_line_cashier` donnent CRUD complet à
   `group_microfinance_cashier` sur `microfinance.caisse.close.session.wizard(.line)`
   (`ir.model.access.csv:154-157`). En revanche `access_microfinance_payment_wizard`
   (`:52`) donne CRUD sur `microfinance.loan.payment.wizard` à `group_microfinance_user`
   **seulement** — un caissier pur (`group_microfinance_cashier` + `group_savings_agent`,
   cf. `test_caisse_pos.py`) n'est pas forcément `group_microfinance_user`. Un nouveau
   wizard nécessiterait sa propre ligne d'accès caissier.
8. **Aucun test JS / tour** n'existe pour `microfinance_caisse_pos` (§7) : la chaîne UI du
   remboursement guichet n'est couverte qu'au niveau Python (`register_operation`).

### 6.5 Verdict §6

Le point technique « ouvrir un wizard depuis le composant OWL du guichet » est **résolu par
un précédent existant dans ce même dépôt** (`microfinance_loan_dashboard.js:openPaymentWizard`
→ `action_open_payment_wizard`) : méthode Python appelée en `orm.call` qui **retourne** un
dict `ir.actions.act_window`, passé à `doAction`. Le motif « dialog + `onClose` refresh » est
lui aussi déjà en place dans le guichet (`openSessionForm`). Les incertitudes résiduelles ne
portent **pas** sur la faisabilité de l'ouverture du wizard mais sur l'**architecture du
flux** (un ou deux appels, où se place le sudo de comptabilisation, comment tracer deux
enregistrements métier, relâchement du garde `balance_total`) — cf. §8.

---

## 7. Tests existants (base de non-régression)

### 7.1 `_allocate_to_installments` / `_allocation_plan`

`microfinance_loan_management/tests/test_repayment_allocation.py` — `TestRepaymentAllocation`
(helper `_make_payment` = `create` + `action_post()`) :

| Test | Vérifie |
|---|---|
| `test_exact_payment_clears_installment` | Montant exact d'une échéance → `paid`, `allocated_*` posés |
| `test_partial_payment_covers_interest_then_principal_before_penalty` | 40 sur (P100/I30/Pen20) → I30 + P10, `state='partial'`, rien sur pénalité |
| `test_insufficient_payment_covers_interest_only` | 25 < I30 → `paid_interest=25`, rien sur principal/pénalité |
| `test_surplus_payment_overflows_to_next_installment_same_priority` | **150 sur 2 échéances → cascade : échéance 1 `paid`, échéance 2 `partial` (`paid_interest=30`), `allocated_interest=50`** |

### 7.2 Comptabilisation

`microfinance_loan_management/tests/test_repayment_accounting.py` — `TestRepaymentAccounting`
(+ `MicrofinanceNoFundMixin`, helper `_pay`) :

| Test | Vérifie |
|---|---|
| `test_move_uses_configured_pcec_accounts_with_real_allocation` | Lignes de l'`account.move` sur les comptes PCEC du produit, équilibre débit/crédit |
| `test_move_amounts_follow_real_allocation_not_theoretical_installment` | Paiement 25 ne touchant que l'intérêt → move à 2 lignes (caisse + intérêt), aucune ligne principal/pénalité |
| `test_move_generated_only_at_payment_not_at_schedule_generation` | Aucune écriture d'intérêt/pénalité avant encaissement (cash-basis) |
| `test_repayment_move_isolated_to_loan_company` | Journal + comptes = agence du crédit (multi-société), création complète d'une agence B |

### 7.3 Préremplissage du montant

`microfinance_loan_management/tests/test_payment_prefill.py` — `TestPaymentPrefill` :

| Test | Vérifie |
|---|---|
| `test_wizard_prefills_amount_and_journal_from_loan` | Wizard : montant = `first.total_amount`, journal = `product.payment_journal_id` |
| `test_wizard_amount_still_manually_editable` | Montant du wizard librement modifiable |
| `test_payment_form_prefills_from_loan_id_onchange` | Même préremplissage sur le **formulaire direct** `microfinance.loan.payment` (onchange `loan_id`) |
| `test_prefill_sums_overdue_installments_rather_than_next_due` | 2 échéances `overdue` → préremplissage = somme de leurs résiduels |

### 7.4 Annulation / contre-passation

`microfinance_loan_management/tests/test_payment_cancel.py` — `TestPaymentCancel` :
`test_cancel_partial_payment_restores_installment_amounts` (restaure `paid_*`, y compris sur
un paiement partiel), `test_cancel_payment_that_closed_loan_reopens_it`,
`test_cancel_blocked_by_locked_period`, `test_cancel_wizard_requires_reason`. Exerce
`_reverse_posted_payment` (reprise par échéance en ordre `(due_date, sequence)` inverse).

### 7.5 Guichet — `register_operation`

`microfinance_savings_management/tests/test_caisse_pos.py` :

| Test | Vérifie |
|---|---|
| `test_register_remboursement_matches_backend_allocation` | `register_operation('remboursement_credit')` → `mouvement.payment_id` posté, `mouvement.interest/principal/penalty_amount` == `payment.allocated_*`, somme == montant |
| `test_pure_cashier_remboursement_credit` | Idem via un utilisateur **caissier pur** (chemin `_run_posting_sudo`) |
| `test_register_blocked_without_open_session` | Refus hors session ouverte |
| `test_direct_savings_transaction_unaffected` | `_create_transaction` direct non impacté par le guichet |
| (frais, décaissement, isolation d'agence, non-fuite du sudo) | hors périmètre cascade |

### 7.6 Auto-débit épargne (réutilise `action_post` → `_allocate_to_installments`)

`microfinance_savings_management/tests/test_auto_debit.py` — `TestAutoDebit` :
`test_auto_debit_nominal_full_amount`, `test_auto_debit_partial_when_balance_insufficient`,
`test_auto_debit_zero_balance_logs_and_does_not_raise`,
`test_auto_debit_bypass_minimum_balance`, `test_cron_isolates_failures_across_loans`,
`test_multi_company_savings_account_isolation`.

### 7.7 Lacunes de couverture

- **`preview_repayment_allocation` : aucun test Python dédié** (`grep` sur les deux dossiers
  `tests/` : aucune référence). Exercée seulement, indirectement, par le JS.
- **Aucun test JS / tour** pour `microfinance_caisse_pos` : `microfinance_savings_management/
  tests/__init__.py:16` n'importe que `test_caisse_pos` (Python, `register_operation`).
- Aucun test ne couvre un montant **supérieur à `balance_total`** (le garde « Surpaiement
  interdit » n'a pas de test de non-régression explicite).
- Aucun test ne couvre une échéance `partial` **échue** (calculée `partial`, pas `overdue`)
  vis-à-vis de l'allocation.

---

## 8. Questions bloquantes pour l'implémentation

1. **Articulation avec le comportement actuel (point 1).** `_allocation_plan` **cascade
   déjà** automatiquement un surplus sur les échéances suivantes (en retard **et** futures),
   sans wizard ni palier, et le cas « première échéance en retard → `partial` si montant
   insuffisant » fonctionne déjà. La nouvelle règle doit-elle (a) **conserver** la cascade
   automatique mais **intercaler une confirmation par wizard** avant de toucher toute
   échéance au-delà de la première échéance en retard, ou (b) **modifier l'algorithme
   d'allocation** lui-même ? Si wizard : refuser le wizard signifie-t-il « n'allouer qu'à la
   première échéance en retard et s'arrêter » (que devient alors `remaining` ?) ou « ne rien
   comptabiliser » ?

2. **Définition de « en retard » pour la cascade.** `state == 'overdue'` strict (exclut les
   échéances partiellement payées et échues, calculées `partial`) ou
   `due_date < today AND state != 'paid'` (les inclut) ? Les deux critères sont en usage
   ailleurs (§3.4). Ordre confirmé `(due_date, sequence)` ?

3. **Surplus au-delà de TOUTES les échéances (point 4).** `_allocate_to_installments` lève
   « Surpaiement interdit » dès `amount > balance_total`. Le point 4 exige d'accepter un tel
   montant. Le garde est-il relâché **uniquement** sur le chemin confirmé par wizard ?
   Comment le surplus est-il traité comptablement — l'`account.move` du
   `microfinance.loan.payment` ne connaît que caisse / principal / intérêt / pénalité ; un
   surplus viré à l'épargne n'est pas une ligne de paiement crédit (écriture séparée ?
   quel journal ? quel compte de liaison ?).

4. **`savings_account_id` vide (point 4).** Le champ est **optionnel et non contraint**
   (§5.1) : un crédit avec surplus peut n'avoir aucun compte lié. Comportement attendu quand
   il est vide : masquer l'option « envoyer sur l'épargne » et ne proposer que
   « anticiper » ? Laisser le caissier choisir un autre compte du client ? Bloquer ? Le code
   ne décide pas.

5. **« Anticiper les échéances futures » vs cascade actuelle (point 5).** La cascade
   existante dépense déjà le surplus sur les échéances futures automatiquement (même boucle
   `_allocation_plan`, pas d'arrêt à la date d'échéance). Le point 5 est-il « la cascade
   existante, mais conditionnée au oui/non du wizard », ou une **règle différente** (p. ex.
   uniquement des échéances entières, pas de `partial` sur la dernière future — ce qui
   contredirait le point 3 qui autorise explicitement `partial`) ?

6. **Deux enregistrements métier en une action de guichet.** Un remboursement qui dépose
   aussi le surplus à l'épargne crée un `microfinance.loan.payment` **et** une
   `microfinance.savings.transaction`. `microfinance.caisse.mouvement` enregistre un seul
   `type` et lie un seul enregistrement (le code remplit `payment_id` seul pour
   `remboursement_credit`). Un `mouvement` de type `remboursement_credit` portant les deux
   liens, deux `mouvement` distincts, ou un `mouvement` parent + enfant ? (Le modèle a les
   champs `payment_id` **et** `savings_transaction_id` ; le chemin de code ne les remplit pas
   ensemble.)

7. **Étape « confirmer » du wizard et droits caissier.** La confirmation doit poster un
   `account.move` (et éventuellement une transaction épargne) ; le caissier n'a ni l'un ni
   l'autre hors `_run_posting_sudo`, **délibérément circonscrit à `register_operation`**
   (§6.4.2). La méthode de confirmation du wizard peut-elle être enveloppée dans le même
   sudo ciblé, ou `register_operation` reste-t-il le point d'entrée unique (le wizard ne
   collectant que les choix, renvoyés à un second appel de type `register_operation`) ?
   Faut-il une ligne `ir.model.access` caissier dédiée pour le nouveau wizard (le wizard
   remboursement existant n'est ouvert qu'à `group_microfinance_user`, §6.4.7) ?

8. **Chemins hors guichet (point 6 : « partout »).** Le wizard est un artefact d'UI.
   `_process_savings_auto_debit` (cron) et le formulaire direct / `action_post` n'ont aucune
   UI pour afficher un wizard. Pour ces chemins, quel repli non interactif : conserver la
   cascade silencieuse actuelle, ou appliquer une règle fixe (jamais d'anticipation, jamais
   de virement épargne) ?

9. **`preview_repayment_allocation` — étendre ou dupliquer.** `@api.model`, retourne 3
   scalaires, **sans test**, **sans appelant Python**. Étendre son retour (clés
   supplémentaires : lignes par échéance, reliquat) est non destructif pour le JS
   (`updateVentilationPreview` ne lit que 3 clés) ; changer les 3 clés existantes est une
   régression. L'aperçu de cascade doit-il étendre cette méthode ou être une méthode sœur ?

10. **Fraîcheur de `installment.state`.** Le passage à `overdue` n'est fiable qu'après le
    cron quotidien `cron_update_overdue_and_penalties` (`_sync_arrears_state` →
    `_compute_state`) : aucun `@api.depends` ne référence « aujourd'hui »
    (`microfinance_loan_installment.py:67-72`). Un remboursement pris au guichet en cours de
    journée voit l'état laissé par le dernier passage du cron. Est-ce acceptable pour
    déterminer « la première échéance en retard », ou la cascade doit-elle recalculer l'état
    à la volée avant d'allouer ?

---

*Audit réalisé le 2026-09-08. Lecture seule — aucune modification de code, de vue, de
données ou de sécurité, aucun commit.*
