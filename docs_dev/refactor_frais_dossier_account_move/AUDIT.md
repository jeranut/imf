# Audit — Refactorisation « Encaisser les frais de dossier » vers un vrai `account.move`

Audit **lecture seule** (Lot 0). Aucune modification de code. Le Lot 1 sera scopé après
validation par Micka.

## TL;DR — la refactorisation visée est **déjà faite**

`action_charge_fee` **crée déjà aujourd'hui un vrai `account.move` comptabilisé**
(`move.action_post()`), le lie au crédit via un champ dédié `fee_move_id` typé
`Many2one('account.move')`, et poste un message chatter. Ce n'est **pas** un simple
`fee_paid = True`. Le code est **committé** (présent à l'identique dans `HEAD`, commit
`13a580c` ou antérieur — le diff non committé de `microfinance_loan.py` ne touche aucune
des méthodes de frais) et **couvert par des tests**
(`tests/test_fee.py::test_charge_fee_generates_move_and_unblocks_disbursement`,
`::test_charge_fee_twice_blocked`).

Vérifié en réel sur **SEFOR** : IS/003362 a `fee_paid = t`, `fee_move_id = 1983` →
écriture `CSH1/2026/00003`, **posted**, journal CRE, débit 100001 « Espèces » 25 000 /
crédit **717003** « Commissions perçues - Commission sur crédit » 25 000, `ref` =
« Frais de dossier crédit IS/003362 », `microfinance_loan_id` renseigné.

Le « champ vide sur des dossiers approuvés » observé = **comportement normal** : IS/001076
et IS/003363 (approuvés, PRET RURAL, `fee_charged_before_disbursement = t`) ont
`fee_paid = f` / `fee_move_id` vide **parce que personne n'a encore cliqué le bouton** —
ils ne peuvent d'ailleurs pas être décaissés tant que les frais ne sont pas encaissés.

Il reste néanmoins de vraies **questions ouvertes** (compte PCEC, journal, race de
double-clic) listées en fin de document.

---

## 1. Code intégral actuel de `action_charge_fee`

`microfinance_loan_management/models/microfinance_loan.py`, **lignes 1577-1592** :

```python
def action_charge_fee(self):
    for loan in self:
        if loan.state != 'approved':
            raise UserError(_('Les frais de dossier ne peuvent être encaissés que sur un crédit approuvé.'))
        if loan.fee_paid:
            raise UserError(_('Les frais de dossier ont déjà été encaissés.'))
        if loan.fee_amount_due <= 0:
            raise UserError(_('Aucun frais de dossier à encaisser pour ce crédit.'))
        move = self.env['account.move'].with_context(
            default_loan_id=False,
            default_loan_line_id=False,
        ).create(loan._prepare_fee_move())
        move.action_post()
        loan.write({'fee_paid': True, 'fee_move_id': move.id})
        loan.message_post(body=_('Frais de dossier encaissés (%.2f). Écriture : %s') % (loan.fee_amount_due, move.name))
    return True
```

Helper appelé — `_prepare_fee_move`, **lignes 1560-1575** :

```python
def _prepare_fee_move(self):
    self.ensure_one()
    product = self.product_id
    journal = product.fee_journal_id
    if not journal or not journal.default_account_id or not product.account_commission_credit_id:
        raise UserError(_('Configurez le journal d\'encaissement des frais, son compte par défaut et le compte commission sur crédit du produit.'))
    return {
        'date': fields.Date.context_today(self),
        'journal_id': journal.id,
        'ref': _('Frais de dossier crédit %s') % self.name,
        'microfinance_loan_id': self.id,
        'line_ids': [
            (0, 0, {'name': _('Encaissement frais %s') % self.name, 'partner_id': self.partner_id.id, 'account_id': journal.default_account_id.id, 'debit': self.fee_amount_due, 'credit': 0.0}),
            (0, 0, {'name': _('Frais de dossier %s') % self.name, 'partner_id': self.partner_id.id, 'account_id': product.account_commission_credit_id.id, 'debit': 0.0, 'credit': self.fee_amount_due}),
        ]
    }
```

