# Audit — Transfert de fonds inter-agences

Audit **en lecture seule**. Aucune modification de code, de vue, de données ou de sécurité.
Aucun commit. État des lieux factuel : aucune solution d'implémentation n'est proposée ici.

Fichiers lus :

- `microfinance_loan_management/models/res_company.py`
- `microfinance_loan_management/models/res_partner.py`,
  `microfinance_savings_management/models/res_partner.py`
- `microfinance_loan_management/models/microfinance_loan.py` (extrait `create`),
  `microfinance_loan_management/models/microfinance_loan_account.py`,
  `microfinance_loan_management/models/microfinance_loan_payment.py`
- `microfinance_savings_management/models/microfinance_savings_account.py`,
  `microfinance_savings_management/models/microfinance_savings_transaction.py`
- `microfinance_savings_management/models/microfinance_caisse_mouvement.py`
- `microfinance_loan_management/models/microfinance_caisse_session.py`,
  `microfinance_loan_management/models/microfinance_caisse_fiche_journee.py`
- `microfinance_loan_management/models/microfinance_loan_product.py`,
  `microfinance_loan_management/models/microfinance_fond_credit.py`,
  `microfinance_loan_management/models/microfinance_fond_contribution.py`
- `microfinance_loan_management/hooks.py`
- `microfinance_loan_management/data/sequence.xml`,
  `microfinance_savings_management/data/ir_sequence_data.xml`
- `microfinance_loan_management/security/microfinance_company_rules.xml`,
  `microfinance_loan_management/security/microfinance_fond_bailleur_rules.xml`,
  `microfinance_loan_management/security/groups.xml`,
  `microfinance_savings_management/security/microfinance_company_rules.xml`,
  `microfinance_savings_management/security/savings_security.xml`,
  `microfinance_savings_management/security/ir.model.access.csv`
- `/opt/odoo17/odoo/addons/base/security/base_security.xml` (`res_partner_rule`)
- `/opt/odoo17/imf_git/plan_compta_pcec/` (template `mg_pcec`, CSV des comptes)
- `microfinance_loan_management/static/src/js/microfinance_caisse_pos.js`
- `microfinance_savings_management/wizard/microfinance_caisse_repayment_wizards.py`
- `docs_dev/guichet_caisse/AUDIT.md` (§5 isolation), `AUDIT_decaissement.md`,
  `AUDIT_cascade_remboursement.md`
- Tests : `test_multi_company.py` (×2), `test_caisse_pos.py`, `test_caisse_security.py`,
  `test_caisse_session_security.py`, `test_cheque_workflow.py`,
  `test_savings_transaction_split_amounts.py`, `test_fond_bailleur.py`

---

## 1. Conventions de numérotation existantes

### 1.1 Mécanisme central : `res.company._get_or_create_numbering_sequence`

`microfinance_loan_management/models/res_company.py:34-52` :

```python
def _get_or_create_numbering_sequence(self, code, padding=6):
    self.ensure_one()
    Sequence = self.env['ir.sequence'].sudo()
    sequence = Sequence.search([('code', '=', code), ('company_id', '=', self.id)], limit=1)
    if not sequence:
        sequence = Sequence.create({
            'name': '%s (%s)' % (code, self.name),
            'code': code, 'company_id': self.id,
            'padding': padding, 'number_next': 1, 'number_increment': 1,
        })
    return sequence.next_by_id()
```

