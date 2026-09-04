# Statut — Lot 1 : retrait du bouton « Générer échéancier » + génération à la 1ʳᵉ sauvegarde

**Décisions Micka :**
1. Retrait du bouton dans un lot dédié qui étend `write()` à la première génération.
2. Ne pas toucher au moteur de calcul d'arrondi ni au paramètre `rounding_mode` / branche
   `distributed` (« garde le mode arrondi et mode calculé déjà géré ») : on retire seulement ce
   dont la génération automatique (onchange → `write()`) ne dépend pas — le bouton et son
   wizard. `distributed` reste accessible par code
   (`action_generate_schedule(rounding_mode='distributed')`, utilisé en test), sans UI.

## Correctif appliqué

### `microfinance_loan_management/models/microfinance_loan.py`
- **`write()` / bloc `_SCHEDULE_TRIGGER_FIELDS`** : suppression de la précondition
  `loan.installment_ids and`. Nouvelle garde :
  `loan.state in _EDITABLE_SCHEDULE_STATES and loan.repayment_frequency_id and loan.loan_amount
  and loan.term`. Dès que les 3 champs essentiels sont renseignés sur un crédit modifiable,
  toute sauvegarde qui passe par `write()` sur un champ source crée **et persiste**
  l'échéancier — y compris la première fois. La garde sur les 3 champs évite un `UserError` de
  `action_generate_schedule()` (périodicité manquante) sur un brouillon incomplet : no-op
  jusqu'à ce qu'ils soient saisis. Mode d'arrondi toujours `last_installment` (comme
  `_propagate_avis_to_loan()`).
- Commentaires de `_SCHEDULE_TRIGGER_FIELDS` et du bloc `write()` réécrits.
- **Suppression de `action_open_generate_schedule_wizard()`**.
- **Non touché** : `action_generate_schedule(rounding_mode='last_installment')`,
  `_build_installment_commands()`, `_compute_installment_targets()` (branche `distributed`
  incluse), les deux onchange d'aperçu.

### Vue / wizard / sécurité
- `views/microfinance_loan_views.xml` : bouton retiré ; commentaire sur `installment_ids
  readonly="1"` mis à jour (mention de la 1ʳᵉ génération, plus de bouton).
- Supprimés : `wizard/microfinance_loan_schedule_rounding_wizard.py`,
  `wizard/microfinance_loan_schedule_rounding_wizard_views.xml`.
- `wizard/__init__.py`, `__manifest__.py`, `security/ir.model.access.csv` : références retirées.

### Limite connue et assumée
La **création** seule d'un crédit (`create()` / premier `Form.save()`) ne génère pas encore
l'échéancier : le hook est sur `write()`, et `installment_ids` (readonly) n'est pas transmis à
la création. La première ré-sauvegarde (ou toute édition ultérieure d'un champ source), le flux
avis CA/CDAG (`_propagate_avis_to_loan()`) ou le décaissement (`action_disburse()`, filet)
génèrent l'échéancier. Hooker `create()` a été écarté : trop large (nombreux tests supposent
« crédit créé → échéancier vide »).

## Tests — `microfinance_loan_management/tests/`

`test_installment_schedule_persistence.py` :
- `test_write_does_not_regenerate_before_first_generation` remplacé par
  `test_write_generates_first_schedule_on_save` (création seule → vide ; 1ʳᵉ ré-sauvegarde sur
  un champ source → échéancier créé et persisté ; modification ultérieure toujours répercutée).
- Nouveau `test_write_first_generation_skipped_when_incomplete` : produit `client_choice` sans
  périodicité choisie → `write()` sur `loan_amount` ne plante pas, `installment_ids` reste vide.
- Inchangés : `test_term_change_after_generation_persists_to_installment_ids`,
  `test_loan_amount_change_after_generation_persists`, `test_write_does_not_regenerate_once_active`.

`test_interest_first_schedule.py::test_distributed_rounding_mode_spreads_remainder_over_last_installments`
inchangé (appelle `action_generate_schedule(rounding_mode='distributed')` en direct, signature
préservée).

## Validation

- Suite complète du module sur `imf_scratch_test`, comparaison baseline (HEAD, mes changements
  retirés via `git stash`) vs après :
  - baseline : `0 failed, 3 error(s)` ;
  - après : `0 failed, 3 error(s)` — **exactement les 3 mêmes erreurs pré-existantes**
    (`TestLoanInstallmentAmount.test_no_recompute_once_loan_is_active` — conflit avec le verrou
    `_check_locked_dossier_fields` déjà commité ; `TestSocialCategoryGrid` ×2 — domaine sans
    rapport). **Aucune régression introduite.**
  - Les 2 nouveaux tests de persistance passent.
- `-u microfinance_loan_management` sur **SEFOR** : `EXIT=0`, « Modules loaded », aucune
  erreur/critique. Modèle `microfinance.loan.schedule.rounding.wizard`, ses champs et la vue du
  bouton proprement retirés du registre/base.

## Reste à faire (hors de mes mains)

- **Redémarrage du service `odoo17`** requis (`sudo systemctl restart odoo17`, `workers=0`)
  pour que le correctif `.py` soit pris en compte — pas les droits sudo ici.
- Contrôle manuel après restart : bouton disparu de l'entête du formulaire crédit ; sur le
  dossier draft `IS/003362` (id 4777, 0 ligne), renseigner périodicité + montant + nb
  d'échéances, ré-enregistrer → onglet Échéancier peuplé ; vérif SQL
  `SELECT count(*) FROM microfinance_loan_installment WHERE loan_id=4777;` == `term`.
- Commit isolé, après revue de Micka.