### Constat

| Question du Lot 0 | Réponse |
|---|---|
| Se contente-t-elle de `fee_paid = True` ? | **Non.** |
| Crée-t-elle un `account.move` ? | **Oui**, via `_prepare_fee_move()`, puis `move.action_post()` → écriture **comptabilisée**. |
| `account.payment` ? | Non (pas de `account.payment` — écriture directe, cohérent avec le reste du module, cf. §5). |
| Respecte-t-elle la compta de caisse (écriture seulement à l'encaissement réel) ? | **Oui** : l'écriture n'est créée qu'au clic du bouton, jamais à l'approbation ni à la génération de l'échéancier. `date = context_today`. |

**Écriture produite** (2 lignes, équilibrée) :

| Ligne | Compte | Débit | Crédit |
|---|---|---|---|
| Encaissement frais `<name>` | `fee_journal_id.default_account_id` (compte de trésorerie du journal) | `fee_amount_due` | — |
| Frais de dossier `<name>` | `product.account_commission_credit_id` (produit) | — | `fee_amount_due` |

Pas de TVA, pas de compte client intermédiaire : encaissement direct trésorerie ↔ produit.

### Second chemin (frais nettés du décaissement)

Quand `product.fee_charged_before_disbursement = False`, `action_charge_fee` n'est **jamais**
appelé : les frais sont portés dans l'écriture de décaissement elle-même — `_prepare_disbursement_move`,
**lignes 1543-1549** ajoute une ligne au crédit `account_commission_credit_id` et diminue la
sortie caisse de `fee_amount_due` (`net_disbursed_amount`). Dans ce cas `fee_move_id` reste
**vide par conception** (le champ ne pointe que sur l'écriture d'encaissement *séparée*). À
garder en tête pour le Lot 1 : si Micka veut un `fee_move_id` toujours renseigné, il faudra
aussi le peupler depuis ce chemin (ou assumer qu'il ne concerne que le mode « frais exigés
avant décaissement »).

---

## 2. État réel du champ « Écriture de frais »

- **Champ réel**, déclaré `microfinance_loan.py:231` :
  ```python
  fee_move_id = fields.Many2one('account.move', string='Écriture de frais', readonly=True, copy=False)
  ```
- **Assigné** dans le code : `action_charge_fee` → `loan.write({'fee_paid': True, 'fee_move_id': move.id})` (`microfinance_loan.py:1590`). C'est le **seul** point d'assignation.
- Exposé en vue : `views/microfinance_loan_views.xml:194` `<field name="fee_move_id" readonly="1"/>` (à côté de `fee_amount_due` L192 et `fee_paid` L193).
- Champ jumeau côté `microfinance.loan.payment` : `move_id` (`microfinance_loan_payment.py:48`), même convention (`readonly`, `copy=False`).
- Lien inverse générique : `account.move.microfinance_loan_id` (`microfinance_loan.py:2132`), exposé côté crédit par `move_ids = One2many('account.move', 'microfinance_loan_id')` (`microfinance_loan.py:175`) et le stat button « Écritures ». L'écriture de frais y apparaît donc **aussi** dans le compteur « Écritures » du dossier, en plus de `fee_move_id`.

**Conclusion** : le champ existe, est correctement typé/lié, et **est peuplé** dès que le
bouton est utilisé. Rien à recréer ; tout au plus à décider si on le renomme / si on couvre
le chemin « frais nettés » (Q3).

---

## 3. Occurrences des comptes `717003` et `420010`

### `717003`

| Emplacement | Contexte |
|---|---|
| `microfinance_loan_management/hooks.py:45` | `LOAN_NEW_SUBACCOUNTS['717003'] = ('Commissions perçues - Commission sur crédit', 'income', False)` — sous-compte PCEC créé par le post-init hook pour chaque société sur plan `mg_pcec`. **Non réconciliable**, type `income`. |
| `microfinance_loan_management/models/microfinance_loan_product.py:318` | `account_commission_credit_id = fields.Many2one('account.account', … default=_pcec_default('717003'))` — **défaut** du champ produit utilisé par `_prepare_fee_move` **et** `_prepare_disbursement_move`. |
| `views/microfinance_loan_product_views.xml:123` | `<field name="account_commission_credit_id"/>` — paramétrable par produit dans l'onglet Comptabilité. |
| `tests/test_fee.py` (11-15, 64, 93) | Le test remplace ce compte par un compte `income_other` ad hoc (`TFEE`) et vérifie que la ligne de crédit de l'écriture pointe dessus. |
| SEFOR (réel) | `account_account` code `717003`, société 1, type `income` ; c'est le compte crédité par l'écriture `1983` d'IS/003362. |

➡️ **`717003` est le compte effectivement utilisé aujourd'hui** pour la contrepartie « produit » des frais de dossier (via le champ produit `account_commission_credit_id`).

### `420010`

**Aucune occurrence en tant que compte comptable**, nulle part dans les deux modules
(`.py`, `.xml`, `.csv`), ni dans `hooks.py`, ni dans
`audit_pcg2005_mapping/mapping_comptes_pcg2005_cefor.md`.

Les 2 seuls hits `grep` sont des **codes de commune géographiques** sans rapport :
- `data/microfinance.geo.commune.csv:728` → `commune_4420010,4420010,Antsalova`
- `data/microfinance_geo_commune_district_link.csv:401` → `commune_4420010,district_melaky_antsalova`

Le mapping PCG2005 du dépôt propose plutôt, pour `account_commission_credit_id` (« Commission
sur crédit »), le compte générique **`708200` Commissions et courtages** (`mapping_…_cefor.md:52`,
confiance « Moyenne »), **pas** `420010`. `420010` provient donc d'une note externe hors dépôt
(plan PCEC bancaire : classe 42 = opérations avec la clientèle / tiers) — **à clarifier par
Micka**, le code ne tranche pas.

---

## 4. Journaux comptables par société & pattern de sélection

### Journaux créés par le post-init hook (`hooks.py`, liste `JOURNALS` ~L68)

| Code | Nom | Type | Compte défaut |
|---|---|---|---|
| `BQOP` | Banque - Opérations | bank | `131001` |
| `BQEP` | Banque - Épargne | bank | `131002` |
| `BQCR` | Banque - Crédits | bank | `131003` |
| `CAI` | Caisse | cash | `101000` |
| `CRE` | Crédits | **cash** | *(aucun — à configurer)* |
| `EPG` | Épargne | **cash** | *(aucun)* |
| `OD` | Opérations diverses | general | *(aucun)* |

Dupliqués **par société** (recherche `code + company_id`, jamais d'ID/réf XML statique — cf.
`_journal_default`, `microfinance_loan_product.py:19`). En réel sur SEFOR (société 1) : `CRE`
(cash, compte défaut `100001` Espèces), `CAI`, `BQOP`, `BQCR`, `EPG`, `OD` tous présents.

Note `hooks.py` : `CRE`/`EPG` **doivent rester `cash`** (jamais `general`) — ce sont les
défauts de tous les champs journaux du module dont le domaine de vue impose
`('type', 'in', ('bank','cash'))`.

### Pattern de sélection du journal (observé)

**Aucun choix dynamique caisse-vs-banque à l'exécution.** Le journal est un **champ de
configuration du produit**, choisi une fois par le paramétreur, avec `CRE` comme défaut :

| Écriture | Champ produit | Défaut | Fichier |
|---|---|---|---|
| Décaissement principal | `disbursement_journal_id` | `_journal_default('CRE')` | `microfinance_loan_product.py:128` |
| Remboursement | `payment_journal_id` | `_journal_default('CRE')` | `microfinance_loan_product.py:133` |
| **Frais de dossier** | **`fee_journal_id`** | **`_journal_default('CRE')`** | `microfinance_loan_product.py:353` |
| Radiation / provision | *(recherche dynamique du journal `type='general'` de la société)* | — | `_prepare_writeoff_move` / `_prepare_provision_move` |

- Les trois champs journaux « opérationnels » ont le **même domaine** :
  `[('type', 'in', ('bank','cash')), ('company_id', '=', company_id)]`.
- `fee_journal_id` est explicitement documenté comme pouvant être « distinct des journaux de
  décaissement/remboursement… (peut être identique à l'un des deux) » — donc l'agence choisit
  caisse (`CRE`/`CAI`) ou banque (`BQ*`) selon comment elle encaisse réellement les frais.
- Le **compte de trésorerie** de l'écriture n'est jamais choisi à la main : c'est toujours
  `journal.default_account_id` (d'où l'exigence, dans `_prepare_fee_move`, que le journal ait
  un compte par défaut).

➡️ **Pattern à réutiliser au Lot 1** : ne pas ajouter de logique de sélection ; s'appuyer sur
`product.fee_journal_id` (déjà en place) + `journal.default_account_id`. La seule question
(Q2) est de savoir si le **défaut** `CRE` convient ou si Micka veut `CAI` (Caisse) par défaut.

---

## 5. Pattern de construction d'un `account.move` (réutilisable)

Trois helpers, tous dans le module, **même forme** — à prendre comme référence pour toute
évolution du Lot 1 :

| Helper | Fichier / lignes | Rôle |
|---|---|---|
| `_prepare_fee_move` | `microfinance_loan.py:1560-1575` | **la cible du chantier** — frais de dossier |
| `_prepare_disbursement_move` | `microfinance_loan.py:1529-1558` | décaissement (+ nettage frais optionnel) |
| `_prepare_payment_move` | `microfinance_loan_payment.py:157-185` | remboursement (ventile principal / intérêt / pénalité) |

### Invariants communs du pattern

1. `self.ensure_one()` en tête.
2. Le helper **retourne un dict de `vals`**, il ne crée rien ; la création + le post sont
   dans la méthode-action (`action_charge_fee` / `action_disburse` / `action_post`).
3. Création systématiquement via
   `self.env['account.move'].with_context(default_loan_id=False, default_loan_line_id=False).create(vals)`
   puis `move.action_post()` — le `with_context` neutralise des défauts parasites d'un
   éventuel contexte d'action.
4. `vals` contient toujours : `date` (`fields.Date.context_today(self)`, sauf remboursement
   qui prend `payment_date`), `journal_id`, `ref` (`_('… crédit %s') % self.name`),
   `microfinance_loan_id` (lien inverse), `line_ids` en commandes `(0, 0, {...})`.
5. Lignes : `name`, `partner_id` (toujours renseigné), `account_id`, `debit`/`credit` (l'un
   à `0.0`). **Pas d'arrondi explicite** dans les helpers — les montants (`fee_amount_due`,
   `net_disbursed_amount`, `allocated_*`) sont déjà des `Monetary` arrondis par l'ORM ; la
   devise vient du journal/société.
6. Le compte de trésorerie = `journal.default_account_id` ; le compte de contrepartie = un
   champ `account_*_id` du **produit**, résolu pour certains via
   `product._get_account(kind, partner)` (`microfinance_loan_product.py:434`) qui choisit la
   variante `individuel` / `groupe` selon `partner.microfinance_client_type`.
   ⚠️ `account_commission_credit_id` (frais) **n'a pas** de variante individuel/groupe — c'est
   un champ unique, pris directement (`product.account_commission_credit_id`).
7. **Multi-société** : jamais de `sudo()` dans ces helpers. L'isolation passe par
   `company_id` du journal (le journal est déjà filtré par société dans son domaine) et par
   les défauts `code + self.env.company` de `_journal_default` / `_pcec_default`. Les seuls
   `sudo()` du domaine frais sont ailleurs (lecture SQL de `fee_amount_due` figé, etc.).
8. Post-traitement dans l'action : `write` du/des champ(s) de lien (`fee_move_id` /
   `move_id`) + `message_post` sur le crédit.
