# Audit — Readonly `amount` + smart button historique transactions (épargne)

Audit **lecture seule** (Lot 0). Aucune modification de code. Le Lot 1 sera scopé après
validation par Micka.

## TL;DR

- **Volet 1** (readonly `amount`) : gap réel, rien ne protège `amount` aujourd'hui, ni en
  vue ni côté serveur. Condition recommandée : `readonly="move_id"` (pas
  `state == 'posted'` — un cas réel existe où `state` redevient `'cancelled'` alors que
  `move_id` reste renseigné).
- **Volet 2** (smart button historique) : **existe déjà** — `action_view_transactions` +
  compteur `transaction_count` sur le formulaire du compte, plus un onglet « Transactions »
  intégré. Rien à créer. Manque juste la colonne « Écriture comptable » dans les deux
  listes.
- **Fiabilité move ↔ transaction** : vérifiée sur 100 % des transactions comptabilisées de
  SEFOR (5, dont un compte avec 2) — **aucune anomalie**, chaque transaction `posted` a un
  `account.move` réel, `posted`, montant identique, et le bon compte épargne en
  contrepartie. Une nuance sans gravité trouvée (label figé au nom du compte au moment de
  l'écriture, cf. §7).

---

## Volet 1 — Readonly `amount`

### 1. Champs exacts

`microfinance_savings_management/models/microfinance_savings_transaction.py` :

```python
amount = fields.Monetary(string='Montant', required=True)                              # ligne 26
...
state = fields.Selection([                                                              # ligne 34
    ('draft', 'Brouillon'), ('posted', 'Comptabilisé'), ('cancelled', 'Annulé'),
], string='État', default='draft', tracking=True)
...
move_id = fields.Many2one('account.move', string='Écriture comptable', readonly=True, copy=False)  # ligne 54
```

Aucun `readonly=` conditionnel sur `amount` en Python (le `readonly=True` de `move_id` ne
concerne que ce champ lui-même). En vue formulaire
(`microfinance_savings_transaction_views.xml`, form), `<field name="amount"/>` est
**inconditionnellement éditable**, y compris sur une transaction `posted`.

### 2. `move_id` vs `state == 'posted'` — lequel choisir ?

**`state` et `move_id` ne sont PAS strictement synonymes** — vérifié dans le code :

- `action_post()` (ligne 286-306) : seul point qui pose `state='posted'`, **toujours**
  dans le même `write()` que `move_id` (`vals = {'move_id': move.id, 'state': 'posted'}`,
  ligne 299). ⟹ `state == 'posted'` **implique toujours** `move_id` renseigné.
- **Mais l'inverse est faux** : `action_reject_cheque()` (ligne 342-369) fait passer une
  transaction de `state='posted'` à `state='cancelled'` (ligne 367) tout en **conservant
  `move_id`** (qui pointe alors vers le move d'origine, lui-même annulé via
  `move._reverse_moves(..., cancel=True)`). Donc une transaction `cancelled` peut très
  bien avoir `move_id` renseigné.

➡️ **Condition recommandée : `readonly="move_id"`**, pas `readonly="state == 'posted'"`.
Avec `state == 'posted'` comme condition, un chèque rejeté (`state` repasse à
`'cancelled'`) **redeviendrait éditable** alors qu'une écriture (annulée) existe toujours
dessous — contraire à l'objectif de la demande (« readonly dès qu'une écriture comptable
existe déjà »). `move_id` est la condition la plus fiable et la plus directe : elle
correspond mot pour mot à l'intitulé du champ affiché (« Écriture comptable »).

### 3. Protection serveur — absente aujourd'hui

Recherche de tout ce qui pourrait déjà bloquer une modification post-comptabilisation :

- **Aucun `def write(` sur `MicrofinanceSavingsTransaction`.**
- 4 `@api.constrains` existants, aucun ne porte sur une modification post-`move_id` :
  `_check_amount` (positivité uniquement), `_check_minimum_balance`,
  `_check_transaction_date_order`, `_check_withdrawal_limit` — tous des contrôles
  *métier* à la création/modification, pas des verrous d'immutabilité.

