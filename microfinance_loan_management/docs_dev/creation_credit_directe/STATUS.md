# Statut dev — creation_credit_directe
Dernière inspection : 2026-08-16

Réversion complète du chantier "point d'entrée unique de création crédit"
(`docs_dev/point_entree_unique_credit/STATUS.md`, mis en œuvre le 2026-07-18). Décision de
Micka : ce chantier est abandonné, le crédit redevient créable directement en Brouillon
depuis le menu **Crédits**, sans dossier d'instruction ni wizard. Correction, pas une nouvelle
exploration — aucun des points tranchés en 2026-07-18 n'a été rouvert.

## Fait
- [x] Lot 1 — Verrou serveur retiré : le bloc `if not self.env.context.get
  ('microfinance_loan_creation_allowed'): raise UserError(...)` supprimé de
  `microfinance.loan.create()` — `models/microfinance_loan.py`. L'override `create()` est
  conservé (génération de référence par séquence + rattrapage paresseux de `loan_account_id`,
  logiques indépendantes du verrou).
- [x] Lot 2 — Menu "Crédits" rouvert à la création : les 3 vues `mode="primary"`
  (`view_microfinance_loan_kanban/tree/form_readonly_create`, `create="0"` en héritage) et
  leur câblage dans `view_ids` de `action_microfinance_loan` supprimés —
  `views/microfinance_loan_views.xml`. Piège rencontré : omettre `view_ids` dans le XML ne
  l'efface pas en base sur une instance déjà installée (Odoo ne touche que les champs
  présents dans la définition) — `eval="[(5, 0, 0)]"` explicite nécessaire. ACL standards
  (`ir.model.access.csv`) inchangés, seule gate de création désormais.
- [x] Lot 3 — Bouton "Nouveau prêt" du tableau de bord : `openNewLoan()` repointé vers
  `microfinance.loan` (formulaire vierge), libellé restauré à l'identique du code
  pré-chantier (retrouvé via `git show 6ac4e82`) — `static/src/js/microfinance_loan_dashboard.js`,
  `static/src/xml/microfinance_loan_dashboard.xml`.
