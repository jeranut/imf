# Statut dev — point_entree_unique_credit
Dernière inspection : 2026-07-18

Suite à l'audit `docs/audit_menu_credits_duplication.md` : le dossier d'instruction
(`microfinance.loan.application`) devient le seul point d'entrée de création d'un crédit
(`microfinance.loan`). Option A retenue.

## Fait
- [x] Lot 1 — Verrou serveur : `microfinance.loan.create()` lève `UserError` sauf contexte
  `microfinance_loan_creation_allowed` (posé uniquement par le wizard
  `microfinance.loan.application.create.loan.wizard.action_validate()`). Vérifié sur le
  chemin d'appel, pas sur le rôle (testé explicitement : un manager avec accès complet
  reste bloqué) — `models/microfinance_loan.py:150-159`
- [x] 6 sites de test légitimes mis à jour (`tests/common.py::_create_loan` + 5 fichiers),
  dont 4 découverts uniquement en exécutant la suite complète
  (`odoo.tests.Form(self.env['microfinance.loan'])` dans `test_fond_default_company.py`,
  invisible au grep statique)
- [x] `tests/test_loan_creation_lock.py` (nouveau, 5 tests) : création directe bloquée,
  bloquée même pour un manager, bloquée en import par lot simulé, autorisée avec le
  contexte, autorisée de bout en bout via le wizard depuis un dossier accepté
- [x] Lot 2 — Menu "Demande de crédit" renommé "Crédits" (`menu_microfinance_loans`) ;
  3 vues dédiées `mode="primary"` (kanban/tree/form, `create="0"` sur la balise racine)
  référencées uniquement par `action_microfinance_loan` — héritent de tout le contenu des
  vues génériques (dont les ajouts du module scoring), sans jamais s'appliquer aux
  fetches des vues génériques elles-mêmes (`action_view_loan` du dossier, wizards de
  remboursement/rééchelonnement/radiation inchangés) — `views/microfinance_loan_views.xml`
  - Bug réel trouvé et corrigé : la première version de `view_ids` (sans `(5,0,0)`)
    dupliquait les lignes `ir.actions.act_window.view` à chaque `-u`, violant la
    contrainte d'unicité `act_window_view_unique_mode_per_action` — idempotence
    vérifiée par deux upgrades consécutifs
- [x] Lot 3 — Bouton "Nouveau prêt" du tableau de bord (`openNewLoan()`) ouvre désormais
  `microfinance.loan.application` (dossier, état draft) au lieu de `microfinance.loan` ;
  libellé renommé "Nouveau dossier" — `static/src/js/microfinance_loan_dashboard.js:183-194`,
  `static/src/xml/microfinance_loan_dashboard.xml:245`. Aucun bouton "Nouveau dossier"
  préexistant, pas de doublon à gérer.
- [x] Lot 4 — Documentation :
  - `README.md` : section "Le parcours d'un dossier de crédit" réécrite (instruction du
    dossier → wizard → cycle du crédit)
  - `USER_GUIDE_FR.md` : "Workflow complet d'un crédit" (diagramme ASCII) et "Gestion des
    dossiers de crédit" réécrits ; FAQ Q9 corrigée ; toute mention du chemin de menu
    "Demandes de crédit → Dossiers de crédit" (qui n'a jamais existé tel quel) supprimée
  - MOWGLI `datasets/dossier_precredit/dataset.yaml` : article -001 réécrit (dossier
    d'instruction, plus microfinance.loan), nouvel article -007 (wizard + soumission du
    crédit, reprend les prérequis/erreurs d'éligibilité de l'ancien -001), -002/-003
    corrigés (libellé de menu seulement, contenu déjà exact)
  - MOWGLI `docs/workflows/dossier_precredit/README.md` : sections 1, 3, 4(A), 8(A), 13,
    14 mises à jour (dossier d'instruction comme point d'entrée, verrou de création)
  - MOWGLI `datasets/reechelonnement/dataset.yaml` et `datasets/comptabilite/dataset.yaml`
    + leurs `docs/workflows/*/README.md` : libellé de menu seulement ("Demande de
    crédit" → "Crédits"), contenu déjà exact (ils éditent un crédit existant, pas sa
    création)
  - `docs/audit_menu_credits_duplication.md` : note d'implémentation ajoutée (section 6),
    Option A confirmée comme mise en œuvre, datée

## À faire / incomplet
- Aucun traitement rétroactif des crédits déjà créés en direct (`application_id`/`loan_id`
  vide côté dossier) — confirmé hors périmètre par Micka (instance en phase de test).

## Incohérences relevées
Aucune incohérence structurelle relevée pour ce chantier une fois les 4 sites de test
manqués (Form()) corrigés — voir section "Fait" ci-dessus pour le détail des deux bugs
réels trouvés et corrigés en cours de route (sites de test manqués, idempotence de
`view_ids`).