- **Une `ir.sequence` dédiée par (société, `code`)**, créée **à la demande** au premier
  appel — jamais pré-déclarée en XML (docstring `:37-39` : jusqu'à 25 agences ajoutées
  manuellement au fil de l'eau, aucune liste figée possible). `sudo()` sur `ir.sequence`.
- Retour = **numéro seul**, déjà complété à `padding` zéros (`next_by_id()` ; les séquences
  créées ici n'ont **ni `prefix` ni `suffix`** — le préfixe agence est concaténé côté
  appelant).
- `padding` par défaut **6** (surchargé par appelant si besoin — aucun appelant actuel ne le
  surcharge).

### 1.2 Le « préfixe agence » : `res.company.agency_code`

`res_company.py:9-19` :

```python
agency_code = fields.Char(string='Code agence', size=3, required=True, help="...ex. IS pour Isotry...")
_sql_constraints = [('agency_code_unique', 'unique(agency_code)', "Le code agence doit être unique par société.")]
```

- **Champ sur `res.company`**, `required=True` (NOT NULL en base) **et** contrôle métier
  explicite en `create` (`:27-29`, `ValidationError` si absent) **et** en `write`
  (`:122-124` : interdit de le vider). `size=3` → 2 ou 3 caractères (`IS`, `DB`).
- **Unicité globale** garantie par `_sql_constraints` (`unique(agency_code)`).
- Amorçage des agences historiques : `hooks.py:136-159` (`_seed_known_agency_codes`, liste
  `KNOWN_AGENCY_CODES` en dur pour les agences déjà en base au moment de l'introduction du
  champ) + `hooks.py:726` appelé par `post_init_hook`.
- C'est le **seul** endroit où le préfixe agence est défini. Pas de mapping externe, pas de
  convention de nommage : lecture directe `company.agency_code`.

### 1.3 Les numéros existants, tous bâtis sur le même patron `AGENCE/SÉRIE`

| Numéro | Code de séquence | Format | Fichier:ligne |
|---|---|---|---|
| **Dossier de crédit** (`microfinance.loan.name`) | `microfinance.loan.agency` | `IS/000001` | `microfinance_loan.py:317-324` |
| **Numéro de compte client permanent** (`res.partner.microfinance_account_number`) | `microfinance.partner.account` | `IS/000001` | `res_partner.py:108-116` (module crédit) |
| **Remboursement** (`microfinance.loan.payment.name`) | `microfinance.loan.payment` | `IS/000001` | `microfinance_loan_payment.py:59-73` |
| **Compte crédit** conteneur (`microfinance.loan.account.name`) | `microfinance.loan.account` (repli) ou reprise du n° client | `IS/000001` | `microfinance_loan_account.py:31-72` |
| **Compte épargne** (`microfinance.savings.account.name`) | `microfinance.savings.account.<I\|G\|T>` (une séquence **par type**) | `IS/I/000001` | `microfinance_savings_account.py:113-122` |
| **Conteneur épargne** | reprend le n° client permanent, préfixé `I` | `IS/I/000001` | `microfinance_savings_account.py:88-104` |

Patron commun (toujours en Python, à la création, dans `@api.model_create_multi create`) :

```python
company = self.env['res.company'].browse(vals.get('company_id') or self.env.company.id)
number = company._get_or_create_numbering_sequence('<code>')
vals['name'] = '%s/%s' % (company.agency_code, number)     # ou '%s/%s/%s' avec un segment TYPE
```

- Le `name`/numéro est **`readonly`, `copy=False`**, généré **une seule fois** et **jamais
  régénéré** ensuite (commentaires explicites `microfinance_loan_payment.py:59-64`,
  `res_partner.py:100-107`).
- L'application de zéros de complétion vient de `ir.sequence.padding` (6), pas d'un `%06d`
  Python.
- Le compte épargne (`_get_next_available_savings_account_name`, `:119-123`) et le compte
  crédit (`microfinance_loan_account.py:47-72`) ajoutent une **boucle `while` anti-collision**
  (`search_count` sur le `name` candidat, on retire de la séquence jusqu'à trouver un libre) —
  garde-fou contre les doublons historiques, pas contre la séquence elle-même.

### 1.4 Séquences globales (contre-exemple)

`data/sequence.xml` et `data/ir_sequence_data.xml` ne contiennent plus que des séquences
**globales** (`company_id eval="False"`) : `microfinance.loan.product`,
`microfinance.fond.credit` (`FND/%(year)s/NNNNN`), `microfinance.savings.product`. Le
commentaire de `sequence.xml` précise que la numérotation `microfinance.loan` /
`microfinance.loan.application` / `microfinance.loan.payment` **a été retirée de ce fichier**
au profit de la séquence par société décrite en §1.1.

### 1.5 Pour le numéro d'ordre du code de transfert

Le patron à reproduire est **sans ambiguïté** : `company._get_or_create_numbering_sequence(
'<nouveau code>')` avec un `code` dédié (probablement deux : un compteur « sortant » côté
source et un « entrant » côté destination, ou un seul selon la conception — **non tranché
ici**), concaténé en Python. Le format cible `T/<n° compte client>/<préfixe source>/<n°
ordre>/<jj>/<mm>/<aa>/<préfixe dest>/<n° ordre>` (point 9 du prompt) **mélange deux numéros
d'ordre distincts** (un par agence) dans une seule chaîne — aucun numéro existant n'a cette
structure composite ; c'est une **nouveauté de patron** (les numéros actuels sont tous
`AGENCE/SÉRIE` mono-segment, éventuellement avec un segment TYPE). Voir §8 Q1.

---

## 2. Structure multi-société actuelle et contrainte d'isolation

> **Point le plus sensible de l'audit.** Règle projet non négociable (rappelée dans
> `docs_dev/guichet_caisse/AUDIT.md §5`, `AUDIT_decaissement.md`, et le commentaire d'en-tête
> de `microfinance_company_rules.xml`) : cloisonnement strict par société sur tous les modèles
> transactionnels, `groups=[]` (s'applique **à tous** les internes, managers et auditeurs
> compris).

### 2.1 `ir.rule` de cloisonnement en place

**`microfinance_loan_management/security/microfinance_company_rules.xml`** — toutes en
`domain_force=[('company_id', 'in', company_ids)]`, `groups eval="[]"` :
`microfinance.loan.product`, `microfinance.loan`, `microfinance.loan.account`,
`microfinance.loan.installment`, `microfinance.loan.payment`, `microfinance.loan.guarantee`,
`microfinance.guarantee.valuation.rule`, `microfinance.loan.reschedule.history` (+ `.line`
via `history_id.company_id`), `microfinance.collection.visit`,
`microfinance.caisse.fiche.journee`, `microfinance.caisse.session`,
`microfinance.caisse.comptage` (+ `.line` via `comptage_id.company_id`),
`microfinance.portfolio.snapshot`, `microfinance.client.blacklist` (via
`partner_id.company_id`).

**`microfinance_savings_management/security/microfinance_company_rules.xml`** — idem :
`microfinance.savings.product`, `microfinance.savings.account`,
`microfinance.savings.transaction`, **`microfinance.caisse.mouvement`**
(`related company_id = session_id.company_id`, store=True — `microfinance_caisse_mouvement.py:21`).

**`security/groups.xml:68-94`** — `microfinance.scoring.profile` / `.rule` / `.line`,
`microfinance.provision.rule` : même domaine, mais `groups` ciblés (user/manager/finance/
auditor).

**`res.partner`** : règle standard Odoo `base.res_partner_rule`
(`/opt/odoo17/odoo/addons/base/security/base_security.xml:12-19`) :

```xml
<field name="domain_force">['|', '|', ('partner_share', '=', False),
    ('company_id', 'parent_of', company_ids), ('company_id', '=', False)]</field>
```

`res.partner.partner_share` est calculé `store=True` (`/opt/odoo17/odoo/addons/base/models/
res_partner.py:388-393`) : `not partner.user_ids or not any(not user.share for user in
partner.user_ids)`. **Un client microfinance n'a aucun `user_ids` → `partner_share = True`.**
La règle se réduit donc, pour un client, à `company_id parent_of company_ids OR company_id =
False`. Un client de l'agence B (`company_id = B`) n'est **pas** `parent_of [A]` (agences
CEFOR sœurs, pas de hiérarchie) → **invisible à un utilisateur de l'agence A**, au niveau du
`res.partner` lui-même, indépendamment de tout domaine applicatif.

### 2.2 `company_ids` ≠ société active (nuance déjà documentée)

`AUDIT.md §5.2` : dans un `domain_force`, `company_ids` = **toutes** les sociétés autorisées
de l'utilisateur (`res.users.company_ids`), pas la société cochée. Le rétrécissement à la
société active passe par `allowed_company_ids` (sélecteur), **honoré par les vues
list/act_window mais pas par les `orm.call` d'une `ir.actions.client`** — le guichet compense
en passant partout un `company_id` explicite issu de `session.company_id[0]`
(`AUDIT.md §5.3`). Conséquence : un utilisateur **mono-agence** (cas normal du caissier) est
de fait borné à son agence par `company_ids`; un utilisateur **multi-agences** (manager /
auditeur régional) verrait déjà, via une méthode qui omet le filtre explicite, les données de
toutes ses agences.

