# AUDIT — Séparer « Compte épargne » (client) et « Produit d'épargne souscrit »

Date : 2026-10-07. Base : MOWGLI (lecture seule). Code : `custom_addons` (diff des lots précédents non commité, inclus).
Aucune modification. Décisions à trancher en **§ h**.

## a) Structure actuelle

**Modèle `microfinance.savings.account`** ([microfinance_savings_account.py](../../microfinance_savings_management/models/microfinance_savings_account.py)) — un seul modèle pour deux rôles :

| Champ | Rôle |
|---|---|
| `name` | référence (readonly), numérotée à la création |
| `partner_id`, `company_id`, `currency_id` | titulaire, agence |
| `is_container` (readonly) | vrai = conteneur (le « compte » du client) ; faux = produit souscrit |
| `product_id` | produit d'épargne ; obligatoire **sauf** conteneur (`_check_product_required_unless_container`) |
| `state` | draft / active / dormant / closed |
| `balance` | **stocké**, calculé depuis les transactions comptabilisées (`transaction_ids`) |
| `opening_date`, `closing_date`, `maturity_date` (stocké), `last_transaction_date` (stocké), `is_dormant` | suivi |
| `microfinance_loan_id` | « Crédit lié » (épargne obligatoire constituée pour un crédit) |
| `transaction_ids`, `loan_account_id` (calculé, cherche le compte crédit du titulaire) | |
| `closure_reason_type/_note` | clôture |

**Lien conteneur ↔ produits : aucun champ.** Le rattachement n'existe que par le même `(partner_id, company_id)`. Un index unique partiel `microfinance_savings_account_container_uniq_idx` garantit un seul conteneur par client et par société.

**Numérotation actuelle** (`AGENCE/TYPE/N`) :
- Conteneur : `<code agence>/I/<N>`, où N = suffixe de `res.partner.microfinance_account_number` (numéro permanent du client, `AGENCE/NNNNNN`, séquence `microfinance.partner.account` par société). C'est le **même N** que le compte crédit (`microfinance.loan.account`). Aucune séquence propre.
- Produit type I (volontaire) : **même séquence** `microfinance.partner.account` que le numéro permanent du client (« Option B », fusion des compteurs), avec saut des noms déjà pris.
- Produit type G (obligatoire) / T (dépôt à terme) : séquences `microfinance.savings.account.G` / `.T` par société.
- Les séquences sont créées à la demande par `res.company._get_or_create_numbering_sequence(code, padding=6)`, sans préfixe dans `ir.sequence` (le préfixe est concaténé en Python).
- **« GY/I/ »** = agence CEFOR Andravoahangy (code `GY`) / type `I` (épargne volontaire), et **pas** « GY = garantie ». La lettre de type vient de `product_type` : `I` = volontaire, `G` = obligatoire (garantie), `T` = dépôt à terme. `IC` est un ancien format de conteneur (« Option A », abrogée).
- Conséquence : conteneurs et produits I se partagent l'espace `AGENCE/I/N`. D'où des trous et une lecture difficile (GY/I/000001-000002 = conteneurs, GY/I/000003-000004 = produits).

**Création automatique :**
- Le conteneur est créé à **l'enregistrement du client**, sous `microfinance_context` (`res_partner.create()` → `_get_or_create_microfinance_savings_container`). Il n'est **jamais** créé à la première souscription.
- Les produits sont toujours **créés à la main** : bouton « Épargne » du crédit (contexte `default_partner_id`, `default_microfinance_loan_id`) ou menu Épargne. Aucun code ne crée de produit à l'octroi ou à l'activation d'un crédit. « EP lié au crédit » est seulement le **nom d'un produit** dans les données, et `microfinance_payroll_loan` (avance spéciale) ne touche pas à l'épargne.

## b) Données MOWGLI

