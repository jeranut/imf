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
`microfinance.loan.product`, défaut 1000.0) — la cible par tranche est arrondie au plus proche
multiple de cette unité avant répartition intérêt/principal (nearest, ni ceiling ni floor).
**Aucune règle spéciale pour les petits crédits** : l'arrondi s'applique même si la cible arrondie
tombe à 0 (vérifié par test dédié). Mettre à 0 désactive l'arrondi. Ce champ n'existait pas du
tout avant ce chantier (recherché exhaustivement : aucun mécanisme d'arrondi ni de jours ouvrables
nulle part dans le module) — la prémisse initiale du prompt ("conserver la logique d'arrondi
existante") était fausse, l'arrondi a donc été conçu de zéro selon la décision validée
explicitement (nearest, 1000 Ar, champ de config, pas de seuil minimal).

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
   parfois observée sur d'autres systèmes. Arrondi de la cible à 1000 Ar (configurable), absent de
   LPF à notre connaissance.
2. **Ventilation de remboursement** : 3 catégories (intérêt, principal, pénalités) avec l'ordre
   intérêt → principal → pénalités, au lieu des 8 catégories LPF (qui distinguent notamment
   commission échue/à échoir, intérêts échus/à échoir séparément du courant) et de leur ordre de
   priorité pénalités/commission avant intérêt/principal. Commission volontairement absente de
   cette ventilation (déjà traitée ailleurs, encaissée séparément au décaissement/via
   `action_charge_fee`).
3. **Comptabilisation** : cash-basis pur (LPF le pratique aussi pour CEFOR selon le contexte donné)
   — pas d'intérêts échus/accrual, écriture au fil de l'eau à chaque remboursement, jamais en
   amont.