### 2.3 Recherche de précédents « deux sociétés à la fois » sur un modèle transactionnel

**Aucun modèle transactionnel du projet n'est aujourd'hui visible par deux agences
nommément.** Deux patrons alternatifs existent, ni l'un ni l'autre équivalent au besoin du
transfert (source ET destination) :

1. **Partage optionnel « une société OU global »** —
   `microfinance_fond_bailleur_rules.xml:16-30` :
   ```xml
   <field name="domain_force">['|', ('company_id', 'in', company_ids), ('company_id', '=', False)]</field>
   ```
   Concerne `microfinance.fond.credit` et `microfinance.fond.contribution`. Le commentaire
   d'en-tête (`:6-15`) qualifie explicitement ce patron de **« PREMIÈRE occurrence dans ce
   module d'un partage optionnel »** et **demande de ne pas le "corriger" en audit
   multi-société** : `company_id = False` = fonds `scope='multi_company'`, visible de
   **toutes** les agences. Ce n'est pas « A et B » mais « A seule » ou « tout le monde »
   (`microfinance_fond_credit.py:24-32`, `_check_scope_company` `:138-145` : `multi_company`
   ⇒ `company_id` **obligatoirement vide**).

2. **Deux `company_id` sur un même enregistrement, l'un "propriétaire" l'autre "de saisie"** —
   `microfinance_fond_contribution.py:44-56` :
   - `company_id` = `related='fond_id.company_id'`, `store=True` (société du fonds, **vide**
     si fonds multi-agences) ;
   - `saisie_company_id` = `Many2one('res.company')`, `required=True`,
     `default=lambda self: self.env.company`, **figé après création** (`write` override
     `:63-70`) — « société ayant réellement effectué le mouvement ».
   C'est le précédent **le plus proche** conceptuellement d'un transfert (une agence agit sur
   un objet dont la société « propriétaire » est autre), mais : (a) `company_id` y est
   `related` d'un parent, pas un second champ libre ; (b) l'`ir.rule` appliquée
   (`microfinance_fond_contribution_company_rule`) borne sur `company_id` (le fonds), **pas**
   sur `saisie_company_id` — donc une contribution d'un fonds `single_company` de l'agence A
   saisie par A reste invisible à B, et une contribution d'un fonds multi-agences est visible
   de tous par la branche `company_id = False`. **Aucune règle ne combine `company_id` et
   `saisie_company_id`.**

**Aucun `company_ids` (`Many2many` vers `res.company`) non-`related` sur un modèle
transactionnel** (`grep` : le seul `company_ids` manipulé dans le code applicatif est
`self.env.user.company_ids` / `self.env.companies`, et la variable `company_ids` injectée par
le moteur `ir.rule`).

### 2.4 Accès cross-agence d'un caissier aujourd'hui — état des lieux

- **Recherche client du guichet : strictement scopée `session.company_id`.**
  `search_caisse_clients` (`microfinance_savings_management/models/res_partner.py:127-140`) :
  ```python
  domain = [('microfinance_partner_type', '=', 'client'), ('company_id', '=', company_id)]
  ```
  `company_id` provient de `state.session.company_id[0]` côté JS
  (`microfinance_caisse_pos.js:193`), session chargée avec
  `["company_id", "=", this.company.currentCompany.id]` (`:79` et cf. `AUDIT.md §5.3`).
  **Double verrou** : (a) domaine applicatif explicite ; (b) `base.res_partner_rule` (§2.1)
  qui, pour un caissier mono-agence, exclut déjà tout client d'une autre agence. Confirmé par
  `test_caisse_pos.py::TestCaisseSearchClients::test_search_scoped_by_company` (`:39-44`).
- `get_client_accounts_summary` (`res_partner.py:143-180`) : filtre
  `a.company_id.id == company_id` / `l.company_id.id == company_id` (`:149, 152`) — même
  restriction.
- `register_operation` (`microfinance_caisse_mouvement.py:84-170`) : **chaque branche**
  (`depot_epargne`/`retrait_epargne`, `remboursement_credit`, `decaissement_credit`,
  `frais_dossier`) commence par `if <account|loan>.company_id != session.company_id: raise
  UserError(...)` (`:103, 111, 131, 145`).
- `_run_posting_sudo` (`:57-82`) : **re-vérifie** `record.company_id != session.company_id`
  **au plus près du bypass sudo** (`:77-81`, `UserError` sinon).
- Tests de non-fuite : `test_caisse_security.py`, `test_caisse_session_security.py`,
  `test_multi_company.py` (×2 : loan + savings) — vérifient qu'un utilisateur d'une agence ne
  voit ni les crédits, ni les journaux, ni les comptes, ni la liste noire d'une autre.

➡️ **Le flux guichet actuel est hermétiquement mono-agence, à quatre niveaux
superposés** (base rule `res.partner`, domaine applicatif, garde de branche, garde sudo). La
fonctionnalité de recherche cross-agence demandée (points 1-2 du prompt) **doit percer
spécifiquement le premier et le deuxième niveau, uniquement pour détecter « ce client
appartient à une autre agence » et proposer le wizard**, sans relâcher les gardes de branche
`register_operation` (`:111` interdit précisément un `remboursement_credit` sur un crédit
hors agence — le flux transfert doit passer par un chemin **distinct**, pas par cette
branche). Conception : §8.

---

## 3. `microfinance.caisse.mouvement` — extensibilité

### 3.1 Le `Selection` `type` actuel

`microfinance_savings_management/models/microfinance_caisse_mouvement.py:26-32` :

```python
type = fields.Selection([
    ('depot_epargne', 'Dépôt épargne'),
    ('retrait_epargne', 'Retrait épargne'),
    ('remboursement_credit', 'Remboursement crédit'),
    ('decaissement_credit', 'Décaissement crédit'),
    ('frais_dossier', 'Frais de dossier'),
], string='Type', required=True)
```

