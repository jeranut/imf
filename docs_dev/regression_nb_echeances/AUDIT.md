# Audit — Régression "Nombre échéances" revient à 8 au lieu de 24 (IS/000289)

Audit en lecture seule (Lot 0). **Aucune modification de code n'a été effectuée.** Le mécanisme
de la régression a été **reproduit et vérifié empiriquement** avec le code réel du dépôt (état
actuel non commité, ce que la demande appelle "Lot 1") contre la base réelle SEFOR (lecture
seule, `env.cr.rollback()` systématique, aucune écriture persistée), via `odoo.tests.common.Form`
qui rejoue exactement la mécanique d'onchange en cascade du client web.

## Résumé exécutif

**Cause identifiée avec un niveau de confiance élevé : régression 100 % introduite par le
Lot 1, pas un bug préexistant.** Les deux nouveaux onchange `_onchange_loan_amount_recompute_installment`
et `_onchange_installment_amount_recompute_terms` (`microfinance_loan.py:637-689`) forment une
**boucle de rétroaction bidirectionnelle** sur le champ `term` ("Nombre échéances") : saisir
`term` déclenche le calcul de `installment_amount`, qui déclenche à son tour le recalcul inverse
de `term` — **dans le même appel onchange**, avant que la valeur saisie par l'utilisateur n'ait
jamais été renvoyée au formulaire. Résultat vérifié : taper `24` dans "Nombre échéances" sur
IS/000289 (PRET RURAL, 500 000 Ar, 36 %, hebdomadaire) fait retomber le champ à **23** dans le
même aller-retour serveur, sans aucune erreur, aucun log, aucun avertissement. Chaque édition
supplémentaire de `loan_amount`/`term`/`repayment_frequency_id` fait redescendre la valeur d'un
cran de plus.

Je n'ai **pas réussi à reproduire exactement la valeur `8`** avec la séquence d'édition la plus
directe (elle se stabilise à **22** après quelques allers-retours, cf. §1). Le mécanisme est
cependant sans ambiguïté et suffit à expliquer la classe de symptôme rapportée ; atteindre
précisément 8 dépend de la séquence exacte de saisie côté utilisateur (ordre des champs modifiés,
corrections successives, changement de périodicité en cours de saisie — cf. §1 scénarios B/C).
Voir la section "Confiance et limites" en fin de document.

L'hypothèse "confusion durée en mois / nombre d'échéances" (`_actual_duration_months`) est
**infirmée par le calcul exact** (§2). Aucune `ValidationError` ni exception serveur n'a été
trouvée dans les logs autour d'une tentative de sauvegarde de ce dossier (§4) : le mécanisme est
un **écrasement silencieux en mémoire pendant l'édition**, pas un revert consécutif à un rejet de
sauvegarde.

---

## Étape 1 — Déclencheur exact reproduit

### Preuve empirique (via `Form`, code réel, produit/fréquence/taux réels de IS/000289)

Configuration confirmée en base (lecture seule) :

```
microfinance_loan_product id=1 "PRET RURAL" : min_term=1, max_term=12 (mois),
    installment_rounding_unit=1000, installment_rounding_mode='ceiling', interest_rate=36
microfinance_repayment_frequency id=2 "Hebdomadaire" : period_kind='days', period_value=7,
    periods_per_year=52
microfinance_loan id=1449 "IS/000289" : term=24, loan_amount=500000, state='enquete'
    (valeur actuellement persistée en base — confirmé 24, pas 8)
```

**Scénario A — séquence la plus directe (saisie du formulaire de bout en bout)** :

| Action utilisateur | `term` résultant | `installment_amount` résultant |
|---|---|---|
| Sélectionner produit PRET RURAL, saisir `loan_amount=500000` (fréquence pas encore choisie) | `1` (inchangé, onchange gardé par `not repayment_frequency_id`) | `0.0` |
| Choisir fréquence Hebdomadaire | `1` (point fixe stable pour term=1, voir §3) | `503 461,54` |
| **Taper `term = 24`** | **`23`** ← *écrasé dans le même appel onchange* | `25 000,0` |
| Retoucher `loan_amount` (ex. re-confirmer 500 000) | `22` | `27 000,0` |
| Retoucher `loan_amount` à nouveau (×10 répétitions) | **stable à `22`** | stable à `27 000,0` |

**Le champ affiche donc `23` dès la frappe du `24`, avant même que l'utilisateur n'ait quitté le
champ suivant.** Ce n'est pas intermittent : c'est déterministe, reproductible à 100 % avec ces
paramètres exacts.

**Scénario B — fréquence changée en cours de saisie (Journalier → Hebdomadaire)** :
`term=24` sous Journalier → écrasé à `23` (installment_amount 22 000) → bascule vers
Hebdomadaire → `term=22` (installment_amount 27 000) → stable à `22` ensuite.

**Scénario C — fréquence changée en cours de saisie (Mensuel → Hebdomadaire)** :
`term=24` sous Mensuel → coïncidence, reste `24` (installment_amount 36 000) → bascule vers
Hebdomadaire → `term=23` (installment_amount 26 000).

