# Moteur de remboursement CEFOR — échéancier interest-first + ventilation 3-buckets vs LPF

Périmètre : `microfinance_loan_management` uniquement, sur `microfinance.loan` (fiche crédit) et
`microfinance.loan.payment` (remboursement). Hors périmètre : frais de dossier/commission (déjà
en place, non touché), crédits de groupe, `microfinance.loan.application` (hors-périmètre, non
wiré), mécanisme d'intérêts échus/accrual, logique de rééchelonnement elle-même
(`_reschedule_installments`, vérifiée compatible mais non modifiée).

Fichier distinct de `docs/ecarts_lpf.md` (celui-ci porte sur les fonds de crédit rotatifs
bailleurs, un sujet différent) : même convention que `microfinance_savings_management/docs_dev/
savings/ecarts_lpf.md`, un fichier par grand chantier plutôt qu'un fourre-tout.

## Lot 1 — Génération d'échéancier interest-first

**Méthode modifiée** : `action_generate_schedule()` sur `microfinance.loan`
(`models/microfinance_loan.py`), uniquement la branche `interest_method == 'flat'` (taux
uniforme). La branche `else` (solde dégressif, `interest_method == 'reducing'`) reste inchangée :
la Décision 1 ne porte que sur le taux uniforme (formule totale d'intérêt connue à l'avance,
indépendante de l'échéancier), ce qui ne vaut pas pour le dégressif où l'intérêt de chaque tranche
dépend justement du rythme d'amortissement.

**Algorithme** : chaque tranche cible un montant total (`total_dû / nb_tranches`), l'intérêt total
du crédit (taux uniforme, formule déjà en place) est consommé en priorité sur les premières
tranches jusqu'à épuisement, le principal ne comble que le reste de la cible ; la dernière tranche
absorbe le reliquat exact (principal restant, intérêt restant) plutôt que de recalculer sa propre
cible, garantissant que les totaux somment exactement au capital et à l'intérêt total.

**Nouveau champ de configuration** : `installment_rounding_unit` (Monetary, sur
`microfinance.loan.product`, défaut 1000.0) — la cible par tranche est arrondie (selon
`installment_rounding_mode`, voir Lot 1 — correction du 2026-08-24 ci-dessous) au multiple de
cette unité avant répartition intérêt/principal. **Aucune règle spéciale pour les petits
crédits** : l'arrondi s'applique même si la cible arrondie tombe à 0 en mode `nearest` (vérifié
par test dédié). Mettre à 0 désactive l'arrondi. Ce champ n'existait pas du tout avant ce
chantier (recherché exhaustivement : aucun mécanisme d'arrondi ni de jours ouvrables nulle part
dans le module) — la prémisse initiale du prompt ("conserver la logique d'arrondi existante")
était fausse, l'arrondi a donc été conçu de zéro. **Le mode `nearest` retenu à l'origine
("ni ceiling ni floor") n'était pas un choix de conception validé sur pièce, contrairement à ce
qu'indiquait cette section jusqu'au 2026-08-24 — c'était un bug d'implémentation, découvert et
corrigé depuis (cf. point 5 de la section "Écarts vs LPF" ci-dessous : LPF arrondit en réalité
au multiple SUPÉRIEUR, `ceiling`, désormais le défaut).**

**Choix du mode de répartition du reliquat d'arrondi — décision du 2026-08-19** : le mode
historique ci-dessus ("Absorption sur la dernière tranche" — toutes les tranches sauf la
dernière visent la même cible arrondie nearest, la dernière absorbe tout le reliquat réel) peut
produire un écart marqué sur la dernière tranche par rapport aux autres, notamment sur des
crédits infra-mensuels à nombreuses échéances : cas de référence `IS/000289` (500 000 Ar, 36 %,
24 échéances hebdomadaires, arrondi 1000) — 23 tranches à 24 000 Ar puis une dernière à
31 076,92 Ar. Plutôt que de figer un seul comportement, un **wizard** (`microfinance.loan.
schedule.rounding.wizard`, ouvert par le bouton "Générer échéancier" via
`action_open_generate_schedule_wizard`) propose désormais un choix explicite à chaque
génération :
- `last_installment` (défaut, comportement historique décrit ci-dessus, inchangé) ;
- `distributed` (nouveau) : la cible des tranches non-finales est arrondie **au plancher**
  (`floor`, jamais nearest, pour ne jamais dépasser le total dû avant lissage), et le reliquat
  est réparti en incréments entiers de `installment_rounding_unit` sur les dernières tranches de
  la liste (les plus proches de la fin) au lieu d'être concentré sur la seule dernière tranche.
  La toute dernière tranche continue d'absorber une fraction résiduelle sous le millier
  (inévitable, non représentable en multiples entiers de l'unité d'arrondi), mais cette fraction
  reste petite comparée au mode absorption.

Implémentation : `_compute_installment_targets(total_due, rounding_unit, rounding_mode)`
calcule la liste des cibles pour les tranches 1..term-1 selon le mode choisi ; la dernière
tranche (`term`) n'utilise jamais cette liste et absorbe toujours le reliquat exact restant —
c'est ce qui garantit, **dans les deux modes**, que la somme exacte des tranches reste
rigoureusement égale au total dû (capital + intérêt) au centime près : seule la répartition de
l'écart d'arrondi entre les tranches change, jamais le montant total réellement payé par
l'emprunteur. `action_generate_schedule(rounding_mode='last_installment')` : paramètre par
défaut, tous les appels internes existants (ex. `action_disburse()` si l'échéancier n'a pas
encore été généré) restent inchangés sans modification. Le mode dégressif
(`interest_method == 'reducing'`) et le rééchelonnement (`_reschedule_installments`, qui
n'applique aujourd'hui aucun arrondi) ne sont pas concernés par ce chantier.

**Effet de bord découvert et corrigé** : le produit de test générique partagé (`tests/common.py`,
utilisé par ~20 fichiers de tests avec des crédits de quelques centaines/milliers d'Ar, sans
rapport avec la granularité réelle CEFOR) aurait hérité du défaut 1000 Ar et cassé une dizaine de
tests sans rapport (cibles arrondies à 0, échéances à 0 Ar rejetées par la validation des
remboursements). Corrigé en désactivant l'arrondi sur ce produit de test générique uniquement
(`installment_rounding_unit: 0`) ; le champ garde son défaut 1000 au niveau du modèle pour tout
produit réel. Les tests dédiés à l'arrondi l'activent explicitement.

**Tests** : `tests/test_interest_first_schedule.py` — cas réel IS/01913 (700 000 Ar, 36 %/an, 11
mensualités, valeurs exactes conformes au document de référence : 85 000/85 000/61 000+24 000/85
000×7/81 000), cas petit crédit (cible arrondie à 0, aucun court-circuit), cas simple sans
débordement (intérêt tenant entièrement dans la 1ère tranche, arrondi désactivé pour ne pas
coupler les deux comportements). `tests/test_grace_period.py` et `tests/test_periodicities.py` mis
à jour (assertions linéaires devenues fausses par construction) avec arrondi désactivé, ces tests
portant sur la forme interest-first/le délai de grâce, pas sur l'arrondi.

## Lot 2 — Ventilation de remboursement (3 buckets)

**Méthode modifiée** : `_allocate_to_installments()` sur `microfinance.loan.payment`
(`models/microfinance_loan_payment.py`). Changement minimal : seul l'**ordre** des 3 buckets a
changé, de `pénalité → intérêt → principal` (LPF) vers `intérêt → principal → pénalité` (CEFOR,
Décision 2). La boucle elle-même (itération sur les échéances non soldées triées par
`due_date`/`sequence`, décrément du montant restant au fil des tranches) était déjà exactement le
mécanisme de débordement demandé — pas de changement structurel nécessaire, seul l'ordre interne
par tranche était inversé.

**Tests** : `tests/test_repayment_allocation.py` — paiement exact, paiement partiel (priorité
intérêt > principal > pénalité vérifiée), paiement insuffisant même pour l'intérêt seul, paiement
en surplus débordant sur la tranche suivante avec le même ordre de priorité.

## Lot 3 — Comptabilisation cash-basis

**Déjà largement en place avant ce chantier** : `_prepare_payment_move()` + `action_post()` sur
`microfinance.loan.payment` existaient déjà, avec la structure exacte demandée par la Décision 3
(écriture générée uniquement à l'encaissement effectif — cash-basis confirmé, jamais à la
génération d'échéancier ; montants proportionnels à la ventilation réelle du Lot 2, pas au montant
théorique de la tranche ; même pattern que `_prepare_disbursement_move`/`_prepare_fee_move`).

**Mapping de comptes PCEC : déjà en place, pas créé par ce chantier.** `microfinance.loan.product`
expose déjà `account_principal_individuel_id`/`_groupe_id` (domaine `asset_receivable`/
`asset_current`), `account_interets_recus_individuel_id`/`_groupe_id` (domaine `income`),
`account_penalites_id` (domaine `income`) — basés sur `account_type`, pas préfixe de code,
cohérent avec la convention déjà établie ailleurs dans le module.

**Point signalé (non corrigé, hors périmètre strict de ce lot)** : le domaine de `journal_id` sur
`microfinance.loan.payment` (filtré par société) est **soft** (UI uniquement) — aucun champ du
module n'utilise `check_company=True`, y compris les champs comptables déjà en place sur
`microfinance.loan.product`. Pas une régression de ce chantier : caractéristique déjà présente
partout dans le module (même famille que l'écart déjà documenté sur `fond_credit_id` dans
`docs/ecarts_lpf.md`).

**Tests** : `tests/test_repayment_accounting.py` — comptes/montants corrects par bucket, absence de
ligne pour un bucket non touché par un paiement partiel (cash-basis 1:1, pas de comptabilisation
théorique), aucune écriture de remboursement avant tout encaissement, isolation multi-société
bout-en-bout (crédit décaissé + remboursé sur une 2e agence, écriture sur le bon journal/société/
comptes).

## Lot 4 — Vue et vérification finale

- Aucun label/tooltip trompeur trouvé sur les vues échéancier/remboursement (aucun `help=`
  mentionnant une répartition linéaire).
- **Incohérence visuelle corrigée** : l'ordre d'affichage des champs `allocated_penalty`/
  `allocated_interest`/`allocated_principal` (vue liste et formulaire de
  `microfinance.loan.payment`, + ordre de déclaration des champs eux-mêmes dans le modèle)
  reprenait l'ancien ordre LPF (pénalité en premier). Réordonné en intérêt → principal → pénalité
  pour refléter visuellement la Décision 2.
- Suite complète des Lots 1-3 rejouée en une seule exécution : voir résultat ci-dessous.

## Écarts vs LPF (résumé)

1. **Répartition d'échéancier** : intérêt-first (Décision 1) au lieu du calcul linéaire d'origine
   du module (montant identique par tranche) — et au lieu de la logique LPF "1ère tranche seule"
   parfois observée sur d'autres systèmes. Arrondi de la cible à 1000 Ar (configurable) — LPF
   arrondit aussi (cf. point 5 ci-dessous), la mention "absent de LPF" présente ici jusqu'au
   2026-08-24 était erronée.
2. **Ventilation de remboursement** : 3 catégories (intérêt, principal, pénalités) avec l'ordre
   intérêt → principal → pénalités, au lieu des 8 catégories LPF (qui distinguent notamment
   commission échue/à échoir, intérêts échus/à échoir séparément du courant) et de leur ordre de
   priorité pénalités/commission avant intérêt/principal. Commission volontairement absente de
   cette ventilation (déjà traitée ailleurs, encaissée séparément au décaissement/via
   `action_charge_fee`).
3. **Comptabilisation** : cash-basis pur (LPF le pratique aussi pour CEFOR selon le contexte donné)
   — pas d'intérêts échus/accrual, écriture au fil de l'eau à chaque remboursement, jamais en
   amont.
4. **Fraction annuelle du taux d'intérêt sur les périodicités infra-mensuelles — RÉSOLU le
   2026-08-18.** Constat initial (exemple comparatif réel, 500.000 Ar / 36%/an / 24 échéances
   hebdomadaires) : LPF calculait un intérêt total de 83.077 Ar, Odoo 82.849,32 Ar (écart ~228 Ar,
   0,27%) — pas un arrondi mineur mais une différence de convention : Odoo utilisait le calcul
   calendaire réel (`period_value / 365`, ex. hebdo = 7/365 ≈ 0,019178) là où LPF traite chaque
   périodicité infra-mensuelle comme une fraction fixe et conventionnelle de l'année,
   indépendamment du nombre exact de jours (hebdo = 1/52 ≈ 0,019231, soit 52 semaines/an, pas
   365/7 ≈ 52,14). Décision validée avec Micka : aligner sur LPF plutôt que documenter l'écart.
   Correctif : nouveau champ `periods_per_year` sur `microfinance.repayment.frequency` (valeurs
   conventionnelles : journalier 365, hebdo 52, quinzaine 26, 4-semaines 13 — mensuel et au-delà
   inchangés, `12 / period_value` étant déjà strictement équivalent à ces bornes), et
   `_period_interest_factor()` simplifiée en `1.0 / freq.periods_per_year` (`microfinance_loan.py`).
   Seul le montant d'intérêt par tranche change — les dates d'échéance réelles restent calculées
   au calendrier exact (`_period_delta()` inchangée, ex. +7 jours chaque semaine). Migration
   `17.0.1.8.0` pour les 10 périodicités déjà chargées en `noupdate="1"` ; aucune reprise
   rétroactive des échéanciers déjà générés (pas en production).
5. **Mode d'arrondi de la cible d'échéance (nearest vs ceiling) — RÉSOLU le 2026-08-24.**
   **Règle confirmée** : *Cible d'échéance = arrondi SUPÉRIEUR (ceiling) de total_dû / nombre
   d'échéances au multiple configuré le plus proche, et non l'arrondi au plus proche.* Le
   diviseur `n` (nombre total d'échéances) était correct dès l'origine (Lot 1 ci-dessus) ; le
   bug était le **mode d'arrondi** : `nearest` au lieu de `ceiling`. Preuve établie sur 9 exports
   bruts LPF (`.XLS`, ClientDataSet Delphi) et le dossier papier `IS/000289`
   (docs_dev/correction_diviseur_echeancier/) : deux cas discriminants confirment `ceiling` sans
   exception — `1.XLS` (700 000 Ar, mensuel, 11 échéances, total dû 931 000) : 931000/11 =
   84 636,36, LPF affiche 85 000 (ceiling) et non 84 000 (nearest) ; `IS/000289` (papier, hebdo,
   24 échéances, total dû 583 077) : 583077/24 = 24 294,875, LPF affiche 25 000 (ceiling) et non
   24 000 (nearest = bug Odoo constaté). Deux autres exports (`2.XLS`, division exacte ; `10.XLS`/
   `12.XLS`) ne sont pas discriminants (les deux modes coïncident) mais ne contredisent pas la
   règle. **Rationale métier** : arrondir vers le haut réduit mécaniquement la dernière tranche
   (le reliquat), donc le risque de queue de crédit — le dernier paiement, le plus exposé en cas
   d'impayé final, reste toujours inférieur ou égal à la cible normale.
   Correctif : nouveau champ `installment_rounding_mode` (Selection `ceiling`/`nearest`, défaut
   `ceiling`) sur `microfinance.loan.product`, et helper partagé
   `_round_installment_target(value, unit, mode)` appelé depuis les deux points de calcul de la
   cible (`_compute_installment_targets` et `_onchange_loan_amount_recompute_installment`,
   `microfinance_loan.py`) — `nearest` reste disponible comme option explicite, non supprimée,
   mais n'est plus le défaut nulle part. Cas `n = 1` (échéance unique) traité explicitement : pas
   de tranche de reliquat pour absorber un dépassement d'arrondi, la tranche unique reste
   toujours le total dû exact, jamais un multiple arrondi qui le dépasserait. **Ce n'était pas un
   écart de conception assumé mais un bug d'implémentation**, maintenant aligné sur LPF (voir
   aussi la correction du texte du Lot 1 ci-dessus, qui présentait à tort `nearest` comme un choix
   validé). Impact rétroactif : nul (un seul crédit existe en base sur SEFOR, IS/000289 lui-même,
   dont l'échéancier déjà généré est de toute façon obsolète et devra être régénéré séparément,
   hors périmètre de ce correctif).
