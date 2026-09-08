# LOT 0 — Audit : "Faharetan'ny findramam-bola" (durée en jours) et "Agent BL"

Audit en lecture seule. Aucune modification de code, de vue ou de données.

## 1. Extrait XML actuel

`report_carnet_remboursement.xml:195` :

```xml
<div class="carnet-row"><u>Faharetan'ny findramam-bola</u> : <strong>384 andro</strong> &#160;&#160; Agent BL : <strong>Man</strong></div>
```

Les deux valeurs ("384" et "Man") sont des chaînes codées en dur, indépendantes du dossier
imprimé — confirmé par le commentaire du bloc (`report_carnet_remboursement.xml:158-169`),
qui liste explicitement "Faharetan'ny findramam-bola, Agent BL" parmi les éléments
volontairement laissés en dur lors du lot précédent de dynamisation de ce bloc.

## 2. Nombre de jours — aucun champ/méthode existant, calcul à construire

**Aucun champ ni méthode ne donne directement une durée en jours** sur `microfinance.loan` :
- `term` (`microfinance_loan.py:58`) : nombre d'**échéances**, pas de jours.
- `_actual_duration_months()` (`microfinance_loan.py:510-525`) : durée en **mois**
  (approximation "1 mois = 30 jours"), pensée pour comparer aux bornes `min_term`/`max_term`
  du produit — pas destinée à un affichage en jours exacts sur un document client.

**Piste confirmée : `disbursement_date` → dernière échéance.** `get_last_installment_date()`
(déjà utilisée ligne 191 de ce même rapport, pour "Fotoana farany hamerenana...") est
**inutilisable telle quelle pour ce calcul** : elle retourne une **chaîne déjà formatée**
JJ/MM/AAAA (via `_format_contrat_date()`, `microfinance_loan.py:2164-2167`), pas un objet
date. `chaîne - date` lèverait une `TypeError` en Python. Il faut passer par la **valeur brute**
déjà utilisée en interne par cette méthode :

```python
self._contrat_sorted_installments()[-1:].due_date   # objet Date, pas formaté
```

`_contrat_sorted_installments()` (`microfinance_loan.py:2169-2174`) trie déjà les échéances
par date puis séquence, ligne de délai de grâce incluse — c'est la même source que
`get_last_installment_date()`, donc cohérente avec la date déjà affichée juste au-dessus dans
ce rapport.

**Formule confirmée** :
```python
(self._contrat_sorted_installments()[-1:].due_date - self.disbursement_date).days
```

**Test sur données réelles** : `IS/003363` (dossier utilisé dans les audits précédents de ce
chantier) a `disbursement_date = NULL` (crédit pas encore décaissé, état probablement
antérieur à `active`) — **impossible de valider le calcul sur ce dossier précis**, il n'a pas
encore de date de décaissement. C'est le **seul** dossier de la base ayant `disbursement_date`
renseigné et un échéancier avec `IS/001076` (`id=2327`, état `active`) :

```
name = IS/001076, disbursement_date = 2026-09-05, term = 24, fréquence = weekly
dernière échéance (due_date max) = 2027-02-09
jours = 2027-02-09 - 2026-09-05 = 157 jours
```

157 jours pour 24 échéances hebdomadaires (24 × 7 = 168 jours en théorie pure) est un résultat
**cohérent** (l'écart s'explique par le calendrier réel d'échéances, jours ouvrés/fériés ou
ajustements de dates, pas une anomalie de la formule). **La formule produit un résultat
plausible** sur le seul cas réel testable dans la base actuelle — aucune donnée ne permet de
confirmer ou d'infirmer la valeur "384" actuellement figée dans le template (ni ce dossier ni
aucun autre dans la base n'a de couple `disbursement_date`/échéancier correspondant à 384
jours ; ce chiffre semble être un exemple arbitraire, pas une valeur calculée depuis un
dossier réel).

**Point de vigilance pour le Lot 1** : `disbursement_date` est `False` pour tout crédit non
encore décaissé (cas normal, ex. `IS/003363`). Une soustraction directe sur un `disbursement_date`
vide lèverait une exception au rendu du PDF. Toute méthode ajoutée pour ce calcul doit suivre
la convention déjà en place dans ce bloc de méthodes (`microfinance_loan.py:2160-2162`,
"ne doivent jamais lever d'exception sur un champ vide") — retourner `0` (ou une chaîne vide)
si `disbursement_date` ou l'échéancier est absent, symétrique de `_format_contrat_date()` qui
retourne `''` dans le même cas.

## 3. "Agent BL" — utilisateur connecté qui imprime, confirmé accessible sans changement de contrôleur

**Aucun précédent dans les rapports de ce module** (`microfinance_loan_management`,
`microfinance_savings_management`) n'utilise `env.user` — recherche exhaustive sans résultat
dans les deux dossiers `report/`.

**Confirmation par le cœur d'Odoo 17** : `env` et `env.user` sont des variables **standard,
déjà disponibles nativement** dans le contexte de rendu de tout rapport QWeb `qweb-pdf`, sans
aucune modification de contrôleur — utilisées telles quelles dans le layout de base que tout
rapport étend (`odoo/addons/web/views/report_templates.xml:29,87,273`, ex.
`env['res.lang']._lang_get(lang or env.user.lang)`). `env.user` désigne l'utilisateur dans le
contexte duquel le rapport est généré, c'est-à-dire **l'utilisateur qui déclenche
l'impression** (pas un champ du dossier) — exactement le comportement demandé.

**`env.user.name` est directement utilisable dans `report_carnet_remboursement.xml`**, sans
modification de contrôleur ni de la classe du rapport. Aucune anomalie, aucun point bloquant.

## 4. Format d'affichage recommandé pour "Agent BL"

Aucune convention spécifique n'existe dans ce module pour un champ "nom d'utilisateur
imprimant" (premier cas d'usage de ce type). En revanche, le même rapport utilise déjà
`<span t-field="o.officer_id.name"/>` pour "Mpikarakara" (ligne 171) — un simple `.name`, sans
distinction login/partenaire. **`env.user.name`** suit exactly la même convention de style et
suffit : c'est le nom complet affiché dans l'interface Odoo pour l'utilisateur (généralement
identique à `env.user.partner_id.name`, sauf configuration explicite différente — non
constatée dans la base actuelle). Pas de raison de préférer `login` (technique,
souvent une adresse e-mail) ni `partner_id.name` (détour inutile) à ce stade.

## Synthèse pour le Lot 1

1. **Durée en jours** : ajouter une méthode dédiée sur `microfinance.loan` (ex.
   `get_loan_duration_days()`, dans le même bloc de méthodes de rapport que
   `get_last_installment_date()`), retournant
   `(self._contrat_sorted_installments()[-1:].due_date - self.disbursement_date).days`,
   avec garde explicite retournant `0` si `disbursement_date` ou la dernière échéance est
   absente — jamais d'exception. Le template affiche `<t t-esc="o.get_loan_duration_days()"/>
   andro` (suffixe "andro" restant du texte fixe, comme demandé).
2. **Agent BL** : `<span t-esc="env.user.name"/>` directement dans le template, aucune
   méthode Python ni modification de contrôleur nécessaire.
3. Aucune anomalie bloquante identifiée sur les deux points. Seule réserve : la valeur "384"
   actuellement en dur ne peut pas être validée par comparaison avec un dossier réel (aucun
   dossier de la base n'atteint cette durée) — la formule est validée sur sa cohérence
   générale (résultat plausible sur `IS/001076`), pas sur une reproduction exacte de "384".

Aucune modification de code effectuée dans ce lot.
