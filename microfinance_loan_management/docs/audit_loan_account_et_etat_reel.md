# Audit — `microfinance.loan.account`, état réel des derniers lots, bug "Montant demandé"

Audit uniquement, aucune modification de code/vue/modèle/donnée effectuée. Toutes les
constatations ci-dessous sont vérifiées directement sur le dépôt et la base SEFOR au moment de
l'audit (2026-08-16), pas supposées.

## 1. Le modèle `microfinance.loan.account` ("Compte crédit")

### Fichier et module
- Modèle : `microfinance_loan_management/models/microfinance_loan_account.py`
- Vues : `microfinance_loan_management/views/microfinance_loan_account_views.xml`
- Tests : `microfinance_loan_management/tests/test_loan_account.py`
- Déclaré dans `microfinance_loan_management/models/__init__.py:10` (`from . import
  microfinance_loan_account`) et `microfinance_loan_management/__manifest__.py:41` (vue).

### Tous les champs (`microfinance_loan_account.py:11-19`)
```python
_name = 'microfinance.loan.account'
_description = 'Compte crédit microfinance (conteneur historique)'
_order = 'id desc'

name = fields.Char(string='Référence', default='Nouveau', copy=False, readonly=True, required=True)
partner_id = fields.Many2one('res.partner', string='Titulaire', required=True)
company_id = fields.Many2one('res.company', string='Société', default=lambda self: self.env.company, required=True)
loan_ids = fields.One2many('microfinance.loan', 'loan_account_id', string='Crédits')
loan_count = fields.Integer(compute='_compute_loan_count')
```
- `name` : Char, `readonly=True`, `default='Nouveau'`, jamais `required` au sens "l'utilisateur
  doit le saisir" — généré par `create()`.
- `partner_id` : Many2one `res.partner`, `required=True`.
- `company_id` : Many2one `res.company`, `required=True`, défaut société courante.
- `loan_ids` : One2many depuis `microfinance.loan.loan_account_id` (voir section suivante).
- `loan_count` : Integer, `compute='_compute_loan_count'`, non stocké.
- Contrainte SQL (`microfinance_loan_account.py:21-24`) :
  `_sql_constraints = [('partner_company_unique', 'unique(partner_id, company_id)', "Un client
  ne peut avoir qu'un seul compte crédit par société.")]` — **un seul compte crédit par client
  et par société**, jamais plusieurs.
- Aucun champ `state`, solde, plafond ou transaction — confirmé par la docstring du modèle
  elle-même (`microfinance_loan_account.py:6-10`) : *"conteneur léger... sans solde, sans
  transactions, sans statut, sans plafond — volontairement absent tant qu'aucune logique
  métier n'a été demandée dessus"*.

### Relation avec `res.partner`
- Champ réciproque sur `res.partner` : `microfinance_loan_account_ids` (One2many, `res_partner.py:132-133`) :
  ```python
  microfinance_loan_account_ids = fields.One2many(
      'microfinance.loan.account', 'partner_id', string='Compte crédit')
  ```
- Création : **jamais manuelle par l'utilisateur en pratique** (le menu dédié a `create="0"`,
  voir vues ci-dessous) — uniquement via `res.partner._get_or_create_microfinance_loan_account()`
  (`res_partner.py:148-161`), appelée depuis deux déclencheurs :
  1. `res.partner.create()` en contexte `microfinance_context` pour un client
     (`res_partner.py:394`).
  2. Rattrapage paresseux dans `microfinance.loan.create()` si `loan_account_id` est absent
     (`microfinance_loan.py:170-176` — commentaire : *"Rattrapage paresseux (cf. correctif
     microfinance.loan.account) : couvre aussi bien un client déjà en base avant l'introduction
     de ce modèle qu'un client créé hors microfinance_context"*).