**Constat général** : quels que soient l'ordre et le nombre d'éditions testés (jusqu'à 12
répétitions), la valeur se stabilise rapidement (20-23) sans jamais descendre à 8 dans mes
scénarios. Le mécanisme racine est confirmé sans ambiguïté ; le chiffre exact `8` rapporté par
l'utilisateur nécessite très probablement une séquence de saisie plus longue ou plus erratique
(plusieurs corrections de montant, changements de produit/fréquence multiples, ou saisie directe
d'un montant d'échéance différent dans le champ `installment_amount` — éditable sans lecture
seule tant que le crédit est en `draft`/`enquete`/etc., cf. `microfinance_loan_views.xml:104`) que
je n'ai pas pu rejouer à l'identique faute d'avoir le clic-par-clic exact de Micka.

**Systématique ou intermittent ?** Systématique dès qu'au moins un aller-retour a lieu sur
`loan_amount`, `term`, `repayment_frequency_id` ou `installment_amount` après la saisie initiale
de `term` — ce qui, dans un usage réel (corrections, hésitations, changement de périodicité),
arrive presque à coup sûr.

---

## Étape 2 — Hypothèse "confusion durée/échéances" : **infirmée par le calcul**

`_actual_duration_months()` (`microfinance_loan.py:207-221`) :
```python
if freq.period_kind == 'months':
    return self.term * freq.period_value
return (self.term * freq.period_value) / 30.0
```
Pour IS/000289 (`term=24`, fréquence Hebdomadaire `period_value=7` jours) :

**`24 × 7 / 30 = 5,6 mois`** — pas `8`, et de toute façon largement dans les bornes du produit
(`min_term=1`, `max_term=12` mois) : cette contrainte ne se déclenche même pas pour ce dossier.

