# Statut — Lot 1 : Blocage de l'approbation si le Comité d'Octroi n'accepte pas

**Arrêt obligatoire après ce Lot — en attente de revue manuelle par Micka avant tout commit ET
avant tout déploiement sur SEFOR (`-u` + restart).** Rien n'a été commité, rien n'a été déployé.

## Ce qui a été fait

- `action_approve()` (`microfinance_loan.py`) appelle désormais `_check_committee_octroi_accepted()`
  sur chaque crédit avant d'écrire `state = 'approved'` — plus aucun changement d'état possible
  sans passer par le contrôle.
- `_check_committee_octroi_accepted()` implémente exactement la règle validée par Micka le
  31/08/2026 (cf. `AUDIT.md`) : `accepted` du 1er comité → autorisé ; `refused` du 1er comité →
  bloqué définitivement (2ème comité ignoré) ; `postponed` du 1er comité → on regarde le 2ème,
  seul `accepted` du 2ème autorise, tout le reste (`refused`/`postponed`/vide/absent) bloque ;
  aucune décision/aucun dossier → bloqué.
- Message d'erreur : **variante détaillée** proposée dans l'audit (celle recommandée), avec un
  `{détail}` qui distingue "aucune décision enregistrée" (dossier absent ou slot vide/absent) de
  "reporté" et de "refusé".
