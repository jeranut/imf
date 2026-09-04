# Statut — Lot 1.2 : Structure conteneur sur microfinance.savings.account

**⏸ ARRÊT respecté — en attente de validation de Micka avant le Lot 1.3 (revoir la dérivation du
numéro).**

## Ce qui a été fait

- Nouveau champ `is_container` (Boolean, `readonly=True`, `copy=False`, défaut `False`) sur
  `microfinance.savings.account` - jamais modifiable depuis le formulaire, réservé à la création
  programmatique (Lot 1.4).
- `product_id` n'est plus `required=True` au niveau champ - remplacé par une contrainte serveur
  `_check_product_required_unless_container` (`@api.constrains('is_container', 'product_id')`),
  qui reproduit l'ancienne garantie pour tout compte réel tout en exemptant un conteneur.
- `action_activate()`, `action_close()`, `_create_transaction()` : chacune lève désormais un
  `UserError` explicite si appelée sur un conteneur (`is_container = True`) - jamais un échec
  silencieux, conformément au principe déjà appliqué sur ce chantier.
- Vues (`microfinance_savings_account_views.xml`) :
  - Formulaire : ruban "Conteneur" (`widget="web_ribbon"`), masquage du statusbar, des boutons
    Activer/Clôturer, du bloc de boutons statistiques (Transactions/Crédits), de
    Produit/Devise/Crédit lié/Suivi/Solde/onglet Transactions - un conteneur affiche seulement
    Référence, Titulaire et Société.
  - Liste : nouveau filtre "Masquer les conteneurs" (`hide_containers`), **actif par défaut**
    sur les actions "Comptes épargne" et "Balance épargne" (via `search_default_hide_containers:
    1`) - retirable en un clic pour les voir si besoin, pas de vue séparée nécessaire.
- 6 nouveaux tests (`tests/test_savings_account_container.py`).

## Résultat des tests

**Tests ciblés** (conteneur, clôture existante, crédit lié), clone jetable de SEFOR, `-u` :
**12/14 passants** - les 2 seules erreurs (`TestSavingsClosure.test_closure_allowed_once_loan_
closed` et `test_closure_blocked_when_linked_to_active_compulsory_loan`) sont **pré-existantes,
sans rapport avec ce Lot** (déjà documentées dans les lots précédents de cette session - un
fonds de crédit rotatif actif dans les données réelles du clone bloque un décaissement de test).

**Suite complète des deux modules**, avant/après ce diff (cumulé avec tous les lots précédents
de cette session) : **597 tests après vs 591 avant (+6, exactement les nouveaux tests), 7 échecs
+ 81 erreurs dans les deux cas, liste strictement identique (diff vide)** - zéro régression.

## Fichiers modifiés

- `microfinance_savings_management/models/microfinance_savings_account.py` : champ
  `is_container`, `product_id` (retrait de `required=True`), nouvelle contrainte, garde-fous sur
  `action_activate`/`action_close`/`_create_transaction`.
- `microfinance_savings_management/views/microfinance_savings_account_views.xml` : formulaire,
  liste, recherche, actions.
- `microfinance_savings_management/tests/test_savings_account_container.py` (nouveau) +
  `tests/__init__.py` (import).

## Rappel

Aucun commit. `-u` lancé sur SEFOR (aucun conteneur réel n'existe encore - le champ `is_container`
vaut `False` partout, comportement strictement inchangé pour tous les comptes existants). Reste à
faire côté Micka : `sudo systemctl restart odoo17` pour déployer. Prochaine étape (Lot 1.3, revoir
la dérivation du numéro) en attente de validation explicite.
