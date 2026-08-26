# Statut — Lot 1 : champs Avis CA/CDAG sur microfinance.loan

**Arrêt obligatoire après ce Lot — en attente de revue manuelle par Micka avant tout commit.**

## Ce qui a été fait

- 9 nouveaux champs sur `microfinance.loan` (8 visibles + `avis_cdag_manually_set`, technique).
- `_compute_installment_target()` paramétrée (`loan_amount`/`term` optionnels, défaut inchangé)
  et nouvelle méthode `_compute_term_from_installment_amount()` extraite de l'ancien code inline
  de `_onchange_installment_amount_recompute_terms` — même formule, aucun changement de calcul,
  réutilisées telles quelles pour les blocs Avis CA et Avis CDAG.
- 4 nouveaux onchange (aller/retour CA, aller/retour CDAG), gardes d'idempotence sur chacun.
- Cascade CA → CDAG, figée définitivement dès que le CDAG modifie son propre bloc
  (`avis_cdag_manually_set`, jamais remis à False).
- `write()` surchargé + `_propagate_avis_to_loan()` : répercussion immédiate sur
  `loan_amount`/`term`/`installment_amount` + régénération de l'échéancier à chaque sauvegarde,
  uniquement pendant que l'état est `avis_ca`/`avis_cdag`. Guard décaissement via
  `_EDITABLE_SCHEDULE_STATES` (même garde que partout ailleurs dans ce fichier).
- `action_ca_review`/`action_cdag_review` posent les valeurs par défaut et appellent l'onchange
  correspondant (même filet de sécurité que `action_start_enquete` déjà existant).
- Vue : nouvelle page "Avis CA / CDAG" sur le formulaire crédit, sans groups/sécurité (Lot 2).
- `microfinance_loan_management/tests/test_loan_avis_ca_cdag.py` : 8 tests (les 7 demandés +
  un test 6bis pour le cas symétrique CDAG), tous passants (détail plus bas).

## Écarts par rapport à la spec littérale — à valider explicitement

**1. Helpers "existants" du snippet — en réalité créés dans ce Lot, pas déjà présents.**
`_compute_term_from_installment_amount` n'existait pas avant ce Lot (la formule était inline
dans `_onchange_installment_amount_recompute_terms`) : je l'ai extraite pour la réutiliser,
formule strictement identique, aucun calcul changé. `_compute_installment_target` existait mais
sans paramètres (lisait toujours `self.loan_amount`/`self.term`) : ajout de deux paramètres
optionnels, défaut = comportement exact d'avant. Aucun des deux changements ne modifie le
résultat des appels déjà existants dans le code (`_onchange_loan_amount_recompute_installment`,
`_onchange_installment_amount_recompute_terms`) - vérifié par les tests déjà existants du Lot
1-bis, toujours passants (cf. plus bas).

**2. Cascade rendue inconditionnelle, pas seulement dans la branche d'écriture
`avis_ca_installment_amount`.** Le snippet de la demande plaçait la cascade CA→CDAG à
l'intérieur du `if` d'écriture d'`avis_ca_installment_amount` (donc sautée si la cible est déjà
auto-cohérente). J'ai vérifié que cela cassait la cascade dans un cas réel : après un
aller-retour via l'onchange inverse (l'utilisateur modifie `avis_ca_installment_amount`
directement), `avis_ca_term` change mais le recalcul de la cible pour ce nouveau terme retombe
souvent exactement sur la même valeur (même mécanisme d'auto-cohérence que le Lot 1-bis) - la
cascade aurait alors été sautée alors même que `avis_ca_term` a réellement changé et doit être
répercuté. Rendue inconditionnelle (déplacée hors du `if`), même principe que le traitement
d'`installment_ids` dans le Lot 1-bis.

**3. `avis_cdag_manually_set` : détection dupliquée dans les deux onchange CDAG, pas un 3e
onchange séparé.** La demande suggérait un onchange dédié écoutant les 3 champs CDAG à la fois.
Risque identifié (question posée par la demande elle-même) : un onchange déclenché par 3 champs
en même temps peut s'exécuter plusieurs fois dans le même cycle (une fois par champ déclencheur
présent dans le lot à traiter). Solution retenue : le test de divergence
(`avis_cdag_amount/term != avis_ca_amount/term` ⇒ saisie manuelle) est dupliqué en tête des deux
onchange CDAG existants (aller et retour) plutôt qu'isolé dans un 3e onchange - une détection
placée uniquement dans l'onchange aller laisserait un cas passer par analyse (édition manuelle
directe d'`avis_cdag_installment_amount` dont le terme recalculé coïncide avec l'ancien : rien
ne change de valeur, l'onchange aller ne serait alors jamais redéclenché dans le même cycle -
pas observé via un test qui aurait échoué, identifié en amont par relecture du mécanisme de
cascade des champs déclencheurs). La duplication (2 lignes, comparaison bon marché) ferme ce cas
sans reproduire le risque de triple exécution signalé par la demande.