9. Contre-passation (si un jour nécessaire pour les frais) : modèle dans
   `microfinance_loan_payment.py:_reverse_posted_payment` (`move._check_fiscalyear_lock_date()`
   puis `move._reverse_moves(...)`, stockage dans `reversal_move_id`).

---

## 6. Risques de double comptabilisation

### Gardes actuelles

- **Serveur** (`action_charge_fee`) : `state != 'approved'` → `UserError` ; `fee_paid` →
  `UserError` ; `fee_amount_due <= 0` → `UserError`.
- **Vue** (`microfinance_loan_views.xml:72`) : bouton `invisible="state != 'approved' or fee_paid or fee_amount_due <= 0"` + `groups="…group_microfinance_finance"`.
- **Web** : un bouton `type="object"` est désactivé par le framework pendant l'appel RPC →
  un double-clic utilisateur dans la **même** session ne déclenche pas deux exécutions.
- **Test** : `tests/test_fee.py::test_charge_fee_twice_blocked` verrouille le comportement
  « 2ᵉ appel → `UserError` ».

### Atomicité

`create()` → `action_post()` → `write({'fee_paid': True, 'fee_move_id': …})` s'exécutent
dans **la même transaction** (un seul appel bouton). Si `action_post()` lève (écriture
déséquilibrée, période verrouillée, compte manquant…), toute la transaction est annulée —
**pas d'écriture brouillon orpheline**, `fee_paid` reste `False`, le dossier reste
ré-encaissable une fois la config corrigée. ✅

