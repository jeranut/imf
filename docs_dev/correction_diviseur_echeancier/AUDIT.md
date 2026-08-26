# Audit — Diviseur de calcul de la cible d'échéance (n vs n-1)

Audit en lecture seule (Lot 0). **Aucune modification de code, de données ni de fichier de
test n'a été effectuée** pour produire ce rapport. Toutes les valeurs ci-dessous ont été
vérifiées directement sur le dépôt (`microfinance_loan_management/models/microfinance_loan.py`,
`tests/test_interest_first_schedule.py`) et sur la base réelle SEFOR (lecture seule, aucune
écriture), sauf mention explicite du contraire.

## Résumé exécutif

**L'hypothèse `/(n-1)` n'est PAS confirmée sans exception.** Elle matche IS/000289 mais
**contredit directement** le dossier de référence déjà validé IS/01913, qui reste conforme à
`/n`. Le cas BM, présenté dans la demande comme deuxième élément de confirmation, s'est révélé
**non vérifiable** (aucun enregistrement en base, chiffres fournis internement incohérents entre
eux) et, pire, **produit une tranche finale négative** si on lui applique naïvement `/(n-1)`
avec arrondi au plus proche — signe qu'une éventuelle correction ne peut pas être un simple
remplacement `n` → `n-1` partout, sous peine de casser d'autres dossiers. Voir conclusion
détaillée en fin de document.

---

## Étape 1 — Inventaire des échéanciers de référence disponibles

Un seul dossier dispose d'un échéancier LPF papier réellement présent et documenté dans le
dépôt : **IS/01913**, cité dans `tests/test_interest_first_schedule.py:13` et
`docs/ecarts_lpf_remboursement.md:77-79` comme "reçu imprimé". Aucun scan/PDF/image de
IS/000289 ou de BM n'existe dans le dépôt (recherché exhaustivement : aucun `.pdf`/`.png`/`.jpg`
autre que des assets d'icônes de modules, aucune pièce jointe en base SEFOR nommée "BM" ou
"01913"/"000289"). Les chiffres de IS/000289 et BM utilisés ci-dessous proviennent donc
uniquement du texte de la demande (comparaison de Micka avec l'échéancier papier, relayée par
l'utilisateur) — pas d'une vérification visuelle indépendante de ma part.

| Dossier | Statut de la source | Capital | Taux | Périodicité | n |
|---|---|---|---|---|---|
| **IS/01913** | Reçu imprimé, déjà documenté et testé dans le dépôt | 700 000 Ar | 36 %/an | Mensuel | 11 |
| **IS/000289** | Dossier réel en base SEFOR (`microfinance.loan` id 1449), figures papier rapportées par Micka dans la demande | 500 000 Ar | 36 %/an | Hebdomadaire | 24 |
| **BM** | **Aucun enregistrement trouvé en base** (partenaire "BM" existe, id 235, mais 0 crédit/dossier associé) ; figures données dans la demande elle-même comme "à confirmer avec les vraies valeurs DB" | 800 000 Ar | inconnu (voir plus bas) | Hebdomadaire | **42 ou 43 — ambigu, voir Étape 2** |

**Recherche effectuée pour BM** (toutes négatives) : `res_partner` nom "BM" → 1 résultat (id 235,
aucun crédit lié) ; `microfinance_loan` avec `loan_amount` entre 750 000 et 850 000 → 0 résultat
sur SEFOR ; `microfinance_loan_application` avec `requested_amount` dans cette plage → 0
résultat ; `ir_attachment` dont le nom contient "BM" → 0 résultat. **Aucune autre base
disponible sur ce serveur ne contient le modèle `microfinance_loan`** (vérifié sur `CEFOR`).
Le dossier BM, s'il existe, n'a donc jamais été saisi dans cette instance Odoo, ou a été saisi
sous une référence/un nom de partenaire différent que je n'ai pas pu identifier.

---

## Étape 2 — Calcul comparatif systématique

### IS/01913 (référence déjà validée)

Intérêt total = 700 000 × 0,36 × (11/12) = **231 000 Ar** exact (aucun arrondi de taux ici,
mensuel). Total dû = **931 000 Ar**.

| n | Total dû | target (/n, arrondi 1000) | target (/(n-1), arrondi 1000) | target LPF réel |
|---|---|---|---|---|
| 11 | 931 000 | **85 000** | 93 000 | **85 000** |

Reconstitution :
- `/n` (10 tranches à 85 000 + dernière) : 10 × 85 000 = 850 000 ; reliquat = 931 000 − 850 000 =
  **81 000** → identique au document de référence (85 000 / 85 000 / 61 000+24 000 / 85 000 ×7 /
  **81 000**), confirmé par `test_is01913_reference_case_interest_exhausted_over_three_installments`.
- `/(n-1)` (10 tranches à 93 000 + dernière) : 10 × 93 000 = 930 000 ; reliquat = 931 000 −
  930 000 = **1 000**. Ce résultat (dernière tranche à 1 000 Ar, alors que le papier montre
  81 000 Ar) est en contradiction frontale avec le document imprimé.

**`/n` matche exactement le papier ; `/(n-1)` ne matche pas du tout.**

### IS/000289

Intérêt total = 500 000 × 0,36 × (24/52) = **83 076,92 Ar** (formule alignée LPF
`periods_per_year`, chantier du 2026-08-18). Total dû = **583 076,92 Ar**.

| n | Total dû | target (/n, arrondi 1000) | target (/(n-1), arrondi 1000) | target LPF réel (rapporté) |
|---|---|---|---|---|
| 24 | 583 076,92 | **24 000** (= Odoo actuel) | **25 000** | **25 000** |

Reconstitution :
- `/n` (23 tranches à 24 000 + dernière) : 23 × 24 000 = 552 000 ; reliquat = 583 076,92 −
  552 000 = **31 076,92** → identique à la valeur "Odoo (actuel)" citée dans la demande.
- `/(n-1)` (23 tranches à 25 000 + dernière) : 23 × 25 000 = 575 000 ; reliquat = 583 076,92 −
  575 000 = **8 076,92 ≈ 8 077 Ar** → identique à la valeur "LPF (papier)" citée dans la demande
  (23 tranches à 25 000 + reliquat 8 077).

**`/(n-1)` matche le papier rapporté ; `/n` matche l'Odoo actuel (donc ne matche pas le
papier).** Les deux formules donnent une somme reconstituée strictement égale au total dû
(vérifié à 0,01 Ar près) — aucune des deux ne "perd" d'argent, seule la répartition change.

