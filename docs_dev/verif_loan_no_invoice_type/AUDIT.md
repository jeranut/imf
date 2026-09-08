# Audit — Vérification : aucune écriture crédit en type facture

Audit **lecture seule** (Lot 0). Aucune modification de code.

## Verdict

**Aucune écriture en type facture détectée côté `microfinance.loan`.** Les 8 points de
création d'`account.move` du module crédit (et de `microfinance_fond_contribution`, même
patron) créent tous des écritures `move_type = 'entry'` (valeur par défaut Odoo, jamais
surchargée), sur des journaux `cash`/`bank`/`general` (jamais `sale`/`purchase`), avec des
lignes `line_ids` classiques (`debit`/`credit` explicites), jamais `invoice_line_ids`.
Confirmé en base réelle (SEFOR) : **100 % des `account.move` existants, tous modules
confondus, sont `move_type = 'entry'`** (12/12).

---

## 1. Table exhaustive des créations d'`account.move`

`grep` sur `env['account.move']` dans `microfinance_loan_management/models/*.py` (aucune
autre occurrence ailleurs dans le dépôt, extensions incluses — `microfinance_savings_management`
ne crée jamais d'`account.move` depuis une méthode de `microfinance.loan`) :

| Fichier | Ligne | Méthode appelante | Helper `_prepare_*` | `move_type` dans le dict | Journal utilisé |
|---|---|---|---|---|---|
| `microfinance_loan.py` | 914 | `action_approve()` | `_prepare_fee_receivable_move` | absent → défaut Odoo | `product.fee_engagement_journal_id` |
| `microfinance_loan.py` | 1699 | `action_charge_fee()` (rattrapage engagement) | `_prepare_fee_receivable_move` | absent → défaut Odoo | `product.fee_engagement_journal_id` |
| `microfinance_loan.py` | 1707 | `action_charge_fee()` (règlement) | `_prepare_fee_settlement_move` | absent → défaut Odoo | `product.fee_journal_id` |
| `microfinance_loan.py` | 1883 | `action_disburse()` | `_prepare_disbursement_move` | absent → défaut Odoo | `product.disbursement_journal_id` |
| `microfinance_loan.py` | 1933 | `action_confirm_write_off()` | `_prepare_writeoff_move` | absent → défaut Odoo | journal `type='general'` (recherche dynamique société) |
| `microfinance_loan.py` | 1995 | `action_post_provisions()` | `_prepare_provision_move` | absent → défaut Odoo | `_get_misc_operations_journal()` (`type='general'`) |
| `microfinance_loan_payment.py` | 193 | `action_post()` (remboursement) | `_prepare_payment_move` | absent → défaut Odoo | `payment.journal_id` (produit `payment_journal_id`) |
| `microfinance_fond_contribution.py` | 124 | `action_post()` (contribution bailleur) | `_prepare_contribution_move` | absent → défaut Odoo | `contrib.journal_id` (produit `journal_id`, `bank`/`cash`) |

`grep -rn "move_type" microfinance_loan_management/models/*.py` → **zéro résultat**. Aucun
des 8 dicts retournés par un `_prepare_*_move()` ne porte la clé `move_type`.

## 2. Valeur par défaut réellement appliquée par Odoo — confirmée, pas supposée

`odoo/addons/account/models/account_move.py` :

```python
move_type = fields.Selection(
    selection=[
        ('entry', 'Journal Entry'),
        ('out_invoice', 'Customer Invoice'), ('out_refund', 'Customer Credit Note'),
        ('in_invoice', 'Vendor Bill'), ('in_refund', 'Vendor Credit Note'),
        ('out_receipt', 'Sales Receipt'), ('in_receipt', 'Purchase Receipt'),
    ],
    string='Type', required=True, readonly=True, tracking=True,
    change_default=True, index=True,
    default="entry",
)
```

`default="entry"` au niveau du champ lui-même. Vérifié aussi qu'aucun des 8 appels
`.with_context(...)` ne pose de clé `default_move_type` (seul `default_loan_id=False,
default_loan_line_id=False` est passé partout) — pas de détournement du défaut par le
contexte non plus. **`move_type` vaut donc `'entry'` pour chacune des 8 créations,
sans exception.**

## 3. Confirmation point par point des helpers déjà connus/documentés

| Helper | `move_type` | Constat |
|---|---|---|
| `_prepare_disbursement_move` | `entry` (défaut) | Décaissement principal (+ nettage frais si `fee_charged_before_disbursement=False`). `line_ids` classiques. |
| `_prepare_payment_move` (L157, `microfinance_loan_payment.py`) | `entry` (défaut) | Remboursement, ventilation intérêt/principal/pénalité en plusieurs lignes `debit`/`credit`. |
| `_prepare_fee_settlement_move` (règlement frais — anciennement `_prepare_fee_move`) | `entry` (défaut) | Débit caisse / crédit créance ou commission. |
| `_prepare_fee_receivable_move` (engagement créance frais, Option A) | `entry` (défaut) | Débit 208005 / crédit 717003, journal OD. |
| **Autres trouvés** : `_prepare_writeoff_move` (radiation) | `entry` (défaut) | Débit perte sur créance / crédit sortie prêt client. |
| **Autres trouvés** : `_prepare_provision_move` (provision) | `entry` (défaut) | Dotation/reprise provision, 2 lignes signées selon le sens du delta. |
| **Autres trouvés** : `_prepare_contribution_move` (fonds bailleur, module non-loan mais même patron) | `entry` (défaut) | Dépôt/retrait bailleur, structurellement identique à `_prepare_disbursement_move` (le commentaire du code le dit explicitement : « Squelette identique à MicrofinanceLoan._prepare_disbursement_move() »). |

Aucun `_prepare_*_move` supplémentaire trouvé dans le module (recherche exhaustive
`def _prepare.*move` sur tous les fichiers de `models/`).

## 4. Type des journaux utilisés — confirmé `cash`/`bank`/`general`, jamais `sale`/`purchase`

Déclarations de champ (`microfinance_loan_product.py`) :

| Champ | Domaine déclaré |
|---|---|
| `disbursement_journal_id` | `[('type', 'in', ('bank','cash')), ...]` |
| `payment_journal_id` | `[('type', 'in', ('bank','cash')), ...]` |
| `fee_journal_id` | `[('type', 'in', ('bank','cash')), ...]` |
| `fee_engagement_journal_id` | `[('type', '=', 'general'), ...]` |
| `journal_id` (fond_contribution) | `[('type', 'in', ('bank','cash')), ...]` |

Radiation/provision : recherche dynamique `[('company_id', '=', ...), ('type', '=', 'general')]`
(jamais `sale`/`purchase`, jamais de journal fixé par référence statique).

**Vérifié en base SEFOR** — journaux réellement configurés sur les 3 produits crédit :

| Produit | Journal décaissement | type | Journal remboursement | type | Journal frais | type |
|---|---|---|---|---|---|---|
| PRET RURAL | CAI | `cash` | CRE | `cash` | CSH1 | `cash` |
| PRET SUCESIVE RURAL | CRE | `cash` | CRE | `cash` | CRE | `cash` |
| PRET FONCTIONNAIRE | CRE | `cash` | CRE | `cash` | CRE | `cash` |

Aucun journal `sale`/`purchase` en jeu nulle part dans le module crédit — le domaine des
champs l'exclut structurellement (pas seulement « il se trouve qu'aucun n'est configuré
ainsi »).

