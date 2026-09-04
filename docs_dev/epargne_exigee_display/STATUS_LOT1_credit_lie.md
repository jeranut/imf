# Statut — Lot 1 : domain + default context sur "Crédit lié" (microfinance_loan_id)

**Commit isolé, en attente de revue de Micka - indépendant de la décision à venir sur l'avenir
de `compulsory`/`microfinance_loan_id` (cf. `AUDIT_COMPLEMENT_credit_lie.md`).**

## Ce qui a été fait

- `action_view_savings_accounts()` (`microfinance_loan_extension.py`) : ajout de
  `default_microfinance_loan_id: self.id` dans le `context` retourné, aux côtés de
  `default_partner_id` déjà présent - le formulaire de création ouvert depuis le smart button
  "Épargne" d'un crédit pré-remplit désormais ce crédit.
- `microfinance_loan_id` (`microfinance_savings_account.py`) : ajout de
  `domain="[('partner_id', '=', partner_id)]"` - même motif déjà en place sur le champ inverse
  `savings_account_id` (`microfinance.loan`), confirmé cohérent (`partner_id` est bien le nom du
  champ client sur les deux modèles).
- **Contrainte serveur** `_check_microfinance_loan_partner_match` (nouvelle, `@api.constrains`) :
  lève une `ValidationError` explicite si `microfinance_loan_id.partner_id != partner_id` - le
  `domain=` seul ne protège que la sélection depuis le formulaire, pas un import/ORM direct/menu
  sans contexte crédit (chemins recensés dans l'audit complémentaire).
- 5 nouveaux tests (`tests/test_savings_account_loan_link.py`).

## Résultat des tests

**Tests ciblés** (nouveau fichier + non-régression clôture), clone jetable de SEFOR, `-u` :
**5/5 nouveaux tests passants**. Les 2 seules erreurs observées sur ce lancement ciblé
(`TestSavingsClosure.test_closure_allowed_once_loan_closed` et
`test_closure_blocked_when_linked_to_active_compulsory_loan`) sont **pré-existantes, sans
rapport avec ce correctif** - échec dans `_check_fond_disponibilite()` (un fonds de crédit
rotatif actif dans les données réelles du clone bloque le décaissement, avant même d'atteindre
le code touché par ce Lot) ; confirmé présentes à l'identique dans les listes de référence déjà
établies aux Lots précédents (`docs_dev/blocage_approbation_comite_octroi/`).

**Suite complète des deux modules**, avant/après ce diff (cumulé avec Lot 1 + Lot 1.1 du
chantier Comité d'Octroi, présents dans le même dépôt de travail) : **587 tests après vs 582
avant (+5, exactement les nouveaux tests), 7 échecs + 81 erreurs dans les deux cas, liste
strictement identique (diff vide)** - zéro régression.

## Fichiers modifiés

- `microfinance_savings_management/models/microfinance_loan_extension.py` : contexte du smart
  button.
- `microfinance_savings_management/models/microfinance_savings_account.py` : `domain=` sur le
  champ + nouvelle contrainte `_check_microfinance_loan_partner_match` + import `ValidationError`.
- `microfinance_savings_management/tests/test_savings_account_loan_link.py` (nouveau) +
  `tests/__init__.py` (import).

## Hors périmètre (respecté)

Aucune création automatique de compte épargne implémentée - reste un chantier à concevoir
séparément (cf. `AUDIT_COMPLEMENT_credit_lie.md`, section "Volet structurel"). Aucune
modification de `guarantee_savings_*` ni `target_during_loan`. Aucun commit déclenché - à la
charge de Micka après revue du diff.
