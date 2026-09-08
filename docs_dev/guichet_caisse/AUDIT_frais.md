# Audit — Intégration Frais de dossier au Guichet Caisse

Audit **en lecture seule**. Aucune modification de code, de vue, de données ni de sécurité.
Aucun commit. Les extraits ci-dessous sont recopiés du code, pas reformulés.

Fichiers de référence :
- `microfinance_loan_management/models/microfinance_loan.py`
- `microfinance_loan_management/models/microfinance_loan_product.py`
- `microfinance_loan_management/models/microfinance_caisse_session.py`
- `microfinance_savings_management/models/microfinance_caisse_mouvement.py`
- `microfinance_loan_management/views/microfinance_loan_views.xml`
- `microfinance_loan_management/tests/test_fee.py`

---

## 1. `action_charge_fee` — comportement actuel

**Définition : `microfinance_loan.py:1714-1764`.** Corps intégral :

```python
def action_charge_fee(self):
    for loan in self:
        if loan.state != 'approved':
            raise UserError(_('Les frais de dossier ne peuvent être encaissés que sur un crédit approuvé.'))
        # Verrou pessimiste ligne (FOR UPDATE) posé AVANT la relecture de fee_paid /
        # fee_amount_due : sérialise deux requêtes « Encaisser les frais » concurrentes sur
        # le même dossier en prod multi-worker (docs_dev/refactor_frais_dossier_account_move/
        # AUDIT.md §6). [...]
        loan.env.cr.execute("SELECT id FROM microfinance_loan WHERE id = %s FOR UPDATE", (loan.id,))
        loan.invalidate_recordset(['fee_paid', 'fee_amount_due'])
        if loan.fee_paid:
            raise UserError(_('Les frais de dossier ont déjà été encaissés.'))
        if loan.fee_amount_due <= 0:
            raise UserError(_('Aucun frais de dossier à encaisser pour ce crédit.'))
        # Rattrapage de l'engagement manquant [...]
        if loan._is_fee_engagement_applicable():
            engagement = self.env['account.move'].with_context(
                default_loan_id=False, default_loan_line_id=False,
            ).create(loan._prepare_fee_receivable_move())
            engagement.action_post()
            loan.fee_receivable_move_id = engagement.id
            loan.message_post(body=_(
                'Engagement frais de dossier (rattrapage à l\'encaissement, %.2f). '
                'Écriture : %s') % (loan.fee_amount_due, engagement.name))
        move = self.env['account.move'].with_context(
            default_loan_id=False,
            default_loan_line_id=False,
        ).create(loan._prepare_fee_settlement_move())
        move.action_post()
        loan.write({'fee_paid': True, 'fee_move_id': move.id})
        receivable_account = loan.product_id.account_fee_receivable_id
        if loan.fee_receivable_move_id and receivable_account.reconcile:
            # Lettrage engagement <-> règlement [...]
            (loan.fee_receivable_move_id.line_ids + move.line_ids).filtered(
                lambda l: l.account_id == receivable_account and not l.reconciled
            ).reconcile()
        loan.message_post(body=_('Frais de dossier encaissés (%.2f). Écriture : %s') % (loan.fee_amount_due, move.name))
    return True
```

**Ce qu'elle fait aujourd'hui** :
1. Garde `state == 'approved'`.
2. `SELECT ... FOR UPDATE` sur la ligne `microfinance_loan` + `invalidate_recordset` +
   gardes `fee_paid` / `fee_amount_due <= 0` (verrou anti-double-comptabilisation, §4).
3. Rattrapage éventuel de l'écriture d'**engagement** (`_prepare_fee_receivable_move`,
   journal OD du produit) si `_is_fee_engagement_applicable()`.
4. Crée et **poste directement** l'écriture de **règlement** (`account.move`,
   `_prepare_fee_settlement_move`) : débit caisse (`product.fee_journal_id.default_account_id`) /
   crédit contrepartie (créance `account_fee_receivable_id` si engagement, sinon repli
   `account_commission_credit_id`).
