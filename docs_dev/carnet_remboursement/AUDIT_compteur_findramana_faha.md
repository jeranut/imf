# LOT 0 — Audit : Compteur "Findramana faha" (rang du crédit pour ce client)

Audit en lecture seule. Aucune modification de code, de vue ou de données.

## 1. Extrait XML actuel

`report_carnet_remboursement.xml:172` :

```xml
<div class="carnet-row"><u>Findramana faha</u> : <strong>4</strong> &#160;&#160; <u>Fifanarahana n°</u> <strong><span t-field="o.name"/></strong></div>
```

"4" est une chaîne codée en dur, indépendante du dossier imprimé — confirmé par le
commentaire du bloc (`report_carnet_remboursement.xml:158-169`, qui liste "Findramana faha"
parmi les éléments volontairement laissés en dur lors du lot précédent de dynamisation de ce
bloc).

## 2. Mécanisme de comptage réutilisable — trouvé, à deux endroits

### a. `_get_scoring_metrics()` (`microfinance_loan.py:751-793`) — le plus proche

```python
loan_domain = [('company_id', '=', self.company_id.id), ('partner_id', '=', self.partner_id.id)]
loans = Loan.search(loan_domain)
...
metrics = {
    ...
    'total_loans': len(loans),
    'active_loans': len(loans.filtered(lambda loan: loan.state == 'active')),
    'closed_loans': len(loans.filtered(lambda loan: loan.state == 'closed')),
    'defaulted_loans': len(loans.filtered(lambda loan: loan.state == 'defaulted')),
    ...
}
```

