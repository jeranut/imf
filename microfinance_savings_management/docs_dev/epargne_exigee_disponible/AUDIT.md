# Lot 0 — Audit : Calcul automatique Épargne exigée / Épargne disponible

Audit en lecture seule (code + SQL `SELECT` sur SEFOR). **Aucune modification de code, de vue,
ni de donnée.**

## Découverte majeure : le mécanisme demandé existe déjà, testé, en production - sous d'autres noms

**Ne pas écrire de nouvelle logique de calcul.** `microfinance_savings_management/models/
microfinance_loan_extension.py` porte déjà, sur `microfinance.loan`, exactement les deux valeurs
demandées, avec la même formule et la même résolution multi-comptes :

- `guarantee_savings_required` (ligne 28-30, `store=True`) = `loan.loan_amount *
  product_id.guarantee_savings_percent / 100.0` (`_compute_guarantee_savings_required`,
  ligne 101-104).
- `guarantee_savings_balance` (ligne 31-35) = somme des soldes des comptes
  `microfinance.savings.account` du client, filtrés sur `product_id ==
  guarantee_savings_product_id` ET `state == 'active'` (`_compute_guarantee_savings_balance`,
  ligne 106-117) - **0.0 sans erreur** si le client n'a pas encore de compte sur ce produit.

Ces deux champs sont déjà **utilisés en production** par `_check_guarantee_savings_eligibility()`
(appelée depuis `_check_eligibility`, donc dès `action_submit`) pour bloquer une demande de
crédit si l'épargne garantie est insuffisante - mécanisme validé, testé
(`tests/test_guarantee_savings.py`, 5 tests), documenté dans
`microfinance_savings_management/docs_dev/savings/ecarts_lpf.md`.

**`guarantee_savings_required` est même déjà `related=` sur `microfinance.loan.application`**
(`microfinance_loan_application_extension.py:29-31`) - mais seulement comme relais technique
invisible en vue (limite Odoo : `invisible=` ne peut pas traverser `loan_id.xxx` directement),
sa propre docstring dit explicitement "valeur sans intérêt propre ici". `guarantee_savings_
balance`, en revanche, **n'est relayé nulle part** sur le dossier à ce jour.

**Recommandation pour le Lot 1** : `required_savings` et `available_savings` doivent devenir de
simples champs `related=` vers ces deux champs déjà existants sur `microfinance.loan` -
**pas un nouveau `compute` dupliquant la recherche/somme** (le draft du Lot 1 fourni avec la
demande réécrit une logique déjà écrite, testée, et déployée ailleurs). Répond de fait, sans
code supplémentaire, à toutes les questions du tableau de décision de la demande (la résolution
"plusieurs comptes → somme" - Option 2 - est déjà le comportement réel et testé de
`guarantee_savings_balance`).

## 1. Noms de champs confirmés sur `microfinance.loan.application`

| Champ (libellé) | Nom technique | Type/état actuel |
|---|---|---|
| Épargne exigée (demande) | `required_savings` | `Monetary`, saisie libre, aucun `compute`/`store`/`readonly` |
| Épargne disponible | `available_savings` | `Monetary`, saisie libre, aucun `compute`/`store`/`readonly` |
| Montant demandé | `requested_amount` | `related='loan_id.loan_amount'`, `readonly=True` - **PAS `amount_requested`** comme supposé dans le draft |

**Point important, à ne pas manquer** : le code actuel documente déjà, dans le `help=` de ces
deux champs, une décision explicite antérieure de les laisser en saisie libre :
- `required_savings` : *"aucun champ équivalent sur microfinance.loan à refléter (pas de notion
  d'épargne exigée pour la demande initiale, avant tout avis CA/CDAG)"*.
- `available_savings` : *"aucun champ équivalent sur microfinance.loan (information externe,
  pas une valeur dérivée du crédit)"*.

Cette affirmation est **devenue fausse** entretemps (le chantier "épargne garantie de crédit",
`docs_dev/savings/ecarts_lpf.md`, a introduit `guarantee_savings_required`/`guarantee_savings_
balance` après cette décision) - ce chantier **inverse une décision explicite documentée**, pas
seulement un oubli. À signaler à Micka comme confirmation, pas comme un problème : le nouveau
besoin est légitime, mais il faudra retirer/corriger ces deux `help=` obsolètes dans le Lot 1.

## 2. Champs produit confirmés

`guarantee_savings_percent` (`Float`) et `guarantee_savings_product_id` (`Many2one` vers
`microfinance.savings.product`) existent bien sur `microfinance.loan.product`
(`microfinance_loan_product_extension.py:50-58`), avec une contrainte déjà en place
(`_check_guarantee_savings_config`, ligne 66+) : pourcentage renseigné ⇒ produit requis.

