# LOT 0 — Audit : `provision_amount` et `savings_requirement_type` (épargne cible progressive)

Audit en lecture seule. Aucune modification de code, de vue ou de données.

## 1. `microfinance.loan.provision_amount` — définition technique complète

Défini dans `microfinance_loan_management/models/microfinance_loan.py:184` :

```python
provision_amount = fields.Monetary(compute='_compute_provision', store=True, string='Provision requise')
```

Compute (`microfinance_loan.py:712-726`) :

```python
@api.depends('state', 'balance_total', 'company_id', 'installment_ids.due_date', 'installment_ids.state')
def _compute_provision(self):
    Rule = self.env['microfinance.provision.rule']
    for loan in self:
        if loan.state not in ('active', 'defaulted'):
            loan.provision_amount = 0.0
            continue
        max_days = loan._get_max_overdue_days()
        rule = Rule.search([
            ('company_id', '=', loan.company_id.id),
            ('min_days', '<=', max_days),
            '|', ('max_days', '=', 0), ('max_days', '>=', max_days),
        ], order='min_days desc', limit=1)
        rate = rule.provision_rate if rule else 0.0
        loan.provision_amount = min(loan.balance_total * rate / 100.0, loan.balance_total)
```

`microfinance.provision.rule` (`microfinance_provision_rule.py`) est une grille de provisionnement
comptable classique en microfinance : par société, un barème de tranches de retard
(`min_days`/`max_days`) associées à un taux (`provision_rate`, en %). Le taux applicable est
celui de la tranche correspondant au **retard maximum observé sur les échéances du crédit**
(`_get_max_overdue_days()`, calcul sur `installment_ids.due_date`/`state`), appliqué au
**solde restant dû** (`balance_total`), plafonné à ce solde.

## 2. Constat explicite : aucun lien avec l'épargne cible progressive

**`provision_amount` n'a aujourd'hui strictement aucun lien avec `savings_requirement_type`,
`savings_target_ratio` ou toute autre notion d'épargne.** Ses seules dépendances sont l'état
du crédit, le solde restant dû, la société, et le retard des échéances. Aucune référence
croisée trouvée dans le code entre `provision_amount`/`microfinance.provision.rule` et
`savings_target_amount`/`savings_requirement_type`/`savings_target_ratio` (recherche
exhaustive sur les deux modules).

C'est un **provisionnement pour risque de crédit** (créances douteuses, logique PAR — voir
aussi `_get_par_breakdown` juste au-dessus dans le fichier, qui utilise le même
`_get_max_overdue_days()` pour classer les crédits en tranches PAR 1-30/31-60/61-90/90+) :
un concept comptable de couverture du risque d'impayé, sans rapport métier avec l'obligation
d'épargne progressive (qui est une condition d'éligibilité à un futur crédit, cf. §3bis,
pas une provision comptable).

**Sur le dossier IS/003363** (capture) : `provision_amount = 0,00 Ar` s'explique simplement
par `_get_max_overdue_days() == 0` (aucune échéance en retard sur ce dossier à ce jour) — la
grille de provisionnement ne s'applique qu'à partir du premier jour de retard. Ce n'est ni
un bug ni un champ "non encore branché" : c'est le comportement attendu de la formule
**actuelle**, qui n'a jamais été conçue pour réagir à l'épargne cible.

**Attendu de Micka vs réalité du code — écart confirmé, pas une interprétation** : l'attente
formulée ("`provision_amount` devrait être calculé à partir du ratio d'épargne cible") ne
correspond à **aucune ligne de code existante**. Il s'agit d'un écart réel entre l'intention
métier et l'implémentation actuelle, pas d'un mécanisme partiellement présent qu'il suffirait
d'étendre. La formule citée au point 1 ci-dessus est la formule réelle, verbatim — elle ne
mentionne ni `savings_target_ratio` ni aucun champ du bloc épargne progressive.

**Usages ailleurs** : `provision_amount` n'apparaît que sur la vue formulaire du crédit
(`microfinance_loan_views.xml:231`, `readonly="1"`) et dans la logique de comptabilisation
de la provision (`microfinance_loan.py:2029-2047`, écriture comptable dédiée par crédit à
partir du delta avec `provision_posted_amount`). Aucun rapport, aucun autre modèle ne le
consomme.

## 3. Épargne cible progressive — définition technique complète