**4. Vue : pas de `readonly` conditionné à l'état, contrairement à `installment_amount`.**
Un premier essai copiait la convention `readonly="state != 'avis_ca'"` /
`readonly="state != 'avis_cdag'"` (même pattern qu'`installment_amount` existant). **Constaté en
test (pas supposé)** : Odoo n'enregistre jamais un champ marqué readonly au moment de la
sauvegarde, même si un onchange vient de le modifier (`odoo/tests/form.py:405`, *"does not save
readonly fields"* - comportement standard du client web, pas une particularité de l'outil de
test). Cela bloquait précisément la cascade CA→CDAG : elle écrit `avis_cdag_*` alors que l'état
est encore `avis_ca`, donc `avis_cdag_amount` restait marqué readonly à cet instant et la valeur
cascadée n'était jamais persistée à la sauvegarde (confirmé par un test qui échouait
systématiquement avant ce retrait). Retiré entièrement - la vue de ce Lot 1 n'a donc aucune
restriction d'édition par état, ce qui est cohérent avec "pas de sécurité dans ce lot" mais va
au-delà de ce que la demande précisait explicitement sur ce point.

**5. Ajout d'une page de vue non demandée explicitement dans la liste des livrables.** La
demande liste "champs, calcul, cascade, propagation" comme périmètre, sans mentionner les vues.
Une page minimale (`Avis CA / CDAG`, sans `groups=`) a été ajoutée car nécessaire pour que les
champs soient accessibles à un formulaire réel et testables via `Form()` (méthode explicitement
demandée en section 6) - sans elle, `Form()` aurait levé "field not found in the view" comme
rencontré lors de l'audit précédent. Si ce n'est pas souhaité à ce stade (attendre le Lot 2), à
signaler : cela nécessiterait de retester la cascade autrement (appels directs aux méthodes
onchange, comme dans `test_loan_installment_amount.py` existant, avec la limite documentée dans
son propre docstring : ne détecte pas les problèmes de cascade réelle).

## Résultat des tests

`microfinance_loan_management/tests/test_loan_avis_ca_cdag.py`, **8/8 passants** :

| Test | Correspond à | Résultat |
|---|---|---|
| `test_1_defaults_populated_on_ca_review` | Demande, test 1 | **PASS** |
| `test_2_ca_amount_change_recomputes_installment_and_cascades` | Demande, test 2 | **PASS** |
| `test_3_ca_term_change_recomputes_installment_and_cascades` | Demande, test 3 | **PASS** |
| `test_4_no_drift_across_repeated_edits` | Demande, test 4 (anti-boucle) | **PASS** |
| `test_5_cdag_manual_edit_stops_cascade` | Demande, test 5 | **PASS** |
| `test_6_propagation_to_loan_on_save_in_avis_ca_state` | Demande, test 6 | **PASS** |
| `test_6bis_propagation_uses_cdag_once_in_avis_cdag_state` | Cas symétrique CDAG, non demandé explicitement mais couvre `_propagate_avis_to_loan` côté `avis_cdag` (le test 6 de la demande ne couvre que le côté `avis_ca`) | **PASS** |
| `test_7_no_propagation_once_disbursed` | Demande, test 7 | **PASS** |

Exécuté sur un **clone jetable** de SEFOR (`pg_dump`/`pg_restore`, détruit après usage - aucune
écriture sur SEFOR), même méthode que le Lot 1-bis, pour la même raison (installation fraîche du
module bloquée par un problème indépendant, `res_company.agency_code`, déjà signalé au Lot 1-bis).