**Configuration réelle sur SEFOR** : un seul produit configuré, **PRET RURAL, `guarantee_savings_
percent = 5`** (pas 20 comme l'exemple de la demande - à corriger si cet exemple sert de
référence ailleurs), produit garanti **EP MORA**.

## 3. Résolution du compte d'épargne du client

- **Plusieurs comptes possibles avec le même produit** : oui, déjà géré - `guarantee_savings_
  balance` fait la **somme** de tous les comptes actifs sur ce produit (Option 2 du tableau de
  décision de la demande, déjà en place et testée - `test_guarantee_savings.py`).
- **Client sans compte sur le produit garanti** : déjà géré, renvoie `0.0` sans erreur
  (`if not guarantee_product or not loan.partner_id: loan.guarantee_savings_balance = 0.0`).
- **`microfinance.savings.account.balance`** : confirmé `compute='_compute_balance',
  store=True` - fiable en lecture directe, recalculé automatiquement à chaque transaction postée
  (`@api.depends('transaction_ids.amount', 'transaction_ids.transaction_type',
  'transaction_ids.state')`).
- **État filtré** : `state == 'active'` (valeur technique anglaise - le draft de la demande
  utilisait `'actif'`, à corriger). Les comptes `dormant`/`closed`/`draft` ne comptent pas -
  comportement déjà établi, à conserver par cohérence.

**Attention à ne pas confondre avec un champ voisin déjà existant** : `savings_amount`
(`microfinance_loan_application_extension.py:8-21`, déjà `related`/compute sur le dossier)
somme **tous** les comptes actifs du client, **sans filtrer par produit** - concept différent de
`guarantee_savings_balance` (filtré sur le produit garanti spécifique du crédit). Le nouveau
`available_savings` doit pointer vers `guarantee_savings_balance` (filtré), pas vers
`savings_amount` (global) - à ne pas confondre au moment d'écrire le `related=`.

## 4. Champ montant confirmé

`requested_amount` (voir tableau section 1) - `related='loan_id.loan_amount'`. Le calcul de
`required_savings` devrait donc naturellement s'appuyer sur la même source
(`loan_id.loan_amount`) - ce qui est exactement ce que fait déjà `guarantee_savings_required`
(`loan.loan_amount * ...`). Aucune divergence entre "montant demandé" et la base du calcul déjà
existant.

## 5. Recensement des dossiers en désaccord

**Aucun.** SEFOR ne compte que **3 dossiers d'instruction au total**, et **aucun n'a de valeur
saisie** sur `required_savings` ni `available_savings` (`0` ligne avec une valeur non nulle sur
l'un ou l'autre). Migration de données : **sans objet, aucun écart à corriger.**

## Recommandation Lot 1 (ajustée par rapport au draft fourni)

```python
# microfinance_savings_management/models/microfinance_loan_application_extension.py
required_savings = fields.Monetary(
    related='loan_id.guarantee_savings_required', string='Épargne exigée (demande)', readonly=True,
)
available_savings = fields.Monetary(
    related='loan_id.guarantee_savings_balance', string='Épargne disponible', readonly=True,
)
```

- **Retirer la déclaration actuelle** de ces deux champs dans `microfinance_loan_management/
  models/microfinance_loan_application.py` (base module) - ils doivent être **redéfinis** dans
  l'extension épargne (comme `guarantee_savings_required` l'est déjà), pas coexister en double
  déclaration. Corriger/retirer leurs `help=` obsolètes au passage.
- **Aucun nouveau champ sur `microfinance.loan`, aucune nouvelle méthode de calcul** - tout
  existe déjà, testé.
- Vue : aucun changement nécessaire (pas de `readonly=` explicite actuellement, l'attribut
  `readonly=True` du champ suffit, même pattern que `ca_required_savings`/`cdag_required_
  savings` juste au-dessus dans la même vue).
- Vérifier qu'aucun `write()` manuel sur ces deux champs ne subsiste ailleurs (wizard, import
  LPF) avant de figer le comportement readonly - recherche à faire en Lot 1, pas effectuée ici
  (lecture du modèle uniquement pour cet audit).

## Points à trancher avec Micka avant le Lot 1

1. **Confirmer l'inversion de la décision documentée** (section 1) - accepter que
   `required_savings`/`available_savings` réutilisent purement et simplement `guarantee_savings_
   required`/`guarantee_savings_balance`, plutôt que d'écrire une logique dédiée séparée.
2. **`savings_amount` vs `guarantee_savings_balance`** (section 3) : confirmer que c'est bien la
   version **filtrée par produit garanti** qui est voulue pour `available_savings` (comme le
   draft de la demande le suggère), pas la somme globale déjà utilisée ailleurs sous
   `savings_amount`.
3. **Duplication mineure assumée** : `guarantee_savings_required` (relais technique existant,
   vue seulement) et `required_savings` (nouveau, même valeur) coexisteront sur le même modèle -
   acceptable (déjà le style de ce module), à confirmer plutôt qu'à fusionner silencieusement.