**Constat : un readonly de vue seul ne protégerait pas contre une écriture par API/import**
(comportement Odoo standard - `readonly=` en vue ne s'applique qu'à l'UI web). Le module a
déjà un pattern équivalent ailleurs à réutiliser comme référence :
`microfinance.loan._check_locked_dossier_fields()` / `_LOCKED_DOSSIER_FIELDS`
(`microfinance_loan_management/models/microfinance_loan.py`) — override de `write()` qui
lève une `ValidationError` si un champ verrouillé est modifié une fois le crédit dans un
état donné.

➡️ **Recommandation pour le Lot 1** : ajouter, en plus du readonly de vue, une garde
serveur du même type — override `write()` sur `microfinance.savings.transaction` levant
une `UserError`/`ValidationError` si `amount` (au minimum) est modifié alors que
`move_id` est déjà renseigné, sauf écriture système (même mécanisme de contexte que
`_check_locked_dossier_fields`, si un chemin légitime de correction existe).

### 4. Autres champs dans la même situation

Le gap n'est pas isolé à `amount`. En vue formulaire, **aucun** des champs suivants n'a de
readonly conditionnel aujourd'hui, alors qu'ils sont tout aussi figés par la logique
métier une fois l'écriture posée : `transaction_type`, `account_id` (« Compte épargne »),
`date`, `payment_method`. Modifier l'un d'eux après comptabilisation désynchronise
silencieusement la transaction de son `account.move` (montant/compte/type ne
correspondent plus à ce qui a été réellement comptabilisé) — exactement le même risque
que pour `amount`.

**Hors scope de cette demande** (qui porte explicitement sur `amount`), mais signalé tel
que demandé : à envisager d'étendre la même condition (`readonly="move_id"`) à ces 4
champs dans un lot dédié, plutôt que de ne traiter que `amount` et laisser les autres
librement modifiables sur une transaction déjà comptabilisée.

---

## Volet 2 — Smart button historique transactions du compte

### 5. État actuel — **le smart button existe déjà**

`microfinance_savings_management/models/microfinance_savings_account.py` :

```python
transaction_ids = fields.One2many('microfinance.savings.transaction', 'account_id', string='Transactions')  # l.46
transaction_count = fields.Integer(string='Nombre de transactions', compute='_compute_counts')               # l.47

def action_view_transactions(self):                                                                          # l.275
    self.ensure_one()
    return {
        'type': 'ir.actions.act_window', 'name': _('Transactions'), 'res_model': 'microfinance.savings.transaction',
        'view_mode': 'tree,form', 'domain': [('account_id', '=', self.id)], 'context': {'default_account_id': self.id},
    }
```

`microfinance_savings_management/views/microfinance_savings_account_views.xml` (l.54-56) :

```xml
<button name="action_view_transactions" type="object" class="oe_stat_button" icon="fa-money">
    <field name="transaction_count" widget="statinfo" string="Transactions"/>
</button>
```

Exactement le pattern demandé au point 6 de l'énoncé (déjà celui de
`action_view_savings_accounts` côté crédit) — **rien à créer**, le bouton est déjà en
place, à côté du bouton « Crédits » (`action_view_loans`).

**En plus** : un onglet « Transactions » intégré au formulaire du compte (l.86-96) avec
une liste readonly (`date`, `transaction_type`, `amount`, `payment_method`,
`state` en badge) — redondant avec le smart button mais déjà présent, pas dans le scope
de cette demande de le retirer.

### 6. Ce qui manque réellement : la colonne « Écriture comptable »

Ni la vue tree par défaut ouverte par le smart button
(`view_microfinance_savings_transaction_tree`, colonnes : date, account_id, partner_id,
transaction_type, amount, payment_method, cheque_state, state) ni l'onglet intégré
(colonnes : date, transaction_type, amount, payment_method, state) **n'affichent
`move_id`**. Impossible aujourd'hui de voir/cliquer l'écriture depuis la liste : il faut
ouvrir chaque transaction individuellement.