### BM — non vérifiable de façon rigoureuse

Deux incohérences internes empêchent de traiter ce cas comme une confirmation solide :

**1. Le nombre d'échéances lui-même est ambigu.** La demande cite "42 ou 43 échéances selon la
source" — ce n'est pas un simple flou d'arrondi, c'est deux valeurs de `n` différentes utilisées
dans le même raisonnement.

**2. Le total dû fourni est incohérent avec les chiffres "Odoo actuel" fournis dans la même
demande.**
- Le texte donne explicitement : total dû ≈ **1 032 615 Ar** ("déduit du profil comparable, à
  confirmer avec les vraies valeurs DB" — la demande reconnaît elle-même cette valeur comme non
  confirmée).
- Mais il donne aussi : "Odoo (actuel) : tranches à 24 000 Ar, reliquat 23 538,46 Ar sur la 43e
  échéance" — ce qui implique un total dû reconstitué de 42 × 24 000 + 23 538,46 = **1 031
  538,46 Ar**.
- Écart entre les deux : **1 076,54 Ar** — trop important pour être un simple bruit d'arrondi.

Je n'ai pas pu lever cette ambiguïté en l'absence de tout enregistrement en base ou de document
source consultable (cf. Étape 1). **Je signale ce doute explicitement plutôt que de choisir
arbitrairement l'une des deux valeurs.**

**Calcul effectué malgré tout, à titre indicatif, en utilisant n=43 et le total dû
auto-cohérent avec les chiffres "Odoo actuel" (1 031 538,46 Ar), pour tester la mécanique de
l'hypothèse `/(n-1)` :**