5. `loan.write({'fee_paid': True, 'fee_move_id': move.id})`.
6. Lettrage engagement ↔ règlement sur le compte de créance si `reconcile=True`.
7. Deux `message_post` sur le crédit.

**Modèle et journal de l'écriture** : `account.move`, journal `product.fee_journal_id`
(champ `microfinance.loan.product`, domaine `type in ('bank','cash')`, défaut journal code
`CRE` — `microfinance_loan_product.py:365-371`). L'engagement de rattrapage utilise
`product.fee_engagement_journal_id` (type `general`, défaut `OD` — `:372-381`).

**Lien avec une session de caisse : AUCUN.** `grep "session_id\|caisse.session"` sur
`microfinance_loan.py` → 0 résultat. `action_charge_fee` ne reçoit aucun paramètre
(`def action_charge_fee(self)`), ne connaît ni journal de session, ni régisseur, ni fiche
journalière. Elle est **entièrement indépendante du guichet**.

**Appelants réels** (`grep -rn action_charge_fee` hors tests) : uniquement le bouton de
formulaire `microfinance_loan_views.xml:72` :
```xml
<button name="action_charge_fee" string="Encaisser les frais de dossier" type="object"
        groups="microfinance_loan_management.group_microfinance_finance"
        invisible="state != 'approved' or fee_paid or fee_amount_due &lt;= 0"/>
```
Aucun cron, aucun wizard, aucun autre `type="object"`.

---

## 2. Créance à l'approbation (`_prepare_fee_receivable_move`)

**Définition : `microfinance_loan.py:1661-1684`.**

**Appelée** :
- Dans `action_approve()` (`microfinance_loan.py:954-963`), pour chaque crédit passant
  `_is_fee_engagement_applicable()`, juste après `write({'state': 'approved', ...})`.
- Et en **rattrapage** dans `action_charge_fee()` (`:1740-1745`) si l'engagement n'a pas été
  créé à l'approbation (produit configuré après coup).

**Garde `_is_fee_engagement_applicable()` (`microfinance_loan.py:965-983`)** — engagement créé
seulement si : `fee_amount_due > 0` ET `product.fee_charged_before_disbursement` ET pas déjà
`fee_receivable_move_id` ET produit configuré (`fee_engagement_journal_id` +
`account_fee_receivable_id` + `account_commission_credit_id`). Si non configuré :
approbation non bloquée, pas d'engagement, l'encaissement retombe sur le repli 717003.

**Écriture d'engagement** (`_prepare_fee_receivable_move`) :
- journal : `product.fee_engagement_journal_id` (OD, pas un mouvement de trésorerie) ;
- débit : `product.account_fee_receivable_id` — **compte de créance, PCEC 208005 par défaut**
  (`microfinance_loan_product.py:321-332`, `default=_pcec_default('208005')`, domaine
  `account_type in ('asset_current','asset_receivable')`). C'est un **champ `Many2one`
  paramétrable sur le produit**, pas un compte en dur.
- crédit : `product.account_commission_credit_id` — **commission sur crédit, PCEC 717003 par
  défaut** (`microfinance_loan_product.py:315-320`, `default=_pcec_default('717003')`, domaine
  `account_type = 'income'`). Champ paramétrable, pas en dur.

⚠️ **Précision sur la mémoire projet** : le 717003 est la **contrepartie produit**
(`account_commission_credit_id`), pas la créance. La **créance** est le 208005
(`account_fee_receivable_id`).

**Écriture de règlement** (`_prepare_fee_settlement_move`, `microfinance_loan.py:1686-1712`) :
- journal : `product.fee_journal_id` (caisse/banque du produit) ;
- débit : `journal.default_account_id` (compte de trésorerie du journal de frais du produit) ;
- crédit : `account_fee_receivable_id` si `fee_receivable_move_id` existe **et**
  `account_fee_receivable_id` est configuré (`use_receivable`), **sinon repli**
  `account_commission_credit_id` (717003 direct — comportement historique).

