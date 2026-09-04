# Statut — Lot 1.1 : Correction de l'écriture silencieuse des champs Comité d'Octroi

**⏸ ARRÊT respecté — en attente de validation de Micka avant le Lot 1.2 (migration ciblée
IS/000289 / IS/001076). Rien n'a été commité, rien n'a été déployé sur SEFOR, aucune donnée
réelle modifiée.**

## Ce qui a été fait

- `committee_first_review_date/decision/postpone_reason/complement/comment` et
  `committee_second_review_date/decision/comment` (`microfinance_loan_application.py`) ne sont
  plus des champs `related=` : ce sont désormais de simples champs `compute=` (lecture identique
  à avant), et **l'écriture est interceptée directement dans `write()`** de
  `microfinance.loan.application` plutôt que via un mécanisme d'inverse par champ.
- `write()` retire ces clés de `vals`, les route vers `_ensure_committee_review_slot()` (1er
  comité) ou `action_add_second_committee_review()` (2ème comité) - toutes deux idempotentes et
  déjà existantes, inchangées - puis écrit **en un seul `write()`** sur le slot enfant concerné.
  Comme demandé : si la création du slot échoue (2ème comité sans 1er refusé), l'erreur explicite
  déjà présente dans `action_add_second_committee_review()` remonte normalement, jamais de
  silence.
- 4 nouveaux tests (`tests/test_committee_review_lazy_slot.py`), chacun vérifié par **requête SQL
  directe** (pas seulement via l'ORM) comme exigé.
- `_check_committee_octroi_accepted()` (garde `action_approve`, Lot 1) : **non modifiée**, comme
  demandé - ses 7 tests existants repassent sans changement.

## Deux écarts techniques significatifs par rapport à la demande littérale

**1. Un `inverse=` classique sur un champ `related=` ne fonctionne PAS ici - contrainte du
framework Odoo, pas un choix.** `odoo/fields.py:setup_related` réassigne inconditionnellement
`self.inverse = self._inverse_related`, écrasant tout `inverse=` fourni en argument, **sauf** si
le champ est `readonly=True` (seul précédent réel trouvé dans Odoo core :
`base_automation.model_name`, justement `readonly=True`, jamais édité depuis un formulaire).
Passer ces champs en `readonly=True` ici aurait réintroduit le "même piège" déjà documenté sur le
chantier Avis CA/CDAG (`docs_dev/workflow_avis_ca_cdag/STATUS.md`, écart n°4) : le client web
n'envoie jamais la valeur d'un champ marqué readonly au moment du save. **Solution retenue** :
abandon complet de `related=` au profit de `compute=` (sans `related`, cette contrainte du
framework ne s'applique plus).

**2. Un `inverse=` partagé entre plusieurs champs (essayé en premier) déclenche un second piège,
plus sournois, qui a fait échouer un test existant non lié au Comité d'Octroi
(`test_blocked_when_first_committee_postponed`).** Idée initiale : faire partager la même
fonction `inverse=` par les 5 champs du 1er comité, pour qu'Odoo les regroupe
(`odoo/models.py:4381`, `determine_inverses[field.inverse].append(field)`) et les écrive en un
seul `write()` sur l'enfant - nécessaire pour que `decision` + `comment` posés ensemble ne
heurtent pas `_check_comment_required_if_refused` (qui validerait `decision` seul, avant que
`comment` n'ait été posé, si écrits séparément). **Ce point lui-même est un bug pré-existant, non
introduit par ce Lot** : avec l'ancien `related=`, chaque champ ayant sa propre
`Field._inverse_related` (liée à l'instance du champ, jamais partagée même pour des champs
"identiques"), le même souci existait déjà en silence - jamais détecté car **aucun test
existant n'a jamais écrit `'refused'` via ces champs parents** (tous les tests écrivent
directement sur `first_committee_review_id`, cf. `test_credit_committee_review.py`). Mais
l'inverse partagée elle-même s'est heurtée à un second piège Odoo, distinct : les champs d'un
même groupe `compute` **non explicitement présents dans les `vals` d'origine ne sont pas
recalculés** au moment où l'inverse partagée les relit - seuls ceux réellement écrits le sont.
Résultat observé : lire `committee_first_review_date` à l'intérieur de l'inverse (alors que seul
`committee_first_decision` avait été écrit) pouvait renvoyer une valeur vide et l'écraser en
base - `NotNullViolation` sur `review_date`, y compris pour un test qui ne touchait jamais qu'à
`committee_first_decision` seul (`test_blocked_when_first_committee_postponed`), confirmant que
ce piège est bien un problème du mécanisme d'inverse en lui-même, pas de mon scénario de test.
**Solution finale retenue** : abandon total du mécanisme d'inverse Odoo pour ces champs -
interception directe dans `write()` (voir ci-dessus), qui ne relit jamais un champ compute pour
en déduire une valeur, mais travaille uniquement à partir du dict `vals` reçu en argument.

## Résultat des tests

**Tests ciblés** (garde comité, comité existant, nouveau lot), clone jetable de SEFOR, `-u` :
**23/23 passants**, 0 erreur.

**Suite complète des deux modules**, avant/après ce diff (Lot 1 + Lot 1.1 cumulés) sur le même
clone : **582 tests après vs 571 avant (+11 : 7 tests Lot 1 + 4 tests Lot 1.1), 7 échecs + 81
erreurs dans les deux cas, liste strictement identique (diff vide)** - zéro régression.

## Fichiers modifiés

- `microfinance_loan_management/models/microfinance_loan_application.py` : champs
  `committee_first_*`/`committee_second_*` (`related=` → `compute=`), `write()` (interception +
  routage), `_ensure_committee_review_slot()` (docstring mise à jour, logique inchangée).
- `microfinance_loan_management/tests/test_committee_review_lazy_slot.py` (nouveau, 4 tests) +
  `tests/__init__.py` (import).

Aucune modification de vue (les champs restent affichés/édités exactement comme avant - même
`widget="radio"`, mêmes `invisible=`/`required=` en XML, rien à changer côté client). Aucune
modification de `_check_committee_octroi_accepted()`, d'`action_add_second_committee_review()`
(logique), ni des contraintes du modèle enfant. Aucun commit, aucun déploiement.

## Rappel pour le Lot 1.3 (commit unique)

Le commit final devra regrouper, comme demandé : la garde Lot 1 (`microfinance_loan.py`), ce
correctif Lot 1.1, et la migration ciblée Lot 1.2 (à venir, après validation Micka) - un seul
commit, pas de commit isolé préalable.

**En attente de la validation de Micka avant le Lot 1.2.**
