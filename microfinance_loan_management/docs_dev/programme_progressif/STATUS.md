# Statut dev — programme_progressif
Dernière inspection : 2026-07-17

## Fait
- [x] Modèles `microfinance.loan.progressive.program` / `.step` (contrainte
  `unique(product_id)`, cf. Lot 0 confirmé avec Micka) —
  `microfinance_loan_management/models/microfinance_loan_progressive_program.py`
- [x] Extension `microfinance.loan.product` : `progressive_step_ids`,
  `progressive_program_id`/`progressive_step_sequence`/`is_progressive_step` (computed,
  `store=True`) — `microfinance_loan_management/models/microfinance_loan_product.py`
- [x] Vue liste + formulaire (sous-liste étapes éditable, `widget="handle"`) sous
  **Microfinance > Configuration > Programmes progressifs** —
  `views/microfinance_loan_progressive_program_views.xml`, menu dans
  `views/microfinance_menus.xml`
- [x] Bandeau lecture seule sur la fiche produit ("Fait partie du programme progressif…")
  — `views/microfinance_loan_product_views.xml`
- [x] Sécurité : 8 lignes `ir.model.access.csv` (lecture pour Agent crédit/Finance/
  Auditeur, écriture pour Manager — Gestionnaire hérite via `implied_ids`, pas de ligne
  dédiée)
- [x] Champ `loan_product_id` (requis, domaine société) sur
  `microfinance.loan.application` — absent avant ce chantier, condition préalable
  nécessaire au calcul (confirmé avec Micka)
- [x] `progressive_eligibility_status`/`progressive_eligibility_message` (computed, non
  stockés) sur `microfinance.loan.application`, recherche cross-agency (`sudo()`, sans
  filtre société, même exception documentée que `microfinance_fond_credit.py`) —
  `models/microfinance_loan_application.py`
- [x] Statut "le plus favorable retenu" en cas de prêts multiples, classement
  `defaulted < prior_active < warning < eligible` — confirmé explicitement avec Micka
- [x] Retard historique reconstitué depuis `arrears_onset_date`/`arrears_cured_date` des
  échéances (pas les métriques de scoring courantes, à 0 sur un prêt clôturé) — formule
  confirmée avec Micka
- [x] Champ `closed_date` ajouté sur `microfinance.loan`, posé par `action_close()` —
  nécessaire pour dater le message d'éligibilité, absent avant ce chantier
- [x] Bandeau `alert` coloré (success/warning/danger selon statut) sur la vue formulaire
  du dossier, mention "Information indicative…", aucun bouton de workflow conditionné —
  `views/microfinance_loan_application_views.xml`
- [x] **Bug préexistant corrigé (hors périmètre initial, mais bloquant)** :
  `action_create_loan()` référençait un wizard inexistant
  (`microfinance.loan.application.create.loan.wizard`) — construit (formulaire minimal :
  produit pré-rempli depuis `loan_product_id`, montant, durée) —
  `wizard/microfinance_loan_application_create_loan_wizard.py` + vue associée. Écart déjà
  identifié à deux reprises dans `docs/ecarts_lpf.md` (chantier fonds bailleurs) avant ce
  chantier, désormais résolu.
- [x] Tests automatisés (`tests/test_loan_progressive_program.py`, 9 tests), **exécutés
  réellement** sur la base de développement SEFOR (`-u microfinance_loan_management
  --test-enable --test-tags`), pas seulement écrits/relus : produit indépendant
  (`not_applicable`), étape 1 (`not_applicable`), aucun prêt antérieur
  (`no_prior_loan`), prêt précédent actif (`prior_active`), prêt clôturé sans retard
  (`eligible`), prêt clôturé avec retard hors tolérance (`warning`), prêt radié
  (`defaulted`), plusieurs prêts — le plus favorable retenu (`eligible` malgré un
  `defaulted` concurrent), cas cross-agency (prêt pris dans une autre société). **9/9
  passent.**
- [x] Mise à jour de 3 sites de test existants (`test_application_workflow.py`,
  `test_field_visit.py`, `test_social_category_grid.py`) pour fournir `loan_product_id`
  désormais requis à la création d'un dossier — vérifiés toujours verts après
  modification.
- [x] `docs/ecarts_lpf.md` mis à jour (item 1 et 7 de "Écarts vs LPF"/"Points de
  décision" marqués résolus, nouvel item 8 sur le rang de prêt global LPF vs chaînage
  produit-à-produit CEFOR).

## À faire / incomplet
- [ ] `verification_disponibilite='at_request'` (chantier fonds bailleurs, sans rapport
  direct) reste sans effet réel : le nouveau wizard de création de crédit ne l'invoque
  pas — hors périmètre de ce câblage minimal, signalé dans `docs/ecarts_lpf.md`.
- [ ] Aucun rapport/PDF ni indicateur de tableau de bord pour le programme progressif —
  non demandé dans ce chantier.
- [ ] Le wizard de création de crédit est volontairement minimal (produit/montant/durée) :
  garanties, périodicité, fonds bailleur, comptes, scoring restent à saisir/calculer
  directement sur `microfinance.loan` après création, jamais dupliqués dans le wizard —
  comportement voulu, pas un manque.

## Incohérences relevées
- La suite de tests `TestEligibility` (`tests/test_eligibility.py`, préexistante, non
  modifiée) échoue actuellement sur la base SEFOR (5/25 tests de la session groupée) à
  cause d'un fonds de crédit rotatif actif réellement configuré pour l'agence CEFOR
  Isotry dans cette base de développement persistante (`_check_fond_disponibilite()`,
  chantier fonds bailleurs) — confirmé sans rapport avec ce chantier (trace d'erreur
  entièrement dans un autre module de code, jamais touché ici). Signalé, pas corrigé
  (hors périmètre).
- `microfinance.loan.progressive.program.step.product_id` référence un produit sans
  contrainte serveur imposant que ce produit appartienne à la même société que le
  programme (`program_id.company_id`) — un programme mono-société pourrait en théorie
  référencer une étape avec un produit d'une autre société via l'API. Pas bloquant en
  usage normal de l'interface (le domaine n'a pas été restreint, volontairement, car un
  programme peut être commun à toutes les sociétés) ; à signaler si Micka souhaite un
  contrôle plus strict.