**Suite complète du module** : 429 tests, mêmes 6 échecs/62 erreurs pré-existants qu'avant ce
Lot (diff exact des tests en échec entre avant/après = **vide**) - tous dus à des données réelles
du clone (fonds bailleurs actifs, codes déjà utilisés), sans rapport avec ce Lot. Aucune
régression introduite, y compris sur les tests du Lot 1-bis (`test_loan_term_installment_
feedback_loop.py`, toujours 5/5 passants, confirmant que le paramétrage de
`_compute_installment_target` n'a rien changé à son comportement par défaut).

## Fichiers modifiés

- `microfinance_loan_management/models/microfinance_loan.py` : 9 champs, `write()` +
  `_propagate_avis_to_loan()`, `action_ca_review`/`action_cdag_review` mis à jour,
  `_compute_installment_target` paramétrée, `_compute_term_from_installment_amount` (nouvelle),
  4 nouveaux onchange Avis CA/CDAG.
- `microfinance_loan_management/views/microfinance_loan_views.xml` : nouvelle page "Avis CA /
  CDAG" (cf. écart n°5 ci-dessus).
- `microfinance_loan_management/tests/test_loan_avis_ca_cdag.py` (nouveau) +
  `tests/__init__.py` (import).
- `microfinance_loan_management/__manifest__.py` : version 17.0.1.8.0 → 17.0.1.9.0 (convention
  déjà suivie au Lot 1/Lot 1-bis, pas de migration nécessaire - aucune donnée existante à
  corriger, un seul crédit en base SEFOR, toujours en état 'enquete').

Aucune modification de `microfinance.loan.product.validation_authority`, ni d'`épargne exigée`
(traitée en saisie libre, aucune règle de calcul existante trouvée - confirmé à l'audit
précédent) - conformément au périmètre.

## Extension (même session) — les 13 champs orphelins de microfinance.loan.application

Suite à un retour visuel de Micka (capture d'écran montrant la section VII du dossier
d'instruction toujours à zéro) : confusion entre les nouveaux champs `avis_ca_*`/`avis_cdag_*`
du crédit (nouvel onglet "Avis CA / CDAG" sur `microfinance.loan`, ce Lot) et les 13 champs
préexistants de `microfinance.loan.application` (section "VII — Avis du CA et du CDAG" du
dossier), explicitement listés en "hors périmètre" de ce Lot 1. Question posée et tranchée par
Micka : les champs du dossier reflètent le crédit en lecture seule (pas de logique dupliquée).

**Fait** : 9 des 13 champs de `microfinance.loan.application` convertis en champs `related`
readonly vers le crédit lié - même mécanisme déjà en place pour `requested_amount`
(`related='loan_id.loan_amount'`, préexistant) :

| Champ dossier | related vers (microfinance.loan) |
|---|---|
| `requested_amount` (déjà en place) | `loan_id.loan_amount` |
| `repayment_amount` | `loan_id.installment_amount` |
| `period` | `loan_id.term` |
| `ca_amount` | `loan_id.avis_ca_amount` |
| `ca_required_savings` | `loan_id.avis_ca_epargne_exigee` |
| `ca_repayment_amount` | `loan_id.avis_ca_installment_amount` |
| `ca_period` | `loan_id.avis_ca_term` |
| `cdag_amount` | `loan_id.avis_cdag_amount` |
| `cdag_required_savings` | `loan_id.avis_cdag_epargne_exigee` |
| `cdag_repayment_amount` | `loan_id.avis_cdag_installment_amount` |
| `cdag_period` | `loan_id.avis_cdag_term` |

`required_savings` ("Épargne exigée (demande)") et `available_savings` ("Épargne disponible")
restent des champs saisis librement - aucun équivalent sur `microfinance.loan` à refléter (pas
de notion d'épargne exigée pour la demande initiale avant tout avis, ni de solde d'épargne
disponible sur le crédit).

**Point à noter, pas tranché par la question posée** : `repayment_amount`/`period` du dossier
reflètent désormais `loan_id.installment_amount`/`loan_id.term`, qui **changent** dès qu'un avis
CA/CDAG est propagé (`_propagate_avis_to_loan`, ce Lot) - le champ "Remboursement (demande)"
n'est donc pas une valeur figée de la demande initiale, il suit la valeur courante du crédit au
même titre que `requested_amount` (qui a déjà ce comportement avant ce chantier). Signalé pour
information, pas un problème constaté, mais à garder en tête si une vraie valeur "demande
initiale figée" est un jour souhaitée séparément de la valeur courante du crédit.

**Vue** : aucune modification nécessaire (`readonly=True` porté par la définition du champ
lui-même, pas par un attribut de vue - même mécanisme que `requested_amount`, déjà readonly
sans rien de spécial dans `microfinance_loan_application_views.xml`).

**Tests** : aucun test existant ne référence ces 13 champs (recherche exhaustive) - rien cassé.
Suite complète revalidée sur un nouveau clone jetable de SEFOR : toujours 6 échecs/62 erreurs
pré-existants, diff exact vide par rapport à l'état juste avant cette extension.

**Déployé sur SEFOR** : `-u microfinance_loan_management` exécuté sans erreur (schéma + related
synchronisés). **Restart du service toujours à faire côté Micka** (`sudo systemctl restart
odoo17`) - même limitation d'environnement que précédemment, pas d'accès sudo interactif ici.
