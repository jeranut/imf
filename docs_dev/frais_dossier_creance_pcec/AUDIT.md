# Audit — Compte PCEC de créance « frais de dossier à recevoir » (Option A)

Audit **lecture seule** (Lot 0). Aucune modification de code.

> ## ✅ Décisions Micka — 2026-09-04 (Lot 1 scopé sur cette base)
>
> | # | Question | Décision |
> |---|---|---|
> | 1 | Compte PCEC de la créance | **Créer le sous-compte `208005`** « Produits à recevoir - Frais de dossier sur crédit » (`asset_current`, `reconcile=True`) — ajout à `LOAN_NEW_SUBACCOUNTS` + migration `17.0.1.11.0/post-migrate.py` pour les sociétés `mg_pcec` (aujourd'hui CEFOR Isotry seul). |
> | 2 | Journal de l'écriture d'engagement | **Nouveau champ produit `fee_engagement_journal_id`** (Many2one `account.journal`, `default = _journal_default('OD')`, domaine `type = 'general'`). Pas de recherche dynamique du journal OD ; pas de réutilisation de `fee_journal_id` (caisse). |
> | 3 | Traitement de `fee_move_id` | **Option A** : ajouter `fee_receivable_move_id` (écriture d'engagement) ; **conserver `fee_move_id`** pour l'écriture de règlement (sémantique inchangée). Zéro régression `test_fee.py` (seul l'assert du compte crédité du règlement, l.62, est à ajuster). |
> | 4 | Portée de configuration du compte | **Produit seul** (`microfinance.loan.product`), comme tous les autres comptes du module. Aucun champ sur `res.company`. |
> | 5 | Mode « frais nettés du décaissement » (`fee_charged_before_disbursement = False`) | **Issue 1 — pas d'écriture d'engagement dans ce mode.** L'engagement à l'approbation n'est créé que pour les produits `fee_charged_before_disbursement = True`. Les produits « nettés » conservent leur écriture unique actuelle (`_prepare_disbursement_move`, crédit `717003` inchangé). `_prepare_disbursement_move` **n'est pas modifié**. `208005` ne reflète alors que les frais des produits « exigés avant décaissement ». |
> | 6 | Rattrapage des dossiers déjà approuvés | **Oui.** Script de migration ponctuel : pour chaque dossier `state == 'approved' AND fee_paid = False AND fee_amount_due > 0 AND product.fee_charged_before_disbursement = True`, créer l'écriture d'engagement rétroactive. Aujourd'hui : **IS/001076 seul** (10 000 Ar). Les dossiers déjà `fee_paid` (IS/003362, IS/003363) ne sont **pas** repris (frais déjà en 717003 via l'ancienne écriture unique). |
>
> **Périmètre Lot 1 qui en découle :**
> 1. `hooks.py` : `LOAN_NEW_SUBACCOUNTS['208005'] = ('Produits à recevoir - Frais de dossier sur crédit', 'asset_current', True)`.
> 2. `microfinance.loan.product` : `account_fee_receivable_id` (défaut `_pcec_default('208005')`) + `fee_engagement_journal_id` (défaut `_journal_default('OD')`) ; ajout vue produit.
> 3. `microfinance.loan` : champ `fee_receivable_move_id` ; méthode `_prepare_fee_receivable_move()` ; renommage `_prepare_fee_move` → `_prepare_fee_settlement_move` (crédit `208005` au lieu de `717003`) ; `action_approve()` crée l'engagement (garde : mode « avant décaissement » + `fee_amount_due > 0` + comptes/journal configurés + `not fee_receivable_move_id`) ; `action_charge_fee()` appelle `_prepare_fee_settlement_move()` (verrou `FOR UPDATE` conservé).
> 4. Vue fiche crédit : ajout `fee_receivable_move_id` à côté de `fee_move_id`.
> 5. `migrations/17.0.1.11.0/post-migrate.py` : création `208005` par société `mg_pcec` + engagement rétroactif des dossiers éligibles (IS/001076).
> 6. `tests/test_fee.py` : ajuster l'assert compte du règlement (l.62) ; nouveau test « engagement créé à l'approbation » ; test « règlement solde la créance 208005 ».
> 7. Manifest : version `17.0.1.10.0` → `17.0.1.11.0`.

Le reste de ce document est le rapport d'audit d'origine (constats + options), conservé
comme référence.

## Rappel de la cible (Option A validée)

| Moment | Écriture actuelle | Écriture cible (Option A) |
|---|---|---|
| **Approbation** (`state → 'approved'`) | *(aucune)* | **Engagement** : débit `account_fee_receivable_id` (nouveau) / crédit `717003` (`account_commission_credit_id`), montant `fee_amount_due` figé |
| **Clic « Encaisser les frais »** | débit caisse (`fee_journal_id.default_account_id`) / crédit `717003` | **Règlement** : débit caisse (`fee_journal_id.default_account_id`) / crédit `account_fee_receivable_id` (solde la créance) |

Bénéfice : le solde débiteur du compte `account_fee_receivable_id` au grand livre = total
des frais de dossier dus non encore encaissés.

---

## 1. Comptes PCEC candidats pour la créance « frais à recevoir »

Source réglementaire : **Arrêté n°20469/2004 du 27 octobre 2004** (CSBF Madagascar),
PCEC 2005, Titre II. Seed Odoo : `plan_compta_pcec/data/template/account.account-mg_pcec.csv`.

⚠️ **La classe 4 du PCEC 2005 n'est PAS « clients »** (contrairement au PCG français) : c'est
« Valeurs immobilisées » (titres, immobilisations). Les créances sur la clientèle sont en
**classe 2** (« Opérations avec la clientèle »), les débiteurs divers en **classe 3**.

| Code | Libellé exact (seed) | Type | `reconcile` (seed) | Classe / rubrique PCEC | Pertinence |
|---|---|---|---|---|---|
| **`208000`** | **Produits à recevoir - Prêts et avances à la clientèle** | `asset_current` | `False` | Cl. 2 — Opérations avec la clientèle, rubrique 208 « Produits à recevoir » | **La plus juste.** Un frais de dossier acquis mais non encaissé EST un produit à recevoir sur une opération de crédit clientèle. Le module y a déjà créé 4 sous-comptes (`208001-208004`, intérêts échus). |
| `208001-004` | Produits à recevoir - Intérêts échus (individuel / groupe / à recevoir …) | `asset_current` | `False` | idem, sous-comptes créés par `microfinance_loan_management` (`hooks.py:LOAN_NEW_SUBACCOUNTS`) | Réservés aux **intérêts**. Slot libre : `208005` / `208006`. |
| `318700` | Produits à recevoir - Débiteurs/créditeurs divers `*` | `asset_current` | `False` | Cl. 3 — Comptes de régularisation / débiteurs divers, rubrique 318 | Alternative si Micka veut **sortir** les frais de l'agrégat « produits à recevoir clientèle » (208). Moins précis. `*` = compte à vérifier (cf. `plan_compta_pcec/doc/comptes_a_verifier.md:75`). |
| `311000` | Débiteurs divers `*` | `asset_current` | **`True`** | Cl. 3, rubrique 311 | Traitement « créance sur un tiers » pur. Déjà `reconcile=True` (lettrage possible sans modif). Sémantiquement en-deçà de « produit à recevoir ». |
| `319000` | Autres débiteurs et créditeurs divers `*` | `asset_current` | `True` | Cl. 3, rubrique 319 | Fourre-tout, à éviter sauf refus des trois précédents. |

### Recommandation

**Créer un sous-compte dédié `208005`** — `Produits à recevoir - Frais de dossier sur crédit`,
`account_type = asset_current`, **`reconcile = True`** (nécessaire pour solder l'engagement
par lettrage contre le règlement ; les `208001-004` sont `reconcile=False` car jamais soldés
par lettrage, l'usage frais est différent).

- Conforme PCEC 2005 : rubrique **208** « Produits à recevoir » de la classe 2, Arrêté
  n°20469/2004.
- Cohérent avec le pattern du module (sous-comptes `208xxx` créés par `hooks.py`).
- Sémantiquement exact (produit acquis / non encaissé sur opération clientèle).

Pas de déclinaison individuel/groupe (le compte produit `account_commission_credit_id` /
`717003` n'en a pas non plus — les frais sont un montant unique par dossier, pas une
ventilation par segment). Un seul compte `208005`.

**Repli sans création de compte** : `318700` (déjà dans le seed). À réserver au cas où Micka
refuse un nouveau code.

### Impact « création de compte »

`208005` n'existe pas encore. `post_init_hook` (`hooks.py:712`) ne crée les sous-comptes
qu'à **l'installation** du module, pas sur `-u`. Le Lot 1 devra donc :
1. ajouter `'208005': ('Produits à recevoir - Frais de dossier sur crédit', 'asset_current', True)` à `LOAN_NEW_SUBACCOUNTS` ;
2. ajouter une migration `migrations/17.0.1.11.0/post-migrate.py` qui rejoue
   `_create_subaccounts(env, company, {'208005': (...)})` pour chaque société
   `chart_template == 'mg_pcec'` — même boucle que le hook.
   Aujourd'hui **une seule société concernée : CEFOR Isotry (id 1)** ; les 10 autres agences
   ont `chart_template` vide (aucun compte PCEC).

---

## 2. Champ reconfigurable — pattern à reprendre

Modèle de référence : `account_commission_credit_id` sur `microfinance.loan.product`
(`models/microfinance_loan_product.py:315-320`).

```python
account_commission_credit_id = fields.Many2one(
    'account.account', string='Commission sur crédit',
    domain="[('account_type', '=', 'income'), ('company_id', '=', company_id)]",
    default=_pcec_default('717003'),
    help="Compte de comptabilisation des frais de dossier. Requis uniquement si des frais sont encaissés pour ce produit.",
)
```

- `_pcec_default(code)` (`microfinance_loan_product.py:6`) : `search([('code','=',code), ('company_id','=', self.env.company.id)], limit=1)` — recopie par **code + société**, jamais de réf XML statique ; recordset vide si absent (champ reste vide, pas d'erreur).
- Domaine filtré `company_id` → chaque produit ne voit que les comptes de SA société.
- **Aucune valeur hardcodée** dans le code métier : `_prepare_fee_move` lit `product.account_commission_credit_id`, jamais un code en dur. ✅ conforme à la contrainte Micka « reconfigurable après coup ».

### Proposition

```python
account_fee_receivable_id = fields.Many2one(
    'account.account', string='Frais de dossier à recevoir',
    domain="[('account_type', 'in', ('asset_current', 'asset_receivable')), ('company_id', '=', company_id)]",
    default=_pcec_default('208005'),
    help="Compte de créance mouvementé à l'approbation du dossier (engagement des frais de "
         "dossier), soldé à l'encaissement effectif. Son solde = total des frais de dossier "
         "dus non encore encaissés. Requis uniquement si des frais sont encaissés pour ce "
         "produit (mode « engagement puis règlement »).",
)
```

- Ajout dans la vue produit `views/microfinance_loan_product_views.xml` à côté de
  `account_commission_credit_id` (ligne 123).
- `_prepare_fee_receivable_move` / `_prepare_fee_settlement_move` liront
  `product.account_fee_receivable_id` — jamais `'208005'` en dur.

---

## 3. Point d'accroche pour l'écriture d'engagement (approbation)

**Méthode : `action_approve()`** — `models/microfinance_loan.py:879-882` :

```python
def action_approve(self):
    for loan in self:
        loan._check_committee_octroi_accepted()
    self.write({'state': 'approved', 'approval_date': fields.Date.context_today(self)})
```

- **Unique transition vers `'approved'`** : `grep "'state': 'approved'"` → seule occurrence
  ligne 882. Aucun autre chemin (pas de write direct ailleurs, pas de migration qui force
  l'état).
- `fee_amount_due` : champ `Monetary(compute='_compute_fee_amount', store=True)`
  (`microfinance_loan.py:229`). `_FEE_FROZEN_STATES = ('approved', 'active', 'closed',
  'defaulted', 'written_off')` (`:343`). Après le `write({'state': 'approved'})`, le recompute
  lit la valeur **figée** en base (branche `frozen` de `_compute_fee_amount`, `:523`). Donc à
  l'instant où l'engagement doit être créé, `fee_amount_due` est **disponible et figé**. ✅
  (décision « fee_amount_due frozen at approval » déjà actée.)
- `approval_date` est posée dans le même `write` → disponible comme `date` de l'écriture
  d'engagement.

### Forme d'implémentation (Lot 1)

Ajouter, **après** le `self.write(...)`, une boucle :

```python
for loan in self:
    if loan._fee_engagement_applicable():   # fee_amount_due > 0, comptes configurés, mode "avant décaissement" (cf. §5 conflit)
        move = self.env['account.move'].with_context(...).create(loan._prepare_fee_receivable_move())
        move.action_post()
        loan.fee_receivable_move_id = move.id
        loan.message_post(body=_('Engagement frais de dossier : %s') % move.name)
```

Garde de ré-entrance : `if loan.fee_receivable_move_id: continue` (une réapprobation ne doit
pas re-créer l'engagement — cf. verrou `action_charge_fee` du lot précédent, même esprit).

---

## 4. Refactor de `_prepare_fee_move` en deux méthodes

Actuel : `_prepare_fee_move` (`microfinance_loan.py:1560-1575`) — 1 écriture caisse→717003,
journal `fee_journal_id`.

### 4.1 `_prepare_fee_receivable_move()` — **nouveau**, engagement à l'approbation

| Ligne | Compte | Débit | Crédit |
|---|---|---|---|
| Engagement frais `<name>` | `product.account_fee_receivable_id` (**208005**) | `fee_amount_due` | — |
| Frais de dossier `<name>` | `product.account_commission_credit_id` (**717003**) | — | `fee_amount_due` |

- `date = approval_date or context_today`.
- `ref = _('Engagement frais de dossier crédit %s') % self.name`.
- `microfinance_loan_id = self.id`.
- **Journal** : ⚠️ **question ouverte** (cf. §8). Un engagement n'est **pas** un mouvement de
  trésorerie → devrait passer par un journal `type='general'` (OD), **pas** `fee_journal_id`
  (cash). Pattern existant pour trouver l'OD : `_prepare_writeoff_move` /
  `_prepare_provision_move` recherchent dynamiquement le journal `type='general'` de la
  société (`hooks.py` : journal `OD`). À défaut, un nouveau champ produit
  `fee_engagement_journal_id` (défaut `_journal_default('OD')`).
- Garde : `UserError` si `account_fee_receivable_id` ou `account_commission_credit_id` ou le
  journal OD manquent (même style que `_prepare_fee_move` actuel).

### 4.2 `_prepare_fee_settlement_move()` — **`_prepare_fee_move` renommé**, règlement au clic

| Ligne | Compte | Débit | Crédit | Changement |
|---|---|---|---|---|
| Encaissement frais `<name>` | `fee_journal_id.default_account_id` (caisse) | `fee_amount_due` | — | inchangé |
| ~~Frais de dossier~~ → **Solde créance frais** `<name>` | ~~`717003`~~ → **`product.account_fee_receivable_id`** | — | `fee_amount_due` | **crédite la créance, plus le produit** |

- `date`, `journal_id = fee_journal_id`, `ref`, `microfinance_loan_id` : inchangés.
- Garde : ajouter `account_fee_receivable_id` à la liste des comptes requis.
- Nom : `_prepare_fee_settlement_move` (explicite) ; garder un alias
  `_prepare_fee_move = _prepare_fee_settlement_move` si des tests/API externes l'appellent —
  `grep` : seul `action_charge_fee` l'appelle en interne, aucun test ne l'appelle
  directement, donc renommage franc possible.

`action_charge_fee` (`:1577`) : remplacer `loan._prepare_fee_move()` par
`loan._prepare_fee_settlement_move()`. Le **verrou `FOR UPDATE` + `invalidate_recordset`**
ajouté au lot précédent reste en place tel quel (protège toujours contre le double
règlement).

---

## 5. Recommandation `fee_move_id` — deux champs

| Option | Détail | Impact vues | Impact `test_fee.py` |
|---|---|---|---|
| **A (recommandée)** — 2 champs | `fee_receivable_move_id` (nouveau, engagement) + garder **`fee_move_id`** pour le **règlement** (sémantique inchangée : « l'écriture d'encaissement des frais ») | +1 champ dans la vue (`views/microfinance_loan_views.xml:194`, à côté de `fee_move_id`) | **Aucun** — `test_fee.py` n'assère que sur `loan.fee_move_id` (l.59-62, 89, 102) = le règlement, toujours peuplé au clic. Reste vert. |
| B — 1 champ resémantisé | `fee_move_id` = « dernier mouvement lié » (engagement puis règlement) | idem | `test_fee.py` l.60 `assertEqual(loan.fee_move_id.state, 'posted')` + l.62 `credit_lines.account_id == self.fee_account` **cassent** : après règlement, `fee_move_id` = règlement dont le crédit est désormais la créance, plus `self.fee_account` (=717003 dans le test). À réécrire. |
| C — 2 champs + renommage | `fee_receivable_move_id` + `fee_settlement_move_id`, suppression de `fee_move_id` | +1 champ, 1 renommé | `test_fee.py` l.59-62, 89, 102 à migrer vers `fee_settlement_move_id`. Migration de données pour renommer la colonne. |

➡️ **Option A** : `fee_receivable_move_id` nouveau + `fee_move_id` conservé pour le règlement.
Zéro régression de test, traçabilité complète (les deux écritures visibles sur la fiche et
dans le compteur « Écritures » via `move_ids`/`microfinance_loan_id`).

Détail test à ajuster quand même dans `test_fee.py::test_charge_fee_generates_move_and_unblocks_disbursement`
(l.62) : `credit_lines.account_id` du move de règlement sera désormais
`account_fee_receivable_id`, pas `account_commission_credit_id`. Le test devra vérifier
`717003` au crédit **de l'écriture d'engagement** (`fee_receivable_move_id`) et la créance au
crédit du règlement. Nouveau test dédié à l'engagement à ajouter.

---

## 6. Portée de configuration du compte — **produit seul**

- **Tous** les comptes du module vivent sur `microfinance.loan.product`
  (`account_principal_*`, `account_interets_recus_*`, `account_penalites_id`,
  `account_commission_credit_id`, `account_recouvrement_id`, `account_papeterie_id`,
  `account_surpaiement_id`, `account_provision_*`, `account_douteux_*`…). Aucun n'a de
  couche de surcharge par société.
- `microfinance.loan.product.company_id` est **`required`** (`microfinance_loan_product.py:364`)
  et tous les domaines de compte filtrent `('company_id', '=', company_id)`. Un produit = une
  société → la configuration est **de fait par (produit × société)**.
- Un même besoin métier sur 2 agences = 2 produits (1 par société), chacun avec son
  `account_fee_receivable_id` pointant sur le `208005` de sa société.

➡️ **`account_fee_receivable_id` sur le produit uniquement**, exactement comme
`account_commission_credit_id`. Pas de champ sur `res.company`.

---

## 7. Dossiers déjà approuvés — pas d'engagement rétroactif

`grep` SEFOR, dossiers en `_FEE_FROZEN_STATES` :

| Dossier | État | `approval_date` | `fee_paid` | `fee_move_id` | `fee_amount_due` | Situation post-Lot 1 |
|---|---|---|---|---|---|---|
| **IS/001076** | approved | 2026-09-01 | **non** | *(vide)* | 10 000 | **Créance jamais engagée.** Frais encore dus → le `208005` sous-estimera les impayés de 10 000 tant que non rattrapé. |
| **IS/003362** | approved | 2026-09-03 | oui | 1983 | 25 000 | Frais encaissés via l'**ancienne** écriture unique caisse→717003 (`CSH1/2026/00003`). Ni engagement ni règlement « nouvelle forme ». |
| **IS/003363** | approved | 2026-09-01 | oui | 1987 | 10 000 | idem (`move 1987`). |

- Aucun de ces 3 n'aura d'écriture d'engagement (fonctionnalité inexistante à leur
  approbation).
- IS/003362 / IS/003363 : frais déjà en produit (717003), **ne rien reprendre** (un rattrapage
  engagement+règlement double-compterait sauf à contre-passer l'ancien move).
- IS/001076 : seul cas où un rattrapage aurait un sens comptable (créance ouverte pour
  refléter les 10 000 réellement dus). À trancher par Micka.

**Hors scope Lot 1 (implémentation).** Juste signalé ici. Si rattrapage retenu : script de
migration ponctuel, dossiers `state == 'approved' AND fee_paid = False AND fee_amount_due > 0`
(aujourd'hui : IS/001076 seul).

---

## 8. Conflit à résoudre — mode « frais nettés du décaissement »

`_prepare_disbursement_move` (`microfinance_loan.py:1543-1549`) : quand
`product.fee_charged_before_disbursement == False`, les frais sont **crédités directement à
`717003`** dans l'écriture de décaissement (jamais de passage par `action_charge_fee`).

Si l'engagement (débit 208005 / crédit 717003) est créé à l'approbation **pour tous les
produits**, alors pour un produit `fee_charged_before_disbursement=False` :
`717003` serait crédité **deux fois** (engagement + décaissement), et `208005` jamais soldé.

**Deux issues possibles (à trancher — question ouverte) :**
1. **Engagement seulement si `fee_charged_before_disbursement == True`** (le plus simple ;
   le mode « nettés » garde son écriture unique actuelle, hors périmètre Option A).
2. Engagement **pour tous**, et modifier la branche nettage de `_prepare_disbursement_move`
   pour créditer **`account_fee_receivable_id`** au lieu de `717003` (le produit ayant déjà
   été constaté à l'engagement) → cohérent, mais touche le décaissement (hors scope
   strictement « frais »).

---

## 9. Questions ouvertes pour Micka (avant Lot 1)

1. **Compte PCEC retenu** : nouveau sous-compte **`208005`** « Produits à recevoir - Frais de
   dossier sur crédit » (`asset_current`, `reconcile=True`, classe 2, Arrêté n°20469/2004) —
   *recommandé* ? ou repli sur **`318700`** existant (« Produits à recevoir - Débiteurs/
   créditeurs divers ») pour éviter un nouveau code ? ou **`311000`** (« Débiteurs divers »,
   déjà `reconcile=True`) ?
2. **Journal de l'écriture d'engagement** : journal **OD** (`type='general'`, recherché
   dynamiquement comme pour radiation/provision) — *recommandé* ? ou nouveau champ produit
   `fee_engagement_journal_id` ? (Ne PAS réutiliser `fee_journal_id`, qui est un journal de
   caisse.)
3. **`fee_move_id`** : **Option A** (ajouter `fee_receivable_move_id`, garder `fee_move_id`
   pour le règlement — zéro régression de test) — *recommandé* ? ou renommage complet
   (Option C, migration de colonne + tests à réécrire) ?
4. **Portée config** : `account_fee_receivable_id` **sur le produit uniquement** (comme tous
   les autres comptes du module) — *recommandé*. Confirmer qu'aucune config par société n'est
   attendue.
5. **Mode « frais nettés du décaissement »** (`fee_charged_before_disbursement=False`) :
   engagement **désactivé** dans ce mode (issue 1, simple) ou décaissement modifié pour
   créditer la créance (issue 2) ?
6. **Rattrapage des dossiers déjà approuvés** : ne rien faire ? ou script ponctuel pour
   ouvrir la créance des dossiers `approved AND NOT fee_paid AND fee_amount_due > 0`
   (aujourd'hui : **IS/001076** seul, 10 000 Ar) ?

---

## Annexe — points d'entrée

| Élément | Emplacement |
|---|---|
| Seed comptes PCEC | `plan_compta_pcec/data/template/account.account-mg_pcec.csv` |
| Comptes « à vérifier » | `plan_compta_pcec/doc/comptes_a_verifier.md` |
| `_pcec_default` / `_journal_default` | `microfinance_loan_management/models/microfinance_loan_product.py:6` / `:19` |
| `account_commission_credit_id` (pattern) | `microfinance_loan_product.py:315-320` |
| Vue compta produit | `views/microfinance_loan_product_views.xml:123` |
| `action_approve` (hook engagement) | `models/microfinance_loan.py:879-882` |
| `_FEE_FROZEN_STATES` / `_compute_fee_amount` (freeze) | `microfinance_loan.py:343` / `:516-541` |
| `_prepare_fee_move` (à scinder) | `microfinance_loan.py:1560-1575` |
| `_prepare_disbursement_move` (branche nettage frais) | `microfinance_loan.py:1543-1549` |
| `action_charge_fee` (+ verrou FOR UPDATE du lot précédent) | `microfinance_loan.py:1577-1602` |
| `fee_move_id` / `fee_paid` (champs) | `microfinance_loan.py:230-231` |
| Vue fiche crédit (bloc frais) | `views/microfinance_loan_views.xml:192-194` |
| `post_init_hook` / `LOAN_NEW_SUBACCOUNTS` / `_create_subaccounts` | `microfinance_loan_management/hooks.py:712` / `:20` / `:114` |
| Migrations (pattern) | `microfinance_loan_management/migrations/17.0.1.8.0/post-migrate.py` |
| Version manifest actuelle | `17.0.1.10.0` → Lot 1 = `17.0.1.11.0` |
| Tests frais | `microfinance_loan_management/tests/test_fee.py` |
| Sociétés `mg_pcec` (SEFOR) | **CEFOR Isotry (id 1) uniquement** ; 10 autres agences sans plan PCEC |