### Gap résiduel — race inter-transactions

`action_charge_fee` lit `loan.fee_paid` **sans `SELECT … FOR UPDATE`** sur la ligne du
crédit. Deux exécutions **concurrentes** (double-clic très rapide sur deux onglets, appel
API/`xmlrpc` en parallèle, ou deux workers) peuvent toutes deux voir `fee_paid = False`
avant que l'une ait committé → **deux `account.move` postés** pour les mêmes frais, et le
2ᵉ `write` écrase `fee_move_id` (le 1ᵉ move devient « perdu » mais reste posté en compta).

- **Probabilité réelle sur cette instance : faible** — `workers = 0` sérialise de fait les
  requêtes. Le risque est théorique tant que la prod reste mono-worker.
- **Pas de garde structurelle** aujourd'hui : ni contrainte SQL `UNIQUE`, ni
  `@api.constrains`, ni verrou explicite.

À arbitrer au Lot 1 (Q4) : soit on considère `workers=0` + bouton désactivé côté web comme
suffisant, soit on ajoute un verrou (`SELECT id FROM microfinance_loan WHERE id = %s FOR
UPDATE NOWAIT` en tête de méthode) ou une contrainte d'unicité partielle sur
`account_move.microfinance_loan_id` filtrée sur les écritures de frais.