- `application_ids[:1]` utilisé pour résoudre le dossier depuis le crédit — même choix que
  `action_view_applications()` déjà en place (cf. audit section 2 : `application_ids` reste un
  One2many non contraint à l'unicité, mais aucun cas réel à plusieurs dossiers observé).
- Tests dédiés : `tests/test_committee_octroi_approval_guard.py` (nouveau), 7 tests couvrant les
  8 cas du tableau de l'audit (les cas 4/5/7/8 étant regroupés car indiscernables pour
  l'utilisateur, voir écart n°2 ci-dessous).
- Fixtures existantes mises à jour pour rester valides sous la nouvelle garde : `tests/common.py`
  (`_loan_in_avis_cdag` → règle le comité à "accepté" avant `action_approve()`, changement
  transparent pour tous les tests qui utilisent ce helper) + 8 fichiers de tests qui appelaient
  `action_approve()` directement sans passer par le helper (`test_cash_balance_check.py`,
  `test_disbursement_limit.py`, `test_fee.py`, `test_fond_bailleur.py`,
  `test_locked_dossier_fields.py`, `test_repayment_accounting.py`, `test_reschedule.py`,
  `microfinance_savings_management/tests/test_caisse_pos.py`) : ajout de
  `loan.action_view_applications(); loan.application_ids.write({'committee_first_decision':
  'accepted'})` juste avant chaque `action_approve()` concerné.

## Écarts par rapport à l'audit — à valider explicitement

**1. Cas "dossier absent" traité par un message dédié, pas par le gabarit `{détail}` commun.**
L'audit proposait un seul gabarit `Impossible d'approuver le crédit {référence} : {détail}...`
pour tous les cas. Le cas "aucun `microfinance.loan.application` du tout" (théorique aujourd'hui,
cf. audit section 3, aucun cas réel observé) utilise un message complet à part
("...aucun dossier d'instruction n'existe pour ce crédit, le comité d'octroi n'a donc rendu
aucune décision...") plutôt que de forcer ce cas dans la variable `{détail}` du gabarit commun -
choix fait pour que ce cas, structurellement différent (pas de dossier du tout, vs dossier avec
décision manquante/refusée/reportée), reste immédiatement identifiable dans le code sans relire
toute la méthode. Signalé car ce n'est pas littéralement ce que proposait l'audit.

**2. Cas 4/5/7/8 du tableau de l'audit fusionnés en un seul message "aucune décision
enregistrée".** L'audit posait la question ouverte de distinguer ces cas (2ème comité non créé /
en attente / slot jamais créé) sans trancher. Traité ici de façon uniforme : `if not first or not
first.decision` → même message pour "le 1er comité n'a jamais été convoqué" et pour "convoqué
mais rien n'a encore été sélectionné" - cohérent avec le principe "ne pas laisser croire à un
refus qui n'a jamais eu lieu" mis en avant par l'audit, mais ne distingue pas plus finement ces
sous-cas entre eux. À confirmer que ce niveau de détail est suffisant.

## Point bloquant CRITIQUE, non résolu — à trancher avant tout déploiement

**Les 2 seuls crédits réels de SEFOR seront bloqués par cette garde dès sa mise en production.**
Revérifié en base aujourd'hui (31/08/2026, lecture seule) : IS/000289 (id 1449) et IS/001076
(id 2327) sont tous les deux **toujours en état `avis_cdag`** (personne n'a encore cliqué sur
Approuver depuis l'audit du 26/08), et leurs dossiers d'instruction respectifs (app id 1154 et
1319) **n'ont toujours aucun 1er comité créé** (`first_committee_review_id` NULL sur les deux).

Conséquence directe : dès que ce Lot est déployé (`-u` + restart), le premier utilisateur qui
tentera d'approuver l'un de ces deux crédits recevra le blocage "aucune décision du comité
d'octroi n'a encore été enregistrée..." - **aucun de ces deux dossiers ne pourra être approuvé
tant qu'une décision de comité n'aura pas été saisie a posteriori.** Comme noté dans l'audit
(section 1), c'est un effet de bord réel du fait que `_ensure_committee_review_slot()` ne
s'applique jamais rétroactivement aux dossiers créés avant le déploiement du Comité d'Octroi.

**Aucune correction automatique n'a été apportée à ces 2 dossiers** (hors périmètre de ce Lot,
et toute écriture sur des données réelles nécessite l'accord explicite de Micka). Deux options à
trancher avant déploiement :
- **Option A** : accepter le blocage — un membre du comité crée/renseigne le 1er comité (décision
  "Accepté") pour ces 2 dossiers via l'interface normale avant que quiconque tente d'approuver.
  Aucune action technique requise, juste une consigne côté métier.
- **Option B** : un script de rattrapage ponctuel (hors de ce Lot) crée les slots manquants avec
  une décision "Accepté" pré-remplie pour ces 2 dossiers spécifiquement, en s'appuyant sur le
  mécanisme déjà en place (`_ensure_committee_review_slot()`), pour éviter toute intervention
  manuelle en production au moment où quelqu'un voudra approuver.

## Résultat des tests

**Suite dédiée** `test_committee_octroi_approval_guard.py`, **7/7 passants** (clone jetable de
SEFOR, `pg_dump`/`pg_restore`, détruit après usage — aucune écriture sur SEFOR) :

| Test | Cas de l'audit couvert |
|---|---|
| `test_blocked_when_no_application_at_all` | Dossier absent |
| `test_blocked_when_first_committee_not_decided` | Cas 7 (slot créé, vide) |
| `test_allowed_when_first_committee_accepted` | Cas 1 |
| `test_blocked_when_first_committee_postponed` | Cas 6 |
| `test_blocked_when_first_refused_and_no_second` | Cas 4 |
| `test_blocked_when_first_refused_and_second_refused` | Cas 3 |
| `test_allowed_when_first_refused_and_second_accepted` | Cas 2 |

**Suite complète des deux modules** (`microfinance_loan_management` +
`microfinance_savings_management`), exécutée avec `-u` (méthodologie des lots précédents) sur le
même clone jetable, **avant/après ce diff** : **578 tests après vs 571 avant (+7, exactement les
nouveaux tests), 7 échecs + 81 erreurs dans les deux cas, liste des tests en échec/erreur
strictement identique (diff vide)** - zéro régression introduite par ce Lot.

**Note méthodologique sur cette validation** : une première tentative de comparaison sans relancer
`-u` entre les deux exécutions faisait apparaître un nombre d'erreurs bien plus élevé (une
violation de contrainte NOT NULL sur `microfinance_loan_product.savings_requirement_type`,
présente à l'identique avec et sans ce diff, donc sans rapport avec ce Lot) - artefact de
l'ordre d'exécution des process, disparaissant totalement dès que `-u` est relancé juste avant
les tests (comportement des lots précédents). Les 7 échecs/81 erreurs restants après `-u` sont
des données réelles du clone (mêmes causes que les "6 échecs/62 erreurs" documentés aux lots
précédents, dont la liste a simplement grandi avec le nombre de tests du dépôt) - à ne pas
confondre avec des régressions.

## Fichiers modifiés

- `microfinance_loan_management/models/microfinance_loan.py` : `action_approve()` +
  `_check_committee_octroi_accepted()` (nouvelle méthode).
- `microfinance_loan_management/tests/test_committee_octroi_approval_guard.py` (nouveau) +
  `tests/__init__.py` (import).
- `microfinance_loan_management/tests/common.py` + 7 fichiers de tests existants +
  `microfinance_savings_management/tests/test_caisse_pos.py` : mise à jour des fixtures pour
  poser une décision de comité "Accepté" avant `action_approve()` (cf. ci-dessus).

Aucune modification de vue, de sécurité, ou de modèle au-delà de `microfinance_loan.py`. Aucun
commit, aucun déploiement sur SEFOR.
