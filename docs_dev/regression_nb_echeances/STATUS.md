# Statut — Lot 1-bis : correction de la boucle de rétroaction term <-> installment_amount

**Arrêt obligatoire après ce Lot — en attente de revue manuelle par Micka avant tout commit.**

## Cause (rappel, cf. AUDIT.md pour le détail)

`microfinance_loan.py:637-720` (avant correctif : lignes 637-689) : les deux onchange
`_onchange_loan_amount_recompute_installment` (écrit `installment_amount` à partir de `term`) et
`_onchange_installment_amount_recompute_terms` (écrit `term` à partir de `installment_amount`)
se redéclenchent l'un l'autre dans le même cycle onchange dès qu'un des deux champs change,
parce que la formule aller (arrondit la cible au multiple supérieur de
`installment_rounding_unit`, mode `ceiling`) et la formule retour (simple division puis
`round()`, sans arrondi symétrique) ne sont pas l'inverse exacte l'une de l'autre. Résultat
vérifié sur IS/000289 (audit) : taper `term = 24` faisait retomber le champ à `23` dans le même
appel serveur, avant même que la valeur saisie ne soit renvoyée au formulaire.

## Correctif appliqué

**Écart assumé par rapport à la structure d'exemple donnée dans la demande** — à signaler
explicitement en revue :

