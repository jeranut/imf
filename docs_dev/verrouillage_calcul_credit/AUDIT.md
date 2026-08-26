# Audit (Lot 0) — Verrouillage des champs "Calcul crédit" après avis CA/CDAG

Audit en lecture seule. **Aucune modification de code, de vue ou de donnée.** Toutes les valeurs
ci-dessous ont été vérifiées directement sur le dépôt (`microfinance_loan_management/models/
microfinance_loan.py`, `views/microfinance_loan_views.xml`) et sur la base réelle SEFOR (lecture
seule, y compris le chatter/tracking) pour la recherche d'impact.

## Correction préalable au périmètre de la demande

**Il n'existe aucun onglet ni groupe nommé "Calcul crédit" sur `microfinance.loan`.** Ce libellé
exact existe bel et bien dans le module, mais sur un **autre modèle** :
`microfinance.loan.product` (`microfinance_loan_product_views.xml:51`, `<page string="Calcul
crédit">`) - c'est la page de **configuration du produit** (taux, méthode d'intérêt, fréquence,
arrondi), pas les champs d'un crédit individuel.

Sur `microfinance.loan` lui-même, les 4 champs décrits dans la demande (montant, durée, taux,
produit) se trouvent en réalité dans le groupe **"Dossier"** (`microfinance_loan_views.xml:93-
111`), en tête de formulaire, hors de tout `<notebook>`/onglet - avec une exception notable pour
le taux (voir section 1). Le reste de ce rapport utilise donc ces emplacements réels ; à signaler
à Micka avant le chiffrage du Lot 1 (aucun renommage de groupe n'est requis pour ce chantier,
juste une clarification de vocabulaire).

---

## Section 1 — Identification exacte des champs

| Champ demandé | Nom technique | Type | `store` | Emplacement vue actuel |
|---|---|---|---|---|
| Montant du crédit | `loan_amount` | `Monetary`, `required=True`, **`tracking=True`** | Oui | Groupe "Dossier", ligne 102 |
| Durée / nb échéances | `term` | `Integer`, `required=True`, default=1, **`tracking=True`** | Oui | Groupe "Dossier", ligne 103 |
| Taux d'intérêt | `interest_rate` | `Float`, **`related='product_id.interest_rate'`, `readonly=False`, `store=True`** | Oui (copie stockée) | **Absent de la vue** - aucun `<field name="interest_rate"/>` nulle part dans `microfinance_loan_views.xml` |
| Produit de crédit | `product_id` | `Many2one('microfinance.loan.product')`, `required=True`, **`tracking=True`** | Oui | Groupe "Dossier", ligne 95 |

**Point critique pour la conception de la contrainte** : `interest_rate` (et `interest_method`,
même mécanisme, related/readonly=False/store=True) est un champ `related` **avec
`readonly=False`** - ce qui signifie qu'Odoo l'expose comme un champ normal, **directement
inscriptible et divergent du produit** (modifier `product_id.interest_rate` après coup ne
modifie PAS rétroactivement `loan.interest_rate`, et inversement). Il n'a aujourd'hui **aucun
widget dans la vue crédit** : personne ne peut le modifier par le formulaire actuel, mais rien
n'empêche une écriture directe (API, import, code) - et il n'est **pas tracké** (`tracking`
absent), donc invisible dans le chatter si jamais modifié. `interest_method` partage exactement
le même profil (related, `readonly=False`, `store=True`, absent de la vue crédit, non tracké).

**Champs miroir Avis CA/CDAG confirmés (noms réels, différents de ceux supposés dans la
demande)** : pas de `ca_montant`/`ca_duree`, mais `avis_ca_amount` / `avis_ca_term` /
`avis_ca_installment_amount` / `avis_ca_epargne_exigee` et leurs équivalents `avis_cdag_*`
(4 champs par bloc, 8 au total, cf. `microfinance_loan.py:96-135`, déjà documentés dans
`docs_dev/workflow_avis_ca_cdag/`). Ces champs sont **distincts** de `loan_amount`/`term` -
aucun `ca_taux`/`ca_produit` n'existe (l'avis ne porte que sur montant/durée/mensualité/épargne,
jamais sur le taux ni le produit).