- [x] Lot 4 — Wizard supprimé : `wizard/microfinance_loan_application_create_loan_wizard.py`
  et sa vue XML effacés (fichiers, pas commit) ; import retiré de `wizard/__init__.py` ;
  entrée retirée de `__manifest__.py` (liste `data`) et de `security/ir.model.access.csv` ;
  bouton `action_create_loan` et la méthode Python associée retirés de
  `microfinance.loan.application` (ne servait qu'à ouvrir ce wizard). Point relevé : `loan_id`
  sur `microfinance.loan.application` reste `readonly=True` (modèle et vue) — sans le wizard,
  plus aucun moyen UI standard de le peupler (seulement ORM/mode développeur). L'enregistrement
  `ir.model` du wizard reste orphelin en base tant que le plantage pré-existant de
  `_process_end` (voir ci-dessous) n'est pas résolu séparément — sans impact fonctionnel.
- [x] Lot 5 — Tests nettoyés : `tests/test_loan_creation_lock.py` (5 tests validant le verrou/
  wizard supprimé) effacé, avec son import dans `tests/__init__.py`. Trouvés en plus par le
  point 3 du lot :
  `test_application_workflow.py::test_full_workflow_to_loan_created` supprimé (testait le
  cycle dossier→wizard→crédit, disparu) ; `test_partner_credit_selection.py::
  _advance_application_to_loan_created` adapté (création directe + `application.write
  ({'loan_id': ...})` au lieu du wizard, alimente 3 autres tests légitimes sur le verrou de
  changement de produit). 6 fixtures utilisant encore `.with_context
  (microfinance_loan_creation_allowed=True)` (devenu no-op) simplifiées en appels directs —
  `common.py` + 5 fichiers de test. Suite complète (359 tests) exécutée sur SEFOR : aucun
  échec lié à ce chantier, les 6 failures/58 errors restants sont la pollution de données
  pré-existante déjà documentée (fonds actifs, produit id=1), sans rapport.
- [x] Lot 6 — Documentation :
  - `docs_dev/point_entree_unique_credit/STATUS.md` : bandeau "ANNULÉ le 2026-08-16" ajouté en
    tête, historique conservé tel quel en dessous.
  - `docs/audit_menu_credits_duplication.md` : note "Conclusion reversée le 2026-08-16"
    ajoutée en tête, au-dessus de la note de mise en œuvre du 2026-07-18 (conservée).
  - `README.md` : section "Le parcours d'un dossier de crédit" réécrite (création directe,
    dossier recentré sur visite/contre-visite, numérotation) — corrige au passage la
    référence au wizard dans la section Numérotation.
  - `USER_GUIDE_FR.md` : tableau "État du dossier" (en réalité les états de
    `microfinance.loan`), diagramme "Workflow complet d'un crédit", section "Gestion des
    dossiers de crédit" (états/actions du dossier ET du crédit, séparés), FAQ Q10 — tous
    réécrits pour refléter à la fois cette réversion et le cycle à 7/4 états déjà en place
    depuis les chantiers précédents (jamais documentés dans ce fichier avant ce lot).
  - MOWGLI `docs/workflows/dossier_precredit/README.md` : réécriture complète (toutes
    sections) — le fichier était resté au niveau du chantier du 18/07 (committee/ca_review/
    cdag_review sur le dossier, états loan `submitted/manager_validated/finance_validated`),
    jamais mis à jour lors des deux chantiers de simplification qui ont précédé celui-ci dans
    la même journée (restructuration `microfinance.loan` en 7 états, puis simplification de
    `microfinance.loan.application` en 4 états) ; corrigé pour les trois chantiers d'un coup.
  - MOWGLI `datasets/dossier_precredit/dataset.yaml` : `description` générale + articles -001
    (dossier recentré visite/contre-visite), -002 (renommé, validation du crédit via avis
    CA/CDAG), -003 (états mis à jour), -007 (repurposé : "Créer un crédit directement" au lieu
    du wizard, id conservé pour ne pas casser les `see_also` croisés). Articles -004/-005/-006
    (qualification client) non concernés, inchangés.
  - **Hors périmètre, volontairement non touché** : `docs_dev/dossier_precredit/STATUS.md`
    (snapshot historique daté du 2026-07-11, décrit un état encore plus ancien — antérieur
    même au câblage initial du modèle) ; `docs/ecarts_lpf.md` et
    `docs/workflows/programme_progressif/README.md` (récits narratifs d'un chantier passé
    mentionnant `action_create_loan()` comme fait historique, pas de la doc prescriptive sur
    le comportement actuel).

## Fichiers touchés (résumé)
- `models/microfinance_loan.py`, `models/microfinance_loan_application.py`, `models/res_partner.py` (aucun changement Lot 6, déjà couvert par les lots précédents de ce même chantier de réversion)
- `views/microfinance_loan_views.xml`
- `static/src/js/microfinance_loan_dashboard.js`, `static/src/xml/microfinance_loan_dashboard.xml`
- `wizard/microfinance_loan_application_create_loan_wizard.py` (supprimé), `wizard/microfinance_loan_application_create_loan_wizard_views.xml` (supprimé), `wizard/__init__.py`
- `__manifest__.py`, `security/ir.model.access.csv`
- `tests/__init__.py`, `tests/test_loan_creation_lock.py` (supprimé), `tests/test_application_workflow.py`, `tests/test_partner_credit_selection.py`, `tests/common.py`, `tests/test_fond_default_company.py`, `tests/test_fond_bailleur_dashboard.py`, `tests/test_repayment_schedule_report.py`, `tests/test_fond_bailleur.py`, `tests/test_repayment_accounting.py`
- `docs_dev/point_entree_unique_credit/STATUS.md`, `docs/audit_menu_credits_duplication.md`, `README.md`, `USER_GUIDE_FR.md`
- `microfinance_mowgli_assistant/docs/workflows/dossier_precredit/README.md`, `microfinance_mowgli_assistant/datasets/dossier_precredit/dataset.yaml`

## À faire / incomplet
- Aucun traitement rétroactif des crédits/dossiers déjà créés sous l'ancien régime — hors
  périmètre, cohérent avec la décision déjà actée le 18/07 pour le chantier d'origine (instance
  en phase de test).
- `ir.model` du wizard supprimé (`microfinance.loan.application.create.loan.wizard`) et les 3
  vues `ir.ui.view` orphelines du Lot 2 restent en base tant que le plantage pré-existant de
  `_process_end` sur SEFOR (champ `capital_increase`, sans rapport) n'est pas résolu
  séparément — sans impact fonctionnel.
- `loan_id` sur `microfinance.loan.application` reste readonly sans aucun moyen UI de le
  peupler (voir Lot 4) — à trancher avec Micka si un rattachement manuel via l'interface est
  souhaité.

## Incohérences relevées
- Le grep exhaustif du Lot 5 a révélé que la documentation (README, USER_GUIDE_FR, MOWGLI)
  n'avait **jamais été mise à jour** pour les deux chantiers de simplification de workflow
  survenus plus tôt le même jour (restructuration `microfinance.loan` en 7 états, puis
  simplification de `microfinance.loan.application` en 4 états) — corrigé dans ce lot en même
  temps que la réversion du wizard, faute de quoi la documentation serait restée fausse sur
  trois chantiers superposés au lieu d'un seul.