---

## 7. Questions ouvertes à trancher par Micka avant le Lot 1

> Contexte : la mécanique « bouton → `account.move` posté → `fee_move_id` » **existe déjà et
> fonctionne**. Les points ci-dessous sont des décisions de paramétrage / durcissement, pas
> une reconstruction.

1. **Compte PCEC de la contrepartie « produit »**
   - Utilisé aujourd'hui : **`717003`** « Commissions perçues - Commission sur crédit »
     (via `product.account_commission_credit_id`, défaut `_pcec_default('717003')`).
   - `420010` **n'existe pas** dans le dépôt (ni compte, ni mapping) — origine à préciser.
   - Le mapping PCG2005 du dépôt suggérait plutôt `708200`.
   - ➡️ Confirmer : on **garde `717003`** (recommandé — c'est cohérent, déjà en prod, déjà
     testé) ou on bascule sur un autre compte ? Si bascule, est-ce un changement de **défaut
     produit** (impacte les nouveaux produits) ou un **reparamétrage** des produits existants
     (PRET RURAL & co) ?

2. **Journal**
   - Champ dédié déjà en place : `product.fee_journal_id`, défaut **`CRE`** (Crédits, type
     *cash*), compte de trésorerie = `journal.default_account_id` (`100001` Espèces sur
     SEFOR).
   - ➡️ Le défaut `CRE` convient-il, ou faut-il **`CAI`** (Caisse) par défaut ? Règle par
     agence : uniforme, ou certaines agences encaissent les frais en banque (`BQ*`) ?
     (Le champ le permet déjà produit par produit — la question est juste le défaut / la
     consigne de paramétrage.)