### Relation avec `microfinance.loan`
- Champ porteur : `loan_account_id` sur **`microfinance.loan`** (pas l'inverse) —
  `microfinance_loan.py:38-46` :
  ```python
  loan_account_id = fields.Many2one(
      'microfinance.loan.account', string='Compte crédit', index=True,
      help="Conteneur regroupant l'historique des crédits de ce client (cf. correctif "
           "numérotation) — pas de logique métier dessus à ce stade. Non required : les "
           "crédits déjà en base avant l'introduction de ce modèle restent sans compte "
           "associé, résolu paresseusement au prochain crédit du même client via "
           "res.partner._get_or_create_microfinance_loan_account() plutôt qu'une migration "
           "globale (volume négligeable à ce jour, décision validée par Micka).",
  )
  ```
- **`ondelete`** : non spécifié explicitement → défaut Odoo `'set null'` pour un Many2one non
  `required`. **Pas de `required=True`** sur ce champ.
- Réponses directes aux questions posées :
  - Un crédit **peut** exister sans compte crédit associé (`loan_account_id` non required) —
    concerne les crédits déjà en base avant l'introduction du modèle.
  - Un compte crédit **peut** exister sans aucun crédit rattaché (`loan_ids` peut être vide) —
    rien ne l'empêche structurellement, bien qu'en pratique le seul chemin de création
    (`_get_or_create_microfinance_loan_account`) est déclenché soit à la création du client
    (aucun crédit encore), soit juste avant la création d'un crédit.
  - Onglet "Crédits" vu dans la capture d'écran = le champ `loan_ids` (One2many), affiché dans
    le formulaire (`microfinance_loan_account_views.xml`, page "Crédits").

### Relation avec `microfinance.loan.application`
- **Aucun champ direct** entre les deux modèles, dans aucun des deux sens — recherche
  exhaustive (`grep -n "loan_account" microfinance_loan_application.py` et `grep -n
  "loan_application\|application_id" microfinance_loan_account.py`) : aucun résultat dans les
  deux cas.
- Le seul rapprochement possible est **indirect, en deux sauts** :
  `microfinance.loan.application.loan_id` → `microfinance.loan` → `microfinance.loan.loan_account_id`
  → `microfinance.loan.account`. Aucune requête ORM native ne fait ce raccourci automatiquement.

### Numérotation (`name`)
Définie dans `create()` et `_get_loan_account_name()` (`microfinance_loan_account.py:31-58`) :
```python
@api.model_create_multi
def create(self, vals_list):
    for vals in vals_list:
        if vals.get('name', 'Nouveau') == 'Nouveau':
            partner = self.env['res.partner'].browse(vals.get('partner_id'))
            company = self.env['res.company'].browse(vals.get('company_id') or self.env.company.id)
            vals['name'] = self._get_loan_account_name(company, partner)
    return super().create(vals_list)

def _get_loan_account_name(self, company, partner):
    if partner.microfinance_account_number:
        candidate = partner.microfinance_account_number
        if not self.search_count([('name', '=', candidate)]):
            return candidate
    return self._get_next_available_loan_account_name(company)

def _get_next_available_loan_account_name(self, company):
    while True:
        number = company._get_or_create_numbering_sequence('microfinance.loan.account')
        candidate = '%s/%s' % (company.agency_code, number)
        if not self.search_count([('name', '=', candidate)]):
            return candidate
```
- **Cas normal** : reprend **directement** `partner.microfinance_account_number`
  (`res.partner`, format `AGENCE/NNNNNN`) — pas de séquence propre, pas de segment TYPE
  (contrairement à l'épargne qui insère I/G/T).
- **Repli** : séquence indépendante par société via
  `company._get_or_create_numbering_sequence('microfinance.loan.account')`, uniquement si le
  client n'a pas encore de `microfinance_account_number` au moment de l'appel.
- Conséquence directement vérifiée en base (section 3) : le nom d'un `microfinance.loan.account`
  est **littéralement identique** au numéro de compte permanent du client — une coïncidence de
  source commune, pas un lien entre les deux modèles.

### Historique git
```
git log --follow --oneline -- microfinance_loan_management/models/microfinance_loan_account.py
git log --follow --oneline -- microfinance_loan_management/views/microfinance_loan_account_views.xml
git log --follow --oneline -- microfinance_loan_management/tests/test_loan_account.py
```
→ **un seul résultat pour les trois fichiers** : `13a580c` — *"Restructure les workflows
crédit/dossier, réversion du point d'entrée unique, navigation crédit-épargne"*, committé le
2026-08-16 16:49:05 +0300.

Le modèle n'a **aucun historique antérieur** dans le dépôt git : il vivait uniquement dans
l'arbre de travail (non commité, comme tout le reste du chantier en cours) jusqu'à ce commit
unique qui a regroupé l'ensemble des lots traités dans la conversation, y compris ceux
antérieurs à l'introduction de ce modèle. Le commit ne documente donc pas *quand* le modèle a
été introduit dans le fil de la conversation, seulement quand il a été committé — cette
information n'est traçable que dans l'historique de conversation, pas dans git.

### Documentation existante le mentionnant
```
grep -rln "loan.account\|Compte crédit" microfinance_loan_management/docs/ docs_dev/ README.md USER_GUIDE_FR.md TECHNICAL_ANALYSIS_FR.md
```
→ **Aucun résultat** dans `README.md`, `USER_GUIDE_FR.md`, `TECHNICAL_ANALYSIS_FR.md`, ni dans
aucun fichier de `docs/`. Seule mention trouvée : `docs_dev/creation_credit_directe/STATUS.md`
(une phrase en passant sur `loan_account_id`, dans le contexte du retrait du verrou de création
— pas une documentation du modèle lui-même). **Ce modèle n'est documenté nulle part dans la
documentation utilisateur ou technique du module.**

---

## 2. État réel des derniers lots (vérifié sur le dépôt, pas supposé)

| Point | État | Preuve |
|---|---|---|
| `microfinance.loan.application.state` : 4 états ou 10 ? | **Appliqué** — cycle à 4 états | `microfinance_loan_application.py:79-84` : `[('draft','Brouillon'),('visite','Visite'),('contre_visite','Contre-Visite'),('fait','Fait')]` |
| `microfinance.loan.state` : `enquete`/`avis_ca`/`avis_cdag` (nouveau) ou `submitted`/`manager_validated`/`finance_validated` (ancien) ? | **Appliqué** — nouveau cycle | `microfinance_loan.py:70-81` : `[('draft',...),('enquete','Enquête'),('avis_ca','Avis CA'),('avis_cdag','Avis CDAG'),('approved',...),('active',...),('closed',...),('defaulted',...),('written_off',...),('cancelled',...)]` |
| Verrou de création `microfinance.loan.create()` | **Retiré** | `microfinance_loan.py:161-177` : `create()` ne contient plus aucun `raise UserError` lié à un contexte — seulement génération de référence + rattrapage `loan_account_id`. `grep -rn "microfinance_loan_creation_allowed" microfinance_loan_management/models/ microfinance_loan_management/views/` → aucun résultat. |
| Vues `view_microfinance_loan_*_readonly_create` (`create="0"` sur le menu Crédits) | **Retiré** | `grep -rn "readonly_create" microfinance_loan_management/views/microfinance_loan_views.xml` → aucun résultat. L'action `action_microfinance_loan` ne porte plus de `view_ids` personnalisés (vues génériques par défaut, sans restriction). |
| `requested_amount` : simple ou `related='loan_id.loan_amount'` ? | **Champ simple**, jamais lié à `loan_id` | `microfinance_loan_application.py:530` : `requested_amount = fields.Monetary(string='Montant demandé', tracking=True)` — pas de `related=`, pas de `compute=`. **Voir section 3, c'est la cause du bug.** |
| `required_savings`/`available_savings`/`period` : simples ou `related` ? | **Champs simples**, jamais liés à `loan_id` | `microfinance_loan_application.py:531,533,534` : `required_savings = fields.Monetary(string='Épargne exigée (demande)')`, `period = fields.Integer(string='Durée demandée (échéances)')`, `available_savings = fields.Monetary(string='Épargne disponible')` — aucun des trois n'a de `related=`. |
| `_get_savings_account_name` : dérive de `partner.microfinance_account_number` ou séquence centralisée sans lien client ? | **Toujours dérivée du client** | `microfinance_savings_account.py:72-76` : docstring confirme *"Le 1er compte épargne d'un type donné pour un client reprend le numéro de compte permanent du client"* — comportement inchangé. |
| `application_ids`/`application_count`/`action_view_applications` sur `microfinance.loan` | **Présents** | `microfinance_loan.py:90` (`application_ids = fields.One2many('microfinance.loan.application', 'loan_id', string='Enquêtes')`), `:131` (`application_count`), `:371` (`loan.application_count = len(loan.application_ids)`), `:1206-1226` (`action_view_applications`). |
| Bouton smart button "Enquête" dans `microfinance_loan_views.xml` (`button_box`) | **Présent** | `microfinance_loan_views.xml:87` : `<button name="action_view_applications" type="object" class="oe_stat_button" icon="fa-search" invisible="state == 'draft'">` |
| Menu **Crédits → Dossiers d'instruction** : libellé actuel | **Renommé "Enquêtes"** | `microfinance_menus.xml:25` : `<menuitem id="menu_microfinance_loan_applications" name="Enquêtes" parent="menu_credits_root" action="action_microfinance_loan_application" sequence="1"/>` |

**Conclusion de la section 2** : tous les points listés dans le prompt sont **appliqués tels que
décrits dans les derniers lots** — aucun écart entre "ce qui a été livré" et le code actuel sur
ces points précis. L'écart réel n'est pas sur ces mécanismes eux-mêmes, mais sur une conséquence
non anticipée (section 3).

---

## 3. Bug "Montant demandé" à 0 sur le dossier IS/000400

### Localisation en base (SEFOR)
```sql
select id, name, state, loan_id, requested_amount, partner_id
from microfinance_loan_application where name = 'IS/000400';
```
→ trouvé directement, un seul enregistrement :

| id | name | state | loan_id | requested_amount | partner_id |
|---|---|---|---|---|---|
| 1154 | IS/000400 | visite | **1449** | *(vide)* | 2555 (RANDRIAMISEZA) |

**`loan_id` n'est pas vide** — il pointe vers le crédit id=1449.

### Le crédit lié (id=1449)
```sql
select id, name, state, loan_amount, product_id, company_id, loan_account_id, partner_id
from microfinance_loan where id=1449;
```
| id | name | state | loan_amount | product_id | company_id | loan_account_id | partner_id |
|---|---|---|---|---|---|---|---|
| 1449 | IS/000289 | enquete | **500000.00** | 1 | 1 | 220 | 2555 |

Le crédit **a bien un montant** (500 000 Ar) — le dossier lié affiche pourtant 0/vide sur
"Montant demandé".

### Le compte crédit conteneur (id=220)
```sql
select id, name, partner_id, company_id from microfinance_loan_account where id=220;
select id, name, state, loan_amount from microfinance_loan where loan_account_id=220;
```
| id | name (loan.account) | partner_id |
|---|---|---|
| 220 | **IS/000400** | 2555 |

Un seul crédit rattaché à ce compte crédit : id=1449 (celui ci-dessus).

**Point de confusion identifié** : le `microfinance.loan.account` id=220 porte le nom
**"IS/000400"** — exactement la même chaîne que la référence du dossier d'instruction
(`IS/000400`, id=1154). Ce n'est **pas un lien entre les deux enregistrements** : les deux noms
dérivent indépendamment de la même source, `res_partner.microfinance_account_number` du client
2555 :
```sql
select microfinance_account_number from res_partner where id=2555;
-- IS/000400
```
- Le nom du dossier (`microfinance.loan.application.name`) est un champ `related=
  'partner_id.microfinance_account_number'` (`microfinance_loan_application.py:55-61`).
- Le nom du compte crédit (`microfinance.loan.account.name`) est calculé une fois à la création
  via `_get_loan_account_name()`, qui reprend directement `partner.microfinance_account_number`
  (section 1).
- Les deux affichent donc la même chaîne "IS/000400" **par coïncidence de source**, sans qu'un
  champ ne les relie l'un à l'autre. Ce n'est pas un bug en soi, mais une source de confusion
  visuelle très plausible en train de lire les fiches.

### Définition actuelle exacte de `requested_amount`
```python
# microfinance_loan_application.py:530
requested_amount = fields.Monetary(string='Montant demandé', tracking=True)
```
**Champ simple, éditable manuellement, sans `related=` ni `compute=` vers `loan_id` ou quoi que
ce soit d'autre.** Confirmé également pour `required_savings` (:531), `period` (:533),
`available_savings` (:534) — tous des champs "Bloc E — Avis CA / CDAG" (commentaire
`microfinance_loan_application.py:527-529`), hérités tels quels de l'ancien cycle à 10 états où
le dossier portait lui-même l'avis CA/CDAG. Ils n'ont jamais été reliés au crédit, ni avant ni
après la simplification à 4 états.

### Cause racine du "0" observé
`loan_id` **n'est pas vide** sur ce dossier — l'hypothèse du prompt ("si le champ est bien
related mais affiche 0, vérifier si loan_id est vide") ne s'applique pas telle quelle : le champ
n'est **jamais** `related`, donc peu importe que `loan_id` soit renseigné ou non, rien ne
recopie `loan_id.loan_amount` dans `requested_amount`.

**Chemin de création identifié** : le dossier a très probablement été créé via le smart button
"Enquête" (`action_view_applications`, `microfinance_loan.py:1206-1226`), qui **crée
explicitement le dossier avec `loan_id` renseigné** mais **sans jamais passer
`requested_amount`** :
```python
# microfinance_loan.py:1213-1219
application = self.env['microfinance.loan.application'].create({
    'partner_id': self.partner_id.id,
    'loan_product_id': self.product_id.id,
    'company_id': self.company_id.id,
    'loan_id': self.id,
})
```
Éléments à l'appui de cette hypothèse (vérifiables, pas certains à 100% sans log applicatif) :
- `loan_id` = 1449 correspond exactement au crédit du même client (partner_id 2555 des deux
  côtés, `loan_product_id`=1 = `product_id`=1 du crédit, `company_id`=1 des deux côtés) — cohérent
  avec les 4 champs explicitement passés par `action_view_applications`.
- `required_savings`, `available_savings`, `period` sont **également vides** sur ce dossier —
  cohérent avec une création par ce chemin (aucun de ces champs n'est dans le dict passé par
  `action_view_applications` non plus), alors qu'une création manuelle depuis le menu
  "Enquêtes" laisserait typiquement l'utilisateur remplir au moins certains de ces champs à la
  main sur le moment.
- `create_date` du dossier (2026-08-16 11:34:54) est très récent par rapport au commit ayant
  introduit ce smart button (2026-08-16 16:49:05, mais rappel : ce commit a regroupé tout le
  travail de la conversation en une fois — le code du smart button existait déjà dans l'arbre
  de travail avant ce commit, donc cette création a bien pu se produire *avant* le commit,
  pendant que Micka testait la fonctionnalité en direct).

**Ce n'est donc pas un bug de régression sur un mécanisme existant, mais un angle mort de
conception du smart button "Enquête" livré dans le lot précédent** : il relie le dossier au
crédit (`loan_id`), mais ne recopie aucune des données financières du crédit
(`requested_amount`, ni les autres champs du "Bloc E") vers le nouveau dossier — champs restés
à leur valeur par défaut (0 / vide).

---

## 4. Synthèse des écarts

- **Aucun écart de fond** entre les lots livrés dans la conversation et l'état réel du dépôt sur
  les mécanismes vérifiés en section 2 (cycles à 4/10 états, verrou de création, vues, smart
  buttons, numérotation épargne) — tout est appliqué comme documenté au fil des tours
  précédents.
- **Un écart de conception non anticipé** sur le smart button "Enquête" (`action_view_applications`) :
  il crée un dossier lié au crédit via `loan_id`, mais ne recopie pas `loan_amount` (ni les
  autres champs du "Bloc E" : `required_savings`, `available_savings`, `period`) vers les champs
  correspondants du dossier — qui ne sont eux-mêmes **jamais** `related` au crédit et
  n'existaient déjà plus dans le cycle simplifié à 4 états que sous forme de vestiges de l'ancien
  workflow à 10 états. Résultat observé : "Montant demandé" à 0 sur `IS/000400` malgré un crédit
  lié (`IS/000289`) à 500 000 Ar.
- **Point de confusion documentaire, pas fonctionnel** : `microfinance.loan.account` (compte
  crédit conteneur) et `microfinance.loan.application` (dossier d'instruction) peuvent afficher
  la **même référence textuelle** (ex. "IS/000400" dans le cas audité) parce que les deux
  dérivent indépendamment du même `partner.microfinance_account_number`, sans qu'aucun champ ne
  les relie entre eux. Peut donner l'illusion d'un lien direct entre les deux enregistrements
  alors qu'il n'y en a aucun.
- **Lacune de documentation** : `microfinance.loan.account` n'est mentionné dans aucun des
  fichiers de documentation utilisateur/technique du module (`README.md`, `USER_GUIDE_FR.md`,
  `TECHNICAL_ANALYSIS_FR.md`, `docs/`) malgré son usage actif (menu dédié, smart buttons sur la
  fiche client, RAZ Microfinance).
- **Historique git peu granulaire pour ce chantier** : le modèle `microfinance.loan.account` et
  l'ensemble des lots traités dans cette conversation n'existaient que dans l'arbre de travail
  jusqu'à un commit unique (`13a580c`) qui les regroupe tous — l'ordre chronologique réel
  d'introduction de chaque fonctionnalité n'est traçable que dans l'historique de conversation,
  pas dans `git log`.