| Agence | Conteneurs | Produits | Solde produits | Solde conteneurs |
|---|---|---|---|---|
| AD Andoharanofotsy | 14 | 2 | 100 000 | 0 |
| BD Ambanidia | 1 | 0 | — | 0 |
| GY Andravoahangy | 2 | 2 | 0 | 0 |
| IS Isotry | 1 | 0 | — | 0 |
| KA Ambohitrimanjaka | 1 | 0 | — | 0 |
| MS Mahitsy | 4 | 0 | — | 0 |
| SY Ampitatafika | 4 | 3 | 75 000 | 0 |
| TA Andranonahoatra | 2 | 0 | — | 0 |
| **Total** | **29** | **7** | **175 000** | **0** |

- États : produits 7 actifs ; conteneurs **26 en brouillon** et 3 actifs. Le code veut des conteneurs toujours actifs ; `container_migration.activate_draft_containers` n'a pas été passé en réel.
- Titulaires avec plusieurs conteneurs (même société) : **0**. Plusieurs produits identiques pour un même client : **0**. Au plus 1 produit par client aujourd'hui.
- Produits **sans conteneur** (même titulaire et société) : **2**, `SY/I/000003` (partner 1641) et `SY/I/000004` (partner 1642) → compte à créer à la migration.
- Conteneurs sans produit : 24. Clients sans conteneur : 9 sur 38.
- Conteneur dont l'agence diffère de celle du titulaire : **1**, `MS/I/000003` (id 606), rangé en société BD (Ambanidia) alors que le titulaire RADONANDRIANINA ELISE est à MS (Mahitsy) avec le numéro `MS/000003`. **Ambigu** : à corriger à la main avant migration.
- Ancien format : `SY/IC/000001` (id 349, conteneur « Option A »).
- **Références vers un conteneur** : transactions 0, mouvements de caisse 0, écritures (`account_move.microfinance_savings_account_id`) 0, mais **5 crédits** pointent leur `savings_account_id` (« Compte épargne (prélèvement) ») vers un conteneur :

| Crédit | État | Compte pointé (conteneur) |
|---|---|---|
| AD/000001 | actif | AD/I/000002 |
| MS/000001 | actif | MS/I/000001 |
| MS/000002 | actif | MS/I/000002 |
| MS/000003 | actif | MS/I/000003 |
| MS/000015 | actif | MS/I/000006 |

  C'est déjà un défaut aujourd'hui : la cible d'épargne progressive lit le solde du conteneur (0), et un prélèvement automatique y serait refusé (« Un conteneur ne peut recevoir aucune transaction »).