C'est un comptage de crédits par client déjà existant, mais **pas directement réutilisable
tel quel** pour ce lot : `total_loans` compte **tous les états sans exception** (y compris
`draft`, `enquete`, `avis_ca`, `avis_cdag`, `cancelled`), ce qui est adapté à un score de
risque (connaître l'historique complet, y compris les demandes abandonnées) mais pas à un
"rang du crédit" affiché sur un document client (qui ne devrait raisonnablement compter que
les dossiers réellement engagés — voir point 4).

### b. `_check_progressive_savings_eligibility()` (`microfinance_savings_management/models/microfinance_loan_extension.py:139-160`) — le plus pertinent pour la définition d'état

```python
previous_loan = self.search([
    ('company_id', '=', self.company_id.id),
    ('partner_id', '=', self.partner_id.id),
    ('id', '!=', self.id),
    ('product_id.savings_requirement_type', '=', 'target_during_loan'),
    ('state', 'in', ('active', 'closed', 'defaulted', 'written_off')),
], order='id desc', limit=1)
```

C'est **le seul endroit du code qui identifie explicitement "le crédit précédent" d'un
client** — exactement le besoin de ce lot. Deux éléments directement réutilisables :
- **La liste d'états `('active', 'closed', 'defaulted', 'written_off')`** comme définition
  de "crédit réellement engagé" (voir confirmation croisée au point 4).
- **`order='id desc'`** comme critère de tri chronologique (voir point 5).

Ce module (`microfinance_savings_management`) est cependant un dépendant de
`microfinance_loan_management` (pas l'inverse, cf. audits précédents de ce chantier) — la
logique elle-même n'est donc pas importable depuis `microfinance_loan_management` sans
dupliquer le filtre d'état ; elle sert ici de **précédent de conception à reproduire**, pas de
code à appeler directement.

### c. `res.partner.microfinance_loan_count` (`res_partner.py:130-140`)

```python
microfinance_loan_ids = fields.One2many('microfinance.loan', 'partner_id', string='Crédits')
microfinance_loan_count = fields.Integer(compute='_compute_microfinance_loan_count')

@api.depends('microfinance_loan_ids')
def _compute_microfinance_loan_count(self):
    for partner in self:
        partner.microfinance_loan_count = len(partner.microfinance_loan_ids)
```

Smart button "Crédits" du client — confirme qu'un compteur de crédits par partenaire existe
déjà dans l'UI, mais **sans filtre de société ni d'état** (compte tout, comme `total_loans`
en 2.a). Le domaine `[('partner_id', '=', self.id)]` d'`action_view_microfinance_loans()`
(`res_partner.py:174-183`) est le plus simple des trois exemples trouvés — cohérent avec la
décision déjà actée de ne pas filtrer par société (point 3).

**Conclusion** : aucun des trois mécanismes n'est directement appelable tel quel, mais leur
combinaison donne exactement la recette recommandée : domaine simple par `partner_id` (comme
2.c), filtré sur les états engagés (comme 2.b), trié par `id` (comme 2.b).

## 3. Portée multi-société — règle confirmée métier, PAS de contrainte serveur technique

**Constat sur les données réelles** : la base `SEFOR` ne compte que **4 crédits au total,
répartis sur 4 partenaires distincts** (`select partner_id, count(distinct company_id) ... having count(distinct company_id) > 1` → 0 ligne). **Aucun partenaire n'a aujourd'hui plus d'un
crédit**, donc impossible de constater sur données réelles un cas où le rang serait ≥ 2, ni un
cas de partage entre agences (le jeu de données actuel ne permet de tester ni l'un ni
l'autre).

**Recherche de contrainte technique** : `res.partner.company_id`
(`res_partner.py:40-46, 87-93`) est bien **documenté et appliqué par contrainte serveur**
(`_check_microfinance_company_required`) comme l'agence exclusive d'un client microfinance —
mais cette contrainte porte uniquement sur le fait qu'un `company_id` doit être renseigné sur
le partenaire, **pas** sur le fait que tous ses crédits (`microfinance.loan.company_id`)
doivent nécessairement correspondre à ce même `company_id`. **Aucune contrainte
(`@api.constrains`) trouvée dans `microfinance_loan.py` ne vérifie `loan.company_id ==
partner_id.company_id` à la création ou l'écriture d'un crédit.**

**Conclusion à signaler à Micka (hors périmètre de correction pour ce lot, comme demandé)** :
la règle "un client ne peut pas avoir de crédits dans plusieurs agences" est **une règle
métier réelle et documentée au niveau du partenaire**, mais **elle n'est aujourd'hui pas
re-vérifiée techniquement au niveau du crédit lui-même** — rien n'empêcherait, par une
manipulation directe (import, changement de société du user courant lors de la création,
etc.), de créer un crédit avec un `company_id` différent de celui du partenaire. Le comptage
"par `partner_id` seul, sans filtre société" reste la bonne décision fonctionnelle actée par
Micka, mais elle repose sur une hypothèse (l'unicité société/partenaire) qui n'est pas
garantie à 100% par le code — un signalement, pas un blocage.

## 4. États à inclure — définition déjà établie par deux précédents concordants

**Précédent n°1** (déjà cité, point 2.b) : `_check_progressive_savings_eligibility` ne
considère un crédit antérieur comme réellement "engagé" (susceptible de bloquer une nouvelle
demande) que s'il est dans l'un des états `('active', 'closed', 'defaulted', 'written_off')`.

**Précédent n°2** (nouveau, trouvé en marge de cet audit) : le bouton "Imprimer le reçu"
(`microfinance_loan_views.xml:98-100`, menu déroulant "Imprimer", juste au-dessus du bouton
"Imprimer le carnet" concerné par ce chantier) :

```xml
<button name="%(action_report_microfinance_loan_disbursement_receipt)d" type="action"
        class="dropdown-item" string="Imprimer le reçu"
        invisible="state in ('draft','enquete','avis_ca','avis_cdag','approved','cancelled')"/>
```

Négation de cette liste = visible seulement pour `('active', 'closed', 'defaulted',
'written_off')` — **exactement le même ensemble d'états** que le précédent n°1, cette fois
utilisé pour déterminer si un crédit a été **réellement décaissé** (le reçu de décaissement
n'a de sens qu'à partir de ce moment). Deux précédents indépendants, dans deux modules
différents, convergent sur la même définition : **`draft`, `enquete`, `avis_ca`, `avis_cdag`,
`approved` et `cancelled` ne comptent pas comme un crédit réellement engagé — seuls `active`,
`closed`, `defaulted`, `written_off` comptent.**

**Recommandation** : reprendre cette même liste `('active', 'closed', 'defaulted',
'written_off')` pour le comptage du rang — `approved` (avis rendu, pas encore décaissé) en
est donc exclu, cohérent avec le fait qu'un crédit "juste approuvé mais jamais décaissé"
n'est pas un "findramana" (emprunt) au sens propre du terme.

**Point à trancher explicitement par Micka au Lot 1** : le bouton "Imprimer le carnet"
lui-même (`microfinance_loan_views.xml:104-105`) **n'a aucune restriction d'état** — il est
visible même en `draft`. Si le carnet est imprimé sur un dossier qui n'est pas encore dans un
état engagé (cas rare mais possible), le dossier en cours d'impression ne compterait pas
lui-même dans son propre rang avec la définition ci-dessus (puisqu'il n'est pas encore
`active`/`closed`/`defaulted`/`written_off`) — le rang afficherait alors "le nombre de crédits
engagés déjà existants avant celui-ci", sans compter le dossier courant. Comportement
probablement correct (le carnet de remboursement n'a de sens réel qu'une fois le crédit
décaissé), mais à confirmer explicitement.

## 5. Critère de tri recommandé

**`order='id desc'` (ou `id asc` selon le sens du rang à calculer)** — c'est le critère déjà
utilisé par le seul précédent direct de "crédit précédent" (`_check_progressive_savings_eligibility`, point 2.b). Raisons de préférer `id` à d'autres options envisagées dans le
prompt :
- **`application_date`** : champ **éditable manuellement** dans la vue (`Dossier` >
  `Suivi`, aucun `readonly`), donc pas garanti strictement croissant ni fiable comme clé de
  tri stricte.
- **`disbursement_date`** : vide (`False`) pour tout crédit non encore décaissé — inutilisable
  comme clé de tri générale (cf. écart déjà rencontré au lot précédent sur
  `get_loan_duration_days()`).
- **Séquence du nom (`IS/NNNNNN`)** : confirmée **strictement croissante par société**
  (`res_company.py:34-49`, `_get_or_create_numbering_sequence`, séquence `ir.sequence` dédiée
  par société et par `code`) — donnerait en théorie le même ordre que `id` pour les crédits
  d'un même partenaire (puisqu'un partenaire est rattaché à une seule société). Mais
  nécessiterait un parsing de chaîne (split sur `/`, cast en entier) pour un résultat
  strictement équivalent à `id`, sans aucun avantage — **`id` est plus simple et déjà le choix
  du seul précédent existant dans le code**.

**Recommandation finale** : trier par `id` (croissant), le rang du dossier imprimé étant sa
position dans la liste des crédits engagés du partenaire triés par `id` croissant.

## Synthèse pour le Lot 1

1. Nouvelle méthode sur `microfinance.loan` (même bloc que `get_loan_duration_days()`),
   ex. `get_loan_rank_for_partner()` :
   ```python
   engaged_loans = self.search([
       ('partner_id', '=', self.partner_id.id),
       ('state', 'in', ('active', 'closed', 'defaulted', 'written_off')),
   ], order='id asc')
   ```
   puis retourner la position (1-indexée) de `self` dans `engaged_loans`, ou le **nombre total**
   de crédits engagés du partenaire jusqu'à et y compris celui-ci selon la sémantique exacte
   à confirmer avec Micka (voir point 4, cas du dossier non encore engagé).
2. Pas de filtre `company_id` dans le domaine, comme déjà tranché.
3. Signaler à Micka (sans corriger dans ce lot) : l'absence de contrainte serveur garantissant
   `loan.company_id == partner_id.company_id` (point 3).
4. Faire trancher par Micka : comportement du compteur si le carnet est imprimé sur un dossier
   pas encore engagé (`draft`/`enquete`/`avis_ca`/`avis_cdag`/`approved`) — le dossier courant
   doit-il forcer son propre comptage (traitement spécial) ou le rang affiché reste-t-il celui
   des crédits engagés précédents uniquement (comportement par défaut de la formule
   ci-dessus) ?
5. Impossible de valider le résultat sur un cas réel avec rang ≥ 2 (aucun partenaire de la
   base SEFOR n'a plus d'un crédit à ce jour) — seule une vérification sur `rang == 1` (cas
   actuel de tous les dossiers existants) sera possible avant mise en production réelle.

Aucune modification de code effectuée dans ce lot.