| n | Total dû (dérivé, non confirmé) | target (/n=43, arrondi 1000) | target (/(n-1)=42, arrondi 1000) | target LPF réel (rapporté) |
|---|---|---|---|---|
| 43 | 1 031 538,46 | **24 000** (= Odoo actuel) | **25 000** | 25 000 (rapporté, sur un crédit dit "comparable à 42 échéances" — potentiellement un **dossier différent**, pas nécessairement BM lui-même) |

Reconstitution `/(n-1)=42` : 42 × 25 000 = **1 050 000** — **supérieur au total dû lui-même**
(1 031 538,46 Ar). Le reliquat de la dernière tranche serait alors **négatif**
(1 031 538,46 − 1 050 000 = **−18 461,54 Ar**). Un échéancier avec une tranche finale négative
est structurellement invalide. Ce résultat ne dépend pas du choix entre les deux valeurs de
total dû données dans la demande : avec l'autre valeur (1 032 615 Ar), le calcul `/(n-1)` donne
aussi 25 000 (arrondi) et un reliquat tout aussi négatif (−17 385,4 Ar).

**Conclusion sur BM : ce cas ne peut pas servir de confirmation rigoureuse.** Au mieux, il est
directionnellement cohérent avec IS/000289 (le papier semble viser une cible plus haute que
l'Odoo actuel) ; au pire, il révèle qu'un remplacement naïf `/n` → `/(n-1)` avec le même arrondi
"au plus proche" peut produire un échéancier invalide (tranche finale négative) sur au moins un
profil de crédit à nombreuses échéances.

---

## Étape 3 — Vérification critique du dossier de référence (IS/01913)

**`/n` et `/(n-1)` donnent des montants de tranche différents sur IS/01913** (85 000 contre
93 000 — un écart de 8 000 Ar par tranche, largement au-dessus du bruit d'arrondi). Ce n'est
donc pas un cas où l'ambiguïté serait passée inaperçue par coïncidence : **la règle actuelle
`/n` a été et reste correctement validée sur ce dossier**, avec un résultat qui correspond
exactement au document imprimé (cf. Étape 2 ci-dessus et le test existant
`test_is01913_reference_case_interest_exhausted_over_three_installments`). Rien n'indique que
la règle `/n` était "déjà fausse sans que cela ait été remarqué" sur ce dossier — au contraire,
elle y est démontrablement juste.

**Ce point est le cœur du problème à trancher au Lot 1** : IS/01913 (11 échéances mensuelles)
valide `/n`, IS/000289 (24 échéances hebdomadaires) valide `/(n-1)`. Une hypothèse à explorer —
non tranchée ici, hors périmètre du Lot 0 — est que la règle LPF pourrait dépendre d'un autre
facteur que je n'ai pas identifié (périodicité infra-mensuelle vs mensuelle ? nombre
d'échéances au-delà d'un certain seuil ? une distinction entre "durée courte" et "durée
longue" ?), plutôt qu'un simple remplacement universel de `n` par `n-1`. Les deux dossiers
disponibles ne permettent de trancher qu'entre "toujours `/n`" et "toujours `/(n-1)`" — aucun
des deux n'est confirmé par les deux dossiers simultanément.

---

## Étape 4 — Localisation du code concerné

### Calcul de la cible (le cœur du sujet)

- **`_compute_installment_targets(self, total_due, rounding_unit, rounding_mode)`** —
  `microfinance_loan_management/models/microfinance_loan.py:687-717`. Ligne clé :
  `raw_target = total_due / n` à la ligne **704**, où `n = self.term` (ligne 703). C'est ici
  que `n` devrait devenir `n - 1` si l'hypothèse est confirmée pour la branche
  `rounding_mode == 'last_installment'` (lignes 715-717) — la branche `'distributed'`
  (lignes 707-714) a sa propre logique de floor + répartition, à réexaminer séparément
  (cf. Étape 5).
- **`_build_installment_commands(self, rounding_mode='last_installment')`** — même fichier,
  lignes 719-816. Appelle `_compute_installment_targets` à la ligne **777**, dans la branche
  `interest_method == 'flat'` (lignes 751-796). La boucle consomme `installment_targets[idx-1]`
  pour les tranches `1..term-1` et calcule la dernière tranche (`idx == self.term`, ligne 782)
  par différence exacte — ce mécanisme de "reliquat exact sur la dernière tranche" ne change
  pas, seule la valeur des cibles intermédiaires change.

### Deuxième calcul indépendant du même montant, à ne pas oublier

**`_onchange_loan_amount_recompute_installment`** —
`microfinance_loan_management/models/microfinance_loan.py:637-663`, ligne **658** :
`target = (loan.loan_amount + total_interest) / loan.term`. C'est une formule **dupliquée**, pas
un appel à `_compute_installment_targets`, qui alimente le champ affiché `installment_amount`
(l'"Échéance" visible dans le formulaire avant génération de l'échéancier détaillé). **Si la
formule de `_compute_installment_targets` change au Lot 1, cette ligne devra être alignée en
même temps**, sous peine que le champ "Échéance" affiché à l'écran ne corresponde plus au
montant réellement généré dans le tableau (régression silencieuse, pas mentionnée dans la
demande initiale — je la signale ici pour qu'elle ne soit pas oubliée au Lot 1).

### Points d'appel de `action_generate_schedule` / `_build_installment_commands`

| Appelant | Fichier:ligne | Mode utilisé |
|---|---|---|
| Bouton "Générer échéancier" → `action_open_generate_schedule_wizard` → wizard `microfinance.loan.schedule.rounding.wizard.action_confirm` | `wizard/microfinance_loan_schedule_rounding_wizard.py:17` | Choisi par l'utilisateur dans le wizard (`last_installment` ou `distributed`) |
| `action_generate_schedule(self, rounding_mode='last_installment')` | `models/microfinance_loan.py:818-831` | Paramètre, défaut `last_installment` |
| `action_disburse()` — génère automatiquement si l'échéancier est vide au décaissement | `models/microfinance_loan.py:1171` | Appel sans argument → toujours `last_installment` |
| `_onchange_loan_amount_recompute_installment` (aperçu champ "Échéance" + rafraîchissement live du tableau) | `models/microfinance_loan.py:637-663` | Formule dupliquée (voir ci-dessus), pas de paramètre `rounding_mode` |
| `_onchange_installment_amount_recompute_terms` (sens inverse : Échéance → nombre d'échéances) | `models/microfinance_loan.py:665-685` | Rafraîchit aussi le tableau via `_build_installment_commands()` sans argument → toujours `last_installment` |

### Tests unitaires qui figent la valeur `/n` (à réécrire au Lot 1, non modifiés ici)

| Fichier | Test(s) | Ce qu'ils figent |
|---|---|---|
| `tests/test_interest_first_schedule.py` | `test_is01913_reference_case_interest_exhausted_over_three_installments` (ligne 12) | Cas de référence papier — **si `/n` change globalement, ce test casserait** ; c'est le signal d'alarme central de cet audit (cf. Étape 3). |
| idem | `test_small_credit_rounded_target_reaches_zero_without_special_case` (ligne 60) | `raw_target = (200+8)/4`, implicitement `/n` |
| idem | `test_short_loan_interest_fits_entirely_in_first_installment` (ligne 90, calcul explicite ligne 104) | `installment_target = (1000.0 + total_interest) / 2` |
| idem | `test_distributed_rounding_mode_spreads_remainder_over_last_installments` (ligne 112) | `average = total_due / 24` (assertion de proximité, pas un calcul de cible direct, mais suppose `/n` comme référentiel "moyenne") |
| idem | `test_last_installment_mode_is_still_the_default_and_unchanged` (ligne 145) | Valeurs exactes câblées en dur : 24 000 / 31 076,92, précisément les valeurs "Odoo actuel" que cet audit met en cause pour IS/000289 |
| `tests/test_grace_period.py` | `test_first_installment_after_short_grace_period` (ligne 19, calcul ligne 38), `test_grace_period_longer_than_period_creates_dedicated_installment` (ligne 42, calcul ligne 66) | `installment_target = (loan.loan_amount + total_interest) / loan.term` |
| `tests/test_periodicities.py` | `test_quarterly_schedule_dates_and_interest` (ligne 47, calcul ligne 57), `test_semiannual_schedule_dates_and_interest` (ligne 63, calcul ligne 71), `test_annual_schedule_dates_and_interest` (ligne 76, calcul ligne 84) | `installment_target = (montant + total_interest) / n` avec n=4, 2, 2 |
| `tests/test_loan_installment_amount.py` | Toute la classe `TestLoanInstallmentAmount` (calcul direct/inverse du champ "Échéance") | Repose sur la formule dupliquée de `_onchange_loan_amount_recompute_installment` (voir ci-dessus) |

---

## Étape 5 — Cas limites à documenter (sans réponse, pour préparer la décision du Lot 1)

1. **`n = 1`** : `_compute_installment_targets` retourne une liste de taille `n - 1 = 0` (déjà le
   cas aujourd'hui, sans problème : la boucle `for idx in range(1, self.term+1)` ne consulte
   jamais `installment_targets[idx-1]` quand `idx == self.term` dès la première itération). Si
   le diviseur devient `n - 1` dans le calcul de `raw_target` lui-même
   (`total_due / (n - 1)`), une division par zéro deviendrait possible pour `n = 1` — à
   distinguer explicitement de la taille de la liste retournée, qui reste correcte par
   construction actuelle.
2. **Mode `distributed` du wizard** : sa logique actuelle (floor sur `total_due / n`, puis
   répartition du reliquat en incréments de `rounding_unit` sur les dernières tranches parmi
   les `n - 1` premières) est **indépendante dans son code** de la question `/n` vs `/(n-1)`
   posée ici pour le mode `last_installment` — mais si le diviseur de référence change pour
   `last_installment`, la question de savoir si le mode `distributed` doit suivre le même
   changement (et comment, étant donné qu'il utilise déjà `floor` et non `round`) reste
   entièrement ouverte et n'a pas été examinée ici.
3. **Délai de grâce (`grace_period_days`)** : la tranche de délai de grâce (le cas échéant) est
   ajoutée à `vals` **avant** la boucle principale, avec `sequence_offset = 1`, mais `n` (le
   diviseur utilisé pour la cible) reste `self.term` — **il n'inclut jamais la tranche de
   grâce**. Autrement dit, `self.term` désigne aujourd'hui uniquement le nombre de tranches
   "normales" post-grâce, jamais le nombre total de lignes générées quand une tranche de grâce
   existe. Reste ouvert : cette interaction est-elle correcte au regard de LPF, ou LPF
   compte-t-il la tranche de grâce dans son propre `n` de référence ? Aucun des trois dossiers
   audités ci-dessus n'a de délai de grâce actif, donc cette question reste entièrement non
   testée par les données disponibles.

---

## Conclusion

- **IS/01913** (référence déjà validée, mensuel, n=11) : confirme `/n`, contredit `/(n-1)`.
- **IS/000289** (réel, hebdomadaire, n=24) : confirme `/(n-1)`, contredit `/n`.
- **BM** : non exploitable de façon rigoureuse (n ambigu 42/43, deux total-dus fournis
  incohérents entre eux à ~1 077 Ar, et surtout — appliquer `/(n-1)` avec arrondi au plus proche
  sur les chiffres donnés produit une **tranche finale négative**, donc un échéancier
  structurellement invalide).

**L'hypothèse "LPF divise toujours par `n-1`" n'est pas confirmée : elle est contredite par le
dossier de référence historique et produit un résultat invalide sur le troisième cas testé.**
Les deux seuls dossiers solides disponibles (IS/01913 et IS/000289) donnent chacun raison à une
formule différente — ce n'est pas un problème d'arrondi ou de saisie, les écarts sont trop
importants (8 000 Ar/tranche sur IS/01913) pour être du bruit. Avant de scoper un Lot 1, il
faudra soit (a) obtenir un troisième échéancier papier réellement consultable qui permette de
départager, soit (b) déterminer avec Micka si un facteur distinctif (mensuel vs infra-mensuel ?
n petit vs n grand ? autre chose ?) explique pourquoi les deux dossiers de référence ne
s'accordent pas sur une règle unique `/n` vs `/(n-1)`.

**Note ajoutée en marge lors de l'addendum ci-dessous, sans modifier ce qui précède** : ce
constat a depuis été résolu par un chantier distinct (arrondi `ceiling`, cf. section
"Découverte majeure" de l'addendum) - conservé tel quel ci-dessus pour l'intégrité de l'audit
d'origine, mais **ne plus utiliser comme état actuel du code** sans lire l'addendum en premier.

---

# Addendum — Dossier IS/001076

Audit en lecture seule (suite du Lot 0 ci-dessus). **Aucune modification de code effectuée.**
Vérifications par lecture de code, requêtes SQL en lecture seule sur SEFOR, et une reproduction
via `odoo.tests.Form` en transaction annulée (`env.cr.rollback()`, aucune écriture persistée).

## Correction préalable au périmètre de la demande

**IS/001076 n'est PAS un troisième cas exploitable pour la question `/n` vs `/(n-1)`, et
l'anomalie observée n'a rien à voir avec un diviseur.** Ce n'est pas non plus "deux axes
distincts" (montant + nombre de lignes) : c'est **un seul phénomène**, entièrement expliqué et
reproduit ci-dessous - un désynchronisme entre les champs `loan_amount`/`term`/
`installment_amount` (mis à jour normalement) et le tableau détaillé `installment_ids` (resté
figé sur un état antérieur), dû à `installment_ids` marqué `readonly="1"` dans la vue crédit.

### Preuve : état réel du dossier au moment de l'audit (lecture SEFOR)

```
microfinance_loan id=2327, name=IS/001076, state=avis_cdag
loan_amount=500000  term=24  installment_amount=25000   <- corrects, cohérents entre eux
avis_ca_amount=500000  avis_ca_term=16  avis_ca_installment_amount=35000
avis_cdag_amount=500000  avis_cdag_term=27  avis_cdag_installment_amount=22000  <- !
```
`avis_ca_term=16` et `avis_cdag_term=27` sont des valeurs laissées par les tests du chantier
"Avis CA/CDAG" (`docs_dev/workflow_avis_ca_cdag/`, Lot 1 tout juste livré au moment de cet
addendum) directement sur **ce même dossier IS/001076**, utilisé comme cobaye pendant ces
tests. **Coïncidence troublante mais confirmée** : `avis_cdag_term=27` et
`avis_cdag_installment_amount=22000` correspondent **exactement** aux valeurs "erronées"
(27 lignes, 22 000 Ar) rapportées dans la demande.

Table `microfinance_loan_installment` pour ce dossier : **27 lignes**, la première à
**22 000,00 Ar**, la dernière (reliquat) à 21 461,54 Ar - identique en tout point à ce que
produirait `_build_installment_commands()` pour `loan_amount=500000, term=27` (mécanisme
`_propagate_avis_to_loan` du chantier Avis CA/CDAG : régénère l'échéancier avec les valeurs de
l'avis CDAG courant à chaque écriture d'un champ avis pendant que le crédit est en état
`avis_cdag` - fonctionnement attendu de ce mécanisme, pas un bug en soi, cf. STATUS.md dudit
chantier). **Ce tableau de 27 lignes est un résidu direct de ces tests**, jamais régénéré
depuis.

### Reproduction exacte du symptôme rapporté (Form, transaction annulée)

```python
loan = env['microfinance.loan'].browse(2327)
# AVANT : term=24, installment_amount=25000 (déjà corrects), installment_ids = 27 lignes
#         (résidu, première ligne 22 000 Ar) - EXACTEMENT l'état déjà en base avant le test.
f = Form(loan)
f.term = 24                      # même valeur que le dossier avait déjà à ce stade
# DANS LE FORMULAIRE (avant sauvegarde) :
#   f.installment_amount = 25000, len(f.installment_ids) = 24  <- aperçu CORRECT, 24 lignes
loan2 = f.save()
# APRES SAUVEGARDE :
#   term=24, installment_amount=25000 (toujours corrects)
#   len(installment_ids) = 27, première ligne = 22 000,00 Ar  <- INCHANGÉ, toujours le résidu
```

**Explication complète, confirmée par cette reproduction** : `_onchange_loan_amount_recompute_
installment` (déclenché par `term`/`loan_amount`/etc., `microfinance_loan.py`) recalcule bien
en mémoire un aperçu correct de 24 lignes à 25 000 Ar dès qu'on touche `term` - c'est ce que
l'utilisateur voit "avant enregistrement" dans le formulaire, et c'est juste. Mais
`installment_ids` est marqué `readonly="1"` dans `microfinance_loan_views.xml`
(`<field name="installment_ids" readonly="1"/>`, onglet "Échéancier"). **Un champ marqué
readonly en vue n'est jamais inclus dans la sauvegarde, même si un onchange vient de le
modifier** - comportement standard du client web Odoo (documenté dans `odoo/tests/form.py:405`,
*"does not save readonly fields"*, déjà rencontré et documenté pendant le chantier Avis CA/CDAG
pour un autre champ, cf. `docs_dev/workflow_avis_ca_cdag/STATUS.md`, écart n°4). Résultat :
l'aperçu à 24 lignes s'affiche correctement à l'écran, mais n'est **jamais persisté** - le
tableau réel en base reste sur son ancien contenu (ici, les 27 lignes du test Avis CDAG), tant
que personne ne clique sur le bouton "Générer échéancier" (qui, lui, écrit directement en base
côté serveur et n'est pas soumis à cette restriction de vue).

## Réponses aux questions posées par la demande

- **Où et quand le recalcul du nombre de lignes intervient-il ?** Nulle part dans le scénario
  observé - c'est l'inverse : il **n'intervient pas**. Le nombre de lignes affiché "avant
  enregistrement" (24) est le bon calcul, jamais persisté ; le nombre de lignes après
  enregistrement (27) n'est le résultat d'**aucun recalcul au moment de cette sauvegarde** -
  c'est un résidu d'une action antérieure et sans rapport (tests Avis CDAG), simplement resté
  inchangé parce que rien ne l'a jamais réécrit depuis.
- **`nombre_echeances` traité comme cible dure ou recalculé ?** **Cible dure**, confirmé : la
  valeur saisie (`term`) est directement celle utilisée par `_build_installment_commands()`
  (`self.term`, aucune transformation). Aucun recalcul du nombre de tranches à partir d'un autre
  paramètre n'a été trouvé nulle part dans le code (recherche déjà exhaustive lors de l'audit
  `docs_dev/regression_nb_echeances/` sur ce même sujet).
- **`_actual_duration_months()` intervient-il ?** Non, confirmé (recherche exhaustive) : cette
  méthode n'est utilisée que dans `_check_product_limits` (`@api.constrains` en lecture seule,
  compare une durée à des bornes produit), jamais dans le calcul de l'échéancier ni dans aucune
  écriture de `term`.
- **Comparaison avec IS/01913 ?** Sans objet pour ce phénomène précis : IS/01913 n'existe pas
  comme enregistrement réel dans cette instance Odoo (confirmé dans l'audit principal ci-dessus,
  Étape 1) - c'est une référence papier codée en dur dans les tests, jamais manipulée via le
  formulaire, donc jamais exposée au bug readonly/onchange décrit ici.
- **IS/001076 comme 3ème dossier de référence ?** **Non recommandé.** Son `installment_ids`
  actuel ne reflète pas un calcul récent avec `term=24` - c'est un résidu d'un `term=27`
  antérieur, sans lien avec la question `/n` vs `/(n-1)`. L'utiliser comme référence produirait
  une comparaison invalide. Si un troisième cas réel est nécessaire pour la question diviseur,
  il faudrait soit un dossier jamais touché par les tests Avis CA/CDAG, soit régénérer
  explicitement l'échéancier de IS/001076 via le bouton "Générer échéancier" avant toute
  nouvelle comparaison (non fait ici, lecture seule oblige).

## Découverte majeure : la question `/n` vs `/(n-1)` de l'audit principal semble déjà résolue

En recalculant les deux cas de référence de l'audit principal **avec le code et la
configuration produit actuels** (mode d'arrondi `installment_rounding_mode='ceiling'`,
confirmé en base sur PRET RURAL, id=1 - introduit par un chantier distinct, "Lot 1" de
`docs_dev/regression_nb_echeances/`, déjà en production au moment de cet addendum) :

| Dossier | n | Total dû | `/n` avec `ceiling` (code actuel) | Cible papier (audit principal) |
|---|---|---|---|---|
| IS/01913 | 11 | 931 000 | **85 000** (931000/11=84636,36 → ceiling 1000) | 85 000 |
| IS/000289 | 24 | 583 076,92 | **25 000** (583076,92/24=24294,87 → ceiling 1000) | 25 000 |

**Les deux dossiers de référence, qui se contredisaient sous l'hypothèse `/n` avec arrondi
"au plus proche" (l'audit principal ci-dessus le documente précisément), concordent tous les
deux sous `/n` avec arrondi `ceiling` — sans changer le diviseur.** Ce n'est pas une nouvelle
hypothèse non testée : c'est déjà le comportement réellement implémenté et couvert par un test
permanent existant, `test_target_is000289_case_ceiling_matches_lpf_paper`
(`tests/test_interest_first_schedule.py:214-222`), dont le commentaire cite explicitement le
même diagnostic que l'audit principal : *"583077/24=24294,875 - nearest donnerait 24 000,
l'ancien bug"*.

**Interprétation, à confirmer par Micka avant de conclure formellement** : il semble que les
deux chantiers ("correction_diviseur_echeancier" et "regression_nb_echeances"/Lot 1 ceiling)
enquêtaient sur le **même symptôme de fond** (Odoo donnait 24 000 Ar au lieu de 25 000 Ar sur
IS/000289) via deux hypothèses de correction différentes et non coordonnées entre elles - changer
le diviseur (`n` → `n-1`) d'un côté, changer le sens d'arrondi (`nearest` → `ceiling`) de
l'autre. La seconde a déjà été implémentée, déployée, et testée sur les deux dossiers de
référence disponibles, sans la contradiction que la première produisait sur IS/01913 ni le
reliquat négatif qu'elle produisait sur le cas BM (cf. audit principal, Étape 2). **Si cette
lecture est confirmée par Micka, le chantier "correction_diviseur_echeancier" pourrait être
clos sans action supplémentaire** - à valider explicitement avant de le faire, ce rapport ne
tranche pas de lui-même une question qui touche à un autre chantier déjà livré.

## Constat annexe, à signaler séparément (hors périmètre direct de cette demande)

Le bug readonly/onchange décrit ci-dessus (`installment_ids` jamais sauvegardé malgré un
aperçu correct) **n'est pas spécifique à IS/001076 ni au chantier Avis CA/CDAG** - il se produit
dès qu'on modifie `loan_amount`/`term` (ou tout champ déclenchant l'onchange de recalcul) sur un
crédit dont l'échéancier a déjà été généré une fois, sans repasser par le bouton "Générer
échéancier". **Vérifié également sur IS/000289** (id=1449, lecture SEFOR) : `term=24`,
`installment_amount=25000` (corrects), mais `installment_ids` ne contient que **8 lignes** en
base - résidu de l'incident déjà documenté dans `docs_dev/regression_nb_echeances/AUDIT.md`
("Nombre échéances revient à 8"), jamais régénéré depuis. **À noter pour éviter toute confusion
si quelqu'un ouvre l'onglet Échéancier de ce dossier précis** : les 8 lignes actuellement
visibles ne correspondent à rien de valide, ni à `term=24` ni à un quelconque calcul récent.

Ce constat est **potentiellement plus urgent** que la question du diviseur elle-même : un
crédit peut afficher un montant/durée/échéance corrects en tête de formulaire tout en ayant un
échéancier détaillé silencieusement obsolète en dessous, sans aucune erreur ni avertissement
visible pour l'utilisateur - risque d'intégrité des données en production. **Non corrigé ici**
(Lot 0, lecture seule) - signalé pour arbitrage d'un éventuel lot correctif séparé, dont le
périmètre (et l'urgence relative face au reste du backlog) reste à discuter avec Micka.
