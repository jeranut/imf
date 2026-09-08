# Audit — Réorganisation Guichet Caisse

Audit **en lecture seule**. Aucun fichier de code, de vue, de données ou de sécurité modifié.
Aucun commit. Périmètre : état réel du code pour préparer le Lot 1 (numpad à gauche, recherche
au centre, liste view à 3 onglets au centre avec colonne « Agence »).

Base de vérification : lecture du code des modules `microfinance_loan_management` et
`microfinance_savings_management`. Les valeurs de `state` et les chemins ci-dessous sont
recopiés du code, pas reformulés.

---

## 1. Architecture actuelle

### 1.1 Nature : composant OWL 100 % custom (pas de vue XML native)

Le guichet est une **`ir.actions.client`** (tag `microfinance_caisse_pos`), rendue par un
composant Owl.js. Aucune vue `form`/`tree`/widget Odoo natif n'intervient dans l'écran
lui-même (seul l'écran « ouvrir une session » est un `ir.actions.act_window` form standard
ouvert en dialogue, cf. `openSessionForm`, `microfinance_caisse_pos.js:70-82`).

| Fichier | Rôle |
|---|---|
| `microfinance_loan_management/static/src/js/microfinance_caisse_pos.js` (299 l.) | Composant `MicrofinanceCaissePos`, toute la logique écran (état, RPC, numpad, validation). |
| `microfinance_loan_management/static/src/xml/microfinance_caisse_pos.xml` (153 l.) | Template Owl `microfinance_loan_management.MicrofinanceCaissePos`. Grille 3 colonnes : `--client` / `--operation` (onglets + numpad) / `--ticket`. |
| `microfinance_loan_management/static/src/scss/microfinance_caisse_pos.scss` (338 l.) | `.o_microfinance_pos__body { display:grid; grid-template-columns:280px 1fr 320px; grid-template-areas:"client operation ticket"; }` (`:59-67`). Media queries `:293` (≤1024) et `:319` (≤768). |
| `microfinance_loan_management/views/microfinance_caisse_pos_views.xml` | `record id="action_microfinance_caisse_pos"` (`ir.actions.client`, `target=current`). |
| `microfinance_loan_management/views/microfinance_menus.xml:21-22` | `menuitem menu_microfinance_caisse_pos` sous `menu_caisse_root`. |
| `microfinance_loan_management/__manifest__.py:70-85` | Enregistrement des assets (`web.assets_backend`). |

Backend Python appelé par le composant :

| Fichier | Éléments |
|---|---|
| `microfinance_savings_management/models/microfinance_caisse_mouvement.py` | Modèle `microfinance.caisse.mouvement` (ligne de ticket) + `_inherit` sur `microfinance.caisse.session` ajoutant `mouvement_ids` (`:109-112`). Méthode `register_operation()` (`:53-106`) = **point d'entrée unique** de validation. Placé dans le module épargne car il référence à la fois crédit et épargne (`microfinance_loan_management` ne dépend pas de `microfinance_savings_management`), cf. commentaire `:11-16`. |
| `microfinance_savings_management/models/res_partner.py:126-140` | `search_caisse_clients(query, company_id)` (`@api.model`). |
| `microfinance_savings_management/models/res_partner.py:142-175` | `get_client_accounts_summary(partner_id, company_id)` (`@api.model`). |
| `microfinance_loan_management/models/microfinance_caisse_session.py` | Modèle `microfinance.caisse.session` : `action_open_session` (`:48-71`), `action_close_session` (`:73-84`). |
| `microfinance_loan_management/models/microfinance_loan_payment.py:115-131` | `preview_repayment_allocation(loan_id, amount)` (`@api.model`, aperçu ventilation sans écriture). |

Tests existants : `microfinance_savings_management/tests/test_caisse_pos.py` (search / summary /
register_operation), `microfinance_loan_management/tests/test_caisse_session.py`,
`test_caisse_security.py`, `test_caisse_cloture.py`, `test_caisse_fiche_journee*.py`,
`test_cashier_access.py`. **Aucun de ces tests n'exerce les méthodes RPC du guichet avec
`with_user(<caissier>)`** : tous tournent en super-utilisateur (voir §5.4).

### 1.2 Flux numpad → validation

État JS (`microfinance_caisse_pos.js:20-35`), champs pertinents :
`session`, `searchQuery`/`searchResults`, `client`, `activeTab` (défaut `"depot_epargne"`),
`selectedAccountId`, `amountStr`, `ventilation`, `mouvements`, `submitting`.

Numpad :

- Montant construit **uniquement dans `state.amountStr` (string)**. Getter `amount`
  = `parseFloat(this.state.amountStr) || 0.0` (`:220-222`).