**La contrepartie caisse/banque au règlement n'est donc PAS un champ dédié type
`account_fee_receivable_id`** : c'est le `default_account_id` du journal
`product.fee_journal_id`. Elle est paramétrable via la configuration de ce journal, pas par
un champ « compte caisse frais » sur le produit. Aucun `session_id`/`journal_id` de session
n'intervient.

---

## 3. `fee_payment_state` et le badge

**Champ : `microfinance_loan.py:243-245`.**
```python
fee_payment_state = fields.Selection(
    [('none', 'Sans frais'), ('unpaid', 'Non payé'), ('paid', 'Payé')],
    string='État frais de dossier', compute='_compute_fee_payment_state')
```
- Valeurs exactes : **`none`, `unpaid`, `paid`**.
- **Non stocké** (`compute` sans `store=True`).

**Compute : `microfinance_loan.py:599-605`**, `@api.depends('fee_amount_due', 'fee_paid')` :
```python
def _compute_fee_payment_state(self):
    for loan in self:
        if loan.fee_amount_due <= 0:
            loan.fee_payment_state = 'none'
        else:
            loan.fee_payment_state = 'paid' if loan.fee_paid else 'unpaid'
```

**Transitions réelles** :
- `none` : dès que `fee_amount_due <= 0` (produit sans frais, ou frais nuls).
- `unpaid` : `fee_amount_due > 0` et `fee_paid == False`. `fee_amount_due` est figé à
  l'approbation (`_FEE_FROZEN_STATES = ('approved','active','closed','defaulted','written_off')`,
  `microfinance_loan.py:372` ; `_compute_fee_amount` `:571-597`). `fee_paid` défaut `False`.
- `paid` : `fee_paid` passe à `True` — **uniquement** dans `action_charge_fee()`
  (`loan.write({'fee_paid': True, 'fee_move_id': move.id})`, `:1754`) OU nettage au
  décaissement (voir plus bas). `fee_paid` est `readonly=True, copy=False`
  (`microfinance_loan.py:230`) ; aucune autre écriture de `fee_paid` dans le code
  (`grep "fee_paid': " / "fee_paid ="`).
- Cas « frais nettés du décaissement » (`fee_charged_before_disbursement == False`) :
  `_prepare_disbursement_move` (`microfinance_loan.py:1640-1649`) inclut une ligne crédit
  `account_commission_credit_id` du montant des frais dans l'écriture de décaissement.
  **`fee_paid` n'est alors PAS mis à `True`** (aucun `write` de `fee_paid` dans
  `action_disburse`) — `fee_payment_state` reste `unpaid` après ce type de décaissement.
  À signaler (§8).

**Badge : `microfinance_loan_views.xml:242-246`** (onglet frais de la vue formulaire crédit) :
```xml
<field name="fee_payment_state" widget="badge" readonly="1"
       decoration-success="fee_payment_state == 'paid'"
       decoration-danger="fee_payment_state == 'unpaid'"
       decoration-muted="fee_payment_state == 'none'"
       invisible="fee_payment_state == 'none'"/>
```
C'est bien `fee_payment_state` (et lui seul) qui pilote la couleur (vert = `paid`, rouge =
`unpaid`, muet + masqué = `none`). Modèle explicitement calqué sur le badge `risk_level` du
scoring (commentaire `microfinance_loan.py:240-242` et `microfinance_loan_views.xml:239`).

**GAP confirmé** : il n'existe **aucune valeur ni aucun champ** correspondant à « frais
engagés, en attente d'encaissement en caisse », distincte de `unpaid`. Aujourd'hui, entre
l'approbation (créance 208005 ouverte) et le clic « Encaisser », l'état reste `unpaid` — rien
ne distingue « à encaisser en caisse » de « pas encore traité ». Le seul marqueur d'un
engagement déjà comptabilisé est `fee_receivable_move_id` (Many2one renseigné), non exposé
comme état.

