# Statut — Lot 1.1 : Extension de l'attribution du numéro permanent

**⏸ ARRÊT respecté — en attente de validation de Micka avant le Lot 1.2 (structure conteneur).**

## Ce qui a été fait

- `microfinance.loan.create()` (`microfinance_loan.py:225-247`) : ajout de
  `partner._assign_microfinance_account_number()`, appelé pour **tout partenaire** dès qu'un
  crédit lui est créé (regroupé avec le rattrapage paresseux existant de `loan_account_id`,
  même bloc `if vals.get('partner_id')`) - **plus de condition sur
  `microfinance_partner_type`**. Idempotent (la méthode elle-même fait `if self.microfinance_
  account_number: return`), donc aucun risque de double attribution sur un 2ème crédit.
- `_assign_microfinance_account_number()` elle-même : **non modifiée** - déjà sans condition de
  type interne, seul le point d'appel a changé.
- Le déclencheur historique (`res.partner.create()`, limité à `microfinance_partner_type ==
  'client'`) **reste inchangé** - cette extension s'ajoute en complément, pas en remplacement,
  pour couvrir le cas réel constaté (partenaire `bailleur` ou de type vide qui emprunte quand
  même).
- 4 nouveaux tests (`tests/test_partner_account_number.py`).

## Cas `RANDRIANATOANDRO Jean Batiste` (id 9, `client` mais numéro permanent vide)

**Vérifié en base (lecture seule) : ce client n'a aujourd'hui aucun crédit** (`microfinance_loan`
WHERE `partner_id = 9` → 0 ligne). **Aucune action de rattrapage nécessaire dans ce Lot** : le
nouveau mécanisme s'auto-corrigera dès la création de son 1er crédit, sans intervention. Cause
racine de l'absence de numéro non creusée plus avant (hors périmètre - ni `bailleur`, ni
`agence`, un `client` normal sans numéro reste une anomalie mineure isolée, probablement un
contact créé hors `microfinance_context` avant l'introduction du mécanisme).

## Résultat des tests

**Tests ciblés** (numéro permanent, numérotation agence, compte crédit), clone jetable de SEFOR,
`-u` : **17/17 passants**, 0 erreur.

**Suite complète des deux modules**, avant/après ce diff (cumulé avec tous les lots précédents
de cette session - Comité d'Octroi, Crédit lié épargne) : **591 tests après vs 587 avant (+4,
exactement les nouveaux tests), 7 échecs + 81 erreurs dans les deux cas, liste strictement
identique (diff vide)** - zéro régression.

## Fichiers modifiés

- `microfinance_loan_management/models/microfinance_loan.py` : `create()`, ajout de l'appel à
  `_assign_microfinance_account_number()`.
- `microfinance_loan_management/tests/test_partner_account_number.py` : 4 nouveaux tests
  (aucun nouveau fichier - ajoutés à la suite existante).

## Rappel

Aucun commit. Prochaine étape (Lot 1.2, structure conteneur sur `microfinance.savings.account`)
en attente de validation explicite.
