# Audit — Retrait du bouton « Générer échéancier » (`microfinance.loan`)

Audit en lecture seule (Lot 0). Aucune modification de code pendant l'audit ; test de
persistance exécuté via `odoo-bin shell` sur SEFOR avec `env.cr.rollback()` en fin de script
(aucune écriture conservée). Le Lot 1 associé (retrait effectif) est décrit dans `STATUS.md`.

## Contexte

Micka veut retirer le bouton **« Générer échéancier »**. L'onchange d'aperçu calcule déjà
l'échéancier exact (pas de divergence de calcul) ; la seule question ouverte était la
**persistance** : `installment_ids` est `readonly="1"` en vue, un champ readonly modifié par
onchange n'est jamais renvoyé à la sauvegarde (cf. `docs_dev/echeancier_obsolete_readonly/`).

## 1. Traitement du bouton vs onchange

**Chaîne du bouton** : `views/microfinance_loan_views.xml` →
`action_open_generate_schedule_wizard()` → wizard `microfinance.loan.schedule.rounding.wizard`
→ `action_confirm()` → `action_generate_schedule(rounding_mode=…)`.

`action_generate_schedule()` :
- garde `state in _EDITABLE_SCHEDULE_STATES` + `repayment_frequency_id` obligatoire (`UserError`
  sinon) ;
- `loan.installment_ids = [(5, 0, 0)] + loan._build_installment_commands(rounding_mode=…,
  raise_on_negative_reliquat=True)` — vide l'o2m puis recrée toutes les lignes.

**Différences réelles avec l'onchange** (calcul identique via `_build_installment_commands`) :
1. `rounding_mode` paramétrable — `distributed` n'était atteignable **que** par ce wizard ;
   l'onchange et `write()` utilisent toujours `last_installment`.
2. `raise_on_negative_reliquat=True` — garde-fou reliquat négatif (l'onchange passe `False`).
3. Écriture serveur hors cycle onchange → persiste toujours.

**Les onchange** (`_onchange_loan_amount_recompute_installment` sur
`loan_amount`/`term`/`repayment_frequency_id`/`interest_rate` ;
`_onchange_installment_amount_recompute_terms` sur `installment_amount`) écrivent
`installment_ids` **en mémoire du formulaire uniquement** — jamais persisté seul (readonly).
La persistance vient de l'override `write()` / `_SCHEDULE_TRIGGER_FIELDS`
(`docs_dev/echeancier_obsolete_readonly/`, commit `3c6cad1`) : à l'écriture d'un de ces champs,
`write()` rappelle `action_generate_schedule()` — mais, **avant ce lot**, uniquement si un
échéancier existait déjà (`if loan.installment_ids`).

## 2. `readonly` sur `installment_ids`

`views/microfinance_loan_views.xml` : `<field name="installment_ids" readonly="1"/>` —
**inconditionnel**, pas lié à un état.

## 3. Test SQL direct sur IS/001076 (id 2327, SEFOR)

Via `odoo-bin shell`, transaction annulée en fin de test.

| Test | Action | SQL brut, même curseur (hors cache ORM) | Connexion psycopg indépendante |
|---|---|---|---|
| A | `write({'term': 12})` + `flush_recordset()` | 24 → **12 lignes** (séq. 1→12) | 24 (txn non commitée — le contrôle tape bien la base) |
| B | `Form(loan)` → `f.term = 10` → save (filtre readonly du client web réel) | 24 → **10 lignes** (séq. 1→10) | — |

Rollback → retour à 24 lignes, **aucune modification de SEFOR**.

➡️ **Persistance CONFIRMÉE** : DELETE + INSERT réellement émis. La sauvegarde web
(`installment_ids` readonly non renvoyé, mais `term` renvoyé) déclenche `write()` →
`action_generate_schedule()` et remplace l'échéancier obsolète en base.

## 4. Usages du bouton / de la méthode

- `action_open_generate_schedule_wizard` : **un seul appelant**, le bouton. Aucune action
  serveur, cron, autre vue. Wizard `schedule.rounding.wizard` utilisé seulement par ce bouton.
- `action_generate_schedule` (méthode socle, **conservée**) : appelée aussi par `write()`
  (`_SCHEDULE_TRIGGER_FIELDS`), `_propagate_avis_to_loan()` (1ʳᵉ génération du flux avis
  CA/CDAG), `action_disburse()` (filet si `installment_ids` vide), et ~30 tests.

## 5. Conclusion

La persistance après édition + sauvegarde est réglée sans le bouton. Restaient deux fonctions
uniques au bouton : (a) la **toute première** génération sur un dossier draft/enquete hors flux
avis ; (b) l'accès UI au mode `distributed`. Le Lot 1 (cf. `STATUS.md`) étend `write()` à la
première génération et acte que `distributed` n'a plus d'accès UI (mais reste accessible par
code, `action_generate_schedule(rounding_mode='distributed')`).