Module `microfinance_savings_management`, fichier `models/microfinance_loan_extension.py`.

**Sur le produit** (`microfinance_loan_product_extension.py:28-42`) :

```python
savings_requirement_type = fields.Selection([
    ('none', 'Aucune exigence épargne'),
    ('target_during_loan', 'Épargne cible pendant le remboursement'),
], string='Exigence épargne', required=True, default='none', tracking=True)
savings_target_ratio = fields.Float(
    string='Ratio épargne cible (%)', default=20.0,
    help='... ratio montant épargne cible / montant emprunté.',
)
savings_product_id = fields.Many2one('microfinance.savings.product', ...)  # produit d'épargne cible
```

**Sur le crédit** (`microfinance_loan_extension.py:22-27, 84-99`) :

```python
savings_target_amount = fields.Monetary(compute='_compute_savings_target_amount', store=True, ...)
savings_target_reached = fields.Boolean(compute='_compute_savings_target_reached', store=True, ...)

@api.depends('loan_amount', 'product_id.savings_requirement_type', 'product_id.savings_target_ratio')
def _compute_savings_target_amount(self):
    for loan in self:
        if loan.product_id.savings_requirement_type == 'target_during_loan':
            loan.savings_target_amount = loan.loan_amount * loan.product_id.savings_target_ratio / 100.0
        else:
            loan.savings_target_amount = 0.0

@api.depends('savings_account_id.balance', 'savings_target_amount')
def _compute_savings_target_reached(self):
    for loan in self:
        loan.savings_target_reached = (
            bool(loan.savings_account_id)
            and loan.savings_target_amount > 0
            and loan.savings_account_id.balance >= loan.savings_target_amount
        )
```

**Formule du montant cible** : `loan_amount * product_id.savings_target_ratio / 100.0` — un
pourcentage fixe du montant emprunté, configuré sur le produit (20% par défaut). Pour
IS/003363 : `100 000 Ar` cible ⇒ cohérent avec `loan_amount * 20% = 100 000` si
`loan_amount = 500 000 Ar` (ratio par défaut du produit, à confirmer sur le produit "PRET
RURAL" mais la formule est limpide et ne dépend d'aucune autre donnée).

**"Épargne cible atteinte"** passe à `True` uniquement quand un `savings_account_id` est
renseigné sur le crédit **et** que son solde (`balance`) est ≥ `savings_target_amount`. Champ
stocké, recalculé automatiquement à chaque mouvement du solde du compte lié.

## 4. Dimension temporelle (deadline) — absence confirmée

**Aucune notion de date limite n'existe dans le code** pour l'épargne cible progressive :
- Aucun champ `Date`/`Datetime` sur `savings_requirement_type`/`savings_target_ratio`
  (produit) ni sur `savings_target_amount`/`savings_target_reached` (crédit).
- Aucune contrainte (`@api.constrains`), aucune méthode cron dans
  `microfinance_loan_extension.py` en lien avec une échéance de l'épargne cible (le seul cron
  du fichier, `cron_process_savings_auto_debit`, concerne le prélèvement automatique sur
  échéances de remboursement en retard — sans rapport avec la cible progressive).
- Le seul contrôle existant est **au moment de la demande d'un crédit suivant**
  (`_check_progressive_savings_eligibility`, `microfinance_loan_extension.py:139-160`) : il
  bloque la demande si un crédit précédent avait `savings_requirement_type =
  'target_during_loan'` et que `savings_target_reached` est resté `False`. C'est un contrôle
  **a posteriori, sans date limite** — la cible doit simplement être atteinte "un jour",
  avant la prochaine demande de crédit ; rien ne force à l'atteindre avant une date donnée
  pendant le remboursement du crédit en cours.

Confirmation explicite : **l'UI (aucun champ de date visible dans "ÉLIGIBILITÉ
PROGRESSIVE") reflète fidèlement l'absence de toute logique de délai dans le code.** Ce
n'est pas un champ caché/non affiché — c'est une fonctionnalité qui n'existe pas encore.

## 5. "Fe-potoana fandrotsahana ny tahiry" — pas un mécanisme réutilisable

Recherche exhaustive du texte "Fe-potoana"/"fandrotsahana"/"tahiry" dans les deux modules :
**une seule occurrence de valeur**, dans `report_carnet_remboursement.xml:194` :