### 3.2 Structure du modèle (champs de lien)

| Champ | Type | Renseigné pour |
|---|---|---|
| `session_id` | M2o `microfinance.caisse.session`, `required`, `ondelete='restrict'` | tous |
| `company_id` | `related='session_id.company_id'`, **store=True** | tous (porte l'`ir.rule` de cloisonnement) |
| `cashier_id` | M2o `res.users`, `required`, `default=env.user` | tous |
| `partner_id` | M2o `res.partner`, `required` | tous |
| `amount` | Monetary, `required` | tous |
| `savings_account_id` | M2o `microfinance.savings.account` | `depot_epargne` / `retrait_epargne` |
| `loan_id` | M2o `microfinance.loan` | `remboursement_credit` / `decaissement_credit` / `frais_dossier` |
| `interest_amount` / `principal_amount` / `penalty_amount` | Monetary | `remboursement_credit` (reflet de `payment.allocated_*`) |
| `payment_id` | M2o `microfinance.loan.payment`, `readonly`, `copy=False` | `remboursement_credit` |
| `savings_transaction_id` | M2o `microfinance.savings.transaction`, `readonly`, `copy=False` | `depot_epargne` / `retrait_epargne` |
| `fee_move_id` | M2o `account.move`, `readonly`, `copy=False` | `frais_dossier` |

Commentaire `:36-38` : « l'un ou l'autre [`savings_account_id`/`loan_id`], jamais les deux —
pas de contrainte de cohérence ici : les méthodes du Lot 3, seules créatrices, savent quel
champ remplir ». Idem `:49-50` pour `payment_id`/`savings_transaction_id`/`fee_move_id` :
**« un seul des trois renseigné selon `type`, jamais plusieurs »** — c'est une **convention
de code, pas une contrainte serveur**.

### 3.3 `register_operation()` — structure et gardes

`:84-170`, `@api.model`. Séquence invariante :

1. `session = browse(session_id)` ; `if not session.exists() or session.state != 'open':
   raise UserError` (`:91-93`).
2. `vals = {'session_id', 'type', 'partner_id', 'amount'}` (`:95-100`).
3. `if/elif` sur `type` — chaque branche : garde `company_id == session.company_id`, appel à
   la primitive métier existante (via `_run_posting_sudo` pour l'étape comptabilisante),
   `vals.update({...lien...})`.
4. `return self.create(vals)` (sauf `frais_dossier` qui `create` plus tôt `:163` pour
   pouvoir écrire `fee_move_id` en `sudo` `:166`).
5. `else: raise UserError('Type d'opération de caisse inconnu : %s')` (`:168-169`).

**Un nouveau `type` s'insère structurellement sans friction** dans ce `if/elif` (ajout d'une
branche + valeur au `Selection` + éventuel nouveau champ de lien). Points d'attention
factuels :

- Le modèle possède **déjà** `payment_id` **et** `savings_transaction_id` (`:51-52`), mais
  **aucun chemin de code ne remplit deux liens sur un même `mouvement`** — `register_repayment_confirmed`
  (`:221-286`, chemin cascade/surplus) crée **deux `mouvement` distincts** (un
  `remboursement_credit` + un `depot_epargne`) plutôt qu'un seul surchargé (commentaire
  `:233-234` : « décision actée : deux mouvements distincts »). Précédent net pour un flux qui
  génère plusieurs enregistrements métier.
- Aucune branche actuelle ne crée **directement** un `account.move` : toutes délèguent
  (`_create_transaction`, `microfinance.loan.payment.action_post`,
  `microfinance.loan.action_process_disbursement`, `microfinance.loan.action_charge_fee`). Un
  `type` transfert qui doit mouvementer la caisse et un compte de transit (§4) **n'a pas de
  primitive existante à déléguer** : soit une nouvelle primitive est créée sur un nouveau
  modèle, soit `register_operation` (ou une méthode sœur) poste elle-même le `move` — ce
  serait une première pour ce fichier (§8 Q3).
- `_run_posting_sudo` (`:57-82`) : le sudo est **délibérément circonscrit à
  `register_operation`** (docstring `:66-69`), le caissier n'ayant ni `create` sur
  `account.move` ni les droits d'écriture sur `microfinance.loan.installment`. Toute étape
  comptabilisante d'un flux transfert menée en identité caissier devra passer par un
  mécanisme sudo ciblé équivalent.

### 3.4 Modèle séparé — ce que dit l'existant (sans trancher)

Le prompt évoque un modèle `microfinance.transfert.inter.agence` distinct, avec lien vers
`caisse.mouvement`. Éléments factuels qui pèsent dans ce sens :

- `microfinance.caisse.mouvement` est **une ligne de ticket de session**
  (`_description = 'Mouvement de caisse (ligne de ticket guichet)'`, `_order = 'id desc'`),
  rattachée à **une** session ouverte, sans état propre, sans cycle de vie. Un transfert a un
  **cycle de vie multi-étapes** (encaissé source → en transit → rapatrié → validé
  destination) qui s'étale sur **deux sessions de deux agences** et **plusieurs jours** — hors
  du modèle de données d'une ligne de ticket.
- Le cloisonnement de `caisse.mouvement` est `company_id = session_id.company_id` (une seule
  agence). Un objet visible source **et** destination ne peut pas y vivre tel quel (§2.3).
- Précédent structurel du « conteneur au-dessus des instances » :
  `microfinance.loan.account` (`microfinance_loan_account.py:1-24` : « conteneur léger …
  volontairement sans solde/état/transactions tant qu'aucune logique métier n'a été
  demandée »). Un modèle transfert serait au contraire **riche en état**.
- Le groupement « plusieurs transferts vers la même agence destination en un lot, chaque
  transaction gardant son numéro » (point 5 du prompt) implique une relation
  **lot 1—N transferts** — deux modèles (`...transfert` + `...transfert.lot` ou `.batch`),
  aucun équivalent existant.

**Rien dans le code n'impose ni n'interdit un modèle séparé** — c'est une décision de
conception (§8 Q2).

---

## 4. Plan comptable — compte de transit

### 4.1 Comment les comptes PCEC sont structurés par société