`_actual_duration_months()` n'est utilisée **qu'en lecture** dans `_check_product_limits`
(`@api.constrains`, ligne 223-231) : elle ne fait qu'un test `if duration_months < ... or > ...:
raise ValidationError`, elle n'écrit jamais dans `term` ni aucun autre champ. Recherche exhaustive
confirmée : `_actual_duration_months` n'apparaît nulle part ailleurs dans le module. **L'hypothèse
numérique "24/8=3" ne correspond à aucun diviseur réel du code** (le seul diviseur de conversion
mois↔jours présent est `/30.0`, et `periods_per_year` de la fréquence Hebdomadaire est `52`, pas
`3` ni un multiple simple donnant 8 à partir de 24). Cette piste est donc écartée.

---

## Étape 3 — Lien avec le Lot 1 : **confirmé, régression neuve, pas un bug préexistant**

Les deux onchange responsables sont entièrement nouveaux dans le diff non commité (confirmé par
`git diff HEAD` : tout le bloc apparaît en `+`, aucune ligne équivalente n'existait avant) :

- `_onchange_loan_amount_recompute_installment` (déclenché par `loan_amount`, `term`,
  `repayment_frequency_id`, `interest_rate`) — écrit `installment_amount` et reconstruit
  `installment_ids` en mémoire (aperçu live).
- `_onchange_installment_amount_recompute_terms` (déclenché par `installment_amount`) — **écrit
  `term`** (`loan.term = max(1, round(computed_terms))`, ligne 688) à partir de
  `installment_amount`, en inversant la formule interest-first.

**Le code contient même déjà une trace explicite que le développeur savait ces deux onchange
couplés et s'était heurté à un symptôme voisin** : le commentaire ligne 645-646 dit littéralement
*"provoquait un tableau affichant l'ancien `term` après un aller-retour via
`_onchange_installment_amount_recompute_terms` (Lot B) - cf. incident signalé par Micka"*. Le
correctif appliqué à l'époque (faire reconstruire `installment_ids` directement dans les deux
onchange plutôt que de compter sur l'ordre d'exécution) a traité le symptôme "tableau
d'échéancier obsolète" mais **n'a pas traité la cause racine : le second onchange réécrit bel et
bien `term` lui-même**, qui est exactement le champ que l'utilisateur vient de saisir.

Concernant `n == 1` et `installment_rounding_mode` : vérifié, ni l'un ni l'autre ne déclenche
d'écriture erronée dans `term`. Le garde-fou `n == 1` (ligne 660, `if rounding and loan.term > 1`)
protège uniquement le calcul de la *cible d'arrondi* pour éviter une cible qui dépasserait le
total dû sur une échéance unique — il n'écrit jamais `term`. `installment_rounding_mode` n'est lu
que par `_round_installment_target` (calcul de valeur), jamais assigné à un champ du crédit.

**Verdict : régression introduite par le Lot 1, sans lien avec un bug antérieur.**

---

## Étape 4 — Logs serveur : aucune erreur au moment de l'édition, revert 100 % silencieux

Recherche sur `/opt/odoo17/odoo.log` (base SEFOR) :

- **Aucune `ValidationError`, aucun traceback, aucune exception** associés à un appel
  `/web/dataset/call_kw/microfinance.loan/onchange` à aucun moment dans le log (toutes les
  requêtes `onchange` sur `microfinance.loan` retournent `200` sans warning, y compris toute la
  session du 2026-08-24 tôt le matin où le dossier a manifestement été édité en boucle — rafales
  d'appels `onchange` toutes les 2 à 30 secondes, cohérentes avec des éditions/corrections
  répétées de champs).
- Deux occurrences **distinctes et antérieures** (2026-08-11 et 2026-08-18) de
  `WARNING odoo.http: La durée doit respecter les limites du produit.` sur des `web_save`
  (contrainte introduite par le Lot 1, `_check_product_limits`) — mais celles-ci datent de la
  phase de configuration du produit/de test de la contrainte elle-même (avant que `max_term` du
  produit ne soit fixé à sa valeur actuelle de 12 mois), **pas** de la session où le "24 → 8" a
  été observé, et **ne concernent pas IS/000289** dont la durée réelle (5,6 mois) est de toute
  façon conforme aux bornes actuelles. Pas de lien de cause à effet établi avec le bug audité.

**Conclusion étape 4** : le pattern "revert après `ValidationError` absorbée côté client" déjà
documenté sur ce projet **ne s'applique pas ici**. Le mécanisme réel est un écrasement en mémoire
pendant l'édition (confirmé §1), qui ne laisse par nature aucune trace serveur : c'est un pur
recalcul onchange, jamais une écriture rejetée.

---

## Étape 5 — Autres onchange en cascade sur les champs concernés

Recherche exhaustive de tous les `@api.onchange` du module (`grep -rn "api.onchange"`) touchant
`nb_installments`/`term`, `repayment_frequency_id`, `loan_amount`, `installment_amount` sur
`microfinance.loan` :

```
microfinance_loan.py:637   @api.onchange('loan_amount', 'term', 'repayment_frequency_id', 'interest_rate')
microfinance_loan.py:669   @api.onchange('installment_amount')
```

**Aucun autre onchange, ni dans `microfinance_loan.py`, ni dans un autre modèle/wizard du module,
ne touche ces quatre champs.** (Les autres onchange du module — `company_id`, `scope`, `loan_id`,
`partner_id`, `microfinance_client_type`, etc. — portent sur des modèles ou des champs sans
rapport.) Il n'existe donc **aucun onchange préexistant, indépendant du Lot 1**, qui pourrait
expliquer ou avoir contribué au bug : les deux seuls onchange en cause sont entièrement neufs.

---

## Localisation précise du code responsable

- **Mécanisme racine (boucle de rétroaction)** :
  `microfinance_loan_management/models/microfinance_loan.py:637-667`
  (`_onchange_loan_amount_recompute_installment`, écrit `installment_amount`) et
  `microfinance_loan_management/models/microfinance_loan.py:669-689`
  (`_onchange_installment_amount_recompute_terms`, écrit `term` — **ligne 688** :
  `loan.term = max(1, round(computed_terms))`).
- La cause de fond est l'asymétrie entre les deux formules : la formule "aller" arrondit la
  cible au multiple de `installment_rounding_unit` (ceiling, ligne 665), la formule "retour"
  (ligne 683-687) ne fait aucun arrondi symétrique et recalcule `term` par simple `round()` d'un
  quotient — un aller-retour ne peut donc structurellement pas être stable, et le champ que
  l'utilisateur vient de taper (`term`) est celui qui se fait écraser.

---

## Confiance et limites

| Constat | Niveau de confiance |
|---|---|
| Le couple d'onchange forme une boucle qui écrase `term` silencieusement, sans erreur serveur | **Élevé** — reproduit empiriquement avec le code et les données réelles de IS/000289 |
| Régression 100 % attribuable au Lot 1 (aucun onchange préexistant sur ces champs) | **Élevé** — confirmé par grep exhaustif + diff Git |
| L'hypothèse durée/mois (`_actual_duration_months`) est hors de cause | **Élevé** — calcul exact (5,6 mois), usage en lecture seule confirmé |
| Absence de `ValidationError`/exception au moment du bug | **Élevé** — recherche exhaustive du log sur la période |
| La valeur **exacte `8`** provient précisément de cette boucle avec la séquence de saisie réelle de Micka | **Moyen** — mes scénarios de reproduction se stabilisent à 20-23, pas 8 ; la mécanique est la même famille de cause, mais je n'ai pas le détail clic-par-clic pour rejouer la séquence exacte (nombre d'éditions, ordre, éventuelle saisie manuelle dans `installment_amount` lui-même qui est éditable et peut produire un écart bien plus grand en un seul coup) |

**Recommandation pour la suite** : avant de scoper le correctif (prochain Lot), il serait utile
que Micka confirme si le "8" est apparu après plusieurs corrections successives du formulaire ou
en une seule action, et si le champ `installment_amount` a été touché manuellement à un moment
donné — cela ne change rien au diagnostic de la cause racine (la boucle de rétroaction doit être
supprimée ou cassée dans tous les cas), mais permettrait de confirmer avec certitude totale la
chaîne d'événements exacte de ce dossier précis.
