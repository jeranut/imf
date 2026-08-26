# Statut — Lot 1 : Section VIII "Comité d'Octroi"

**Arrêt obligatoire après ce Lot — en attente de revue manuelle par Micka avant tout commit.**

## Ce qui a été fait

- Nouveau modèle `microfinance.credit.committee.review` (`microfinance_loan_management/models/
  microfinance_loan_application.py`, fin de fichier) : `application_id`, `committee_number`
  (`first`/`second`), `review_date`, `decision` (radio, accepté/refusé/reporté), `postpone_reason`
  (radio, 5 valeurs), `complement` (texte libre), `comment` (texte libre).
- Sur `microfinance.loan.application` : `committee_review_ids` (One2many, jamais rendu en
  `<tree>`), 2 slots `Many2one` (`first_committee_review_id`/`second_committee_review_id`,
  readonly, copy=False - même patron que `vad_visit_id` etc.), champs `related` en cartes pour
  chaque slot (`committee_first_*`/`committee_second_*`).
- `_ensure_committee_review_slot()` : crée le 1er slot à la création du dossier (même patron que
  `_ensure_field_visit_slots`), appelée depuis `create()`.
- `action_add_second_committee_review()` : crée le 2ème slot à la demande (bouton), seulement si
  le 1er comité a la décision "refusé".
- 4 `@api.constrains` sur le nouveau modèle : commentaire obligatoire si refusé, 2ème comité
  jamais "reporté", 2ème comité impossible si 1er pas refusé, décision du 1er verrouillée tant
  qu'un 2ème existe (protège contre une incohérence rétroactive, ajout au-delà de la demande
  littérale - cf. écarts ci-dessous).
- `create()`/`write()`/`unlink()` surchargés sur le nouveau modèle : `AccessError` si
  l'utilisateur courant n'est pas dans `group_microfinance_credit_committee` (sauf `env.su` et
  sauf la création bootstrap du 1er slot, cf. écarts).
- Vue : remplacement du placeholder "standby" (`microfinance_loan_application_views.xml:662-670`)
  par les 2 blocs de cartes, `groups="...group_microfinance_credit_committee"` sur le `<group>`
  englobant.
- `ir.model.access.csv` : 4 nouvelles lignes (`group_microfinance_user` création seule - besoin
  du bootstrap -, `group_microfinance_credit_committee` CRUD sauf unlink,
  `group_microfinance_manager` CRUD complet, `group_microfinance_auditor` lecture seule).
- `microfinance_loan_management/tests/test_credit_committee_review.py` : 12 tests, tous
  passants (détail plus bas).

## Écarts par rapport à la demande littérale — à valider explicitement

**1. Bug évité de justesse, découvert en écrivant le code (pas en testant) : le bootstrap du 1er
slot aurait bloqué la création de N'IMPORTE QUEL dossier par un utilisateur non membre du
comité.** `_ensure_committee_review_slot()` est appelée depuis `create()` de
`microfinance.loan.application`, par **n'importe quel enquêteur créant un dossier** - pas
forcément un membre du comité d'octroi. Sans garde, mon propre `create()` du nouveau modèle
(groupe requis) aurait empêché la création du dossier lui-même. Corrigé par un contexte de
bootstrap (`microfinance_bootstrap_committee_slot`, même principe que
`microfinance_bootstrap_field_visit_slots` déjà utilisé pour VAD/VAV) qui contourne le contrôle
de groupe **uniquement** pour cette création automatique d'une ligne vide (aucune décision
posée) - la création du **2ème** slot (`action_add_second_committee_review`, un acte délibéré)
reste, elle, soumise au contrôle normal.

**2. `AccessError` plutôt que `ValidationError`** pour le contrôle de groupe - mon propre audit
Lot 0 proposait une synthèse `@api.constrains` + `ValidationError`. En écrivant le code, j'ai
choisi `AccessError` via un override `create()`/`write()`/`unlink()` à la place : c'est
sémantiquement le bon type d'exception pour un refus de permission (pas une erreur de donnée),
et ça colle exactement au seul précédent `has_group()` déjà présent dans le module
(`action_reopen_day`, qui lève aussi `AccessError`) - `@api.constrains` aurait été moins naturel
pour "bloquer n'importe quelle écriture", qui n'est pas vraiment une contrainte sur la valeur
d'un champ. Signalé car ça diffère de ma propre proposition d'audit.

**3. Aucune exemption pour `group_microfinance_manager`.** Contrairement à d'autres flux du
module (ex. `action_reopen_day` qui autorise spécifiquement les managers), le contrôle de groupe
ici est **strictement** limité à `group_microfinance_credit_committee`, lecture littérale de la
demande ("réutilisation de group_microfinance_credit_committee", aucune mention d'une
dérogation manager). Un manager qui n'est pas membre du comité serait donc bloqué en écriture
sur ce modèle malgré son rôle "Manager crédit" par ailleurs. `ir.model.access.csv` lui donne
pourtant des droits CRUD complets (cohérence avec le reste du module) - c'est bien mon override
Python qui restreint plus loin, pas l'ACL. À confirmer que c'est l'intention.

**4. `postpone_reason` non rendu obligatoire.** La demande décrit "affichage conditionnel" du
champ raison du report si décision = reporté, sans jamais dire qu'il doit être obligatoire
(contrairement au commentaire, explicitement "obligatoire" pour refusé). Traité littéralement :
visible seulement si reporté, jamais requis. Signalé au cas où l'obligation était implicite.

