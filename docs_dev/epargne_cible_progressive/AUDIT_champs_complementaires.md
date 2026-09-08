# LOT 0 — Audit : Ajout "Épargne ciblé comptabilisé" et "Date limite épargne ciblée"

Audit en lecture seule. Aucune modification de code, de vue ou de données.

## 1. Extrait XML actuel du bloc concerné

Le bloc "Résumé financier" est natif à `microfinance_loan_management`
(`views/microfinance_loan_views.xml:210-249`) ; les champs épargne y sont injectés par
héritage depuis `microfinance_savings_management`
(`views/microfinance_loan_views_inherit.xml:17-23`) :

```xml
<!-- microfinance_loan_management/views/microfinance_loan_views.xml:246-248 -->
<field name="fee_move_id" readonly="1"/>
<field name="net_disbursed_amount" readonly="1"/>
<field name="bypass_cash_balance" invisible="state != 'approved'"/>
</group>
```

```xml
<!-- microfinance_savings_management/views/microfinance_loan_views_inherit.xml:13-23 -->
<field name="co_borrower_id" position="after">
    <field name="savings_requirement_type" invisible="1"/>
    <field name="savings_account_id"/>
</field>
<field name="fee_move_id" position="after">
    <field name="savings_target_amount" invisible="savings_requirement_type != 'target_during_loan'" readonly="1"/>
    <field name="savings_target_reached" invisible="savings_requirement_type != 'target_during_loan'" readonly="1"/>
    <field name="guarantee_savings_required" invisible="not guarantee_savings_required" readonly="1"/>
    <field name="guarantee_savings_balance" invisible="not guarantee_savings_required" readonly="1"/>
    <field name="guarantee_savings_verified" invisible="not guarantee_savings_required" readonly="1"/>
</field>
```

`savings_target_amount` ("Épargne cible (pendant remboursement)") s'insère donc **juste
après `fee_move_id`**, dans le groupe "Résumé financier" — pas une section séparée. Il est
`readonly="1"` et `invisible` sauf si `product_id.savings_requirement_type ==
'target_during_loan'` (champ relais `savings_requirement_type`, `related`, chargé en
`invisible="1"` juste pour servir de condition — pattern déjà en place pour
`guarantee_savings_required`/`balance`/`verified` juste en dessous).

Confirmé : c'est bien le champ "Épargne cible" identifié dans l'audit précédent
(`savings_target_amount`, `microfinance_loan_extension.py:22-23`) — aucun nouveau champ à
créer pour celui-ci, seul son emplacement/label est à vérifier (voir §5).

## 2. `savings_account_id` et `balance` — noms et types exacts

- `microfinance.loan.savings_account_id` : `Many2one('microfinance.savings.account', ...)`
  (`microfinance_loan_extension.py:16-21`) — compte source du prélèvement automatique **et**
  compte dans lequel est vérifiée la cible d'épargne progressive (double usage, confirmé par
  le `help` du champ lui-même).
- `microfinance.savings.account.balance` : `fields.Monetary(compute='_compute_balance',
  store=True, string='Solde')` (`microfinance_savings_account.py:38`) — champ stocké,
  recalculé automatiquement (c'est lui qui alimente déjà `_compute_savings_target_reached`
  via `savings_account_id.balance`, cf. audit précédent §3).

**Recommandation pour "Épargne ciblé comptabilisé"** : un champ `related` simple,
`related='savings_account_id.balance'`, `store=True` (pour rester cohérent avec les autres
champs du bloc, tous stockés, et pour permettre un futur tri/regroupement en vue liste sans
recalcul). Pas besoin d'un `compute` dédié : c'est une simple lecture du solde, aucune
transformation. Un `related` non stocké fonctionnerait aussi mais romprait la convention
"tout est stocké" du bloc.

## 3. Comportement si `savings_account_id` est vide

`savings_account_id` est un `Many2one` non `required` — confirmé vide par défaut sur tout
crédit qui n'a pas encore de compte épargne lié (aucune contrainte `@api.constrains` ne
l'impose, aucun `required=True` dans sa définition). Un `related` sur un `Many2one` vide
retourne la valeur par défaut du type (`0.0` pour un `Monetary`) sans lever d'erreur —
comportement Odoo standard, déjà implicitement vérifié par `_compute_savings_target_reached`
qui teste explicitement `bool(loan.savings_account_id)` avant d'utiliser `.balance` (ligne
96 de `microfinance_loan_extension.py`) précisément parce que ce cas (compte non renseigné)
est un cas normal et attendu, pas une exception.

**Conclusion** : "Épargne ciblé comptabilisé" affichera `0,00 Ar` tant qu'aucun compte
épargne n'est lié au crédit — aucun risque de crash.

## 4. Convention de formatage monétaire

Tous les champs `Monetary` du bloc "Résumé financier" (`principal_total`, `balance_total`,
`provision_amount`, `savings_target_amount`, `guarantee_savings_required`, etc.) sont
affichés **sans attribut `widget` explicite** — le rendu monétaire (symbole de devise,
formatage) est automatique pour tout champ de type `Monetary` en vue formulaire Odoo dès lors
que le modèle expose un `currency_id` (déjà le cas ici, utilisé implicitement par tous les
champs Monetary existants). **À reproduire à l'identique** : ni `widget="monetary"` ni
formatage manuel, juste `<field name="..." readonly="1"/>`.

## 5. Emplacement recommandé pour les 2 nouveaux champs

Les insérer dans le même `xpath` déjà utilisé par le module épargne (`fee_move_id` position
`after`), directement à la suite de `savings_target_amount`/`savings_target_reached`, avant
le bloc `guarantee_savings_*` (qui concerne un mécanisme différent — épargne garantie de
crédit, pas épargne cible progressive) :