La demande proposait de comparer chaque valeur recalculée à **l'ancienne valeur du même champ**
(ex. : ne pas réécrire `installment_amount` si elle est déjà égale à la nouvelle cible ; ne pas
réécrire `term` si déjà égal au nouveau `term` calculé). **J'ai vérifié par simulation (avant
d'écrire le code, puis empiriquement après) que cette garde littérale ne corrige PAS le symptôme
principal** : lors de la toute première saisie légitime de `term = 24`, `installment_amount`
part de `0.0` (donc différent de la cible calculée) et le nouveau `term` calculé en retour (`23`)
est authentiquement différent de `24` — la garde "recalcule vers une valeur différente de l'ancienne"
ne bloque donc rien, précisément parce que le calcul aller et le calcul retour ne sont pas des
fonctions inverses l'une de l'autre (arrondi `ceiling` d'un côté, aucun arrondi symétrique de
l'autre). Une garde de simple non-régression n'empêche que la dérive lors d'éditions
*ultérieures*, pas l'écrasement initial qui est le symptôme rapporté par Micka.

**Garde effectivement implémentée**, plus robuste et qui corrige bien le symptôme principal :
dans l'onchange retour, avant de recalculer `term`, on compare `installment_amount` non pas à
son ancienne valeur, mais à **ce que l'onchange aller calculerait pour le `term` ACTUEL** (via
une nouvelle méthode factorisée `_compute_installment_target()`, ligne 637 - extraite du corps de
l'onchange aller, aucune formule de calcul modifiée). Si les deux correspondent déjà, le
changement d'`installment_amount` ne peut venir que du recalcul automatique de l'onchange aller
lui-même (pas d'une saisie manuelle de l'utilisateur dans ce champ) : on ne touche alors pas à
`term`. On ne recalcule `term` que lorsque `installment_amount` diverge réellement de cette
cible - c'est-à-dire quand l'utilisateur vient de modifier `installment_amount` à la main. C'est
toujours une "garde d'idempotence" au sens demandé (aucune formule de calcul changée, seule une
condition ajoutée autour de l'affectation existante), mais le point de comparaison est différent
de l'exemple fourni.

Une garde symétrique plus simple (comparer à l'ancienne valeur) a été gardée en plus côté
onchange aller, pour éviter une réécriture inutile d'`installment_amount` quand la cible n'a
réellement pas changé (cf. commentaire ligne 673-677).

**Champs tiers** : `installment_ids` est reconstruit sans condition dans les deux onchange - il
ne porte aucun onchange propre (vérifié par grep exhaustif, cf. AUDIT.md étape 5 et commentaire
ligne 686-690), donc le reconstruire ne peut pas retrigger la boucle ; le garder inconditionnel
évite aussi un cas marginal où `term` change sans que la cible arrondie change.

**Commentaire ligne 645-646 (ancien)** : remplacé. Il documentait un symptôme voisin déjà
partiellement traité (tableau `installment_ids` affichant l'ancien `term`) sans mentionner que le
couplage pouvait aussi écraser `term` lui-même - la nouvelle version (lignes 673-677 et 702-711)
documente la cause réelle et la garde qui la corrige, avec renvoi vers `AUDIT.md`.

## Résultat des tests

Nouveau fichier `microfinance_loan_management/tests/test_loan_term_installment_feedback_loop.py`
(ajouté à `tests/__init__.py`), utilisant `Form()` - même méthode que l'audit, rejoue exactement
la cascade onchange du client web (par opposition à `test_loan_installment_amount.py` existant,
qui appelle les onchange comme de simples méthodes et ne pouvait donc pas détecter ce bug,
cf. son propre docstring).

| Test | Correspond à | Résultat |
|---|---|---|
| `test_term_survives_direct_entry` | Demande §Tests 1 (séquence simple) | **PASS** |
| `test_term_stable_across_repeated_edits` | Demande §Tests 2 (multi-éditions montant) | **PASS** |
| `test_term_stable_across_frequency_change` | Demande §Tests 2 (multi-éditions périodicité, variante) | **PASS** |
| `test_installment_amount_manual_edit_recomputes_term_once_and_sticks` | Demande §Tests 3 (sens inverse) | **PASS** |
| `test_is000289_non_regression_schedule_unchanged` | Demande §Tests 4 (non-régression IS/000289) | **PASS** |

Vérification empirique complémentaire (`Form()` ad hoc contre les vraies données PRET RURAL/
IS/000289, même méthode que l'audit, lecture seule sur SEFOR) :
- `term = 24` reste `24` (avant correctif : retombait à `23` immédiatement).
- 12 répétitions de retouche `loan_amount` après coup : `term` reste `24` (avant correctif :
  dérivait progressivement vers 20-22).
- Changement de périodicité en cours de saisie (Journalier → Hebdomadaire, ou Mensuel →
  Hebdomadaire) après `term = 24` : `term` reste `24`.
- Modification manuelle d'`installment_amount` à 40 000 Ar (`term=24`, `loan_amount=500000`) :
  `term` recalculé une fois à `14`, puis stable indéfiniment (retouches ultérieures de
  `loan_amount` sans effet sur `term` ni sur `installment_amount`).

## Suite de tests complète du module

Exécutée sur un **clone jetable** de SEFOR (`pg_dump`/`pg_restore` vers une base séparée,
détruite après usage - aucune écriture sur SEFOR) car une installation entièrement fraîche du
module échoue pour une raison **indépendante de ce lot** (contrainte NOT NULL sur
`res_company.agency_code` lors d'un install propre, société de base sans code agence - non
traité ici, hors périmètre).

Résultat identique avant/après ce correctif (diff exact des tests en échec) : **6 échecs, 62
erreurs, toujours les mêmes**, tous dus à des données réelles présentes dans le clone (fonds
bailleurs actifs rendant `fond_credit_id` obligatoire en `action_disburse`, codes d'activité/
journées de caisse déjà utilisés dans SEFOR en collision avec les fixtures de test, etc.) - un
artefact de test contre un clone de production, sans rapport avec ce lot. **Aucune régression
introduite** : le diff des tests en échec entre l'état d'avant ce correctif et l'état d'après est
strictement vide.

## Fichiers modifiés

- `microfinance_loan_management/models/microfinance_loan.py` : `_compute_installment_target()`
  (nouvelle méthode, ligne 637) + gardes anti-boucle dans les deux onchange (lignes 663-733,
  remplace l'ancien bloc 637-689).
- `microfinance_loan_management/tests/test_loan_term_installment_feedback_loop.py` (nouveau).
- `microfinance_loan_management/tests/__init__.py` (import du nouveau fichier de test).

Aucune modification de `_compute_installment_targets`, `_round_installment_target`,
`_build_installment_commands`, ni du mode d'arrondi `ceiling` - conformément au périmètre.