➡️ **Proposition (réponse au point 9 de l'énoncé)** : ajouter
`<field name="move_id"/>` :
- à la vue tree par défaut (`view_microfinance_savings_transaction_tree`) — impact global
  (tree générique réutilisée ailleurs, à vérifier qu'aucune autre vue n'en dépend avec un
  nombre de colonnes contraint) ; ou
- plus sûr et strictement local à la demande : dans l'onglet « Transactions » du
  formulaire compte (l.88-96), qui est un tree **inline** propre à cette vue — aucun
  risque de régression ailleurs. *Recommandé.*

Dans les deux cas, `move_id` étant un `Many2one` déjà `readonly=True`, il s'affichera
nativement comme lien cliquable vers la fiche `account.move` (même comportement que
documenté pour `fee_move_id` côté crédit, docs_dev/badges_fee_guarantee/).

### 7. Fiabilité move ↔ transaction — vérifiée sur SEFOR (100 % des transactions réelles)

Base SEFOR : **5 transactions au total**, toutes `deposit`/`posted` (aucune des autres
valeurs de `transaction_type` n'a encore été créée en réel, cf. lot précédent). Un seul
compte porte plusieurs transactions : **IS/I/000039** (2 transactions).

| Transaction | Compte | Montant | `move_id` | État move | Montant move | Compte sur le move | Cohérent ? |
|---|---|---|---|---|---|---|---|
| 263 | IS/I/000039 | 500 000 | 863 (EPG/2026/00001) | posted | 500 000 | IS/I/000039 | ✅ |
| 264 | IS/I/000039 | 50 000 | 1007 (EPG/2026/00002) | posted | 50 000 | IS/I/000039 | ✅ |
| 265 | IS/I/000040 | 50 000 | 1008 (EPG/2026/00003) | posted | 50 000 | IS/I/000040 | ✅ |
| 758 | IS/I/002721 | 100 000 | 1976 (EPG/2026/00004) | posted | 100 000 | IS/I/002721 | ✅ |
| 759 | IS/I/000041 | 100 000 | 1982 (EPG/2026/00005) | posted | 100 000 | IS/I/000041 | ✅ |

Pour chacune : `move.microfinance_savings_account_id` pointe bien vers le **même** compte
que `transaction.account_id`, `move.amount_total == transaction.amount`, move réellement
`posted` (pas de move fantôme en brouillon). Lignes du move 1982 (IS/I/000041) contrôlées
en détail : débit 101000 (Espèces) 100 000 / crédit 213001 (compte d'épargne à régime
spécial) 100 000 — équilibré, comptes cohérents avec un dépôt.

**Aucune transaction `posted` sans move, aucun montant divergent, aucun compte
incohérent.** ✅ Aucune anomalie à remonter au sens du point 8 de l'énoncé (liste vide).

### Nuance trouvée (sans gravité, à connaître) — libellé figé au nom du compte

Les `ref`/`name` des lignes de move 863 et 1007 affichent **« Dépôt épargne
IS/I/000400 »**, alors que le compte s'appelle aujourd'hui **IS/I/000039**. Ce n'est
**pas une incohérence de données** : le compte 141 a été **renommé** `IS/I/000400` →
`IS/I/000039` le 2026-08-31 (tracé dans le chatter du compte, `mail_tracking_value`),
**après** la création des moves 863/1007 (2026-08-16). `_prepare_transaction_move()`
construit le libellé via `_('Dépôt épargne %s') % account.name` (ligne 210) — une chaîne
figée au moment de la création du move, pas un champ lié en direct : comportement normal
et souhaitable en comptabilité (on ne réécrit jamais le texte d'une écriture déjà postée
au fil des renumérotations ultérieures).

➡️ **Ne rien corriger** (les libellés historiques doivent rester tels quels). C'est
justement un argument de plus pour la recommandation du §6 : exposer `move_id`
(nom + lien réel, toujours à jour) en plus du texte figé, pour qu'un utilisateur qui
consulte l'historique ne se fie pas uniquement au libellé de l'écriture s'il cherche le
compte par son numéro actuel.

---

## Récapitulatif des propositions pour le Lot 1

| # | Proposition | Fichier |
|---|---|---|
| 1 | `amount` → `readonly="move_id"` en vue formulaire | `views/microfinance_savings_transaction_views.xml` |
| 2 | Garde serveur (override `write()`) bloquant la modification de `amount` une fois `move_id` renseigné, sur le modèle de `_check_locked_dossier_fields` | `models/microfinance_savings_transaction.py` |
| 3 | *(signalé, hors scope explicite)* Étendre potentiellement le même readonly à `transaction_type`/`account_id`/`date`/`payment_method` | idem |
| 4 | Ajouter `<field name="move_id"/>` à l'onglet « Transactions » du formulaire compte (tree inline, sans impact ailleurs) | `views/microfinance_savings_account_views.xml` |
| 5 | *(optionnel)* Ajouter aussi `move_id` à la vue tree générique `view_microfinance_savings_transaction_tree` | `views/microfinance_savings_transaction_views.xml` |
| — | Smart button du point 2 de l'énoncé | **déjà existant, rien à faire** |
| — | Anomalies move manquant | **aucune trouvée, rien à corriger** |

---

## Annexe — points d'entrée

| Élément | Emplacement |
|---|---|
| `amount` / `state` / `move_id` | `microfinance_savings_management/models/microfinance_savings_transaction.py:26,34,54` |
| `action_post` (state+move_id posés ensemble) | `microfinance_savings_transaction.py:286-306` |
| `action_reject_cheque` (state≠posted avec move_id conservé) | `microfinance_savings_transaction.py:342-369` |
| `_prepare_transaction_move` (construction du libellé figé) | `microfinance_savings_transaction.py:203-284` |
| Vue form transaction (`amount` sans readonly) | `views/microfinance_savings_transaction_views.xml:18-56` |
| Vue tree transaction (sans `move_id`) | `views/microfinance_savings_transaction_views.xml:3-16` |
| Smart button + compteur (compte) | `models/microfinance_savings_account.py:46-47,275-279` ; `views/microfinance_savings_account_views.xml:54-56` |
| Onglet « Transactions » intégré (compte) | `views/microfinance_savings_account_views.xml:86-96` |
| Pattern de verrou serveur de référence | `microfinance_loan_management/models/microfinance_loan.py` — `_check_locked_dossier_fields` / `_LOCKED_DOSSIER_FIELDS` |
| Échantillon vérifié | SEFOR — comptes `IS/I/000039` (2 transactions), `IS/I/000040`, `IS/I/002721`, `IS/I/000041` |