---

## 4. Verrou anti-double-comptabilisation

**Emplacement exact : `microfinance_loan.py:1727`**, dans `action_charge_fee()` :
```python
loan.env.cr.execute("SELECT id FROM microfinance_loan WHERE id = %s FOR UPDATE", (loan.id,))
loan.invalidate_recordset(['fee_paid', 'fee_amount_due'])
if loan.fee_paid:
    raise UserError(_('Les frais de dossier ont déjà été encaissés.'))
```
- Modèle / table : **`microfinance_loan`** (verrou de ligne pessimiste sur le dossier).
- Posé **avant** la relecture de `fee_paid` / `fee_amount_due` (via `invalidate_recordset`
  pour forcer un re-SELECT après acquisition du verrou).
- Objectif (commentaire `:1718-1726`) : sérialiser deux clics « Encaisser » concurrents en
  prod multi-worker ; la transaction perdante attend le commit de la gagnante, puis relit
  `fee_paid == True` et lève, au lieu de créer un second `account.move`.
- Relâché automatiquement au commit/rollback de la transaction du clic.
- Référence de conception : `docs_dev/refactor_frais_dossier_account_move/AUDIT.md §6`.

**Ce verrou est propre à `action_charge_fee`.** `register_operation`
(`microfinance_caisse_mouvement.py`) ne pose **aucun** `FOR UPDATE` sur `microfinance.loan`
pour ses opérations crédit actuelles (`remboursement_credit`, `decaissement_credit`) — il
s'appuie sur la garde `session.state == 'open'` et sur les gardes internes des méthodes
appelées. **Tout nouveau chemin caisse pour les frais devra reproduire ce `FOR UPDATE` +
relecture `fee_paid`** (sinon régression du garde-fou multi-worker).

**Testé** : `test_fee.py::test_charge_fee_concurrent_guard_no_double_move` (`:166-192`) et
`test_charge_fee_twice_blocked` (`:159-164`).

---

## 5. Intégration `register_operation` — faisabilité et contraintes de placement

**Aucun type `frais_dossier` n'existe.** `microfinance.caisse.mouvement.type`
(`microfinance_caisse_mouvement.py:26-31`) :
```python
type = fields.Selection([
    ('depot_epargne', 'Dépôt épargne'),
    ('retrait_epargne', 'Retrait épargne'),
    ('remboursement_credit', 'Remboursement crédit'),
    ('decaissement_credit', 'Décaissement crédit'),
], string='Type', required=True)
```
`register_operation()` (`:81-136`) ne branche que ces 4 valeurs (sinon
`UserError('Type d\'opération de caisse inconnu')`, `:136`). `grep -rn "frais\|fee\|charge_fee"` sur
`microfinance_caisse_mouvement.py`, `microfinance_caisse_session.py` et
`microfinance_caisse_pos.js` → aucune occurrence fonctionnelle (une seule mention « frais
nettés » en commentaire de `decaissement_credit`).