```xml
<field name="fee_move_id" position="after">
    <field name="savings_target_amount" invisible="savings_requirement_type != 'target_during_loan'" readonly="1"/>
    <field name="savings_target_booked_amount" invisible="savings_requirement_type != 'target_during_loan'" readonly="1"/>  <!-- nouveau : "Épargne ciblé comptabilisé" -->
    <field name="savings_target_deadline" invisible="savings_requirement_type != 'target_during_loan'"/>  <!-- nouveau : "Date limite épargne ciblée", éditable -->
    <field name="savings_target_reached" invisible="savings_requirement_type != 'target_during_loan'" readonly="1"/>
    ...
</field>
```

**Visibilité conditionnelle proposée** : identique à `savings_target_amount`/
`savings_target_reached`, soit `invisible="savings_requirement_type != 'target_during_loan'"`
— cohérent avec le fait que ces deux nouveaux champs n'ont de sens que dans ce mode
d'exigence épargne (pas de raison de les afficher pour `none`, ni de créer une règle de
visibilité différente du reste du bloc).

Nom technique proposé pour "Date limite épargne ciblée" : `savings_target_deadline` (miroir
naturel de `savings_target_amount`/`savings_target_reached`, déjà dans
`microfinance_loan_extension.py`). Pas de proposition de nom arrêtée pour "Épargne ciblé
comptabilisé" dans le prompt d'origine — `savings_target_booked_amount` retenu par analogie
avec le vocabulaire déjà en place (`provision_posted_amount`/`fee_amount_due` utilisent tous
deux un participe/adjectif après le nom métier) ; à confirmer/ajuster avec Micka au Lot 1 si
un autre nom est préféré.

## 6. Groupes de sécurité à répliquer

**Aucun `groups=` n'est appliqué au niveau champ nulle part dans ce bloc** (ni sur les
champs natifs `microfinance_loan_management` du "Résumé financier", ni sur les champs ajoutés
par héritage `microfinance_savings_management`) — le contrôle d'accès aux champs de
`microfinance.loan` se fait uniquement au niveau modèle, via
`microfinance_loan_management/security/ir.model.access.csv` :

```
access_microfinance_loan_user,loan.user,model_microfinance_loan,group_microfinance_user,1,1,1,0
access_microfinance_loan_manager,loan.manager,model_microfinance_loan,group_microfinance_manager,1,1,1,1
access_microfinance_loan_finance,loan.finance,model_microfinance_loan,group_microfinance_finance,1,1,0,0
access_microfinance_loan_auditor,loan.auditor,model_microfinance_loan,group_microfinance_auditor,1,0,0,0
access_microfinance_loan_comptable,loan.comptable,model_microfinance_loan,group_microfinance_comptable,1,0,0,0
access_microfinance_loan_cashier,loan.cashier,model_microfinance_loan,group_microfinance_cashier,1,0,0,0
access_microfinance_loan_credit_committee,loan.credit_committee,model_microfinance_loan,group_microfinance_credit_committee,1,0,0,0
```

Les groupes `group_microfinance_user`, `group_microfinance_manager` et
`group_microfinance_finance` ont déjà `perm_write=1` sur `microfinance.loan` — c'est déjà
suffisant pour rendre `savings_target_deadline` éditable par ces trois profils sans aucune
ligne de sécurité supplémentaire à ajouter. `auditor`, `comptable`, `cashier`,
`credit_committee` restent en lecture seule (`perm_write=0`), donc naturellement exclus de
l'édition — comportement cohérent avec le champ éditable voisin `bypass_cash_balance`
(ligne 248, également sans `groups=` propre, qui repose sur les mêmes permissions modèle).

**Recommandation : ne pas ajouter de `groups=` sur le nouveau champ Date** — aucun champ
similaire du bloc n'en a, et un commentaire déjà présent dans la vue
(`microfinance_loan_views.xml:252-257`) documente explicitement qu'un `readonly` conditionné
à l'état a déjà été testé puis retiré ailleurs dans ce même formulaire à cause d'un piège
Odoo (`odoo/tests/form.py:405` : un champ `readonly` n'est jamais sauvegardé même modifié par
onchange) — signal supplémentaire pour garder ce nouveau champ simple (éditable sans
condition d'état ni groupe dans cette phase, conformément au prompt qui le veut "éditable
manuellement").

## Synthèse pour le Lot 1

1. `savings_target_amount` existe déjà, correctement affiché — aucun changement requis dessus.
2. Nouveau champ `savings_target_booked_amount` (nom à confirmer) : `related =
   'savings_account_id.balance'`, `store=True`, `string='Épargne ciblé comptabilisé'`, dans
   `microfinance_loan_extension.py` (module épargne, comme les champs voisins). `0,00 Ar` sûr
   si `savings_account_id` vide.
3. Nouveau champ `savings_target_deadline` : `fields.Date(string='Date limite épargne
   ciblée')`, simple, sans `compute` (mode de calcul à fournir plus tard par Micka), éditable
   sans restriction de groupe ni d'état.
4. Insertion vue : dans le même `xpath` `fee_move_id`/`position="after"` de
   `microfinance_loan_views_inherit.xml`, juste après `savings_target_amount`, avant
   `savings_target_reached`, avec la même condition `invisible=` que ses voisins.
5. Aucune ligne de sécurité (`ir.model.access.csv`) à ajouter — les permissions modèle
   existantes suffisent pour les deux nouveaux champs.

Aucune modification de code effectuée dans ce lot. Le Lot 1 sera généré après validation de
ce rapport par Micka (notamment le nom définitif de "Épargne ciblé comptabilisé" et la
confirmation de l'emplacement/ordre des champs).
