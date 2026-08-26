# Lot — Garde-fou reliquat négatif (effet de bord de l'arrondi `ceiling`)

## Résumé exécutif

La condition mathématique exacte est dérivée et vérifiée par reproduction du cas rapporté
(§1). **Le scan complet de la base SEFOR trouve 1 dossier réellement affecté à ce jour :
IS/001076 (id 2327), dernière tranche à -5 153,85 Ar** (§2) — pas le dossier "BM" décrit dans la
demande (ce code agence n'existe pas dans SEFOR, cf. audits précédents), mais un cas réel,
actuellement en base, avec exactement les mêmes chiffres (30 échéances hebdomadaires, cible
21 000 Ar, reliquat -5 153,85 Ar). Le garde-fou est implémenté et testé (§3, zéro régression sur
la suite complète du module). Le dossier affecté n'a **pas** été corrigé, conformément à la
consigne - liste transmise ci-dessous pour arbitrage avec Micka.

---

## Partie A — Audit

### A.1 — Condition mathématique exacte et exemple chiffré

Pour la méthode "intérêt d'abord" (`interest_method == 'flat'`, seule méthode concernée -
la méthode dégressive n'a pas de notion de cible arrondie), le moteur de calcul
(`_build_installment_commands`, `microfinance_loan.py`) impose que chacune des `n-1` premières
tranches vise exactement le même total (`principal_amount + interest_amount`), et que la dernière
tranche (`n`) absorbe tout le reliquat restant. Il en découle une identité exacte, indépendante de
la répartition interne principal/intérêt :

```
reliquat_dernière_tranche = total_due - target * (n - 1)
```

où :
- `total_due = loan_amount + total_interest` (capital + intérêt total du crédit, taux uniforme)
- `target = unit * ceil(total_due / n / unit)` — cible par tranche, arrondie au multiple
  **supérieur** de `unit` (`installment_rounding_unit` du produit, mode `ceiling`,
  `_round_installment_target`)
- `n = self.term`, `unit = product_id.installment_rounding_unit`

**Condition de reliquat négatif** (stricte, celle codée dans le garde-fou) :

```
unit * ceil(total_due / (n * unit)) * (n - 1) > total_due
```

**Borne pire cas, utile pour évaluer le risque sans calculer l'arrondi exact** : l'écart entre
`target` et la moyenne brute `total_due/n` est strictement inférieur à `unit` (propriété du
`ceil`). En reportant cette borne dans la formule, le reliquat peut devenir négatif dès que :

```
total_due < unit * n * (n - 1)
```

Cette borne n'est qu'une **condition suffisante d'alerte** (le cas réel dépend du reste exact de
la division), mais elle montre l'essentiel : le risque croît **quadratiquement** avec `n` et ne
dépend que du rapport `total_due / unit`, pas du produit ou de la fréquence en tant que tels -
tout produit qui autorise un `n` élevé avec un montant modeste est structurellement exposé.

**Exemple chiffré reproduisant exactement le cas rapporté** (vérifié par calcul direct sur le
moteur réel, `_build_installment_commands`, transaction annulée) :

| Paramètre | Valeur |
|---|---|
| `total_due` | 603 846,15 Ar |
| `n` (term) | 30 (hebdomadaire) |
| `unit` | 1 000 Ar |
| `target` (cible/tranche) | `ceil(603846,15 / 30 / 1000) * 1000` = `ceil(20,128...) * 1000` = **21 000 Ar** |
| `reliquat` (tranche 30) | `603846,15 - 21000 * 29` = **-5 153,85 Ar** |

Chiffres identiques à ceux rapportés ("cible 21 000 Ar", "-5 153,85 Ar") - confirmation directe
que le mécanisme identifié dans la demande est le bon, sans hypothèse supplémentaire.

### A.2 — Recensement exhaustif en base (SEFOR)

Requête SQL brute (lecture seule, hors ORM) sur `microfinance_loan_installment`, toutes lignes
confondues, recherchant `principal_amount < 0`, `interest_amount < 0`, ou leur somme négative -
aucune limitation de portée, toute la table scannée :

```sql
SELECT loan_id, sequence, due_date, principal_amount, interest_amount
FROM microfinance_loan_installment
WHERE principal_amount < 0 OR interest_amount < 0 OR (principal_amount + interest_amount) < 0;
```

**Résultat : 1 ligne.**

| `loan_id` | Dossier | Séquence | Date d'échéance | Principal | Intérêt | Total |
|---|---|---|---|---|---|---|
| 2327 | IS/001076 | 30 | 2027-03-23 | -5 153,85 | 0,00 | **-5 153,85 Ar** |

État du dossier au moment du constat : `term=30`, `loan_amount=500 000`, produit **PRET
FONCTIONNAIRE** (hebdomadaire, `installment_rounding_unit=1000`, `ceiling`), `state=avis_cdag`,
`write_date` très récent (quelques minutes avant ce lot). **Origine directe, à signaler
honnêtement** : ce dossier est le même que celui régénéré dans le Lot précédent
(`docs_dev/echeancier_obsolete_readonly/`) à `term=24` (échéancier valide, 24 lignes) - son
`term` a ensuite été remodifié à `30` (manifestement pour tester/confirmer ce cas précis avant de
me transmettre cette demande), et le correctif `write()` du Lot précédent (qui régénère
`installment_ids` à chaque modification de `term`, cf. `_SCHEDULE_TRIGGER_FIELDS`) a
**correctement** régénéré un échéancier à 30 lignes cohérent avec `term=30` - mais **sans le
garde-fou** (qui n'existait pas encore à ce moment), il a laissé passer la tranche négative telle
quelle. C'est donc une confirmation en conditions réelles, pas seulement une reproduction
synthétique : le Lot précédent corrige bien la stale-schedule, mais n'empêchait pas *ce*
problème-ci, qui est distinct - exactement la raison d'être de ce Lot.

**IS/000289 (id 1449, l'autre seul dossier de SEFOR)** : aucune ligne négative, `term=24`
inchangé depuis le Lot précédent, hors de la zone à risque (cf. borne A.1 : `total_due < unit *
n * (n-1)`, soit ici `total_due < 1000*24*23 = 552 000` pour être à risque en pire cas ; or
`total_due ≈ 583 077 > 552 000` sur ce dossier - cohérent avec l'absence de problème observé).

**Volume : négligeable en valeur absolue (1 ligne sur 2 dossiers), mais 50 % des dossiers
existants** - SEFOR ne contient toujours que ces 2 crédits au total (cf. audit précédent). Pas
d'escalade séparée avant la fin du lot au sens de la consigne (le chiffre est trivial à
communiquer dans ce même rapport), mais signalé en tête de ce document comme demandé.

### A.3 — Profil de risque commun

**Configuration des 3 produits réels de SEFOR** :

| Produit | Fréquence | `max_term` | `unit` | Mode | `max_amount` |
|---|---|---|---|---|---|
| PRET RURAL | au choix (Journalier/Hebdo/Mensuel) | 12 | 1 000 | ceiling | 500 000 |
| PRET SUCESSIVE RURAL | au choix (Hebdo/Quinzaine/Mensuel) | 12 | 1 000 | ceiling | 1 000 000 |
| **PRET FONCTIONNAIRE** | **Hebdomadaire fixe** | **48** | 1 000 | ceiling | 4 000 000 |

**Les trois produits partagent le même `installment_rounding_unit=1000`/`ceiling`** (config de
production par défaut, Lot 1) - le risque n'est donc pas propre à un produit mal configuré, mais
à la combinaison **fréquence courte + `n` (nombre d'échéances) élevé** pour un montant donné,
conformément à la borne quadratique dérivée en A.1.

**PRET RURAL et PRET SUCCESSIVE RURAL sont plafonnés à `max_term=12`** - quelle que soit la
fréquence choisie par le client, `n` ne peut jamais dépasser 12 sur ces deux produits, ce qui les
maintient largement hors de la zone à risque pour les montants qu'ils autorisent (borne pire cas
à `n=12` : `total_due < 1000*12*11=132000`, très inférieur aux `min_amount` de ces produits :
100 000 et 500 000 Ar respectivement).

**PRET FONCTIONNAIRE est structurellement le produit à risque du catalogue actuel** : seul
produit à combiner une fréquence courte (hebdomadaire, imposée, pas au choix) avec un `max_term`
élevé (48, soit jusqu'à 48 échéances hebdomadaires ≈ 11 mois). Le dossier affecté (IS/001076,
`term=30`) utilise précisément ce produit. Borne pire cas à `n=30` : `total_due <
1000*30*29=870000` - largement dans la plage de montants réellement autorisée par ce produit
(`min_amount=100000`, `max_amount=4000000`). À `n=48` (plafond du produit), la borne monte à
`1000*48*47=2256000` : un crédit PRET FONCTIONNAIRE avec un montant modeste et un grand nombre
d'échéances hebdomadaires reste dans la zone à risque même en pire cas. **Aucun autre dossier de
ce profil n'existe encore en base** (SEFOR n'a que 2 crédits au total, cf. A.2) - le risque est
donc pour l'instant latent (pas de deuxième cas caché), mais structurel au produit, pas
accidentel au dossier IS/001076.

---

## Partie B — Garde-fou implémenté

### Localisation du contrôle

Un seul point d'insertion, dans `_build_installment_commands()` (`microfinance_loan.py`), juste
après la boucle de construction des tranches de la branche `interest_method == 'flat'` (avant la
branche dégressive). Nouveau paramètre `raise_on_negative_reliquat=False` (défaut inchangé,
préserve explicitement le contrat existant de la méthode - *"un onchange ne doit jamais planter
sur un formulaire incomplet"*, cf. son propre docstring) : seul `action_generate_schedule()`
passe `raise_on_negative_reliquat=True`.

**Pourquoi un seul point suffit pour couvrir "tous les points d'entrée"** (vérifié par grep
exhaustif, comme pour le Lot précédent) : `action_generate_schedule()` est l'unique méthode qui
persiste réellement `installment_ids` dans tout le module - le bouton "Générer échéancier"
(wizard), `_propagate_avis_to_loan()` (chantier Avis CA/CDAG) et l'écriture automatique de
`write()` (`_SCHEDULE_TRIGGER_FIELDS`, Lot précédent) l'appellent tous les trois, et
**uniquement** eux. Les onchange d'aperçu (`_onchange_loan_amount_recompute_installment` etc.)
continuent d'appeler `_build_installment_commands()` sans ce paramètre (défaut `False`) : ils
restent silencieux sur ce cas, comme avant - un aperçu de formulaire négatif n'est pas persisté
de toute façon (Lot précédent), donc pas grave de le laisser s'afficher tel quel un instant avant
que l'utilisateur ne clique "Générer échéancier" et obtienne l'erreur bloquante à ce moment-là.

### Message affiché

```
Impossible de générer cet échéancier : avec ce montant, ce nombre d'échéances et l'arrondi
actuel, la dernière échéance calculée serait négative (-5153.85 Ar). Cela arrive en général
quand le nombre d'échéances est élevé par rapport au montant du crédit. Contactez le support
technique pour ajuster le paramétrage (produit ou unité d'arrondi) avant de continuer.
```

Vocabulaire volontairement non technique (pas de "ceiling", pas de "n-1"), conforme à la demande.

### Tests

Nouveau fichier `tests/test_schedule_negative_reliquat_guard.py` (4 tests, ajouté à
`tests/__init__.py`) :
- `test_bm_case_raises_before_any_write` : reproduction exacte du cas (mêmes `total_due`, `n`,
  `unit` qu'en A.1) - vérifie la `ValidationError` **et** qu'aucune ligne n'a été écrite avant
  l'exception (`loan.installment_ids` inchangé après l'échec).
- `test_non_regression_reference_case_weekly_still_passes` / `_monthly_still_passes` : les deux
  cas de référence déjà validés par le Lot 1 (`ceiling`, IS/000289 et IS/01913) restent positifs
  et ne déclenchent pas le garde-fou.
- `test_write_trigger_also_blocked` : le garde-fou bloque aussi la régénération automatique
  déclenchée par `write()` (Lot précédent), pas seulement l'appel explicite au bouton.

### Validation - zéro régression

Suite complète du module (647 tests) comparée strictement (par la liste des `FAIL`/`ERROR`,
`comm` sur les deux listes triées) entre l'état juste avant ce Lot et l'état avec le garde-fou :
**listes identiques** - les mêmes 6 échecs et 62 erreurs pré-existants (environnement SEFOR non
isolé - fonds de crédit actif, rapport HTML, KPI dashboard, etc. - sans rapport avec ce Lot, déjà
documentés dans le Lot précédent), aucun de plus, aucun de moins.

**Effet de bord détecté et corrigé en cours de route** : l'ajout du garde-fou a d'abord fait
échouer 5 tests pré-existants (`test_fond_bailleur.py`, `test_fond_bailleur_dashboard.py`,
`test_repayment_accounting.py`) qui créent chacun un produit "agence B" secondaire, dupliqué
trois fois presque à l'identique, **sans désactiver `installment_rounding_unit`** (contrairement
au produit de test partagé `common.py`, qui le désactive explicitement pour cette raison même).
Avec des montants ronds et courts (`1000 Ar`/3 échéances, `900 Ar`/3 échéances) non représentatifs
de la granularité CEFOR réelle, ces produits tombaient authentiquement dans la zone à risque
(reliquat -970/-1073 Ar) - le garde-fou faisait donc correctement son travail, mais sur des
données de test sans rapport avec ce qu'elles vérifient (visibilité multi-société d'un fonds
partagé). Corrigé en ajoutant `'installment_rounding_unit': 0` aux 3 blocs de création de ces
produits, cohérent avec le pattern déjà documenté dans `common.py`.

---

## Limite de fond (non résolue dans ce lot, par consigne explicite)

Ce lot **bloque** le cas, il ne le **résout** pas : un crédit dans la zone à risque (ex. PRET
FONCTIONNAIRE, montant modeste, `term` élevé) ne peut plus produire d'échéancier du tout, sans
alternative proposée à l'utilisateur autre que "contacter le support". Deux pistes de solution de
fond existent (citées dans la demande, non tranchées ici) : distribuer le surplus d'arrondi sur
plusieurs tranches plutôt que le concentrer sur la seule dernière (mode `distributed`, qui existe
déjà dans le code et semble structurellement à l'abri de ce risque par construction - floor au
lieu de ceiling sur les tranches intermédiaires, cf. `_compute_installment_targets`, mais pas
encore validé formellement contre ce cas précis, hors périmètre de vérification de ce lot), ou
revenir à un arrondi `nearest` sur les tranches intermédiaires quand `ceiling` produirait un
reliquat négatif. Nécessite une décision de Micka sur le comportement attendu de LPF dans ce cas
précis, non observé dans les exports disponibles à ce jour (tous avaient un `n` trop faible pour
déclencher le cas) - non traité ici.

## Dossier déjà affecté - non corrigé, pour arbitrage

**IS/001076 (id 2327)** reste en base avec sa tranche 30 à -5 153,85 Ar, tel que trouvé en A.2.
Aucune correction automatique effectuée (consigne explicite). Rapprochement à faire avec le Lot
précédent (`docs_dev/echeancier_obsolete_readonly/`) : c'est le même dossier de test qui y avait
déjà été régénéré une première fois - probable qu'il ait servi une seconde fois à volontairement
reproduire ce cas-ci avant de me transmettre cette demande. À noter pour Micka : avec le
garde-fou désormais actif, toute tentative de régénérer l'échéancier de ce dossier tel quel
(`term=30`) échouera désormais avec le message ci-dessus, tant que `term`/`loan_amount` ou
l'unité d'arrondi du produit n'auront pas été ajustés.