- Références vers des produits : 8 transactions, 8 mouvements de caisse, 8 écritures, 5 crédits (dont les 5 ci-dessus). Elles ne bougent pas.
- Numéros d'épargne en texte libre : 8 écritures (`name`/`ref`) et 16 lignes d'écriture contiennent un numéro `AGENCE/I|G|T/NNNNNN` ; 0 dans le chatter. Ce sont des **historiques figés**, d'où l'intérêt de conserver les numéros existants (`legacy_number`).
- **FETSEPR** : aucune occurrence dans le code ni dans les modules ; s'il s'agit d'un import externe, il faut m'en donner le format.
- Séquences : `microfinance.partner.account` par société (8), `microfinance.savings.account.I` (3, inutilisées depuis l'Option B), `.G` (2), `microfinance.savings.product` (code produit, global).

## c) Références au modèle dans le code

| Emplacement | Usage | Impact / changement nécessaire |
|---|---|---|
| `microfinance_savings_account.py` | modèle, numérotation, conteneur, `is_container` (13 occurrences), index unique, cron dormance | retirer la logique conteneur et la numérotation `AGENCE/TYPE/N` ; ajouter `account_id` (obligatoire), `rank`, `legacy_number`, numérotation `<compte>-RR` ; libellé UI « Produit d'épargne souscrit » |
| `res_partner.py` (épargne) | création du conteneur à l'enregistrement du client ; `action_view_microfinance_savings` ; **guichet** `search_caisse_clients`, `get_client_accounts_summary` | conteneur → `microfinance.savings.compte` (nom à définir) créé à la 1re souscription **ou** à l'enregistrement du client (D2) ; récapitulatif guichet : renvoyer compte + produits |
| `microfinance_loan_extension.py` | `savings_account_id` (prélèvement), `_get_repayment_surplus_savings_account` (exclut les conteneurs), épargne garantie (somme par produit), bouton « Épargne » | domaine `savings_account_id` → produits ; plus de filtre `is_container` ; le bouton ouvre les produits du client avec création rattachée au compte |
| `microfinance_caisse_mouvement.py` + `microfinance_caisse_repayment_wizards.py` | dépôt/retrait guichet, surplus versé en épargne | inchangés (pointent des produits) ; vérifier qu'un produit sans compte ne peut plus exister |
| `microfinance_savings_transaction.py` | `account_id` → produit, écritures, contrôles | inchangé (le libellé « Compte épargne » devient « Produit d'épargne ») |
| `microfinance_loan_account_extension.py` | compteur et bouton « Comptes épargne » sur le compte crédit | pointer vers le nouveau compte (1) et ses produits |
| `microfinance_dashboard_extension.py` | 2 tuiles (hors conteneurs, lot précédent) | 3 tuiles : comptes (nouveau modèle), produits actifs, encours (f) |
| `container_migration.py` | utilitaires de migration des conteneurs (renommage, doublons, séquences, activation) | obsolète après la scission ; à conserver tant que la migration n'est pas validée, puis retirer |
| `views/microfinance_savings_account_views.xml` | `is_container` (15 occurrences : ruban « Conteneur », boutons masqués, filtre « Masquer les conteneurs »), vues menu verrouillées | retirer `is_container` ; libellés « Produit d'épargne » ; champ compte readonly ; nouvelles vues du compte |
| `views/microfinance_savings_menus.xml` | menus Comptes épargne / Transactions / Balance / Produits | « Comptes épargne » → nouveau modèle ; nouveau menu « Produits d'épargne » |
| `security/ir.model.access.csv` | 5 lignes sur le modèle (agent épargne, manager épargne, manager/finance/auditeur crédit) | mêmes droits sur le nouveau modèle ; création réservée au code (pas de create pour les agents ?) |
| `security/microfinance_company_rules.xml` | règle société sur le modèle | même règle sur le nouveau modèle. **Aucune règle d'isolement par agent** sur l'épargne aujourd'hui (seule la règle société) |
| `report/savings_receipt_report.xml` | 4 rapports QWeb sur le modèle (reçus) | inchangés (produit) ; affichage du numéro de compte en plus |
| `data/ir_cron_data.xml` | capitalisation, dormance | inchangés (produits) |
| `microfinance_loan_management/static/src/js/microfinance_caisse_pos.js` | onglets dépôt/retrait, liste `savings_accounts`, `get_account_transactions` | afficher le compte puis ses produits (champ `account_name` en plus) |
| `microfinance_data_reset_wizard` | supprime transactions et comptes épargne par société | ajouter le nouveau modèle (après les produits) |
| `microfinance_payroll_loan`, `microfinance_load_test`, `microfinance_mowgli_assistant`, `mowgli_payroll_pcec` | aucune référence au modèle | aucun changement |
| `microfinance_transfert_inter_agence` (non installé) | point d'extension épargne prévu, non implémenté | aucun changement |
| Tests | 17 fichiers référencent le modèle ou `is_container` | à adapter (conteneurs → comptes) |

## d) Comptabilité
- Le solde vit sur le produit (`balance` stocké, calculé depuis les transactions `posted`). Chaque transaction comptabilisée génère une écriture, reliée au produit (`account_move.microfinance_savings_account_id`) et à la transaction.
- Les comptes PCEC sont paramétrés **sur le produit d'épargne** (`microfinance.savings.product`) selon le type de client : `account_epargne_individuel/groupe/entreprise_id`, intérêts payés, intérêts d'avance, coût des intérêts, pénalités, commissions, attente chèques, etc. (résolus par `product._get_account('epargne', partner)`).
- **Un compte parent n'a aucun impact comptable** : il agrège des soldes de gestion (somme des produits) sans écriture propre ni compte PCEC. Le plan comptable des établissements de crédit reste porté par les produits. Aucun lettrage, journal ou compte comptable n'est à créer ou déplacer.

## e) Création automatique
- Conteneur : à l'enregistrement du client (`microfinance_context`), en même temps que le compte crédit `microfinance.loan.account` (même N).
- Produits : jamais automatiques. « EP lié au crédit » est un produit (volontaire) que l'agent souscrit à la main, souvent depuis le bouton « Épargne » du crédit (qui préremplit `microfinance_loan_id`). L'avance spéciale ne crée aucune épargne.
- Guichet : dépose et retire sur un produit existant, n'en ouvre jamais.

## f) Dashboard
- Aujourd'hui (lot précédent) : « Comptes épargne actifs (hors conteneurs) » = produits actifs ; « Encours épargne (hors conteneurs) » = somme des soldes des produits.
- Cible : « Comptes épargne actifs » (nouveau modèle, D4), « Produits d'épargne actifs » (produits `state='active'`), « Encours épargne » (somme des produits actifs, égale à la somme des soldes des comptes) ; chacune avec le domaine de son lien.

## g) Plan de migration proposé
**Version 17.0.1.7.0 de `microfinance_savings_management`** (actuelle 17.0.1.6.0).

1. **Pré-requis manuels** (avant `-u`) : corriger le conteneur 606 (`MS/I/000003` rangé en BD) ; trancher les 5 crédits pointant un conteneur (D5).
2. **Code** : nouveau modèle compte + `account_id` (non requis au niveau base pendant la transition, contrainte Python), `rank`, `legacy_number`. `is_container` est conservé en lecture seule le temps de la transition.
3. **post-migrate** (dry-run par défaut, paramètre `microfinance_savings.split_dry_run`, CSV `microfinance_migrations/scission_epargne_<base>_<horodatage>_<dryrun|reel>.csv`), idempotent :
   - a. Pour chaque conteneur : créer le compte (titulaire, société, **nom = nom du conteneur conservé**, `legacy_number` = ce nom), ou réutiliser le compte existant (même titulaire et société).
   - b. Pour chaque produit : rattacher au compte du même titulaire et de la même société ; le créer s'il manque (2 cas SY). Rang = ordre d'ouverture (`opening_date`, puis `id`). Nom du produit **conservé** (`legacy_number` = nom actuel).
   - c. Crédits pointant un conteneur (5) : traitement selon D5 ; jamais deviné.
   - d. Vérifications : nombre de produits, somme des soldes, nombre de transactions et d'écritures identiques avant et après ; aucun produit sans compte.
   - e. Suppression des conteneurs du modèle produit **seulement si** a–d sont tous verts et qu'aucune référence ne pointe encore dessus (sinon : listés, conservés).
4. **Contrainte finale** : `account_id` requis en base (dans une version suivante, ou dans le même post-migrate si 3d et 3e sont verts).
5. **Renumérotation** des noms existants vers `CE/AG/NNNNNN(-RR)` : uniquement via l'assistant dédié, en dry-run, après ton accord (hors migration).

**Rollback** : `pg_dump` avant la montée de version ; la migration ne supprime rien tant que les vérifications ne sont pas toutes vertes, et le CSV liste chaque création ou rattachement.

**Risques** :
- La suppression des conteneurs est irréversible sans dump : elle ne doit pas se faire dans le même passage que la création des comptes tant que tu n'as pas relu le CSV (recommandé : passage réel en deux temps).
- Concurrence sur le rang : contrainte unique `(account_id, rank)` + verrou `SELECT … FOR UPDATE` sur le compte à la souscription.
- Le compte crédit (`microfinance.loan.account`) et le compte épargne partagent aujourd'hui le même N. Avec une séquence `CE/AG/NNNNNN` indépendante, les numéros divergeront (D1).
- Tests : 17 fichiers à adapter, auxquels s'ajoutent les tests du dashboard épargne du lot précédent.

## h) Écarts et décisions à trancher

**D1 — Numéro du compte.** Le prompt demande une séquence par agence `CE/<agence>/NNNNNN`. Aujourd'hui le N du conteneur **est** le numéro permanent du client, partagé avec le compte crédit (`AD/000003` ↔ `AD/I/000003`).
- (a) Séquence propre `CE/AD/NNNNNN` : le N du compte épargne diverge du numéro client et du compte crédit.
- (b) `CE/AD/<N du numéro permanent du client>` : pas de nouvelle séquence, et le même N côté crédit et épargne. Sans trou, puisqu'il y a un compte par client et par agence.
- **Recommandé : (b)**, qui garde un numéro unique par client lisible partout. Le préfixe `CE` reste configurable par société.

**D2 — Création du compte.** Le prompt dit « créé automatiquement à la **première souscription** ». Aujourd'hui, le conteneur est créé **à l'enregistrement du client**.
- (a) À la première souscription seulement : plus de compte vide pour les 24 clients sans produit.
- (b) À l'enregistrement du client, comme aujourd'hui.
- **Recommandé : (a)**, conforme au prompt. Les 24 conteneurs vides deviennent alors des comptes sans produit (statut « ouvert, 0 produit ») ; à la migration, faut-il les créer quand même ou seulement pour les clients ayant au moins un produit ?

**D3 — Noms existants des produits.** « Numéros existants conservés tels quels » : les produits gardent leur nom `AGENCE/I|G/N` et les comptes issus des conteneurs gardent `AGENCE/I/N` (ou `SY/IC/000001`).
- Conteneurs et produits I partagent le **même espace de noms** : par exemple à GY, `GY/I/000001-000002` sont des comptes (anciens conteneurs) et `GY/I/000003-000004` des produits d'autres clients. Il n'y a aucun doublon (la séquence saute les noms pris), mais on ne distingue pas un compte d'un produit à la lecture, et le nom d'un produit ne contient pas celui de son compte.
- Recommandé : migration sans renommer (comme demandé), puis assistant de renumérotation proposé tout de suite après, avec dry-run et CSV, pour éliminer cette confusion.

**D4 — État du compte.** Le nouveau modèle a un état. Proposé : `actif` dès qu'un produit est actif ou dormant, `clôturé` quand tous ses produits sont clôturés, `ouvert` sinon (aucun produit). États **calculés**, jamais saisis. À valider, ainsi que la définition de la tuile « Comptes épargne actifs » (= comptes ayant au moins un produit actif).

**D5 — 5 crédits pointant un conteneur** (AD/000001, MS/000001-003, MS/000015). Le champ cible un produit, pas un compte.
- (a) Le repointer vers **l'unique** produit actif du client dans l'agence s'il y en a exactement un ; sinon le vider et le lister. Aujourd'hui, AD/000001 a 1 produit (AD/I/000012) et les 4 MS n'en ont aucun : ils seraient vidés et listés.
- (b) Les vider tous et les lister.
- **Recommandé : (a).** Point lié : `savings_account_id` (prélèvement) et `microfinance_loan_id` (crédit lié) ne sont pas synchronisés ; ce n'est pas l'objet de ce chantier.

**D6 — Conteneur 606 (`MS/I/000003` en société BD)** : correction manuelle de sa société (BD → MS) avant migration, ou rattachement au compte MS du titulaire par la migration ? **Recommandé : correction manuelle**, journalisée, puisque la migration ne devine jamais.

**D7 — Nom technique du nouveau modèle.** Proposé : `microfinance.savings.compte`. `microfinance.savings.account` est déjà pris par le produit et ne change pas. Ou `microfinance.savings.holder.account`. À choisir.

**D8 — Isolement par agent.** L'épargne n'a **que** la règle société (pas de règle par agent, contrairement au crédit). Le prompt demande des « ir.rule d'isolement alignées sur les modèles actuels » : on recopie la règle société sur le nouveau modèle, sans ajouter d'isolement par agent ? **Recommandé : oui**, l'isolement épargne par agent serait un chantier à part.

**D9 — FETSEPR** : introuvable dans le code et les données. S'il s'agit d'un export ou d'un import externe qui utilise les numéros d'épargne, il faut m'en donner le format pour l'adapter.
