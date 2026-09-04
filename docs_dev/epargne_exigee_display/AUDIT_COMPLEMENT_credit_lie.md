# Lot 0 (complément) — Champ "Crédit lié" non restreint sur microfinance.savings.account

Audit en lecture seule. **Aucune modification de code, de vue, ou de donnée.** Note : le rapport
d'audit Lot 0 initial du chantier "Épargne exigée display" n'a pas été retrouvé dans ce dépôt
(`docs_dev/`) - ce complément est autonome et ne suppose aucun contenu de ce rapport initial.

## Résumé

**Confirmé sur les 3 points factuels de l'audit, et le trou fonctionnel est bien réel : il
n'existe AUCUN code de création automatique d'un compte épargne obligatoire lié à un crédit,
nulle part dans le dépôt.** Ce n'est donc pas un simple oubli de `readonly` (Option A) : c'est un
mécanisme jamais implémenté (Option B). Le champ `microfinance_loan_id` et la valeur
`product_type = 'compulsory'` ("Obligatoire (liée à un crédit)") existent au niveau du modèle,
mais rien ne les alimente ni ne les exploite en dehors d'un seul garde-fou à la clôture.

## 1. Flux de création automatique

**Recherche exhaustive, confirmée vide** : `grep -rn "savings.account'\].create" --include="*.py"`
sur tout le dépôt ne retourne **aucun résultat hors des fichiers de tests**
(`microfinance_savings_management/models/microfinance_savings_account.py:29` déclare le champ,
mais aucun `create()` programmatique de ce modèle n'existe dans le code applicatif). Ni à
l'approbation (`action_approve`), ni au décaissement (`action_disburse`), ni à la validation du
produit de crédit, ni ailleurs : aucun déclencheur ne crée de compte épargne.

Le seul mécanisme réellement actif et automatique en lien avec l'épargne exigée est
`_check_guarantee_savings_eligibility()` (`microfinance_loan_extension.py`, appelée depuis
`_check_eligibility` dès `action_submit`) - mais **structurellement différent** de ce que suppose
la question : il ne s'appuie pas sur un compte unique pré-assigné via `microfinance_loan_id`, il
**somme le solde de tous les comptes actifs du client sur le produit d'épargne garantie
configuré** (`guarantee_savings_product_id` sur le produit de crédit). Confirmé par
`docs_dev/savings/ecarts_lpf.md` (module `microfinance_savings_management`) : l'ancien
mécanisme à compte unique pré-assigné (`savings_requirement_type = 'upfront_apport'`) a été
**retiré** lors d'un lot antérieur, remplacé par ce mécanisme par pourcentage/somme de comptes -
**aucune migration de données nécessaire à l'époque car aucun enregistrement réel n'utilisait
`upfront_apport`**.

**Point à signaler explicitement, au-delà de la question posée** : ceci crée une ambiguïté de
conception à trancher avant le Lot 1. Le champ `microfinance_loan_id` et `product_type =
'compulsory'` semblent relever d'un troisième mécanisme, distinct à la fois de
`target_during_loan` (épargne cible pendant le remboursement, pas de compte dédié non plus - un
seul champ `savings_account_id` à choix MANUEL côté crédit, cf. point 4) et de la garantie par
pourcentage (`guarantee_savings_*`, ci-dessus). **Aucun des deux mécanismes actuellement actifs
et automatiques n'utilise `microfinance_loan_id`/`compulsory`** - le seul usage réel de ces deux
éléments dans tout le code applicatif est le garde-fou de `action_close()` (interdiction de
clôturer un compte obligatoire lié à un crédit actif, cf. point 4). Il est donc possible que
`compulsory`/`microfinance_loan_id` soit un concept **antérieur, jamais achevé**, plutôt qu'une
fonctionnalité active à réparer telle quelle - à confirmer avec Micka avant de concevoir le Lot 1
(cf. section "Points à trancher" ci-dessous).

## 2. `readonly`/éditable du champ

**Confirmé : le champ n'est readonly nulle part, dans aucun état.** Déclaration
(`microfinance_savings_account.py:29-32`) :
```python
microfinance_loan_id = fields.Many2one(
    'microfinance.loan', string='Crédit lié',
    help="Renseigné quand ce compte est une épargne obligatoire constituée pour un crédit précis.",
)
```
Aucun `readonly=`. Vue (`microfinance_savings_account_views.xml:62`) : `<field
name="microfinance_loan_id"/>`, sans attribut - ni `readonly=`, ni `domain=`, ni condition sur
`state`. **Recherche exhaustive confirmée** : c'est la SEULE vue référençant ce champ dans tout
le dépôt (aucune vue héritée ne le restreint ailleurs). Comportement **identique** sur un compte
"Nouveau" et sur un compte déjà lié/existant, quel que soit son état (`draft`/`active`/
`dormant`/`closed`) - éditable dans tous les cas, y compris sur un compte `active` ou `closed`.

## 3. Absence de domaine

**Confirmée.** Ni `domain=` au niveau de la déclaration du champ (ci-dessus), ni au niveau de la
vue. Rien ne restreint les crédits proposés au titulaire du compte (`partner_id`) - n'importe
quel crédit du système est sélectionnable, quel que soit son titulaire, exactement comme observé
sur le terrain.

**Contraste utile** : le champ inverse, `savings_account_id` sur `microfinance.loan` (`"Compte
épargne (prélèvement)"`, `microfinance_loan_extension.py:16-20`), a lui un domaine correct et
déjà en place : `domain="[('partner_id', '=', partner_id)]"`. Ceci confirme que l'absence de
domaine sur `microfinance_loan_id` est très probablement un oubli plutôt qu'un choix délibéré -
le motif est déjà connu et appliqué ailleurs dans le même module.

## 4. Cause directe confirmée du constat terrain (smart button "Épargne")

`action_view_savings_accounts()` (`microfinance_loan_extension.py:73-81`) :
```python
def action_view_savings_accounts(self):
    self.ensure_one()
    return {
        'type': 'ir.actions.act_window',
        'name': _('Épargne'),
        'res_model': 'microfinance.savings.account',
        'view_mode': 'tree,form',
        'domain': [('partner_id', '=', self.partner_id.id)],
        'context': {'default_partner_id': self.partner_id.id},
    }
```
**Confirmé exactement comme anticipé par l'audit** : le contexte ne pousse que
`default_partner_id`, jamais `default_microfinance_loan_id` - alors que `self` (le crédit, donc
`self.id`) est parfaitement connu à cet instant. C'est la cause directe, confirmée, du champ vide
observé en création depuis `IS/003362 / Épargne / Nouveau`.

## Chemins de création actuels (tous manuels, confirmé)

1. **Smart button "Épargne" depuis la fiche crédit** (`action_view_savings_accounts`) : contexte
   incomplet (ci-dessus) - le crédit d'origine est perdu dès l'ouverture du formulaire.
2. **Menu Épargne direct** (création hors contexte crédit) : aucun contexte crédit à propager,
   par nature - l'agent doit alors sélectionner manuellement le bon crédit dans la liste
   ouverte, sans aucune garantie que ce soit celui du bon titulaire (domaine absent, point 3).
3. **Import/API** : aucune contrainte (`@api.constrains`) ne vérifie la cohérence
   `microfinance_loan_id.partner_id == partner_id` - confirmé par recherche exhaustive des
   contraintes du modèle (aucune ne porte sur ces deux champs ensemble).

Aucun de ces chemins ne correspond à la "création automatique par le système" confirmée par
Micka comme étant le comportement voulu - parce que ce mécanisme n'existe pas.

## Recommandation pour le Lot 1

**Ce n'est pas un simple passage en readonly (Option A) : la création automatique est un
mécanisme à concevoir et implémenter (Option B)**, pas seulement à sécuriser après coup. Deux
volets distincts, à trancher avec Micka :

**Volet immédiat (correctif ciblé, faible risque)** : ajouter `default_microfinance_loan_id:
self.id` au contexte de `action_view_savings_accounts()`, et un `domain="[('partner_id', '=',
partner_id)]"` sur le champ `microfinance_loan_id` (même motif que `savings_account_id`, point
3) - referme l'incohérence de données la plus visible (lier le compte au crédit d'un autre
client) sans attendre la conception complète de l'automatisation, mais **ne** répond **pas** à
la demande de Micka ("créé automatiquement", pas "pré-rempli puis confirmé manuellement").