## 5. Lignes d'écriture — `account.move.line` classique, jamais `invoice_line_ids`

Les 8 `_prepare_*_move()` retournent tous une clé **`line_ids`** (jamais
`invoice_line_ids`), en commandes ORM `(0, 0, {...})` portant explicitement `debit` et
`credit` (jamais `price_unit`/`quantity`/`tax_ids`, qui sont les clés du mécanisme
facture). Exemple représentatif (`_prepare_disbursement_move`) :

```python
'line_ids': [
    (0, 0, {'name': ..., 'partner_id': ..., 'account_id': principal_account.id, 'debit': self.loan_amount, 'credit': 0.0}),
    ...
]
```

Aucune trace de `tax_ids`, `price_unit`, `quantity`, `invoice_date`, `invoice_line_ids`,
ou de tout autre champ propre au mécanisme facture, dans l'ensemble des 8 helpers.

## 6. Comptes PCEC positionnés en lignes classiques

Les comptes cités (203001 principal, 717003 commission, 208005 créance frais, comptes de
pertes/provisions, comptes bailleur) sont tous passés via `account_id` sur une ligne
`(0, 0, {...})` de `line_ids`, jamais via un mécanisme de ligne de facture. Aucun de ces
comptes n'a de configuration fiscale (`tax_ids`) associée dans ces écritures.

## 7. Vérification en base réelle (SEFOR)

```sql
SELECT move_type, count(*) FROM account_move WHERE microfinance_loan_id IS NOT NULL GROUP BY move_type;
-- entry | 3

SELECT move_type, count(*) FROM account_move WHERE microfinance_fond_contribution_id IS NOT NULL GROUP BY move_type;
-- entry | 2

SELECT move_type, count(*) FROM account_move GROUP BY move_type;
-- entry | 12   (TOUS les account.move de la base, tous modules confondus)
```

**Aucun `account.move` de type `out_invoice`/`in_invoice`/`out_refund`/`in_refund` n'existe
dans la base**, ni lié au module crédit ni ailleurs. Rien à corriger, rien à migrer.

## Note (hors périmètre de ce lot)

Le même contrôle rapide (`grep move_type`) sur `microfinance_savings_management` ne
trouve aucune occurrence non plus (même absence de surcharge, même défaut `entry`
attendu) — cohérent avec ce lot, mais **non vérifié en profondeur ici** (hors scope :
cette demande porte explicitement sur `microfinance.loan`). Si un audit formel du même
type est voulu côté épargne, il faudrait le scoper séparément.

---

## Annexe — points d'entrée

| Élément | Emplacement |
|---|---|
| `_prepare_disbursement_move` | `microfinance_loan.py:1588` |
| `_prepare_fee_receivable_move` | `microfinance_loan.py:1619` |
| `_prepare_fee_settlement_move` | `microfinance_loan.py:1644` |
| `_prepare_writeoff_move` | `microfinance_loan.py:1905` |
| `_prepare_provision_move` | `microfinance_loan.py:1953` |
| `_prepare_payment_move` | `microfinance_loan_payment.py:157` |
| `_prepare_contribution_move` | `microfinance_fond_contribution.py:85` |
| Déclaration `move_type` (core Odoo) | `odoo/addons/account/models/account_move.py:145-162` |
| Domaines des journaux crédit | `microfinance_loan_product.py:128-136,365-375` |
