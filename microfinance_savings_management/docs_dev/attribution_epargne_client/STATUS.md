# Statut dev — attribution_epargne_client
Dernière inspection : 2026-10-07

Correctif : un produit d'épargne ne s'attribue (crée) plus que depuis le smart button
« Épargne » de la fiche client ou le bouton « Épargne » du crédit — le menu Épargne > Produits
d'épargne devient consultation seule. Réversion volontaire d'un choix du lot précédent
(docs_dev/epargne_split/, qui avait explicitement laissé ce menu créable : « Le menu Produits
garde les vues créables »). Pas de modification des vues de base ni d'EAT/MIIA.

Garde fou ajouté en cours de lot, hors périmètre initial de la demande : un même produit
d'épargne ne peut pas être souscrit deux fois simultanément (non clôturé) sur un même compte.

## Audit (étape 0) — façons de créer `microfinance.savings.account`

| Point d'entrée | Avant ce lot | Après ce lot |
|---|---|---|
| Menu Épargne > Produits d'épargne (`action_microfinance_savings_account`) | **Créable** (vues génériques, `view_ids` vidé exprès par le lot précédent) | **Fermé** : vues `*_menu` (déjà `create="0" import="0"`/`duplicate="0"`, réutilisées telles quelles — elles servaient déjà à la balance et aux tuiles du dashboard) + `context: {savings_menu_readonly: True}` |
| Smart button « Épargne » (`res.partner.action_view_microfinance_savings`) | Ouvrait le **compte/titulaire** (`microfinance.savings.holder.account`, jamais créable) — pas une entrée d'attribution du tout | **Seule entrée d'attribution avec le bouton crédit** : ouvre les PRODUITS du client (domaine `partner_id=self`), vue `view_microfinance_savings_account_form_attribution` (titulaire/agence lecture seule), contexte `default_partner_id`/`default_company_id`/`microfinance_savings_attribution` |
| Bouton « Épargne » du crédit (`microfinance.loan.action_view_savings_accounts`) | **Créable**, vues génériques (repli implicite, `partner_id`/`company_id` modifiables jusqu'à l'enregistrement) | Mêmes vues dédiées que le smart button (`view_microfinance_savings_account_form_attribution`) + `microfinance_savings_attribution` ; `default_microfinance_loan_id` inchangé |
| Guichet (dépôt/retrait, `microfinance_caisse_mouvement.py`, JS POS) | Ne crée jamais de produit — opère sur un produit existant | Inchangé (confirmé par grep, aucun `.create(` sur ce modèle dans le guichet) |
| Wizards (`microfinance_caisse_repayment_wizards.py`, `microfinance_savings_renumber_wizard.py`) | Lecture/recherche seulement | Inchangé |
| Migration (`savings_split_migration.py`, `container_migration.py`) | `write()` de rattachement (`account_id`, `rank`, `legacy_number`) sur des produits **déjà existants**, jamais `create()` sur ce modèle | Inchangé — hors de portée de la garde serveur (qui ne filtre que `create()`) |
| `microfinance_data_reset_wizard` | Supprime uniquement (`search_count`/suppression par lots) | Inchangé |
| `microfinance_load_test` | Aucune référence au modèle | Inchangé |
| Tests (`tests/*.py`) | `create()` ORM direct, sans contexte spécial | Inchangé — la garde ne filtre que le contexte `savings_menu_readonly`, jamais posé par les tests |
| Import / duplication depuis la liste du menu | Possibles (vues créables) | Fermés : `import="0"` (vue liste) et `duplicate="0"` (vue formulaire) des vues `*_menu`, déjà en place avant ce lot |

Aucun cas imprévu : l'audit confirme que **seuls** le menu, le smart button et le bouton crédit
créent un produit via l'UI ; tous les autres chemins (guichet, wizards, migration, reset, tests)
n'appellent jamais `create()` sur ce modèle dans un contexte UI, donc jamais affectés par la
garde serveur (scopée au seul contexte `savings_menu_readonly`).

## Fait

- [x] **Vue d'attribution** `view_microfinance_savings_account_form_attribution`
  (`views/microfinance_savings_account_views.xml`) : hérite de la vue générique
  (`view_microfinance_savings_account_form`), `mode="primary"`, force `partner_id` et
  `company_id` en lecture seule **inconditionnelle** (la vue générique ne les verrouille qu'après
  enregistrement, via `readonly="id"` — modifiables à la création). `account_id` reste
  lecture seule/masqué jusqu'à l'enregistrement (résolution serveur inchangée, `invisible="not
  id"`, déjà présent). `product_id` reste le seul champ que l'agent renseigne.
