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