- `pressDigit(d)` (`:194-200`) : concatène, plafonné à 12 caractères hors `.`.
  `pressDecimal()` (`:202-208`) : ajoute `.` (ou `0.` si vide), refuse un 2ᵉ point.
  `pressBackspace()` (`:210-213`) : `slice(0,-1)`. `pressClear()` (`:215-218`) : vide +
  `ventilation=null`.
- Chaque touche appelle `updateVentilationPreview()` (`:224-233`) qui **ne fait rien sauf si
  `activeTab === 'remboursement_credit'`** et `selectedAccountId` + `amount > 0` → alors
  `orm.call("microfinance.loan.payment", "preview_repayment_allocation", [selectedAccountId, amount])`.
- Markup : `xml:111-117`, `.o_microfinance_pos__keypad` (grille `repeat(3,1fr)`), chiffres
  1-9 + `,` + `0` + retour arrière ; bouton « Effacer » séparé `:117`.

Validation :

- `canSubmit` (`:237-245`) : session + client + `amount > 0` + `selectedAccountId` + pas déjà
  en cours.
- `submitOperation()` (`:247-276`) : `orm.call("microfinance.caisse.mouvement",
  "register_operation", [session.id, activeTab, client.id, amount, savingsAccountId|false,
  loanId|false])` (le 5ᵉ ou 6ᵉ argument selon `kind`). Puis notification, reset partiel,
  `loadSession()` + `selectClient(client.id)`.
- `register_operation()` (`microfinance_caisse_mouvement.py:53-106`), dispatch sur `type` :
  - `depot_epargne` / `retrait_epargne` : garde `account.company_id == session.company_id`
    (sinon `UserError`), puis `account._create_transaction('deposit'|'withdrawal', amount,
    payment_method='cash')`. `_create_transaction` (`microfinance_savings_account.py:179-200`)
    **poste immédiatement** (`transaction.action_post()` `:199`).
  - `remboursement_credit` : garde company, `create` d'un `microfinance.loan.payment`
    `{loan_id, amount, journal_id: session.journal_id}` puis `payment.action_post()`. Reflète
    `payment.allocated_interest/principal/penalty` dans le mouvement.
  - `decaissement_credit` : garde company, `loan.action_disburse()`. **Le montant saisi au
    numpad est ignoré** : `action_disburse()` ne prend aucun montant et décaisse toujours
    l'intégralité configurée ; le mouvement enregistre `loan.net_disbursed_amount`
    (`:99-102`).
  - Refus si `session.state != 'open'` (`:61-62`).
- Le modèle `microfinance.caisse.mouvement` **ne fait aucune comptabilisation propre** : il
  trace le résultat des mécanismes existants (`payment_id` / `savings_transaction_id`).

### 1.3 Recherche client

`onSearchInput` (`:108-118`) → debounce 300 ms (`_searchTimer`) → `performSearch()`
(`:120-130`) → `orm.call("res.partner", "search_caisse_clients", [searchQuery,
session.company_id[0]])`.

`search_caisse_clients(query, company_id)` (`res_partner.py:126-140`) :
```python
domain = [('microfinance_partner_type', '=', 'client'), ('company_id', '=', company_id)]
if query:
    domain += ['|', ('name', 'ilike', query), ('microfinance_account_number', 'ilike', query)]
partners = self.search(domain, limit=20)
# renvoie [{'id', 'name', 'account_number': microfinance_account_number}]
```
Méthode dédiée (pas de surcharge de `name_search`, pour ne pas impacter EAT/immobilier sur le
même `res.partner`). **Pas de `sudo`.**

Sélection : `selectClient(partnerId)` (`:132-148`) → `orm.call("res.partner",
"get_client_accounts_summary", [partnerId, session.company_id[0]])`.
`get_client_accounts_summary` (`res_partner.py:142-175`) renvoie :
```
{'savings_accounts': [{'id','name','product','balance'}],   # filtrés company + state=='active'
 'loans':            [{'id','name','state','balance_total','next_due_date','next_due_amount'}]}
                                     # filtrés company + state in ('approved','active','defaulted')
```
`next_installment` = 1ʳᵉ échéance `residual_amount > 0.01` triée `(due_date, sequence)`.

### 1.4 Les 4 boutons d'opération

`static TABS` (`:8-13`) : 4 entrées `{id, label, icon, kind}` avec `kind ∈ {savings, loan}` :
`depot_epargne` (savings), `retrait_epargne` (savings), `remboursement_credit` (loan),
`decaissement_credit` (loan).

- `setActiveTab(tabId)` (`:159-164`) : pose `state.activeTab`, **remet à zéro**
  `selectedAccountId`, `amountStr`, `ventilation`.
- `activeTabKind` (`:166-168`) : `savings` ou `loan`. Pilote quelles lignes de la colonne
  gauche sont cliquables (`xml:62-63` épargne, `xml:73-74` crédits).
