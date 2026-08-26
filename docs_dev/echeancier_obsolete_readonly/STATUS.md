# Statut — Lot 1 : correction `installment_ids` obsolète (readonly + onchange)

**Option retenue (choix utilisateur, le rapport ne tranchait pas)** : Option 2 — garder les
onchange d'aperçu tels quels, ajouter une écriture réelle dans `write()` qui régénère
`installment_ids` tant que le crédit reste dans `_EDITABLE_SCHEDULE_STATES`.

## Correctif appliqué

`microfinance_loan_management/models/microfinance_loan.py` — nouvelle constante
`_SCHEDULE_TRIGGER_FIELDS = {'loan_amount', 'term', 'repayment_frequency_id', 'interest_rate',
'installment_amount'}`, et `write()` étendu : dès qu'un de ces champs est écrit, régénère
`installment_ids` via `action_generate_schedule()` (même chemin déjà sûr, déjà utilisé par le
bouton "Générer échéancier" et par `_propagate_avis_to_loan()`), **uniquement si** un échéancier
existe déjà (`loan.installment_ids` non vide - ne force pas une première génération hors du
wizard, qui laisse le choix du `rounding_mode`) et si le crédit est encore modifiable
(`_EDITABLE_SCHEDULE_STATES`).

**Limitation connue et assumée, héritée du pattern déjà en place** (`_propagate_avis_to_loan`,
avant ce correctif) : la régénération automatique utilise toujours `rounding_mode=
'last_installment'` (défaut) - `rounding_mode` n'est stocké nulle part sur le crédit, seulement
transitoire dans le wizard. Un crédit dont l'échéancier initial avait été généré en mode
`'distributed'` reverrait donc son reliquat redistribué en `'last_installment'` dès la première
modification de `loan_amount`/`term`/etc. après génération. Pas une régression introduite par ce
correctif (le même comportement existait déjà pour `_propagate_avis_to_loan`) - signalé pour
arbitrage futur si jugé nécessaire, hors périmètre de ce Lot.

`microfinance_loan_management/views/microfinance_loan_views.xml` — commentaire ajouté sur le
`readonly="1"` d'`installment_ids` pour éviter qu'un futur lecteur ne le retire par erreur en
pensant qu'il bloque la persistance.

## Tests

Nouveau fichier `tests/test_installment_schedule_persistence.py` (4 tests, ajouté à
`tests/__init__.py`) :
- `test_term_change_after_generation_persists_to_installment_ids` : reproduction directe du
  symptôme IS/001076 (échéancier à 27 lignes résiduel, `term` ramené à 24 - doit persister 24
  lignes après sauvegarde).
- `test_loan_amount_change_after_generation_persists` : même bug déclenché par `loan_amount`.
- `test_write_does_not_regenerate_before_first_generation` : ne force pas une génération hors
  wizard tant qu'aucun échéancier n'existe.
- `test_write_does_not_regenerate_once_active` : n'écrase pas un échéancier réel une fois le
  crédit actif (protège l'historique de paiement).

## Validation

- Suite ciblée (persistence + feedback loop Lot 1-bis + interest-first schedule + avis CA/CDAG) :
  31 tests, 0 échec, 0 erreur.
- Suite complète du module (641 tests) : comparée avec/sans le correctif (bascule temporaire via
  `if False and ...`, puis restaurée) pour isoler l'effet réel du changement, en tenant compte de
  ce que la base SEFOR n'est pas un environnement de test isolé (plusieurs suites pré-existantes
  échouent déjà indépendamment de ce correctif, ex. `test_dashboard_par`, `test_provision`,
  `test_write_off` : toutes échouent avec la même cause - "Un fonds de crédit rotatif actif
  existe pour cette agence" - un fonds resté actif dans SEFOR depuis un test manuel antérieur,
  sans lien avec `installment_ids`). Résultat de la comparaison stricte (`comm` sur les deux
  listes de FAIL/ERROR) : **aucune régression** - les deux runs partagent exactement les mêmes 62
  erreurs et mêmes 6 échecs pré-existants ; les 2 seules différences sont
  `TestInstallmentSchedulePersistence.test_term_change_after_generation_persists_to_installment_
  ids` et `test_loan_amount_change_after_generation_persists`, qui échouent sans le correctif et
  passent avec.

## Régénération des dossiers déjà obsolètes

Sur confirmation explicite (écriture en base) : `IS/000289` (id 1449, 8→24 lignes) et
`IS/001076` (id 2327, 27→24 lignes) régénérés via `action_generate_schedule()` (même geste que
le bouton "Générer échéancier"), vérifié indépendamment par requête SQL brute après coup - somme
des principaux = `loan_amount` (500 000 Ar) pour les deux, 24 lignes chacun.

## Reste à faire (hors de mes mains)

**Redémarrage du service `odoo17` requis** (`sudo systemctl restart odoo17`, `workers=0`) pour
que le correctif Python soit pris en compte par l'instance en cours - je n'ai pas les droits sudo
pour l'exécuter moi-même.