**Champ adjacent à trancher explicitement avec Micka, hors des 4 demandés mais du même groupe
"Dossier"** : `installment_amount` (Monetary, lié bidirectionnellement à `loan_amount`/`term` par
onchange, cf. section 4) a déjà un `readonly` conditionnel en vue
(`readonly="state not in ('draft','enquete','avis_ca','avis_cdag','approved')"`, ligne 104) qui
le laisse **éditable jusqu'à `approved` inclus** - donc actuellement toujours modifiable pendant
`avis_ca`/`avis_cdag`. "Calcul crédit" au sens de la demande inclut-il ce champ, ou seulement les
4 cités ? Une réponse "non" laisserait une brèche : modifier `installment_amount` recalcule
`term` par onchange (section 4) - un champ qui serait, lui, verrouillé.

---

## Section 2 — Cartographie du champ `state`

Nom exact : `state`, `fields.Selection(..., default='draft', tracking=True, index=True)`
(`microfinance_loan.py:71-82`). Liste complète et ordonnée (ordre de déclaration = ordre
d'affichage du widget statusbar) :

| # | Valeur | Libellé |
|---|---|---|
| 1 | `draft` | Brouillon |
| 2 | `enquete` | Enquête |
| 3 | `avis_ca` | Avis CA |
| 4 | `avis_cdag` | Avis CDAG |
| 5 | `approved` | Approuvé |
| 6 | `active` | Actif |
| 7 | `closed` | Clôturé |
| 8 | `defaulted` | Défaut |
| 9 | `written_off` | Radié |
| 10 | `cancelled` | Annulé |

`avis_ca` et `avis_cdag` sont en positions 3 et 4, immédiatement après `enquete`.

**États réellement atteignables après `avis_ca`/`avis_cdag`, d'après le graphe de transition réel
du code (pas seulement l'ordre de la Selection)** - vérifié exhaustivement, toutes les méthodes
`action_*` qui écrivent `state` :

```
enquete --action_ca_review()--> avis_ca --action_cdag_review()--> avis_cdag
  --action_approve()--> approved --action_disburse()--> active
      --action_close()--> closed
      --action_mark_default()--> defaulted --action_close()--> closed
                                --action_write_off()/action_confirm_write_off()--> written_off
```

**`cancelled` est déclaré dans la Selection mais n'est écrit par AUCUNE méthode et n'est
déclenché par AUCUN bouton dans toute la base de code actuelle** (recherche exhaustive :
`grep "'state':\s*'cancelled'"` et `grep action_cancel`, zéro résultat). C'est un état mort au
sens strict - présent pour un usage futur non implémenté, cohérent avec d'autres vestiges déjà
documentés dans ce module (groupes fantômes, `validation_authority` sans effet, etc.).

**Réponse à la question posée par la demande** ("le verrouillage doit-il rester actif dans TOUS
les états ultérieurs ?") : les états réellement atteignables après `avis_ca`/`avis_cdag` sont
`approved`, `active`, `closed`, `defaulted`, `written_off` (`cancelled` inatteignable
actuellement). **Point de tension à signaler, pas tranché ici** : `_EDITABLE_SCHEDULE_STATES =
('draft', 'enquete', 'avis_ca', 'avis_cdag', 'approved')` (`microfinance_loan.py:220`) traite
aujourd'hui `approved` comme un état où l'échéancier (`installment_amount`/`installment_ids`)
reste librement régénérable - cohérent avec le "readonly jusqu'à approved" actuel
d'`installment_amount` (section 1). Si le verrouillage de `loan_amount`/`term`/`interest_rate`/
`product_id` doit s'appliquer dès `avis_ca` **et rester actif à `approved`** (lecture "a priori
oui" de la demande), cela crée une incohérence partielle avec `_EDITABLE_SCHEDULE_STATES`, qui
resterait permissif sur les champs dérivés (mensualité/échéancier) pendant que les champs source
(montant/durée) seraient déjà verrouillés à ce même état - à clarifier avec Micka avant le Lot 1
(harmoniser les deux listes, ou assumer consciemment le décalage).

---

## Section 3 — Cas "reporté"

**Aucun mécanisme de report/rejet n'existe dans le code actuel.** Recherche exhaustive
(`report`, `reporte`, `differe`, `rejet` dans `microfinance_loan.py`, `microfinance_loan_
views.xml`) : aucune occurrence pertinente (les seules trouvées concernent `action_print_
repayment_schedule`/`action_report_...`, des rapports PDF, sans rapport avec un avis). `action_
ca_review()` et `action_cdag_review()` sont des transitions **strictement à sens unique** :
aucune des deux ne propose de branche retour vers `draft`/`enquete`, ni de nouvel état
"reporté"/"rejeté" dans la Selection `state`.

**Conséquence directe pour ce Lot** : la question posée par la demande ("le crédit revient-il à
un état antérieur qui permettrait une nouvelle saisie ?") **n'a pas de réponse dans le code
actuel, faute de mécanisme à observer** - ni oui, ni non, la situation ne se présente simplement
jamais aujourd'hui. Le verrou n'a donc **aucun cas de levée à gérer pour l'instant** : tant
qu'aucune méthode ne ramène `state` à `draft`/`enquete` depuis `avis_ca`/`avis_cdag`, une
contrainte fondée uniquement sur la valeur courante de `state` (pas sur un flag séparé) se
lèverait automatiquement le jour où un tel mécanisme de retour serait ajouté - propriété
favorable à noter pour la conception du Lot 1, sans qu'il soit nécessaire de la construire
maintenant. Si Micka veut ce mécanisme de "report", c'est un chantier séparé (nouvel état +
nouvelle transition), pas un prérequis de blocage pour ce Lot.

---

## Section 4 — Points d'écriture à risque (CRITIQUE)

### 4.1 — Écritures directes sur `loan_amount`/`term` pendant `avis_ca`/`avis_cdag` : un seul
mécanisme système identifié, et il écrit précisément pendant ces deux états

**`_propagate_avis_to_loan()`** (`microfinance_loan.py:280-...`, appelée depuis l'override de
`write()` ligne 262-278 dès qu'un champ de `_AVIS_PROPAGATION_TRIGGER_FIELDS` - `avis_ca_amount`,
`avis_ca_term`, `avis_ca_installment_amount`, `avis_cdag_amount`, `avis_cdag_term`, `avis_cdag_
installment_amount` - est écrit) :

```python
def _propagate_avis_to_loan(self):
    self.ensure_one()
    if self.state not in self._EDITABLE_SCHEDULE_STATES:
        return
    if self.state == 'avis_ca':
        source_amount, source_term, source_installment = (
            self.avis_ca_amount, self.avis_ca_term, self.avis_ca_installment_amount)
    elif self.state == 'avis_cdag':
        source_amount, source_term, source_installment = (
            self.avis_cdag_amount, self.avis_cdag_term, self.avis_cdag_installment_amount)
    else:
        return
    if not source_amount or not source_term:
        return
    if self.loan_amount == source_amount and self.term == source_term:
        return
    source_installment = source_installment or self._compute_installment_target(source_amount, source_term)
    self.write({
        'loan_amount': source_amount,
        'term': source_term,
        'installment_amount': source_installment,
    })
    self.action_generate_schedule()
```

**C'est le seul et unique mécanisme du module qui écrit `loan_amount`/`term` alors que `state`
vaut déjà `avis_ca` ou `avis_cdag`** (confirmé par grep exhaustif de `.loan_amount =`/
`'loan_amount':`/`.term =`/`'term':` sur tout le fichier - aucune autre occurrence hors création,
`_reschedule_installments` (état `active` uniquement, hors périmètre) et cette méthode). Son
comportement est **explicitement conditionné à `self.state in ('avis_ca', 'avis_cdag')`** (via le
`if`/`elif`/`else: return`) : c'est structurellement le point d'écriture que la demande anticipe
en section 4, formulé de façon quasi identique dans son propre commentaire de code (ligne 262-267
: *"aucun des trois champs écrits ici ... ne fait partie de _AVIS_PROPAGATION_TRIGGER_FIELDS,
l'appel récursif ne retrouve donc jamais de champ déclencheur et s'arrête de lui-même"*).

**`product_id` et `interest_rate` : aucun écrivain système identifié.** Recherche exhaustive
(`\.product_id\s*=`, `'product_id':`, `\.interest_rate\s*=`, `'interest_rate':` sur tout le
fichier) : zéro occurrence en dehors de la création du crédit (`create()`, avant tout état avis).
**Verrouiller ces deux champs dès `avis_ca` est donc, à ce jour, sans risque de collision avec un
mécanisme système existant** - contrairement à `loan_amount`/`term`.

### 4.2 — `_propagate_avis_to_loan()` ne s'exécute jamais pendant `action_ca_review()`/
`action_cdag_review()` elles-mêmes

Point de détail vérifié, utile pour la conception : `action_ca_review()` pose bien `avis_ca_
amount`/`avis_ca_term` par défaut (`microfinance_loan.py:717-722`) et appelle même directement
`loan._onchange_avis_ca_recompute_installment()` (déclenchant potentiellement une cascade vers
`avis_cdag_amount`) - mais tout cela se produit **avant** la ligne finale `self.write({'state':
'avis_ca', ...})` de la même méthode : au moment de ces écritures, `self.state` vaut encore
`enquete` (l'ancien état), donc `_propagate_avis_to_loan()` (si déclenchée par ces écritures de
champs avis) tombe dans la branche `else: return` et ne fait rien. **`_propagate_avis_to_loan()`
ne s'active concrètement que plus tard**, quand un membre du CA/CDAG modifie le bloc Avis
CA/CDAG **après** que le bouton ait déjà fait passer `state` à `avis_ca`/`avis_cdag` (sauvegarde
de formulaire suivante) - c'est ce moment précis qui doit rester non bloqué par la future
contrainte.

### 4.3 — Onchange du groupe "Dossier" : écrivent `installment_amount`/`installment_ids`, pas
`loan_amount`/`term`/`product_id` eux-mêmes - sauf un, dans le sens inverse

- `_onchange_loan_amount_recompute_installment` (déclenché par `loan_amount`/`term`/
  `repayment_frequency_id`/`interest_rate`) : écrit `installment_amount` et `installment_ids`
  (aperçu), **jamais** `loan_amount`/`term`/`product_id` eux-mêmes - ces champs sont les
  déclencheurs, pas les cibles. Aucune collision directe avec la future contrainte sur ces 3
  champs.
- `_onchange_installment_amount_recompute_terms` (déclenché par `installment_amount`) : écrit
  **`term`** en retour (`loan.term = new_term`, ligne ~874 selon le lot précédent) et
  `installment_ids`. **C'est le seul onchange qui écrit un des 4 champs demandés** - via le
  champ adjacent `installment_amount` évoqué en section 1. Si `installment_amount` reste
  éditable pendant `avis_ca`/`avis_cdag` (ce qu'il est aujourd'hui, cf. section 1) alors que
  `term` devient verrouillé, cet onchange resterait techniquement capable de recalculer `term`
  en mémoire dans le formulaire (aperçu) - la sauvegarde serait alors bloquée par la nouvelle
  contrainte serveur (filet de sécurité qui jouerait ici son rôle), mais l'expérience
  utilisateur serait confuse (un champ non verrouillé qui, une fois modifié, fait échouer la
  sauvegarde à cause d'un effet de bord sur un autre champ verrouillé) - argument
  supplémentaire pour trancher explicitement le sort d'`installment_amount` (section 1) avant
  le Lot 1.

### 4.4 — Conséquence pour la conception de la contrainte (constat, pas une proposition de
solution - hors périmètre de ce Lot 0)

Une `@api.constrains` qui bloquerait toute écriture de `loan_amount`/`term` dès que `self.state
in ('avis_ca', 'avis_cdag')`, sans distinction, **casserait `_propagate_avis_to_loan()`** dès la
première utilisation réelle du bloc Avis CA/CDAG après la transition - la contrainte ne peut pas
se fonder sur `state` seul, elle doit pouvoir distinguer "écriture système de propagation" de
"saisie manuelle utilisateur sur le champ générique". Aucune mécanique de ce type n'existe
aujourd'hui dans le module pour ce cas précis (le rapprochement le plus proche, `self.env.
context` pour signaler un appel interne, est un pattern Odoo standard mais **pas encore utilisé
nulle part dans `microfinance_loan.py`** - à concevoir au Lot 1, pas ici).

---

## Section 5 — État actuel des `readonly`/`attrs` en vue

| Champ | Ligne | `readonly` actuel |
|---|---|---|
| `loan_amount` | 102 | **Aucun** - toujours éditable, quel que soit `state` |
| `term` | 103 | **Aucun** - toujours éditable, quel que soit `state` |
| `product_id` | 95 | **Aucun** - toujours éditable, quel que soit `state` |
| `interest_rate` | - | **Champ absent de la vue** (aucun `readonly` à retirer/ajouter, un `<field>` serait à créer si jamais exposé) |
| `installment_amount` (adjacent, section 1) | 104 | `readonly="state not in ('draft','enquete','avis_ca','avis_cdag','approved')"` - éditable jusqu'à `approved` inclus, verrouillé seulement à partir de `active` |

**Aucun verrouillage n'existe donc aujourd'hui sur les 4 champs demandés, en vue comme en
Python** (confirmé aussi par l'absence totale de `@api.constrains` sur `loan_amount`/`term`/
`product_id`/`interest_rate` dans tout le fichier - recherche exhaustive des décorateurs `@api.
constrains` du modèle, aucun ne les cite).

---

## Section 6 — Recherche d'impact sur les données existantes

Les 3 champs `loan_amount`, `term`, `product_id` sont **`tracking=True`** (`interest_rate` ne
l'est pas - aucune trace exploitable pour lui). `state` l'est aussi. Requête en lecture seule sur
`mail_tracking_value`/`mail_message` (chatter réel, SEFOR), pour les 2 seuls crédits existants
(`id=1449` IS/000289, `id=2327` IS/001076) :

**IS/000289 (id 1449)** : `state` n'a jamais dépassé `enquete` (jamais atteint `avis_ca`) - donc
**hors périmètre du risque décrit par cette demande, par construction** (le verrou ne
s'appliquerait de toute façon jamais à ce dossier tant qu'il reste en `enquete`). 7 modifications
de `term` tracées, toutes en `draft`/`enquete`.

**IS/001076 (id 2327) : impact confirmé, ampleur significative.** Séquence tracée (chatter réel,
horodatée) :

| Heure | Événement |
|---|---|
| 00:22:20 | `state` : Enquête → **Avis CA** (+ `avis_ca_amount`/`avis_cdag_amount` : 0→500 000, seule écriture tracée de ces deux champs sur tout l'historique) |
| 00:24:13 | **`term` : 24 → 16** (état déjà Avis CA) |
| 00:25:15 | `state` : Avis CA → **Avis CDAG** |
| 00:42:34 | **`term` : 16 → 27** (état déjà Avis CDAG) |
| 06:09 - 06:11 | 3 modifications supplémentaires de `term` (état déjà Avis CDAG) |
| 12:05 - 12:08 (lot précédent, garde-fou reliquat) | 6 modifications supplémentaires de `term`, jusqu'à 30 (état déjà Avis CDAG) |
| 2026-08-26 00:18 | `term` : 30 → 24 (remis à une valeur saine, état toujours Avis CDAG) |

**12 modifications de `term` tracées au total sur ce dossier, la totalité (12/12) après le
passage en `avis_ca`** (la première, `term: 24→16` à 00:24:13, suit de moins de 2 minutes
l'entrée en `avis_ca` à 00:22:20 - aucune n'a eu lieu en `draft`/`enquete`). **Aucune de ces 12
écritures ne coïncide temporellement avec une écriture tracée de `avis_ca_amount`/`avis_cdag_
amount`** (une seule ligne de tracking pour ces deux champs sur tout l'historique, à 00:22:20,
avant la toute première modification de `term` en avis) - **ce sont donc, avec une quasi-
certitude, des modifications manuelles directes du champ générique `term`**, pas des écritures
du mécanisme de propagation système (`_propagate_avis_to_loan`) décrit en section 4. C'est
exactement le scénario que ce Lot cherche à empêcher, déjà observé en pratique - 1 dossier sur 1
qui a atteint `avis_ca` dans SEFOR en présente un exemple caractérisé. Aucune trace de
modification de `loan_amount` ou `product_id` sur ce dossier (montant resté à 500 000 Ar tout du
long).

**Portée de ce constat** : SEFOR ne contenant que 2 crédits au total (dont 1 seul a atteint
`avis_ca`), ce résultat ne permet pas d'estimer une fréquence en environnement de production
réel - il confirme seulement que le scénario à risque **s'est déjà produit**, pas son ampleur
future. Cohérent avec les audits précédents (`docs_dev/echeancier_obsolete_readonly/`,
`docs_dev/garde_fou_reliquat_negatif/`) : ce même dossier IS/001076 sert de banc d'essai répété
pour les différents chantiers en cours, ce qui explique le volume de modifications de `term`
observé.

---

## Proposition de formulation du message d'erreur (`ValidationError`)

Non tranchée, proposée pour discussion - inclut la référence du crédit et le libellé du champ,
sans jargon technique :

```
Impossible de modifier « %(field_label)s » sur le crédit %(loan_name)s : ce champ est verrouillé
depuis le passage en avis CA/CDAG. Contactez le support technique si ce montant doit encore être
corrigé à ce stade.
```

`%(field_label)s` substitué par le libellé du champ concerné ("Montant crédit", "Nombre
échéances", "Taux intérêt annuel (%)", "Produit") pour rester précis sans citer de nom technique
interne, `%(loan_name)s` par ex. "IS/001076".

---

## Récapitulatif des points à trancher avec Micka avant le Lot 1

1. **`installment_amount`** (section 1 et 4.3) : inclus dans le verrouillage "Calcul crédit" ou
   explicitement hors périmètre ? Impact direct sur la cohérence de l'expérience utilisateur.
2. **`approved` comme état verrouillé** (section 2) : à harmoniser ou non avec
   `_EDITABLE_SCHEDULE_STATES`, qui traite aujourd'hui `approved` comme encore modifiable pour
   l'échéancier dérivé.
3. **Distinction système/utilisateur** (section 4.4) : la contrainte doit prévoir un mécanisme
   (probablement un flag de contexte, à concevoir au Lot 1) pour laisser passer l'écriture de
   `_propagate_avis_to_loan()` sans rouvrir la porte à une saisie manuelle déguisée - point de
   conception à traiter explicitement dans le chiffrage du Lot 1, pas dans ce rapport.
4. **`interest_rate`/`interest_method`** : champs actuellement absents de la vue crédit - le
   verrouillage porte-t-il sur le champ Python (au cas où une future vue les exposerait ou
   qu'une écriture API survienne), ou est-ce sans objet tant qu'aucun widget n'existe ?

Stop après ce rapport, conformément à la consigne.