- `actionableSavingsAccounts` (`:170-172`) = `client.savings_accounts` (déjà filtrés
  serveur : `state=='active'`).
- `actionableLoans` (`:174-183`) : pour `decaissement_credit` → `loans.filter(l.state ===
  "approved")` ; pour `remboursement_credit` → `l.state === "active" || "defaulted"` ;
  sinon `[]`.
- `selectAccount(id)` (`:185-190`) : pose `selectedAccountId` ; si onglet
  `remboursement_credit`, déclenche `updateVentilationPreview()`.
- Actions Python à la validation : cf. §1.2 (`register_operation`).

Le routing d'écran est donc **entièrement porté par `state.activeTab` + `state.client` +
`state.selectedAccountId`**, aucun `doAction`/navigation Odoo interne (hors dialogue
d'ouverture de session).

---

## 2. Décaissements en attente

### 2.1 Champ / états trouvés

`microfinance.loan.state` — `microfinance_loan.py:79-90`, valeurs exactes :
```
draft, enquete, avis_ca, avis_cdag, approved, active, closed, defaulted, written_off, cancelled
```
Workflow (méthodes) :
`draft` → `action_start_enquete` → `enquete` → `action_ca_review` → `avis_ca` →
`action_cdag_review` → `avis_cdag` → `action_approve` → `approved` → `action_disburse` →
`active`.

**« Avisé/avalisé mais non décaissé » au sens strict du code = `state == 'approved'`.**
`action_disburse()` (`microfinance_loan.py:1910-1932`) refuse durement tout autre état :
```python
if loan.state != 'approved':
    raise UserError(_('Le crédit doit être approuvé avant décaissement.'))
```
`avis_ca` / `avis_cdag` sont des **étapes de revue antérieures** : un crédit dans ces états
doit encore passer `action_approve()` (qui vérifie `_check_committee_octroi_accepted`,
`:945`) avant de pouvoir être décaissé. Si « avisé » doit inclure `avis_ca`/`avis_cdag`, c'est
une décision de périmètre (Q1).

Contrôles supplémentaires de `action_disburse()` au-delà de l'état (`:1914-1922`) :
`signed_contract` téléversé (obligatoire), `fee_paid` si `product_id.fee_charged_before_
disbursement`, `_check_disbursement_limit`, `_check_cash_journal_balance`,
`_check_fond_disponibilite`. Un crédit `approved` peut donc être « en attente » tout en étant
**bloqué** faute de contrat signé ou de frais encaissés.

Date d'entrée en `approved` : `approval_date` posé dans `action_approve()`
(`microfinance_loan.py:946`).

### 2.2 Action / domaine / vue existants pour ces prêts

**Aucune action, aucun domaine nommé, aucun menu, aucun smart button dédié** aux prêts « à
décaisser ». La vue recherche crédit (`microfinance_loan_views.xml:47-53`) n'a que les filtres
`active` / `overdue` / `defaulted` et des `group_by` (`state`, `product_id`, `officer_id`).

Le sous-ensemble « `approved` non décaissé » n'est matérialisé qu'aux endroits suivants (à
réutiliser, ne pas réinventer un domaine divergent) :

- `microfinance_caisse_pos.js:176-178` — `actionableLoans` : `l.state === "approved"`.
- `res_partner.py:151-153` — `get_client_accounts_summary` : `l.state in ('approved','active',
  'defaulted')` (mélange décaissables + remboursables).
- `microfinance_loan_views.xml:73` — bouton `action_disburse` : `invisible="state != 'approved'"`.
- `microfinance_dashboard_controller.py:108` — `state_badge['approved'] = ('warning', 'En attente')`.
- `microfinance_caisse_mouvement.py:94-98` — garde de `register_operation` type
  `decaissement_credit` (implicite : `action_disburse` lèvera si ≠ `approved`).

### 2.3 `company_id`

**Champ direct, stocké, `required=True`** sur `microfinance.loan` :
`microfinance_loan.py:46` :
```python
company_id = fields.Many2one('res.company', string='Société',
                             default=lambda self: self.env.company, required=True, tracking=True)
```
Non dérivé de `partner_id` ni du compte crédit. `microfinance.loan.installment.company_id` et
`microfinance.loan.payment.company_id` sont des `related='loan_id.company_id'` **stockés**
(`microfinance_loan_installment.py:42`, `microfinance_loan_payment.py:42`).

### 2.4 Éléments trouvés vs gaps

- Champ d'état : présent (`state`, indexé `:90`). Domaine « à décaisser » = `[('state','=',
  'approved'), ('company_id','=', <société session>)]` (à confirmer Q1/Q6).
- Colonne date : `approval_date` disponible.
- Gap : montant à afficher (`loan_amount` brut vs `net_disbursed_amount` net des frais) — Q2.
- Gap : faut-il inclure/flaguer les `approved` bloqués (contrat non signé, frais impayés) — Q1.

---

## 3. Échéances du jour

### 3.1 Modèle et champs

`microfinance.loan.installment` — `microfinance_loan_installment.py`. Échéances individuelles
(pas de modèle tiers) :

| Champ | Déf. | Note |
|---|---|---|
| `due_date` | `:12` Date, **`index=True`** | Date d'échéance. |
| `total_amount` | `:16` Monetary, compute **stocké** | `principal+interest+penalty`. |
| `residual_amount` | `:20` Monetary, compute **stocké** | `max(total - (paid_principal+paid_interest+paid_penalty), 0)`. |
| `state` | `:21-26` Selection, compute `_compute_state` **stocké**, `readonly=False` | valeurs : `pending`, `partial`, `paid`, `overdue`. |
| `paid_principal` / `paid_interest` / `paid_penalty` | `:17-19` | |
| `company_id` | `:42` related stocké → `loan_id.company_id` | |
| `partner_id` | `:41` related stocké → `loan_id.partner_id` | |
| `arrears_onset_date` / `arrears_cured_date` | `:28-39` Date, `readonly`, `index` sur onset | Historique persistant des épisodes de retard. |
| `payment_ids` | `:40` M2M vers `microfinance.loan.payment` | |

### 3.2 Mécanisme « en retard »

`_compute_state` (`microfinance_loan_installment.py:52-63`) :
```python
today = fields.Date.context_today(self)
if line.total_amount and line.residual_amount <= 0.01:      -> 'paid'
elif line.residual_amount < line.total_amount:              -> 'partial'
elif line.due_date and line.due_date < today:              -> 'overdue'
else:                                                       -> 'pending'
```
Conséquences précises :
- Une échéance **partiellement payée et en retard** est `partial`, **pas** `overdue`.
- `@api.depends('residual_amount', 'total_amount', 'due_date')` — **aucune dépendance sur
  « aujourd'hui »** : le basculement `pending → overdue` au fil des jours **ne se produit pas
  seul**. Il est forcé par le cron quotidien `cron_update_overdue_and_penalties` (data/cron.xml)
  qui appelle `_sync_arrears_state()` (`:65-80`) → `_compute_state()` puis journalisation
  `arrears_onset_date`/`arrears_cured_date`.

« Jours de retard » : `microfinance.loan._get_max_overdue_days()`
(`microfinance_loan.py:624-632`) = `max((today - due_date).days)` sur les échéances
`state == 'overdue'`. **Méthode, non stockée.** Aucun champ « jours de retard » /
`days_overdue` en base (seul `arrears_onset_date` est persisté).

### 3.3 Domaine / méthode « échéances du jour » existant

**`microfinance.loan.installment.get_due_today(company_id)`** — déjà présent,
`microfinance_loan_installment.py:82-93` (`@api.model`) :
```python
today = fields.Date.context_today(self)
return self.search([
    ('company_id', '=', company_id),
    ('due_date', '=', today),
    ('state', '!=', 'paid'),
], order='due_date, loan_id')
```
→ **strictement `due_date == today`**, ne remonte **pas** les retards. Consommé par
`microfinance_dashboard_controller.py:128` (`today_installments`, `today_installments_count`).

Domaines « retard » existants (dashboard, `microfinance_dashboard_controller.py`) :
- `top_overdue_loans` (`:138`) : `Installment.search([('company_id','=',company.id),
  ('state','=','overdue'), ('residual_amount','>',0)])`.
- graphe mensuel (`:63-66`) : `[('company_id','=',company.id), ('state','=','overdue'),
  ('due_date','>=', months[0])]`.
- **Ces deux domaines filtrent `installment.state`, jamais `loan.state`** : ils incluent donc
  les échéances de crédits non décaissés dont un échéancier a été généré en phase d'aperçu
  (anomalie A1 de `docs_dev/dashboard_portefeuille_agent/AUDIT.md §3.5` : `IS/000289` en
  `avis_cdag`, 24 échéances, 2 `overdue`). À ne pas reproduire pour l'onglet 2.

### 3.4 Éléments trouvés vs gaps

- Volet « remboursements attendus aujourd'hui » : `get_due_today(company_id)` réutilisable
  tel quel pour la partie **strictement du jour**.
- Gap « y compris retards » : aucune méthode existante ne combine « aujourd'hui + en
  retard ». Domaine à définir (Q3), p. ex. `[('company_id','=',c), ('state','!=','paid'),
  ('due_date','<=',today), ('loan_id.state','in',('active','defaulted'))]` — le filtre
  `loan_id.state` est **indispensable** (cf. §3.3) et n'existe nulle part aujourd'hui.
- Gap « dépôts attendus aujourd'hui » (volet épargne de l'onglet 2) : **aucun modèle
  d'échéancier d'épargne / de versement daté attendu n'existe**. Le seul objectif d'épargne
  est `microfinance.loan.savings_target_amount` (montant cible d'épargne obligatoire pendant
  remboursement, `microfinance_savings_management/models/microfinance_loan_extension.py:22-23`,
  compute stocké), **sans aucune date d'échéance**. → Q4.

---

## 4. Épargne en attente

### 4.1 États trouvés

`microfinance.savings.transaction.state` — `microfinance_savings_transaction.py:34-38` :
valeurs `draft`, `posted`, `cancelled`.

`_create_transaction` (`microfinance_savings_account.py:179-200`) **appelle immédiatement
`transaction.action_post()`** (`:199`). `action_post()` (`microfinance_savings_transaction.py:
302-322`) crée et poste l'`account.move`, met `state='posted'`. **Aucun état intermédiaire
« en attente » n'est produit par le flux normal** : une transaction créée par la voie
standard (guichet inclus) n'est jamais laissée en `draft`. Un `draft` n'existe que via
création ORM/import direct sans post.

Le guichet actuel force `payment_method='cash'` pour `depot_epargne` et `retrait_epargne`
(`microfinance_caisse_mouvement.py:74-75`).

### 4.2 Seule notion « en attente » existante côté épargne : le chèque

`microfinance.savings.transaction.cheque_state` — `microfinance_savings_transaction.py:39-47`,
valeurs `en_attente`, `compense`, `rejete`. Ne concerne **qu'un dépôt par chèque**
(`payment_method == 'cheque'` et `transaction_type == 'deposit'`). La transaction est déjà
`state == 'posted'` (montant logé sur un compte d'attente chèques), le `cheque_state` gère
l'après :
- `action_clear_cheque()` (`:324-356`) → `cheque_state='compense'` + `clearing_move_id`.
- `action_reject_cheque(reason)` (`:358-385`) → `cheque_state='rejete'`, `state='cancelled'`,
  contre-passation.

Comme le guichet impose `payment_method='cash'`, **il ne produit jamais de chèque en
attente** ; ces enregistrements viennent d'une saisie de transaction hors guichet.

### 4.3 Conclusion (gap)

Une file générique « opérations épargne à traiter » **n'existe pas** dans le code actuel.
Options possibles, à trancher (Q5) — **ne pas inventer de champ** :
- (a) surfacer les dépôts chèque `cheque_state == 'en_attente'` (seule notion « pending »
  réelle) ;
- (b) surfacer les `microfinance.savings.transaction` en `state == 'draft'` (jamais produites
  par le flux courant aujourd'hui) ;
- (c) nouveau concept à définir avec Micka.

---

## 5. Isolation multi-société

### 5.1 Record rules existantes (`ir.rule`)

Toutes avec `groups eval="[]"` (→ **tous** les utilisateurs internes, managers/auditeurs
compris) et `domain_force = [('company_id', 'in', company_ids)]`.

`microfinance_loan_management/security/microfinance_company_rules.xml` :
`microfinance.loan.product`, **`microfinance.loan`** (`:16-21`), `microfinance.loan.account`,
**`microfinance.loan.installment`** (`:36-41`), **`microfinance.loan.payment`** (`:43-48`),
`microfinance.loan.guarantee`, `microfinance.guarantee.valuation.rule`,
`microfinance.loan.reschedule.history` + `.line` (`history_id.company_id`),
`microfinance.collection.visit`, `microfinance.caisse.fiche.journee`,
**`microfinance.caisse.session`** (`:93-98`), `microfinance.client.blacklist`
(`partner_id.company_id`).

`microfinance_savings_management/security/microfinance_company_rules.xml` :
`microfinance.savings.product`, **`microfinance.savings.account`** (`:14-19`),
**`microfinance.savings.transaction`** (`:21-26`), **`microfinance.caisse.mouvement`**
(`:28-33`).

`res.partner` : règle standard Odoo `base.res_partner_rule` (multi-société : partenaires sans
société visibles par tous, sinon `company_id in company_ids`). Les clients microfinance ont
toujours un `company_id` (`microfinance_loan_management/models/res_partner.py:40-46` +
contrainte `_check_microfinance_company_required` `:87-93`).

### 5.2 Nuance déterminante : `company_ids` ≠ société active

Dans un `domain_force` d'`ir.rule`, `company_ids` désigne l'ensemble des **sociétés
autorisées** de l'utilisateur (`res.users.company_ids`), **pas** la société couramment
sélectionnée. La règle borne donc à *toutes les agences de l'utilisateur à la fois*.

Le rétrécissement à la société active, en Odoo standard, est assuré séparément par le
sélecteur de société qui injecte `allowed_company_ids` dans le contexte, **honoré par les
vues `list`/`act_window`** — mais **pas** par une `ir.actions.client` custom qui appelle
`orm.searchRead` / `orm.call` : celle-ci n'obtient que la borne de l'`ir.rule` (toutes
sociétés autorisées), sauf si elle ajoute elle-même un filtre `company_id` explicite.

### 5.3 Ce que fait le guichet actuel

Chaque appel serveur passe un `company_id` explicite issu de `state.session.company_id[0]`,
la session elle-même étant chargée avec `["company_id", "=", this.company.currentCompany.id]`
(`microfinance_caisse_pos.js:54`) :

- `search_caisse_clients` : `('company_id', '=', company_id)` dans le domaine
  (`res_partner.py:132`).
- `get_client_accounts_summary` : `a.company_id.id == company_id` /
  `l.company_id.id == company_id` (`res_partner.py:149, 152`).
- `loadMouvements` : filtre `('session_id', '=', session.id)` (`microfinance_caisse_pos.js:90`).
- `register_operation` : re-vérifie `account/loan.company_id == session.company_id`
  (`microfinance_caisse_mouvement.py:72, 79, 96`), sinon `UserError`.

### 5.4 Constat par modèle et réponse « fuite »

| Modèle (onglet) | Cloisonnement natif suffisant ? |
|---|---|
| `microfinance.loan` (onglet 1) | `ir.rule` borne aux sociétés **autorisées** seulement. **Domaine `company_id` explicite requis** dans la nouvelle liste pour scoper à l'agence de la session. |
| `microfinance.loan.installment` (onglet 2) | Idem. `get_due_today(company_id)` prend déjà un `company_id` explicite — patron à reprendre. |
| `microfinance.savings.account` / `.transaction` (onglet 3) | Idem — filtre `company_id` explicite requis. |

**Un caissier peut-il aujourd'hui voir des données d'une autre agence via le guichet ?**

- **Via l'UI du guichet telle que livrée : NON.** Tous les appels serveur portent un filtre
  `company_id` explicite (§5.3) et `register_operation` re-garde la cohérence d'agence. La
  session est chargée sur `company.currentCompany.id`.
- **Au niveau ORM / record rule : OUI, conditionnel.** Si le `res.users.company_ids` du
  caissier contient plusieurs agences, un `orm.searchRead('microfinance.loan', [], …)` sans
  clause société — depuis un client instrumenté, ou depuis un futur onglet qui oublierait le
  filtre explicite — renverrait les crédits/échéances/épargnes de **toutes** ses agences,
  parce que l'`ir.rule` utilise `company_ids` et non la société active.
  **Preuve** : les `domain_force` des deux `microfinance_company_rules.xml` sont
  `[('company_id', 'in', company_ids)]` ; aucune règle ne référence la société active.
  `test_caisse_pos.py` / `test_caisse_security.py` créent des utilisateurs caissier/manager
  avec un `company_ids` à une seule entrée (`test_caisse_security.py:98`) — le cas
  multi-société d'un même utilisateur n'est jamais testé.
- Si le caissier n'a qu'une société dans `company_ids` (cas mono-agence courant), l'`ir.rule`
  suffit et les filtres explicites sont une ceinture-bretelles.

### 5.5 Droits d'accès du groupe Caissier (impact direct sur les 3 onglets)

`group_microfinance_cashier` **implique `group_microfinance_user`** (`groups.xml:35-39`).
D'où, pour un **caissier pur** (cashier + user impliqué) :

| Modèle | Droits | Source |
|---|---|---|
| `microfinance.loan` | read / write / create | `ir.model.access.csv:23` (user) + `:93` (cashier, read) |
| `microfinance.loan.installment` | **read seul** | `ir.model.access.csv:35` (user) — **aucune ligne cashier** |
| `microfinance.loan.payment` | read / write / create | `ir.model.access.csv:92` (cashier) |
| `microfinance.loan.account` | read | `:27` / `:96` |
| `microfinance.caisse.session` | read / write / create | `:127` |
| `microfinance.caisse.fiche.journee` | read / write / create | `:122` |
| `microfinance.caisse.mouvement` | read / write / create | `microfinance_savings_management/security/ir.model.access.csv:18` |
| **`microfinance.savings.account`** | **AUCUN** | accès réservé à `group_savings_agent` / `group_savings_manager` / loan-manager / loan-finance / auditor (`microfinance_savings_management/security/ir.model.access.csv:5-9`) |
| **`microfinance.savings.transaction`** | **AUCUN** | idem (`:10-13`) |

`group_microfinance_cashier` **n'implique aucun groupe épargne** (`savings_security.xml` :
`group_savings_manager` implique seulement `group_savings_agent`).

**Conséquence** : un caissier pur qui appelle `get_client_accounts_summary` (lit
`microfinance_savings_account_ids`) ou `register_operation` type `depot_epargne` /
`retrait_epargne` (`_create_transaction` → `microfinance.savings.transaction.create` +
`account.move`) déclencherait un `AccessError`. **Aucune** des méthodes RPC de la caisse
n'utilise `sudo()` (vérifié sur `microfinance_caisse_mouvement.py`, `res_partner.py`,
`microfinance_caisse_session.py`). Les tests existants n'appellent jamais ces méthodes en
`with_user(<caissier>)` → chemin non testé. En pratique, le guichet actuel ne fonctionne pour
un caissier que si celui-ci s'est vu **aussi** attribuer `group_savings_agent` (et des droits
`account.move`). → Q7.

Menus : `menu_caisse_root` est visible pour `group_microfinance_cashier` **et**
`group_microfinance_manager` (`microfinance_menus.xml:20`). Les menus « Crédits » et
« Épargne » excluent le caissier — un caissier pur ne voit que « Caisse ».

---

## 6. Réutilisabilité

### 6.1 À garder tel quel (Python / métier)

- `microfinance.caisse.mouvement.register_operation()` — point d'entrée unique de validation ;
  réutilise déjà `_create_transaction`, `microfinance.loan.payment.action_post`,
  `loan.action_disburse`, et porte les gardes d'agence. Indépendant du layout.
- `microfinance.loan.payment.preview_repayment_allocation()` — aperçu ventilation, sans
  écriture.
- `res.partner.search_caisse_clients()` — recherche client (nom / n° de compte permanent),
  scopée agence.
- `microfinance.caisse.session` : `action_open_session` / `action_close_session`,
  `mouvement_ids`, related soldes via `fiche_journee_id`.
- `microfinance.loan.installment.get_due_today(company_id)` — base réutilisable pour le volet
  « strictement du jour » de l'onglet 2.
- `microfinance.loan._get_max_overdue_days()` — « jours de retard » par crédit (non stocké),
  pour une colonne d'ancienneté d'arriéré.
- Gardes de cohérence d'agence dans `register_operation`.

### 6.2 À garder mais étendre (Python)

- `res.partner.get_client_accounts_summary()` — orienté « un client sélectionné » ; renvoie
  déjà `next_due_date` / `next_due_amount` par crédit. Les 3 onglets ont besoin de **listes
  agrégées non liées à un client sélectionné** → nouvelles méthodes dédiées (style
  `get_due_today` : `@api.model`, `company_id` explicite), plutôt que surcharger celle-ci.
- Aucune méthode existante pour « `approved` non décaissé » (onglet 1) ni « épargne en
  attente » (onglet 3) → à créer, en réutilisant les domaines/états recensés (§2.2, §4).

### 6.3 À réécrire (présentation uniquement)

- `microfinance_caisse_pos.xml` — grille 3 colonnes → numpad à gauche / recherche + liste 3
  onglets au centre / (ticket à repositionner). Le bloc liste à onglets est du markup neuf.
- `microfinance_caisse_pos.scss` — `grid-template-columns` (`280px 1fr 320px`, `:63`),
  `grid-template-areas`, media queries `:293` et `:319`.
- `microfinance_caisse_pos.js` — ajouter un état d'onglet **pour la liste centrale** (distinct
  du `static TABS` des 4 opérations), les RPC vers les nouvelles méthodes de liste, et la
  donnée de la colonne « Agence ». La logique numpad / recherche / onglets-opération existante
  reste.

### 6.4 Couplages cachés à connaître

- `state.amountStr` est **un seul champ partagé** par les 4 opérations ; `setActiveTab()` le
  vide (`:159-164`). `updateVentilationPreview()` est appelé à chaque touche mais no-op sauf
  onglet `remboursement_credit` (`:224-233`). Déplacer le numpad ne change rien à cela.
- `selectAccount()` déclenche aussi `updateVentilationPreview()` pour l'onglet remboursement
  (`:185-190`). Si une ligne de la liste centrale devient une surface de sélection
  (`selectedAccountId`), ce câblage doit être préservé / réconcilié.
- `activeTabKind` gouverne la cliquabilité des lignes de la **colonne gauche** (épargne vs
  crédit, `xml:62-63`, `:73-74`). La sélection vit aujourd'hui **uniquement** dans la colonne
  gauche ; si la liste centrale devient la surface de sélection, cette logique à deux endroits
  doit être unifiée.
- Aucune dépendance à l'ordre DOM / au focus : pas de `querySelector`, pas de `t-ref` sur le
  numpad ni sur l'input de recherche. L'input est piloté par `t-att-value` + `t-on-input`
  (debounce `_searchTimer`), indépendant de sa position.
- `loadSession()` s'exécute `onMounted`, après chaque `submitOperation` et à la fermeture de
  `openSessionForm`. Tout l'écran dépend d'**une** session ouverte pour
  `company.currentCompany.id` ; les 3 nouveaux onglets doivent utiliser ce même
  `state.session.company_id` comme clé de scope (pas la société active de l'UI, cf. §5).
- `microfinance.caisse.mouvement` vit dans `microfinance_savings_management` (dépendance),
  `microfinance.caisse.session` dans `microfinance_loan_management` : toute nouvelle méthode
  touchant les deux mondes (crédit + épargne) doit vivre côté `microfinance_savings_management`
  (cf. commentaire `microfinance_caisse_mouvement.py:11-16`).

---

## 7. Questions bloquantes pour le Lot 1

1. **Onglet 1 — périmètre « avisé/avalisé non décaissé ».** Strictement `state == 'approved'`
   (seul état accepté par `action_disburse`), ou inclure aussi `avis_ca` / `avis_cdag`
   (revus mais pas encore approuvés par le comité) ? Les crédits `approved` **bloqués**
   (contrat non signé, frais de dossier impayés — cf. contrôles de `action_disburse`,
   `microfinance_loan.py:1914-1922`) doivent-ils apparaître (avec un indicateur) ou être
   masqués ?

2. **Onglet 1 — affichage.** Tri par `approval_date` ? Colonne montant = `loan_amount` (brut)
   ou `net_disbursed_amount` (net des frais réellement sorti de caisse) ?

3. **Onglet 2 — définition exacte de l'ensemble.** `due_date == today` seul (méthode
   existante `get_due_today`), ou `due_date <= today AND state != 'paid'`, ou `state ==
   'overdue'` + les `pending` du jour ? Confirme-t-on le filtre `loan_id.state in ('active',
   'defaulted')` (pour exclure les échéances de crédits non décaissés — cf. §3.3 et
   `docs_dev/dashboard_portefeuille_agent/AUDIT.md` A1) ? Les échéances **partiellement
   payées et en retard** (statut `partial`, pas `overdue` — §3.2) sont-elles incluses ?

4. **Onglet 2 — volet épargne.** Il n'existe aucun modèle de versement d'épargne daté
   attendu. « Dépôts attendus aujourd'hui » signifie-t-il : (a) retirer l'épargne de l'onglet
   2 ; (b) les crédits à épargne obligatoire dont `savings_account_id.balance <
   savings_target_amount` ; ou (c) un nouveau concept d'échéancier de contribution à
   concevoir ?

5. **Onglet 3 — « Épargne en attente ».** Aucun état « en attente » générique n'existe pour
   `microfinance.savings.transaction` (le flux normal poste immédiatement). Est-ce : (a) les
   dépôts chèque `cheque_state == 'en_attente'` (seule notion « pending » réelle du code) ;
   (b) les transactions `state == 'draft'` (jamais produites par le flux courant) ; ou (c) un
   nouveau concept ? (Ne pas inventer de champ tant que ce n'est pas tranché.)

6. **Multi-société.** Un caissier peut-il être multi-agence (`res.users.company_ids` de
   longueur > 1) ? Si oui, les nouvelles listes **doivent** porter un domaine explicite
   `company_id == session.company_id` (l'`ir.rule` ne borne qu'à *toutes* les sociétés
   autorisées, §5.2/§5.4). Confirme-t-on que la société de la **session** est l'unique clé de
   scope (et non la société active de l'UI) ?

7. **Droits d'accès.** Le groupe Caissier sera-t-il doté de `group_savings_agent` (nécessaire
   pour lire `microfinance.savings.account` / `.transaction` et exécuter `depot_epargne` /
   `retrait_epargne` — §5.5), ou faut-il retravailler les méthodes RPC de la caisse en
   `sudo()` + contrôles d'agence explicites ? Aujourd'hui `group_microfinance_cashier` seul ne
   peut pas lire les modèles épargne et les méthodes ne sont pas `sudo`.

8. **Colonne « Agence ».** Le caissier étant normalement mono-agence et chaque ligne étant
   déjà scopée à la société de la session, la colonne Agence est-elle purement informative
   (toujours = agence de la session), ou une vue inter-agences est-elle visée pour les
   managers (`menu_caisse_root` est aussi visible pour `group_microfinance_manager`) ? Une
   vue inter-agences rouvre la Q6 et s'écarte du cloisonnement « scié sur `company.id` »
   appliqué partout ailleurs.

---

*Audit réalisé le 2026-09-07. Lecture seule — aucune modification de code, de vue, de données
ou de sécurité, aucun commit.*