**Contrainte de placement** (rappel `docs_dev/guichet_caisse/AUDIT.md §1.1 / §6.4) :
- `microfinance.caisse.mouvement` **vit dans `microfinance_savings_management`** parce qu'il
  référence à la fois crédit et épargne ; `microfinance_loan_management` **ne dépend pas** de
  `microfinance_savings_management` (dépendance inverse).
- `microfinance.caisse.session` vit dans `microfinance_loan_management` ; `mouvement_ids` y
  est ajouté par `_inherit` **depuis le module épargne**
  (`microfinance_caisse_mouvement.py:134-137`).

**Conséquence pour un type `frais_dossier` (touche uniquement `microfinance.loan`)** :
- Ajouté **dans `register_operation` / le Selection `type` de `microfinance.caisse.mouvement`**
  (module épargne) : **légal** — le module épargne dépend du module crédit, il peut
  référencer `microfinance.loan`, `microfinance.loan.product`, `action_charge_fee`, etc. sans
  dépendance circulaire. C'est le même schéma que `remboursement_credit` /
  `decaissement_credit` déjà présents. Un type mono-crédit de plus n'introduit aucune
  nouvelle contrainte de dépendance.
- Un mécanisme **entièrement côté `microfinance_loan_management`** (sans passer par
  `microfinance.caisse.mouvement`) pourrait voir `microfinance.caisse.session` (même module)
  mais **pas** `microfinance.caisse.mouvement` (module épargne) — il ne pourrait donc pas
  produire de ligne de ticket ni alimenter `mouvement_ids` / le totalisateur du ticket de
  session. La cohérence « 1 opération guichet = 1 `microfinance.caisse.mouvement` » impose
  donc de passer par le module épargne pour la traçabilité ticket.

**Gardes/structure réutilisables de `register_operation`** (`microfinance_caisse_mouvement.py`) :
- garde session ouverte `:88-89` (`session.exists() and session.state == 'open'`) ;
- garde cohérence agence `loan.company_id == session.company_id` (`:107-108` pour
  `remboursement_credit`, `:127-128` pour `decaissement_credit` ; `:99-100` pour l'épargne) ;
- helper `_run_posting_sudo(record, session, method_name, *args, **kwargs)` (`:53-79`, ajouté
  au Lot 1.1bis) : `record.ensure_one()`, re-vérifie `record.company_id == session.company_id`
  (`:73-74`), puis `getattr(record.sudo(), method_name)(*args, **kwargs)` — exécute la méthode
  comptabilisante en `sudo()` —
  conçu pour `action_post` / `action_disburse` / `_create_transaction`. `action_charge_fee`
  est du même genre (poste des `account.move`, écrit `fee_paid`), donc **candidat au même
  passage `_run_posting_sudo`** — mais `action_charge_fee` fait aussi un `env.cr.execute(...
  FOR UPDATE)` : à valider que l'exécution sous `sudo()` ne perturbe pas le verrou (le curseur
  est le même, le `sudo` ne change que l'utilisateur — a priori sans impact, à confirmer).
- traçabilité : champs `payment_id` / `savings_transaction_id` sur `microfinance.caisse.mouvement`
  (`:50-51`). **Aucun champ `fee_move_id` / `loan_id` dédié frais** — un type `frais_dossier`
  aurait besoin de tracer vers `loan.fee_move_id` (le `loan_id` existe déjà `:39`).

---

## 6. Agence / `company_id`

- `fee_amount_due` (`microfinance_loan.py:229`), `fee_paid` (`:230`), `fee_payment_state`
  (`:243`), `fee_receivable_move_id` (`:237`), `fee_move_id` (`:239`) : **tous des champs
  directs de `microfinance.loan`**. `microfinance.loan.company_id` (`:46`, `required=True`,
  `default=lambda self: self.env.company`) les couvre. `ir.rule` multi-société sur
  `microfinance.loan` : `security/microfinance_company_rules.xml`
  (`domain_force=[('company_id','in',company_ids)]`, `groups` vide — cf.
  `docs_dev/guichet_caisse/AUDIT.md §5.1`).
- Les comptes et journaux de frais sont sur `microfinance.loan.product`, qui a son propre
  `company_id` (`microfinance_loan_product.py:386`, `required=True`) et des domaines
  `('company_id', '=', company_id)` sur `account_fee_receivable_id`,
  `account_commission_credit_id`, `fee_journal_id`, `fee_engagement_journal_id`.
- Aucune contrainte `@api.constrains` ne vérifie `loan.company_id == product.company_id`
  (même constat que pour `officer_id` / `partner_id.company_id` dans les audits précédents).

---

## 7. Tests existants (base de non-régression)

**Un seul fichier : `microfinance_loan_management/tests/test_fee.py`, classe `TestFee`.**

`setUpClass` (`:9-41`) : crée un compte `fee_receivable_account` (`asset_current`,
`reconcile=True`), un journal OD, et un produit avec
`fee_journal_id = disbursement_journal`, `fee_engagement_journal_id = od_journal`,
`account_fee_receivable_id`, `account_commission_credit_id`.

| Test | Ligne | Couvre |
|---|---|---|
| `test_fee_amount_fixed` | 43 | `fee_amount_due` (fixe) |
| `test_fee_amount_percentage` | 48 | `fee_amount_due` (%) |
| `test_fee_payment_state_badge` | 53 | `fee_payment_state` : `none` / `unpaid` / `paid` (via `action_charge_fee`) |
| `test_disburse_blocked_when_fee_unpaid_and_required` | 67 | blocage `action_disburse` si frais impayés |
| `test_disburse_allowed_when_fee_not_required` | 73 | décaissement OK si `fee_charged_before_disbursement=False` |
| `test_charge_fee_generates_move_and_unblocks_disbursement` | 79 | engagement (208005/717003) + règlement (caisse/208005) + lettrage + `fee_paid` + déblocage décaissement |
| `test_fee_engagement_skipped_when_fee_netted` | 113 | pas d'engagement si frais nettés |
| `test_charge_fee_retrofits_missing_engagement` | 121 | rattrapage engagement dans `action_charge_fee` |
| `test_fee_settlement_falls_back_to_commission_when_product_unconfigured` | 142 | repli crédit 717003 si produit non configuré Option A |
| `test_charge_fee_twice_blocked` | 159 | 2ᵉ `action_charge_fee` → `UserError` |
| `test_charge_fee_concurrent_guard_no_double_move` | 166 | **verrou `FOR UPDATE` + `invalidate_recordset`** : aucune 2ᵉ écriture |
| `test_net_disbursed_amount_equals_loan_amount_when_fee_charged_separately` | 194 | `net_disbursed_amount` (frais séparés) |
| `test_disburse_nets_fee_in_single_move` | 199 | `net_disbursed_amount` + écriture de décaissement nette |
| `test_fee_frozen_from_approval` | 221 | `_FEE_FROZEN_STATES` / `_compute_fee_amount` |

**Aucun test** ne fait passer les frais par une session de caisse / `register_operation` /
`microfinance.caisse.mouvement` (recherche `caisse` dans `test_fee.py` → 0). Toute
modification devra donc **ajouter** la couverture du chemin caisse sans casser ces 14 tests.

---

## 8. Questions bloquantes pour l'implémentation

1. **Rôle exact du bouton `action_charge_fee` après le changement.** Le prompt dit qu'il doit
   « faire apparaître le dossier dans un onglet Frais du guichet ». Or aujourd'hui le bouton
   *comptabilise*. Devient-il : (a) un simple marqueur (nouveau champ/état « à encaisser en
   caisse ») sans effet comptable, la comptabilisation étant déplacée dans le chemin caisse ?
   (b) supprimé, l'onglet Frais étant peuplé par un pur domaine
   (`state == 'approved' and not fee_paid and fee_amount_due > 0`) sans action préalable ?
   Non déterminable depuis le code.

2. **Nouvel état « en attente d'encaissement caisse ».** GAP confirmé (§3) : faut-il ajouter
   une valeur à `fee_payment_state` (`pending_cashier` ?), un champ booléen distinct, ou se
   contenter du domaine `approved + not fee_paid + fee_amount_due > 0` (qui inclut aussi les
   dossiers jamais présentés en caisse) ? Impact sur le badge de la fiche crédit
   (`microfinance_loan_views.xml:242-246`) et sur `_compute_fee_payment_state` à trancher.

3. **Journal de l'écriture de règlement dans le chemin caisse.** Aujourd'hui
   `product.fee_journal_id` (par produit, défaut `CRE`). En caisse, faut-il utiliser
   `session.journal_id` (journal de caisse de la session, comme `remboursement_credit` /
   `decaissement_credit`), ou conserver `product.fee_journal_id` ? Les deux peuvent diverger.
   Le compte de trésorerie débité changerait en conséquence
   (`session.journal_id.default_account_id` vs `product.fee_journal_id.default_account_id`).

4. **Verrou `FOR UPDATE`.** Doit être reproduit dans le nouveau chemin (§4). À confirmer :
   posé dans `register_operation` (module épargne) sur la table `microfinance_loan`, ou
   `action_charge_fee` reste la méthode qui poste (appelée depuis `register_operation`) et
   garde son verrou tel quel ? Compatibilité `env.cr.execute("... FOR UPDATE")` sous
   `_run_posting_sudo` (sudo) à vérifier.

5. **Rattrapage d'engagement** (`_is_fee_engagement_applicable` → `_prepare_fee_receivable_move`,
   journal OD). Conservé dans le chemin caisse (une écriture OD non-trésorerie créée pendant
   une opération de caisse) ? Ou pré-condition : refuser l'opération caisse si l'engagement
   n'existe pas et renvoyer vers l'approbation ?

6. **Lettrage engagement ↔ règlement** sur `account_fee_receivable_id` (si `reconcile=True`) :
   à préserver à l'identique dans le chemin caisse (sinon le solde du 208005 ne reflète plus
   les créances réellement ouvertes).

7. **Type `frais_dossier` sur `microfinance.caisse.mouvement`.** Placement acté côté
   `microfinance_savings_management` (§5, dépendance légale) ? Champs nécessaires : `loan_id`
   existe déjà ; faut-il un `fee_move_id` (traçabilité vers `loan.fee_move_id`) sur
   `microfinance.caisse.mouvement`, sur le modèle de `payment_id` / `savings_transaction_id` ?

8. **Montant.** Les frais sont un montant figé (`fee_amount_due`), non saisi au pavé
   numérique. Comme `decaissement_credit` (qui ignore la saisie et prend
   `net_disbursed_amount`), l'onglet Frais doit-il ignorer le numpad et prendre
   `fee_amount_due` ? Le pavé numérique reste-t-il visible/désactivé sur cet onglet ?

9. **Groupe / accès.** `action_charge_fee` est aujourd'hui réservé à
   `group_microfinance_finance` (bouton `microfinance_loan_views.xml:72`). Le guichet est
   utilisé par `group_microfinance_cashier`. Le caissier doit-il pouvoir encaisser les frais
   (élargissement d'accès), ou l'onglet Frais est-il visible mais l'action réservée ? Note :
   le caissier n'a pas `create` sur `account.move` (cf.
   `docs_dev/guichet_caisse/STATUS_lot1.md` §1.1bis) → le chemin frais en caisse aurait le
   même besoin de `sudo()` ciblé que les autres opérations.

10. **Cas « frais nettés du décaissement »** (`fee_charged_before_disbursement == False`) :
    `fee_paid` n'est jamais mis à `True` (§3), `fee_payment_state` reste `unpaid` après
    décaissement. Ces dossiers doivent-ils apparaître dans l'onglet Frais du guichet
    (ils ne devraient pas — les frais sont déjà comptabilisés au décaissement) ? Le domaine
    de l'onglet doit donc probablement inclure `product_id.fee_charged_before_disbursement == True`.

11. **Multi-worker sur `register_operation`.** Au-delà du `FOR UPDATE` frais, `register_operation`
    n'a aujourd'hui aucun verrou de ligne pour `remboursement_credit` / `decaissement_credit` ;
    ajouter le verrou frais crée une asymétrie — hors périmètre de ce chantier mais à
    signaler.

---

*Audit réalisé le 2026-09-07. Lecture seule — aucune modification de code, de vue, de données
ou de sécurité, aucun commit.*