3. **Champ de lien**
   - `fee_move_id` (`Many2one('account.move')`, `readonly`, `copy=False`) existe, est typé,
     est peuplé, est affiché, et l'écriture remonte **aussi** dans `move_ids` / le compteur
     « Écritures ».
   - ➡️ On **réutilise `fee_move_id` tel quel** (recommandé) ? Renommage du libellé
     souhaité ? Faut-il aussi le peupler dans le chemin **« frais nettés du décaissement »**
     (`fee_charged_before_disbursement = False`), où il reste vide par conception aujourd'hui ?

4. **Double-clic / double comptabilisation**
   - Gardes actuelles : `fee_paid` (serveur + vue) + bouton web auto-désactivé + test
     `test_charge_fee_twice_blocked`. Atomique dans la transaction.
   - Gap : pas de verrou ligne → double post possible sous **vraie** concurrence (non
     atteignable en pratique avec `workers = 0`).
   - ➡️ On considère l'existant **suffisant** (mono-worker) ou on ajoute un garde-fou
     structurel (verrou `FOR UPDATE NOWAIT` en tête de `action_charge_fee`, ou contrainte
     d'unicité sur l'écriture de frais par crédit) ?

---

## Annexe — fichiers & points d'entrée

| Élément | Emplacement |
|---|---|
| `action_charge_fee` | `microfinance_loan_management/models/microfinance_loan.py:1577` |
| `_prepare_fee_move` | `microfinance_loan.py:1560` |
| `_prepare_disbursement_move` (nettage frais) | `microfinance_loan.py:1529` (lignes frais 1543-1549) |
| `fee_paid` / `fee_move_id` (champs) | `microfinance_loan.py:230-231` |
| `move_ids` (O2m inverse) | `microfinance_loan.py:175` |
| `AccountMove.microfinance_loan_id` | `microfinance_loan.py:2132` |
| Bouton vue | `views/microfinance_loan_views.xml:72` ; champs frais L192-194 |
| `account_commission_credit_id` (défaut `717003`) | `microfinance_loan_product.py:315-318` |
| `fee_journal_id` (défaut `CRE`) | `microfinance_loan_product.py:353` |
| `fee_charged_before_disbursement` | `microfinance_loan_product.py:360` |
| `_get_account` (variante individuel/groupe) | `microfinance_loan_product.py:434` |
| `_pcec_default` / `_journal_default` | `microfinance_loan_product.py:6` / `:19` |
| `717003` (déclaration sous-compte) | `microfinance_loan_management/hooks.py:45` |
| Liste `JOURNALS` | `hooks.py` (~L68) |
| Pattern écriture remboursement | `microfinance_loan_payment.py:157` (`_prepare_payment_move`), `:188` (`action_post`), `:225` (`_reverse_posted_payment`) |
| Tests frais | `microfinance_loan_management/tests/test_fee.py` |
| Preuve réelle SEFOR | crédit `IS/003362` → `account_move` id `1983` (`CSH1/2026/00003`, posted, 100001 / 717003, 25 000) |