**Volet structurel (création réellement automatique)** : à concevoir - nécessite de trancher
au moins :
- Quel déclencheur exact (approbation ? décaissement ? une valeur spécifique de
  `savings_requirement_type` ou un nouveau champ dédié, puisque `compulsory` n'est référencé
  nulle part comme condition de déclenchement aujourd'hui) ?
- Quel produit d'épargne assigner automatiquement (aucun champ actuel ne désigne un "produit
  d'épargne obligatoire par défaut" pour un produit de crédit - à la différence de
  `guarantee_savings_product_id`, qui existe déjà pour l'autre mécanisme) ?
- **Ambiguïté de conception à lever en priorité** (section 1) : `microfinance_loan_id`/
  `compulsory` sont-ils un concept toujours voulu et distinct de `guarantee_savings_*`
  (épargne garantie, déjà fonctionnelle) et de `target_during_loan` (épargne cible, déjà
  fonctionnelle) ? Ou un concept antérieur jamais achevé, à fusionner avec l'un des deux
  mécanismes existants plutôt qu'à compléter tel quel ? Le seul usage réel actuel
  (`action_close`, garde-fou de clôture) fonctionnerait à l'identique quel que soit le
  mécanisme choisi pour peupler `microfinance_loan_id`, donc ce choix ne clôt aucune porte.