- **Plan de comptes = `account.chart.template` `mg_pcec`** (module `plan_compta_pcec`,
  `models/template_pcec.py`, décorateur `@template('mg_pcec')`). Données comptes :
  `plan_compta_pcec/data/template/account.account-mg_pcec.csv` (colonnes
  `id,name,code,account_type,reconcile`).
- Système de chart template **Odoo 17** : à l'installation du plan sur une société, **chaque
  compte du CSV est copié pour cette société** (`account.account.company_id` est requis en
  Odoo 17). Donc **chaque agence CEFOR possède son propre jeu complet de comptes**, avec les
  mêmes `code`. C'est ce que confirment tous les défauts calculés du module :
  `microfinance_loan_product.py:6-16` (`_pcec_default`) et `:19-27` (`_journal_default`)
  cherchent **`[('code', '=', code), ('company_id', '=', self.env.company.id)]`** — jamais un
  `ref()` XML statique (commentaire `:7-10` : « les comptes PCEC sont dupliqués par société
  via le chart template »).
- `hooks.py:716-725` (`post_init_hook`) : pour **chaque** `res.company` dont
  `chart_template == 'mg_pcec'` (`:722`), crée des sous-comptes dédiés + **7 journaux
  standards par société** (`_create_journals` `:123-133`, liste `JOURNALS` `:77-85` :
  `BQOP, BQEP, BQCR, CAI, CRE, EPG, OD`), chacun avec `company_id = company.id` et un
  `default_account_id` recherché par `(code, company_id)`.