- [x] **Menu fermé** : `action_microfinance_savings_account` pointe désormais sur les vues
  `view_microfinance_savings_account_tree_menu`/`_form_menu` (déjà `create="0"`, réutilisées sans
  duplication) + `context: {'savings_menu_readonly': True}`.
- [x] **Garde serveur** (`models/microfinance_savings_account.py`, `create()`) : si le contexte
  porte `savings_menu_readonly` sans `microfinance_savings_attribution`, `UserError` explicite
  (« L'attribution d'un produit d'épargne se fait depuis la fiche client (bouton Épargne). »).
  Portée volontairement limitée à ce seul contexte — documenté dans le code et ce fichier —
  pour ne jamais bloquer migration/tests/load_test/guichet/wizards, qui ne posent jamais ce
  contexte.
- [x] **Garde cohérence agence** (point 6) : si la société demandée pour le produit diffère de la
  société du titulaire, `ValidationError` avec message métier clair, levée AVANT la contrainte
  générique déjà existante sur `microfinance.savings.holder.account._check_coherence()` (même
  exception, message plus actionnable — cas le plus courant : agence active ≠ agence du client).
- [x] **Garde doublon produit** (hors périmètre initial, demandé en cours de lot) : un même
  `product_id` ne peut pas être ouvert (état ≠ `closed`) deux fois sur le même `account_id` —
  `ValidationError` nommant le produit et l'enregistrement déjà ouvert. Un produit clôturé ne
  compte plus : resouscription possible après clôture (testé). Migration (`savings_split_
  migration`) exemptée par son contexte dédié, pour ne pas faire échouer un rattachement
  historique (anciens conteneurs pouvant contenir des doublons hérités).
- [x] **Smart button client** (`res_partner.py`) : réécrit pour ouvrir les produits (plus le
  compte/titulaire — toujours consultable séparément via le menu « Comptes épargne », non
  touché), avec la vue d'attribution en formulaire et le flag `microfinance_savings_attribution`.
  Compteur `microfinance_savings_count` déjà basé sur le même domaine
  (`microfinance_savings_account_ids`, `account_id != False`) : testé égal au nombre de lignes de
  la liste ouverte.
- [x] **Bouton Épargne du crédit** (`microfinance_loan_extension.py`) : même vue d'attribution
  explicite (au lieu du repli implicite sur les vues génériques create=true), même flag,
  `default_microfinance_loan_id` inchangé.
- [x] **Tests** (`tests/test_savings_account_menu_creation_lock.py`, réécrit) :
  - Vues du menu toujours verrouillées (`create`/`import`/`duplicate`) + câblage `view_ids` +
    contexte `savings_menu_readonly` sur l'action.
  - Garde serveur : contexte menu seul → `UserError` ; contexte menu + flag d'attribution →
    autorisé.
  - Vue d'attribution : `partner_id`/`company_id` lecture seule inconditionnelle (`readonly="1"`
    dans l'arch, pas `readonly="id"`).
  - Smart button : ouvre bien `microfinance.savings.account` (pas le compte), domaine, contexte,
    vue formulaire utilisée ; compteur == lignes de la liste ouverte (y compris client sans
    produit → 0 == 0, liste vide).
  - Bouton crédit : même vue d'attribution, `default_microfinance_loan_id` prérempli.
  - Doublon produit : bloqué si ouvert, autorisé après clôture du premier.
  - Cohérence agence : création refusée pour une société différente de celle du titulaire.
- [x] **Effets de bord corrigés dans des tests existants** (non liés à l'attribution, cassés par
  le nouveau garde-fou doublon car ils réutilisaient `self.savings_product` plusieurs fois sur un
  même titulaire par simple commodité) :
  - `tests/common.py` : ajout de `savings_product_2`/`savings_product_3` (copies du produit de
    test), pour que ces scénarios restent indépendants de la nouvelle règle d'unicité.
  - `tests/test_savings_holder_account.py::test_three_products_one_account_ranks_and_balance` :
    3 produits distincts (plus 3×le même) ; le 4e produit (test du rang jamais réutilisé) relie
    volontairement le produit déjà clôturé du 3e, démontrant au passage la resouscription
    après clôture.
  - `tests/test_savings_holder_account.py::test_duplicate_rank_rejected_by_database` : les deux
    produits comparés pour le rang utilisent maintenant des `product_id` différents (le test
    porte sur l'unicité du **rang**, pas sur celle du produit).
  - `tests/test_savings_transaction_limits.py::test_transaction_date_order_is_per_account` : les
    deux comptes comparés (ordre des transactions **par compte**) utilisent des produits
    différents.
  - `tests/test_savings_holder_account.py::test_product_of_other_agency_client_rejected`
    (préexistant, teste déjà le point 6 via la contrainte générique du compte) : la nouvelle
    garde de cohérence agence lève la **même** `ValidationError` (pas de changement de ce test),
    juste avec un message plus tôt dans la pile.
- [x] **Déploiement sur MOWGLI** : `pg_dump -Fc`
  (`backups/MOWGLI_before_attribution_epargne_20261007_194612.dump`), `systemctl restart
  odoo17_2`, puis 4 passages `odoo-bin -u microfinance_savings_management --test-enable
  --test-tags /microfinance_savings_management --stop-after-init` (itération jusqu'à ce que mes
  propres tests et les régressions introduites soient résolues — cf. ci-dessus) :
  - Passage 1 : 39 erreurs (dont 2 vrais bugs dans mes nouveaux tests : CIN invalide, inversion
    `(view_id, mode)` au lieu de `(mode, view_id)` dans `dict(action['views'])`).
  - Passage 2 (tests corrigés) : 39 → 4 erreurs en moins attendues mais 3 régressions
    nouvelles identifiées (doublon produit cassant 3 tests existants) + 1 test préexistant
    (`test_product_of_other_agency_client_rejected`) cassé par `UserError` au lieu de
    `ValidationError` attendu.
  - Passage 3 (régressions corrigées) : 36 erreurs, toutes pré-existantes et sans rapport
    (`test_auto_debit` ×5, `test_caisse_pos` ×20, `test_caisse_session_theoretical_balance` ×2,
    `test_guarantee_savings` ×4, `test_progressive_eligibility` ×3, `test_savings_closure` ×2) +
    1 dernier cas (`test_three_products_one_account_ranks_and_balance`, 4e produit retombant sur
    le même `product_id` que le 1er, toujours ouvert).
  - Passage 4 (final) : **35 erreurs + 1 échec, toutes pré-existantes et confirmées sans rapport**
    avec ce lot (même liste que passage 3 moins le dernier cas) ; `0` erreur dans
    `test_savings_account_menu_creation_lock`, `test_savings_holder_account`,
    `test_savings_transaction_limits`, `test_savings_account_loan_link`. Service redémarré,
    actif, répond (`/web/login` → 303).

## À faire / incomplet

- **Tests fonctionnels UI non faits** (pas de navigateur dans cette session) :
  - Smart button « Épargne » depuis une fiche client réelle : liste des produits, « Nouveau »
    actif, titulaire/agence préremplis et grisés, sélection du produit, enregistrement →
    compte résolu et rang/nom `-RR` générés.
  - Menu Épargne > Produits d'épargne : absence du bouton « Nouveau » en liste et en formulaire,
    import désactivé, titulaire non modifiable en consultation.
  - Bouton « Épargne » du crédit : même parcours, `microfinance_loan_id` prérempli et visible.
  - Non-régression guichet (dépôt/retrait), transactions, tuiles du tableau de bord épargne
    (valeur == lignes de la liste liée, déjà couvertes par le lot précédent).
- La contrainte de doublon ne traite pas explicitement le cas `microfinance_loan_id` (épargne
  obligatoire liée à un crédit précis) : un client pourrait théoriquement vouloir deux produits
  du même type pour deux crédits différents, simultanément ouverts. Non demandé explicitement,
  non traité ici — à clarifier si ce cas se présente (actuellement bloqué comme tout doublon).
- Pas de garde serveur ajoutée sur un **changement de contexte a posteriori** (`write()`) pour
  `savings_menu_readonly` : la garde ne couvre que `create()`, conforme au périmètre demandé
  (attribution = création). `write()` du produit (ex. changement d'état) reste possible depuis le
  menu en consultation, comme avant.

## Fichiers touchés (résumé)

- `models/microfinance_savings_account.py` (`create()` : garde menu, cohérence agence, doublon
  produit)
- `models/res_partner.py` (`action_view_microfinance_savings`)
- `models/microfinance_loan_extension.py` (`action_view_savings_accounts`)
- `views/microfinance_savings_account_views.xml` (vue d'attribution, action du menu verrouillée)
- `tests/common.py` (`savings_product_2`/`savings_product_3`)
- `tests/test_savings_account_menu_creation_lock.py` (réécrit)
- `tests/test_savings_holder_account.py`, `tests/test_savings_transaction_limits.py` (corrections
  de produit dupliqué sans rapport avec leur objet)
- `docs_dev/attribution_epargne_client/STATUS.md` (ce fichier)