```xml
<div class="carnet-row"><u>Fe-potoana fandrotsahana ny tahiry</u> : <span class="carnet-highlight"><strong>18/08/2027</strong></span></div>
```

**C'est une date écrite en dur dans le template QWeb** ("18/08/2027" figé, identique quel que
soit le dossier imprimé) — pas un `t-field`/`t-esc` sur un champ calculé. Le commentaire
juste au-dessus (`report_carnet_remboursement.xml:158-169`) le confirme explicitement : ce
libellé (avec 5 autres lignes du même bloc) a été **volontairement laissé en dur**, hors
périmètre du lot qui a dynamisé le reste du carnet
(`docs_dev/carnet_remboursement/AUDIT_bloc_findramana.md`, Lot 0).

**Conclusion : il n'existe aucun mécanisme de calcul de date limite réutilisable nulle
part dans le codebase actuel** — ni pour "Fe-potoana fandrotsahana ny tahiry" (texte figé,
zéro logique serveur), ni pour l'épargne cible progressive (aucune notion de date, cf. §4).
Une future date limite pour l'épargne cible progressive devra être **construite de zéro**,
sans modèle interne à copier.

## 6. Workflow / contraintes — portée du blocage actuel

`savings_target_reached = False` bloque aujourd'hui une seule chose : la **demande d'un
nouveau crédit** par le même partenaire, si ce nouveau crédit fait suite à un crédit dont le
produit imposait `target_during_loan` (`_check_progressive_savings_eligibility`, appelé
depuis `_check_eligibility`, donc à `action_submit`). Ce n'est **pas** un blocage sur le
crédit en cours lui-même : le crédit dont la cible n'est pas atteinte peut continuer à vivre
normalement (paiements, clôture normale en fin de terme) sans que `savings_target_reached`
n'intervienne — c'est purement informatif sur ce crédit précis, le contrôle bloquant ne
s'exerce que sur le suivant.

## Recommandation

**Construire un mécanisme séparé**, pas étendre un mécanisme temporel existant — il n'y en a
aucun à étendre (ni côté épargne cible, ni le "Fe-potoana" du carnet qui est un texte figé
sans logique). Deux volets bien distincts à concevoir, indépendamment de ce qui existe :

1. **Un nouveau champ date sur le produit** (ex. `savings_target_deadline_type` +
   nombre de jours/mois depuis le décaissement, sur le modèle de ce qui existe déjà côté
   scoring/étapes progressives pour d'autres délais — ex. `late_tolerance_days` vu dans
   `microfinance_loan_application.py:1154` pour un délai de tolérance de retard, qui est un
   *pattern* de configuration de délai sur produit, réutilisable comme **inspiration de
   style de champ**, pas comme mécanisme de date à proprement parler).
2. **Un compute de date limite sur le crédit** (`savings_target_deadline`, à partir de
   `disbursement_date` + le délai configuré), dans la continuité naturelle des champs déjà
   en place (`savings_target_amount`, `savings_target_reached`) dans
   `microfinance_loan_extension.py`.
3. **Décision à trancher avec Micka avant tout Lot 1** : que doit-il se passer si la date
   limite est dépassée sans que la cible soit atteinte ? Aujourd'hui le seul point de contrôle
   est la demande du crédit suivant (`_check_progressive_savings_eligibility`) — un dépassement
   de date limite doit-il déclencher une action sur le crédit **en cours** (alerte,
   `message_post`, champ d'état dédié) ou seulement durcir le contrôle déjà existant sur le
   crédit suivant ? Ce choix détermine si un cron devient nécessaire (aucun cron de ce type
   n'existe aujourd'hui pour l'épargne progressive) ou si un simple champ compute suffit.

**Sur `provision_amount`** : ne pas le modifier dans le cadre de ce chantier sans clarifier
d'abord avec Micka s'il s'agit bien d'un besoin réel et distinct (faire dépendre une
provision **comptable** pour créances douteuses d'un ratio d'**épargne cible** mélangerait
deux logiques métier normalement indépendantes — risque de crédit vs. éligibilité
progressive) ou d'une confusion de nommage avec `savings_target_amount`/
`guarantee_savings_required` (déjà existants et déjà basés sur des ratios/produits). À
confirmer explicitement avant d'envisager le moindre changement sur ce champ.

Aucune modification de code effectuée dans ce lot.