- **Tous les comptes de crédit/épargne du module sont donc des comptes par société**
  (`account_principal_*`, `account_interets_*`, `account_penalites_id`,
  `account_fee_receivable_id` = `_pcec_default('208005')`, etc. —
  `microfinance_loan_product.py:159-336`). Les écritures de remboursement
  (`microfinance_loan_payment.py:167-195`, `_prepare_payment_move`) débitent
  `self.journal_id.default_account_id` (caisse de l'agence du crédit) et créditent les comptes
  principal/intérêt/pénalité **de cette même agence**.

### 4.2 Comptes « de liaison » déjà présents dans le PCEC (non utilisés par le module)

`account.account-mg_pcec.csv` :

| `id` | `name` | `code` | `account_type` | `reconcile` |
|---|---|---|---|---|
| `pcec_196` | Pertes de valeur sur opérations internes de trésorerie - réseau | `196000` | `asset_current` | False |
| `pcec_301` | **Opérations entre siège et succursales/agences** | `301000` | `asset_current` | **True** |
| `pcec_302` | **Opérations entre succursales/agences** | `302000` | `asset_current` | **True** |
| `pcec_335` | Virements internes | `335000` | `asset_current` | True |
| `pcec_336` | Comptes de liaison - encaissement | `336000` | `asset_current` | True |
| `pcec_503` | Comptes de liaison - Produits/charges différés | `503000` | `liability_current` | False |

- `grep` sur les deux modules : **aucun de ces comptes n'est référencé** aujourd'hui
  (`301000/302000/335000/336000/pcec_301...` : 0 occurrence hors CSV/doc PCEC). `pcec_302`
  « Opérations entre succursales/agences » correspond **littéralement** au besoin fonctionnel
  « Fonds en transit inter-agences », et `301/302/335/336` sont marqués `reconcile=True` (donc
  aptes au lettrage source↔destination).
- `template_pcec.py:35` : `'transfer_account_code_prefix': '335'` — le compte de virement
  interne standard Odoo (utilisé par le rapprochement bancaire natif, `account_journal_
  suspense_account_id = 'pcec_335'` `:37`). **Déjà réservé par le cœur Odoo** à un autre usage
  (comptes d'attente de transfert de trésorerie), donc à ne pas détourner sans analyse.

### 4.3 Par société ou centralisé ?

**Le code ne tranche pas** (aucun compte de transit n'existe encore côté module). Faits qui
cadrent la question :

- **Structurellement, un `account.account` ne peut pas être « centralisé »** dans ce montage :
  `company_id` est requis, le plan est dupliqué par agence. Un « compte de liaison partagé »
  au sens strict (un seul `account.account` sans société) n'est **pas** un objet que produit
  le chart template `mg_pcec` ; il faudrait le créer hors template, ce qui casserait le patron
  `_pcec_default('<code>')` (recherche `(code, company_id)`).
- Le patron **déjà appliqué à 100 %** des comptes du module (trésorerie incluse) est
  **« un compte par agence, même code »** (§4.1). Un compte `302000` par agence CEFOR est
  l'option qui s'aligne sur l'existant : l'agence source débite **son** `302000`
  (créance sur le réseau), l'agence destination crédite **son** `302000` à réception, le
  rapprochement inter-agences se fait par lettrage/rapprochement manuel des deux `302000`
  homonymes (mécanisme comptable classique de comptes réciproques).
- L'autre option (un unique compte de liaison hors template, partagé) **n'a aucun précédent
  dans ce projet** et sort du système de chart template.

Décision (par société vs centralisé) + choix du code (`302000` existant, ou un `208xxx`/
`325xxx` dédié comme l'a fait `account_fee_receivable_id = 208005` pour les frais) : §8 Q4.

### 4.4 « Compte immédiatement dans le solde caisse de l'agence source »

Le « solde caisse » affiché au guichet (`microfinance_caisse_pos.xml:51-53`,
`state.session.closing_balance`) = `microfinance.caisse.fiche.journee.closing_balance`,
**calculé exclusivement depuis `account.move.line`** posées sur
`journal.default_account_id`, à la date du jour
(`microfinance_caisse_fiche_journee.py:92-125`, `_refresh_amounts`). Il **n'est pas** calculé
depuis les `microfinance.caisse.mouvement`. Donc « l'argent compte immédiatement dans le
solde caisse source » ⇒ le flux transfert-sortant **doit poster un `account.move`
comptabilisé qui débite le compte de caisse (`default_account_id`) du journal de la session
source**, dès l'encaissement — contrepartie = le compte de transit (§4.3). Le
`microfinance.caisse.mouvement` de type transfert n'est qu'une **trace de ticket**, sans
effet sur le solde.

---

## 5. `hr.employee` — disponibilité et structure

### 5.1 `hr` est une dépendance déclarée mais `hr.employee` n'est utilisé nulle part

- `microfinance_loan_management/__manifest__.py:11` : `'depends': [... 'hr' ...]` — présent
  **depuis le commit initial** (`git log -S"'hr'"` : un seul commit, « Initial commit »).
- `grep -rn "hr.employee" microfinance_loan_management/ microfinance_savings_management/` (hors
  tests) : **0 occurrence**. Aucun champ `Many2one('hr.employee', ...)`, aucun `_inherit`
  `hr.employee`, aucune vue. Les seules occurrences de « hr » sont la dépendance du manifest
  et des `<hr/>` HTML dans `report_contrat_credit.xml`.
- **La raison de la dépendance `hr` n'apparaît nulle part dans le code** — possible héritage
  historique / transitif (le module dépend aussi de `calendar`, `contacts`,
  `base_accounting_kit`). Aucune fonctionnalité observable ne la justifie. **Question ouverte
  factuelle** : la dépendance est-elle réellement nécessaire ? (Hors périmètre : ne pas la
  retirer sans analyse.)

### 5.2 Le patron « personne responsable d'une action » dans ce projet = `res.users`

**Tous** les champs de responsabilité pointent vers **`res.users`**, jamais `hr.employee` :

| Champ | Modèle | Fichier:ligne |
|---|---|---|
| `officer_id` (Agent crédit) | `microfinance.loan` | `microfinance_loan.py:102` |
| `manager_id` | `microfinance.loan` | `microfinance_loan.py:103` |
| `finance_user_id` | `microfinance.loan` | `microfinance_loan.py:104` |
| `collection_agent_id` (Agent recouvrement) | `microfinance.loan` | `microfinance_loan.py:105` |
| `officer_id` (related) | `microfinance.loan.payment` / `.installment` | `:45` / `:45` |
| `agent_id` (Agent terrain) | `microfinance.collection.visit` | `microfinance_collection_visit.py:13` |
| `officer_id` | `microfinance.portfolio.snapshot` | `microfinance_portfolio_snapshot.py:15` |
| `surveyor_id` (Enquêteur), `ca_responsible_id`, `agent_id` (VAD/VAV) | `microfinance.loan.application` | `microfinance_loan_application.py:63-64, 505-534, 1882` |
| `user_id` | `microfinance.loan.reschedule.history` | `:14` |
| `cashier_id` (Caissier) | `microfinance.caisse.mouvement` | `microfinance_caisse_mouvement.py:23-25` |
| `cashier_id` | `microfinance.caisse.session` | (module crédit) |

Ces champs servent aussi au **scope des rôles** (`_get_agent_portfolio_scope` compare
`user.id` à `officer_id`, `microfinance_loan.py:961`) et aux `groups` microfinance
(`security/groups.xml`), qui sont des **groupes `res.users`**.

➡️ **Il n'existe aucun patron `hr.employee` à réutiliser.** Le patron établi « personne
responsable » est `Many2one('res.users')`. Introduire `hr.employee` pour le coursier serait un
**nouveau patron** dans ce projet (même si la dépendance `hr` le permet techniquement).

### 5.3 Le coursier : employé de l'agence source ou tiers externe ?

**Le code ne dit rien** (le concept de coursier n'existe pas encore). Le prompt (point 5)
évoque « `hr.employee` **ou** partenaire dédié » et « société de transport de fonds »
possible. Aucun élément du code ne permet de trancher :

- si le coursier est **toujours** un salarié CEFOR de l'agence source → `hr.employee` (ou
  `res.users`, pour rester sur le patron §5.2) filtrable par société ;
- s'il peut être un **prestataire externe** (transporteur de fonds) → `res.partner` (avec un
  `microfinance_partner_type` dédié, ou un flag), car un tel prestataire n'est ni salarié ni
  utilisateur.

**Question ouverte — à ne pas deviner** (§8 Q5). Le prompt demande une « référence
structurée » : `hr.employee` a `company_id` (multi-société natif) ; `res.partner` a
`company_id` (mais règle de partage `base.res_partner_rule`, cf. §2.1) ; `res.users` a
`company_ids`.

---

## 6. Recherche cross-agence dans le guichet

### 6.1 Domaine actuel exact

`microfinance_savings_management/models/res_partner.py:127-140`, `@api.model` :

```python
def search_caisse_clients(self, query, company_id):
    domain = [('microfinance_partner_type', '=', 'client'), ('company_id', '=', company_id)]
    if query:
        domain += ['|', ('name', 'ilike', query), ('microfinance_account_number', 'ilike', query)]
    partners = self.search(domain, limit=20)
    return [{'id': p.id, 'name': p.name, 'account_number': p.microfinance_account_number} for p in partners]
```

Appelé par `microfinance_caisse_pos.js:184-200` (`refreshOtherClients`), debounce 300 ms,
`query.length >= 2`, avec `this.state.session.company_id[0]` — puis filtre côté client les
résultats déjà présents dans l'onglet actif (`otherClients` = « Autres clients »,
`microfinance_caisse_pos.js:36-40`, `:159`).

### 6.2 Les deux verrous à considérer (état des lieux, pas solution)

1. **Le domaine applicatif** : `('company_id', '=', company_id)` — borne dure à l'agence de
   la session.
2. **`base.res_partner_rule`** (§2.1) : même si le domaine applicatif était élargi, un
   `self.search(...)` exécuté **en identité caissier** ne retournerait **aucun** client d'une
   autre agence (`partner_share = True` + `company_id` de B pas `parent_of` [A]). La méthode
   est `@api.model` **non `sudo`**.

Donc « chercher aussi hors `session.company_id` » implique **au minimum** :
- lever le `('company_id','=', company_id)` (ou le remplacer par une logique explicite
  « agence de session OU autres agences ») **dans cette méthode uniquement** ;
- **et** un contournement de `base.res_partner_rule` (p. ex. `sudo()` ciblé sur la recherche,
  avec re-restriction manuelle au strict nécessaire) — sans quoi le résultat reste vide.

Le prompt insiste : la recherche élargie ne doit **servir qu'à détecter** « client d'une
autre agence » pour proposer le wizard, **pas** à donner un accès général cross-société aux
données de ce client (crédits, comptes, historique). `get_client_accounts_summary`
(`res_partner.py:143-180`) et toutes les branches de `register_operation` restent scopées
`session.company_id` (§2.4) : **ces méthodes-là ne doivent pas être élargies** ; le flux
transfert doit exposer **uniquement** ce dont le wizard a besoin (n° compte crédit, n°
dossier, nom client, date, agence — point 8 du prompt), sur un chemin dédié. Le « changement
minimal » exact et son périmètre de sudo : **conception, §8 Q6**.

### 6.3 Données demandées pour l'onglet « Transfert » (point 8) — disponibilité

| Colonne demandée | Source | Disponible ? |
|---|---|---|
| Numéro de compte crédit | `microfinance.loan.loan_account_id.name` (`microfinance_loan.py:47`) | Oui |
| Numéro de dossier crédit | `microfinance.loan.name` (`:25`, format `AGENCE/NNNNNN`) | Oui |
| Nom du client | `microfinance.loan.partner_id.display_name` | Oui |
| Date de l'opération | à porter par le futur modèle transfert (date d'encaissement source) | À créer |
| Agence | `microfinance.loan.company_id` (agence propriétaire) et/ou société source | Oui (côté crédit) |

---

## 7. Tests existants pertinents

### 7.1 Aucun test de transfert / inter-agence transactionnel

`grep -rn "transfer|transfert|inter.agence|inter_agence"` sur les deux dossiers `tests/` :

- **Aucun test** ne couvre un transfert de fonds entre agences, ni un modèle transactionnel
  visible par deux sociétés.
- `test_cheque_workflow.py:36` `test_clear_cheque_transfers_to_real_account` : « transfer » y
  désigne le passage d'un **compte d'attente chèque vers le compte épargne réel**, **au sein
  d'une même agence** — sans rapport.
- `microfinance.savings.transaction.transaction_type` a une valeur **`'transfer'` = « Virement
  entre comptes »** (`microfinance_savings_transaction.py:24`, dans `DEBIT_TYPES` `:8`,
  libellé « Virement épargne » `:247`). C'est un **virement entre deux comptes épargne d'un
  même client/agence**, **pas** un transfert inter-agences. `test_savings_transaction_split_
  amounts.py:26` l'exerce parmi les types de débit. **Collision de vocabulaire à connaître**
  (ne pas réutiliser ce type pour le flux inter-agences).

### 7.2 Tests d'isolation multi-société réutilisables comme base de non-régression

- `microfinance_loan_management/tests/test_multi_company.py` — `TestMultiCompanyIsolation` :
  domaines de comptes/journaux filtrés par société (`:35-77`), crédit/produit/compte/journal
  **non visibles** à un utilisateur d'une autre agence (`:90-125`), `company_id` client requis
  en contexte microfinance (`:126-146`), liste noire cloisonnée (`:148-160`).
- `microfinance_savings_management/tests/test_multi_company.py` — isolation épargne
  (comptes/transactions), isolation du compte épargne multi-société.
- `microfinance_savings_management/tests/test_caisse_pos.py` —
  `TestCaisseSearchClients::test_search_scoped_by_company` (`:39-44`) : **assertion directe
  que `search_caisse_clients` d'une agence ne retourne pas le client d'une autre**. Toute
  évolution de cette méthode devra faire évoluer ce test en conséquence (sans lever
  l'assertion pour les chemins non-transfert).
- `microfinance_loan_management/tests/test_caisse_security.py`,
  `test_caisse_session_security.py` — non-fuite du sudo `_run_posting_sudo`, cloisonnement
  session/mouvement.
- `microfinance_savings_management/tests/test_caisse_pos.py::test_pure_cashier_*` — exécution
  du chemin `_run_posting_sudo` sous un **caissier pur** (`group_microfinance_cashier` +
  `group_savings_agent`, sans droits comptables) — patron de test à reprendre pour un flux
  transfert mené par un caissier.

### 7.3 Tests de numérotation (patron à répliquer pour le n° de transfert)

- `microfinance_loan_management/tests/test_partner_account_number.py` — dérivation
  `AGENCE/NNNNNN` du n° de compte client permanent.
- `microfinance_savings_management/tests/test_savings_account_number_derivation.py`,
  `test_savings_principal_account_on_create.py` — dérivation `AGENCE/TYPE/NNNNNN`, séquence
  par type, réécrits lors du Lot 1.3.
- `test_agency_numbering.py` (×2), `test_product_code_sequence.py` /
  `test_product_code_sequence.py` — séquences par société / globales.

---

## 8. Questions bloquantes pour l'implémentation

1. **Format et génération du code de transfert.** Le format cible (point 9)
   `T/<n° compte client>/<préfixe source>/<n° ordre source>/<jj>/<mm>/<aa>/<préfixe dest>/
   <n° ordre dest>` combine **deux numéros d'ordre** (un par agence) dans une seule chaîne —
   aucun numéro existant du projet n'a cette forme composite (§1). Faut-il : (a) **deux
   séquences par société** (`microfinance.transfert.sortant` côté source,
   `microfinance.transfert.entrant` côté destination), le code final n'étant complété qu'à la
   validation destination ? (b) le « n° ordre dest » est-il connu dès l'encaissement source
   (placeholder `000` dans l'exemple `T/IS00000/IS/000/01/05/27/DB/000`) puis renseigné au
   rapatriement ? (c) `<n° compte client>` dans le code = `microfinance_account_number` du
   client **sans le `/`** (`IS00000` dans l'exemple, vs `IS/00000` stocké) — confirmer la
   règle de normalisation. (d) `padding` du n° d'ordre (l'exemple montre 3 chiffres `000`, le
   défaut projet est 6).

2. **Modèle séparé vs nouveau `type` sur `microfinance.caisse.mouvement`.** Le cycle de vie
   multi-étapes / multi-agences / multi-jours d'un transfert (§3.4) ne loge pas dans une
   « ligne de ticket de session ». Confirme-t-on un modèle dédié
   (`microfinance.transfert.inter.agence`) **plus** un modèle de lot de rapatriement
   (`...lot`), avec `microfinance.caisse.mouvement` conservé uniquement comme trace de caisse
   (type `transfert_sortant` à la source, `transfert_entrant` à la destination) reliée par un
   `Many2one` ? Ou un seul modèle transfert portant lui-même les deux effets de caisse ?

3. **Où et comment est posté l'`account.move`.** Aucune branche de `register_operation` ne
   crée aujourd'hui un `account.move` directement (§3.3) — toutes délèguent à une primitive.
   Le transfert-sortant n'a pas de primitive à déléguer. La comptabilisation (débit caisse
   source / crédit compte de transit) est-elle portée par une nouvelle méthode du modèle
   transfert, enveloppée dans un sudo ciblé équivalent à `_run_posting_sudo` (le caissier
   n'a pas `create` sur `account.move`) ? Idem pour la contre-passation/validation à la
   destination (débit compte de transit / crédit … quoi : caisse destination ? directement
   les comptes du crédit via un `microfinance.loan.payment` ?).

4. **Compte « Fonds en transit inter-agences » : par société ou centralisé, et quel code.**
   §4.3 : le montage chart-template impose de fait **un compte par agence** (même code) ;
   un compte unique partagé sortirait du patron `_pcec_default`. Utilise-t-on le compte PCEC
   **`302000` « Opérations entre succursales/agences »** déjà présent (`reconcile=True`), un
   compte dédié type `208xxx`/`325xxx` (comme `account_fee_receivable_id=208005` pour les
   frais), et où le paramètre est-il porté (champ sur `res.company` ? sur le produit de
   crédit ? constante) ? Le rapprochement des deux `302000` homonymes source/destination
   est-il manuel (lettrage) ou assisté ?

5. **Nature du coursier.** `hr.employee` (salarié CEFOR) ou `res.partner` dédié (prestataire
   externe de transport de fonds) — le prompt laisse les deux ouverts, le code n'a **aucun
   patron `hr.employee`** (§5.2, tout est `res.users`). Le coursier est-il nécessairement
   rattaché à l'agence source ? Peut-il varier d'un lot à l'autre ? (Ne pas deviner —
   demande explicite du prompt.)

6. **Périmètre exact du perçage de l'isolation pour la recherche.** §6.2 : élargir
   `search_caisse_clients` suppose de lever son filtre `company_id` **et** de contourner
   `base.res_partner_rule` (sudo ciblé). Quel périmètre : (a) la recherche cross-agence
   ne renvoie-t-elle que `{id, name, account_number, agency_name}` (assez pour proposer le
   wizard) sans jamais exposer crédits/comptes/historique du client via un chemin élargi ?
   (b) déclenche-t-on la recherche cross-agence **systématiquement en parallèle** de la
   recherche locale, ou seulement si la recherche locale ne trouve rien ? (c) le résultat
   cross-agence est-il visuellement distinct (« client d'une autre agence → transfert ») ?

7. **Détection automatique du cas transfert.** À quel moment le guichet bascule-t-il en mode
   transfert : dès que le client sélectionné a `company_id != session.company_id` ? Seulement
   si ce client a un **crédit actif** dans son agence propriétaire (le transfert ne vise que
   le remboursement crédit, point 10) ? Que se passe-t-il si le même nom/numéro existe dans
   plusieurs agences ?

8. **Validation destination = comptabilisation réelle du remboursement.** Point 7 du prompt :
   c'est à la saisie de la référence de transfert par le caissier destination que
   « l'écriture sur le crédit est comptabilisée ». Cela crée un `microfinance.loan.payment`
   sur le crédit (agence destination) — mais la contrepartie n'est **pas** la caisse
   (l'argent est arrivé par le coursier, pas au guichet destination) : c'est le compte de
   transit. Or `_prepare_payment_move` (`microfinance_loan_payment.py:167-195`) débite
   **toujours** `self.journal_id.default_account_id` (caisse). Faut-il un `journal_id`
   spécifique « transit » pour ce paiement, un post-traitement de l'écriture, ou un chemin de
   comptabilisation distinct de `microfinance.loan.payment` ? La cascade multi-échéances
   (`_allocation_plan`) et le garde « Surpaiement interdit » (`:147-148`) s'appliquent-ils
   tels quels ?

9. **Rôle et session côté destination.** L'onglet « Transfert » du guichet destination
   affiche les transferts en attente « automatiquement » (point 7). Ces transferts
   appartiennent à des sessions/agences **autres** que la session destination courante :
   quelle méthode les liste, sous quel scope (le modèle transfert doit être visible de
   l'agence destination — d'où la question §2.3 sur l'`ir.rule` d'un modèle bi-agences), et
   la validation exige-t-elle une **session de caisse destination ouverte** (comme toutes les
   autres opérations guichet, `register_operation:91-93`) même si aucun cash ne transite au
   guichet à ce moment ?

10. **Groupement en lot de rapatriement.** « Plusieurs transferts vers la même agence
    destination peuvent être groupés, chaque transaction gardant son n° » (point 5). Le lot
    porte-t-il une référence propre (séquence dédiée), le coursier, la date de remise, le
    montant acquitté total ? Un transfert peut-il être retiré d'un lot avant remise ? Le
    ticket imprimé (point 5) est au niveau lot ou au niveau transfert ?

11. **Extension épargne future (point 10).** Le modèle doit « garder l'extension possible »
    pour dépôt/retrait épargne inter-agence sans l'implémenter. Cela oriente-t-il vers un
    champ `operation_type` (`remboursement_credit` seul pour l'instant) sur le modèle
    transfert, et un lien polymorphe / deux `Many2one` optionnels (`loan_id`,
    `savings_account_id`) comme sur `microfinance.caisse.mouvement` ? Le code de transfert
    (§8 Q1) intègre `<n° compte client>` — resterait-il valable pour un compte épargne
    (`AGENCE/I/NNNNNN`) ?

12. **Dépendance `hr`.** Constat §5.1 : `hr` est déclaré dans le manifest depuis l'origine
    mais `hr.employee` n'est utilisé nulle part. Si le coursier devient un `hr.employee`, la
    dépendance trouve enfin un usage ; sinon, faut-il la conserver ? (Signalement, pas une
    action.)

---

*Audit réalisé le 2026-09-09. Lecture seule — aucune modification de code, de vue, de
données ou de sécurité, aucun commit.*