**5. Limite du widget radio, contournée côté serveur, pas côté vue.** Le 2ème comité ne doit pas
pouvoir choisir "Reporté" (décision actée). Odoo ne permet pas de masquer une option précise
d'un `widget="radio"` par ligne (pas de mécanisme trouvé, ni dans ce module ni dans le framework
standard) : la vue du 2ème comité affiche donc toujours les 3 options au widget, mais
`_check_second_committee_no_postpone` rejette "Reporté" au niveau serveur si sélectionné malgré
tout. Comportement fonctionnellement correct (impossible d'enregistrer "Reporté" au 2ème
comité), mais l'ergonomie n'empêche pas de cliquer dessus avant l'erreur - à évaluer si
acceptable ou si une solution JS/widget custom est souhaitée dans un lot ultérieur.

**6. Contrainte ajoutée au-delà de la demande littérale** :
`_check_first_committee_decision_consistency` (empêche de changer la décision du 1er comité
tant qu'un 2ème existe). Non demandée explicitement, ajoutée pour fermer un trou de cohérence
identifié en écrivant le code (sans elle, on pouvait faire disparaître la justification du 2ème
comité en rouvrant le 1er). Aucun mécanisme de suppression/mise à jour en cascade du 2ème
comité n'a été ajouté (pas demandé) - l'utilisateur devrait supprimer le 2ème comité lui-même
avant de pouvoir rouvrir le 1er (pas de bouton de suppression prévu dans ce lot, à faire via
liste technique/Python si besoin - limite connue, pas un blocage).

**7. Champ "Complément" implémenté comme texte libre générique**, faute de précision sur le
libellé tronqué de la fiche papier ("Complément sur ...") - question ouverte n°2 de l'audit
Lot 0, restée sans réponse. Nommé `complement`, aucune logique dessus. À corriger/renommer/
supprimer une fois la précision obtenue.

**8. Nom du modèle non re-tranché.** L'audit Lot 0 proposait `microfinance.loan.application.
committee.review` comme alternative plus cohérente avec la convention stricte du module (tous
les autres modèles enfants de `microfinance.loan.application` sont préfixés ainsi). Cette
demande réutilise `microfinance.credit.committee.review` directement dans ses exemples de code
sans retrancher la question : j'ai suivi ce nom tel quel plutôt que redemander, renommage facile
si besoin (juste des `related=`/`_name` à changer, aucune donnée en base à ce stade).

## Résultat des tests

`microfinance_loan_management/tests/test_credit_committee_review.py`, **12/12 passants** :

| Test | Vérifie |
|---|---|
| `test_first_slot_created_at_application_creation_by_any_user` | Bootstrap 1er slot, y compris pour un utilisateur hors comité |
| `test_committee_member_can_set_first_decision` | Un membre du comité peut écrire |
| `test_comment_required_when_refused` | Contrainte commentaire obligatoire (refusé) |
| `test_comment_present_when_refused_ok` | ... n'empêche pas une écriture valide |
| `test_second_committee_hidden_until_first_refused` | Bouton d'ajout du 2ème comité refuse si 1er pas refusé |
| `test_second_committee_available_after_first_refused` | ... l'autorise si 1er refusé |
| `test_second_committee_cannot_be_postponed` | Contrainte "pas de report au 2ème comité" |
| `test_second_committee_requires_first_refused_at_orm_level` | Contournement du bouton (create() direct) toujours bloqué |
| `test_cannot_change_first_decision_while_second_exists` | Contrainte de cohérence rétroactive (écart n°6) |
| `test_non_committee_member_write_blocked_at_orm_level` | **Point central de la double protection** : write() direct hors vue |
| `test_non_committee_member_create_blocked_at_orm_level` | idem, create() direct |
| `test_non_committee_member_unlink_blocked_at_orm_level` | idem, unlink() direct |

Exécuté sur un **clone jetable** de SEFOR (`pg_dump`/`pg_restore`, détruit après usage), même
méthode que les lots précédents (installation fraîche toujours bloquée par le problème
`res_company.agency_code` déjà signalé, indépendant de ce lot).

**Suite complète du module** : 441 tests, mêmes 6 échecs/62 erreurs pré-existants qu'avant ce
lot (diff exact des tests en échec entre avant/après = **vide**). Aucune régression introduite.

## Fichiers modifiés

- `microfinance_loan_management/models/microfinance_loan_application.py` : nouveau modèle
  `MicrofinanceCreditCommitteeReview` (fin de fichier), champs/méthodes Bloc F sur
  `MicrofinanceLoanApplication`, hook dans `create()`.
- `microfinance_loan_management/views/microfinance_loan_application_views.xml` : remplacement
  du placeholder Section VIII.
- `microfinance_loan_management/security/ir.model.access.csv` : 4 nouvelles lignes.
- `microfinance_loan_management/tests/test_credit_committee_review.py` (nouveau) +
  `tests/__init__.py` (import).
- `microfinance_loan_management/__manifest__.py` : version 17.0.1.9.0 → 17.0.1.10.0.

Aucune modification des modules EAT/MIIA, aucun commit effectué, sens/usage existant de
`group_microfinance_credit_committee` sur `microfinance.loan` (Avis CA/CDAG) non touché -
conformément aux règles non négociables.
