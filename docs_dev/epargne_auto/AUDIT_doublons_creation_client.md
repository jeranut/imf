# AUDIT — « doublons » de comptes épargne à la création d'un client

Date : 2026-09-21 — audit **lecture seule** (aucun correctif, aucun commit, aucune donnée modifiée).
Périmètre : `microfinance_loan_management`, `microfinance_savings_management` (+ balayage de
`microfinance_transfert_inter_agence`, `microfinance_data_reset_wizard`, `microfinance_mowgli_assistant`).
Base interrogée : `MOWGLI` (SELECT seuls, session `default_transaction_read_only=on`).
Reproduction : copie jetable `MOWGLI_audit_tmp` (`pg_dump`/`pg_restore`, rollback, base supprimée ensuite).

## 0. Résumé

1. **Le code ne crée qu'UN compte épargne à l'enregistrement du client** (le « compte principal »).
   Reproduit avec traceback sur BD, SY, session ≠ agence du client, et agence sans produit par défaut :
   1 appel à `create()` du compte, 1 seul appelant. Aucun doublon d'enregistrement du client.
2. **Le 2ᵉ compte est le conteneur `is_container`, créé à la création du 1er crédit** (pas à la
   création du client). Preuve SQL : conteneur SY/I/000002 et crédit SY/000001 ont le même
   `create_date` à la microseconde (2026-09-21 08:53:08.083973), 3 min 18 s après le client.
   C'est le comportement voulu (« Option A » : principal et conteneur coexistent), pas un bug de
   double appel — mais il est perçu comme un doublon et il **casse la règle de numérotation** (§5).
3. **Le « 3 comptes dans les autres agences » et le « 2 dans BD » ne sont pas reproductibles ici** :
   dans `MOWGLI`, les 2 clients BD créés aujourd'hui (1637, 1638) et les 2 du 17/09 ont 1 compte chacun ; une seule paire existe
   (client 1640, SY). Aucun chemin du code de ce dépôt ne peut produire 3 comptes à partir de la
   seule création du client (maximum théorique : 1 principal + 1 conteneur par client et société).
   → voir §6 : la donnée ou le code testé n'est probablement pas celui de cette machine.
4. Il n'existe **aucune contrainte SQL** ni index d'unicité sur `microfinance_savings_account`
   (seulement pkey + FK) : rien n'empêche mécaniquement un vrai doublon.

## 1. Inventaire des points de création de `microfinance.savings.account`

| # | Fichier:ligne | Déclencheur | Garde anti-doublon |
|---|---|---|---|
| 1 | `microfinance_savings_management/models/res_partner.py:59` (dans `_get_or_create_microfinance_savings_principal_account`, appelée l.32 depuis `create()` l.18-33) | `res.partner.create()` avec `context.microfinance_context` et `microfinance_partner_type == 'client'` ; ne fait rien (+ notification bus) si la société du client n'a pas de `microfinance_savings_default_product_id` | Oui, partielle : `search([partner, product])` — **sans filtre société**, sans `is_container`, sans état. Pas de verrou, pas de contrainte SQL |
| 2 | `microfinance_savings_management/models/res_partner.py:87` (dans `_get_or_create_microfinance_savings_container`, appelée l.293 de `microfinance_loan_extension.py`) | `microfinance.loan.create()` (surcharge l.279-294) : pour chaque partenaire des crédits créés, quel que soit son type | Oui : `search([partner, company, is_container=True])`. Pas de contrainte SQL (choix documenté l.71-75, cf. `docs_dev/epargne_exigee_display/AUDIT_LOT0_conteneur_epargne.md`) |
| 3 | `microfinance_savings_management/models/microfinance_savings_account.py:72-86` (`create()` du compte) | N'en crée pas : attribue seulement le nom (`_get_savings_container_name` l.88, `_get_savings_account_name` l.104) | — |
| 4 | UI : bouton « Épargne » du crédit (`microfinance_loan_extension.py:81`, contexte `default_partner_id`/`default_microfinance_loan_id`) et menu Épargne → Nouveau | Création **manuelle** par l'agent (ouvre le formulaire, pas de création automatique) | Aucune (création volontaire) |
| — | `microfinance_loan_management/models/res_partner.py:469` → `:201` et `microfinance_loan.py:393` | Créent le **compte crédit** (`microfinance.loan.account`), pas un compte épargne | `unique(partner_id, company_id)` sur le compte crédit |

Vérifiés et **absents** : `write()` sur `res.partner` ou sur le compte qui créerait un compte
(le `write()` de `res_partner.py` loan_management l.~490 ne crée qu'un dossier de crédit),
`base.automation` (aucune), `ir.actions.server` (2, sans lien épargne : provisions, clôture caisse),
`ir.cron` (capitalisation, dormance, prélèvement auto, pénalités, PAR, provisions — aucun ne crée
de compte), data XML / `post_init_hook` / migrations épargne (comptes PCEC uniquement), JS
caisse (lecture/dépôt/retrait, pas de `create` de compte), wizard RAZ (suppression uniquement),
transfert inter-agences (n'écrit pas de compte épargne : `savings_account_id` y est explicitement
« à ne pas ajouter maintenant »), `onchange`/`compute` (aucun effet de bord d'écriture).
Le garant/conjoint créé par `name_create` (partenaire 1639, type vide) ne déclenche rien : la
condition `microfinance_partner_type == 'client'` l'exclut.

## 2. Causes candidates — verdict pour chacune

| | Hypothèse | Verdict | Preuve |
|---|---|---|---|
| a | `create()` appelé plusieurs fois / `super()` double / logique dupliquée entre les 2 modules | **Écartée** | La surcharge n'existe qu'à `microfinance_savings_management/models/res_partner.py:18` (le module crédit ne connaît pas le modèle épargne). Traceback de repro : 1 seul appel, 1 seul appelant (`res_partner.py:32 → :59`) |
| b | Création dans `create()` ET `write()` | **Écartée** | Aucun `write()` ne crée de compte (§1) |
| c | Boucle sur les sociétés | **Écartée** | Aucune boucle `res.company`/`allowed_company_ids` dans les points de création. Repro : session IS (`env.company=1`) créant un client SY → compte créé sur la société du client (3), pas sur la société de session : `company = self.company_id or self.env.company` (`res_partner.py:48`) |
| d | Conteneur créé à l'enregistrement du client | **Écartée** | Le conteneur n'est créé que par `microfinance.loan.create()` (`microfinance_loan_extension.py:291-293`). Repro : client seul → 0 conteneur ; 1er crédit → 1 conteneur ; 2ᵉ crédit → 0 création |
| e | Boucle sur les produits d'épargne | **Écartée** | Un seul produit par société : `microfinance_savings_default_product_id` (`res_partner.py:49`) |
| f | Double clic / double RPC | **Écartée pour les cas observés** | Journal Odoo : un seul `res.partner/web_save` par client (08:22:41, 08:24:23, 08:49:49, 09:29:14, 09:33:38). Un double envoi *avant* réponse créerait 2 **partenaires**, chacun avec son compte, jamais 2 comptes sur un même partenaire — et l'absence de contrainte SQL ne l'empêcherait pas dans ce cas |
| g | Configuration par agence | **Constatée mais sans effet de duplication** | Produit par défaut renseigné pour IS(35), BD(36), SY(105) seulement ; TA, SB, MA, TS, KA, AD, BM, GY : vide → **0** compte à la création + notification (repro D). Séquences `microfinance.savings.account.I` séparées par société (`res_company._get_or_create_numbering_sequence`) |

**Cause racine confirmée de ce qui est observable** : ce n'est pas un doublon de création, c'est la
coexistence *voulue* de deux enregistrements — principal (à la création du client) et conteneur (au
1er crédit) — plus un défaut de numérotation qui les rend indiscernables (§5).

## 3. Requêtes SQL de vérification (SELECT seulement) et résultats sur `MOWGLI`

```sql
-- Comptes par client de test (portée : tous les clients ; 8 comptes en tout)
select a.id, p.name, a.company_id, a.name, a.is_container, a.product_id, a.state,
       a.microfinance_loan_id, a.create_uid, a.create_date
from microfinance_savings_account a join res_partner p on p.id = a.partner_id
order by a.partner_id, a.id;

-- Portée réelle du problème : partenaires ayant > 1 compte par société
select partner_id, company_id, count(*) n,
       count(*) filter (where is_container) conteneurs,
       count(*) filter (where not is_container) reels
from microfinance_savings_account group by 1,2 having count(*) > 1;

-- Écart de create_date entre comptes d'un même client (même transaction = écart ~0)
select id, partner_id, is_container, create_date,
       create_date - lag(create_date) over (partition by partner_id order by id) ecart
from microfinance_savings_account;

-- Conteneur ↔ crédit : même transaction ?
select a.id, a.create_date, l.name, l.create_date
from microfinance_savings_account a join microfinance_loan l
  on l.partner_id = a.partner_id and l.company_id = a.company_id
 and l.create_date = a.create_date
where a.is_container;

-- Produits épargne par agence (il n'y a pas de flag « création automatique » : c'est
-- res_company.microfinance_savings_default_product_id)
select c.id, c.agency_code, c.microfinance_savings_default_product_id
from res_company c order by c.id;
```

Résultats :

| Client | Agence | Comptes | Détail |
|---|---|---|---|
| 1637 JIRA Fetsy, 1638 Rakoto (créés par uid 2) | BD | 1 chacun | `BD/I/000004`, `BD/I/000005`, produit 36, brouillon |
| 1161, 1164 | BD | 1 chacun | `BD/I/000001-2`, actifs |
| 1641 Andrianantenaina, 1642 RAKOTONDRABE (uid 2) | SY | 1 chacun | `SY/I/000003-4`, produit 105, actifs |
| **1640 RANDRIANARIVO ELIO** (uid 8) | SY | **2** | 348 `SY/I/000001` réel, produit 105, **08:49:49.763232** ; 349 `SY/I/000002` conteneur, **08:53:08.083973** = `create_date` du crédit 745 `SY/000001`. Écart 3 min 18 s → transactions séparées |

Portée : 1 seul couple partenaire/société avec > 1 compte (celui d'ELIO) ; 1 conteneur au total.
Sociétés : 11 ; produit par défaut renseigné sur 3 seulement (IS, BD, SY). Utilisateurs de test
2 et 8 ont tous deux `company_id = 1` (Isotry) comme société par défaut : `env.company` de leur
session peut différer de l'agence du client, ce qui est correctement géré (repro C).

## 4. Reproduction instrumentée (copie jetable, rollback)

`create()` du compte enveloppé pour journaliser la pile d'appel ; utilisateur 2, `microfinance_context=True`.

| Cas | env.company | société client | Appels `create()` compte | Appelant | Comptes obtenus |
|---|---|---|---|---|---|
| A client BD | 2 | 2 | 1 | `res_partner.py:32 → :59` (principal) | `BD/I/…` produit 36 |
| B client SY | 3 | 3 | 1 | idem | `SY/I/…` produit 105 |
| C client SY, session IS | 1 | 3 | 1 | idem | société 3, produit 105 |
| D client TA (pas de produit défaut) | 4 | 4 | 0 | — | aucun (+ notification) |
| E 1er crédit du client B | 3 | 3 | 1 | `microfinance_loan_extension.py:293 → res_partner.py:87` (conteneur) | 1 réel + 1 conteneur |
| F 2ᵉ crédit | 3 | 3 | 0 | — | inchangé |

Aucun cas ne produit plus de 2 comptes. Script : non conservé dans le dépôt (scratchpad de session) ;
la base jetable et le filestore de copie ont été supprimés.

## 5. Règle attendue vs comportement actuel

| Règle métier | Comportement actuel | Écart |
|---|---|---|
| 1 compte épargne par client à la création | 1 compte réel (produit par défaut de l'agence), **si** le produit est configuré ; sinon 0 + notification | Conforme. Le compte reste en **brouillon** jusqu'à `action_activate` manuel (BD 346/347 : brouillon ; SY : activés à la main) |
| Conteneur uniquement au 1er crédit | Conforme (`microfinance_loan_extension.py:291`) | Aucun |
| Numéro du conteneur synchronisé avec le crédit (`AGENCE/I/<suffixe du compte client>`) | **Non respecté dès que le suffixe est déjà pris** : `_get_savings_container_name` (`microfinance_savings_account.py:88-102`) retombe sur la séquence `I` si `SY/I/000001` existe | **Bug de numérotation prouvé** : crédit `SY/000001`, conteneur `SY/I/000002` (attendu `SY/I/000001`) |

Mécanisme : le compte réel et le conteneur puisent dans le **même espace de noms `AGENCE/I/NNNNNN`**
— le réel via la séquence `microfinance.savings.account.I` (`:119-124`), le conteneur via le suffixe
du numéro client (`:97-100`). Pour le 1er client d'une agence les deux valent `000001` : le réel
(créé en premier, à l'enregistrement) prend le nom, le conteneur est rejeté. Pour les clients
suivants la collision est aléatoire (ex. futur conteneur de Feno `SY/000002` → `SY/I/000002`,
déjà pris par le conteneur d'ELIO). Le test `test_container_number_synchronized_with_loan_account`
ne le voit pas : il crée le partenaire **hors** `microfinance_context`, donc sans compte principal.

## 6. Différence « BD (2) vs autres agences (3) » — ce qui est établi et ce qui ne l'est pas

- **Établi** : 2 = compte principal + conteneur du 1er crédit (cas ELIO, SY). C'est le maximum que
  le code de ce dépôt génère pour un client et une société. Aucune dépendance à la société : la
  logique est identique pour toutes les agences ; seule la présence du produit par défaut varie
  (IS/BD/SY oui, 8 autres agences non → 0 compte à la création).
- **Non établi** : le « 3 ». Rien dans ce dépôt ni dans la base `MOWGLI` ne le produit. Pistes à
  vérifier **là où le test a eu lieu**, dans cet ordre :
  1. La base/serveur testé est-il `MOWGLI` sur cette machine ? Je n'ai pas pu joindre « rotas »
     (aucune entrée SSH/hosts ; ce poste est `srv1092944`). Comparer sur rotas :
     `git -C <addons> status --short`, `git -C <addons> diff --stat origin/main`, et
     `md5sum microfinance_savings_management/models/{res_partner,microfinance_loan_extension,microfinance_savings_account}.py microfinance_loan_management/models/{res_partner,microfinance_loan}.py`
     (ici : les 3 fichiers épargne sont identiques au commit `6d105af`, non modifiés).
  2. Un 3ᵉ compte créé **à la main** (menu Épargne / bouton « Épargne » du crédit, point 4 du §1)
     — le seul chemin sans garde qui ajoute un compte réel.
  3. Un code absent de `origin/main` sur rotas (hook, automated action, module non versionné).
  4. Exécuter, sur la base testée, la requête « portée » et la requête d'écart de `create_date`
     du §3 : un écart ~0 = même transaction (boucle interne), des minutes = créations séparées,
     `create_uid` = un utilisateur → manuel.

## 7. Écarts et incohérences relevés (non corrigés)

- `microfinance_loan_extension.py:295` : `return True` mort après `return loans`.
- `res_company.py` (savings) : l'aide du champ décrit une ouverture « à la création de son premier
  dossier d'instruction de crédit » ; le code l'ouvre à la création du client (docstring l.19-27
  de `res_partner.py`). Le champ d'aide induit en erreur.
- `_get_or_create_microfinance_savings_principal_account` cherche par `(partner, product)` **sans
  société** : sous règle multi-société, une recherche depuis une session d'une autre agence ne voit
  pas les comptes cachés, et un même client transféré d'agence peut se voir rouvrir un compte.
- Numéro `BD/I/000003` absent alors que 000001-2-4-5 existent : séquence consommée sans compte
  (séquences Postgres non transactionnelles, ou compte supprimé par RAZ). Non élucidé.

## 8. Options de correctif (non appliquées)

| Option | Effet | Risques / coûts |
|---|---|---|
| **A. Corriger la numérotation du conteneur** (recommandée en 1er) : réserver au conteneur l'espace `AGENCE/I/<suffixe client>` en faisant sauter cette valeur par la séquence des comptes réels (`_get_next_available_savings_account_name` saute déjà les noms existants, mais pas ceux qui **seront** pris), ou donner au conteneur un code de type distinct | Règle « numéro synchronisé » tenue ; supprime l'ambiguïté visuelle | Changement de format de nom si code distinct ; renommer les conteneurs existants (1 en base ici) ; adapter `test_container_number_synchronized_*` pour tester avec `microfinance_context` |
| **B. Garde d'idempotence renforcée** sur le principal : chercher `(partner, company, is_container=False)` et le `product` ; verrouiller (`SELECT … FOR UPDATE` sur le partenaire ou `pg_advisory_xact_lock`) | Couvre la course de 2 RPC concurrents et le cas « client sur plusieurs sociétés » | Faible ; ne traite pas les créations manuelles |
| **C. Contrainte SQL unique partielle** `(partner_id, company_id) WHERE is_container` (conteneur) et, si voulu, `(partner_id, company_id, product_id) WHERE NOT is_container AND state != 'closed'` | Garantie en base, quelle que soit l'origine | Migration : `CREATE UNIQUE INDEX` échoue s'il existe déjà des doublons → dry-run §9 **avant** ; la 2ᵉ contrainte interdit deux comptes réels sur le même produit (déjà permis aujourd'hui, à valider métier) ; écart assumé avec le choix documenté l.71-75 |
| **D. Supprimer le point de création redondant** | — | **Aucun point redondant trouvé** : principal et conteneur ont des rôles distincts. Supprimer l'un contredit la décision « Option A ». À ne faire que si le métier tranche « un seul enregistrement » : alors abandonner le principal ou le conteneur, avec migration des soldes/transactions |
| **E. Rendre le brouillon explicite** (activer à la création ou masquer les comptes en brouillon sans solde) | Réduit la perception de « compte en trop » | Décision métier (dépôt minimal d'ouverture) |

## 9. Impact sur l'existant — dry-run (SELECT seulement, à exécuter sur chaque base, y compris prod)

```sql
-- 9.1 Vrais doublons à traiter : même client, même société, même produit, non clôturé
select partner_id, company_id, product_id, array_agg(id order by id) ids, count(*)
from microfinance_savings_account
where not is_container and state != 'closed'
group by 1,2,3 having count(*) > 1;

-- 9.2 Conteneurs multiples pour un même client/société (bloquerait l'index partiel de C)
select partner_id, company_id, array_agg(id order by id) ids, count(*)
from microfinance_savings_account where is_container
group by 1,2 having count(*) > 1;

-- 9.3 Doublons « fusionnables » : sans transaction ni solde (supprimables sans perte)
select a.id, a.name, a.partner_id
from microfinance_savings_account a
where not exists (select 1 from microfinance_savings_transaction t where t.account_id = a.id)
  and a.partner_id in (select partner_id from microfinance_savings_account
                       where not is_container group by partner_id, company_id, product_id having count(*) > 1);

-- 9.4 Conteneurs dont le numéro n'est pas synchronisé avec le compte crédit (option A)
select a.id, a.name conteneur, la.name compte_credit
from microfinance_savings_account a
join microfinance_loan_account la on la.partner_id = a.partner_id and la.company_id = a.company_id
where a.is_container
  and a.name != split_part(la.name,'/',1) || '/I/' || split_part(la.name,'/',2);
```

Résultat sur `MOWGLI` : 9.1 → 0 ligne ; 9.2 → 0 ; 9.3 → 0 doublon ; 9.4 → **1 ligne** (conteneur 349
`SY/I/000002` vs compte crédit `SY/000001`). **Aucun compte n'est à fusionner ni supprimer** dans
`MOWGLI` : le seul cas à corriger est le renommage du conteneur 349 (option A), à faire par script
dédié, avec sauvegarde préalable et redémarrage puis `-u` selon l'ordre de déploiement habituel.

## 10. État du dépôt (signal demandé)

Ce poste (`/opt/odoo17_2/custom_addons`, branche `main`, 1 commit d'avance sur `origin/main`) a
**41 entrées non commitées** (`git status`) : `microfinance_loan_management` modifié (dont
`models/res_partner.py` : garde CIN inter-agences, `res_company.py` : société mère/fonds partagés,
`microfinance_loan.py`), fichiers non suivis (`microfinance_fond_partage.py`,
`microfinance_fond_allocation.py`, `microfinance_fond_parent_mixin.py`, tests, vues, 2 dossiers
`docs_dev/…`). Rien de ce delta ne touche la création de compte épargne (les 2 tests épargne
modifiés ajoutent seulement un CIN, requis par la nouvelle garde). Le serveur `odoo17_2` (démarré
08:14) exécute cet arbre de travail. Je n'ai pas pu comparer avec rotas (inaccessible d'ici).

---

## 11. Correctif appliqué (Option A validée) — 2026-09-21

**Aucun commit** : diff à relire. Tout est dans `microfinance_savings_management` ; aucun fichier du
module crédit (garde CIN, société mère, fonds partagés) n'est touché. Version du manifeste
17.0.1.3.0 → **17.0.1.4.0**.

### Règle de nommage

| Objet | Format | Source du numéro |
|---|---|---|
| Compte réel (inchangé, jamais renuméroté) | `AGENCE/I|G|T/NNNNNN` | séquence par type et par société |
| **Conteneur** | `AGENCE/IC/<numéro>` | suffixe du **compte crédit** du client pour la société (ex. compte crédit `SY/000012` → `SY/IC/000012`) ; aucun appel à une séquence |

Choix d'interprétation à confirmer : « numéro du crédit » = numéro du **compte crédit**
(`microfinance.loan.account`, unique par client et par société), pas celui d'un crédit
individuel (`microfinance.loan.name`, séquence propre à chaque crédit, différent du compte crédit :
constaté en repro, crédit `SY/000003` pour compte crédit `SY/000006`). C'est la seule source qui a la
même cardinalité que le conteneur. Repli : numéro de compte permanent du client si aucun compte
crédit n'existe. Nom cible déjà pris → `ValidationError` explicite (plus de suffixe silencieux).

### Règle de cardinalité vérifiée dans le code

**1 conteneur par client ET par société** (pas par crédit) : la garde existante cherchait
`(partner, company, is_container)`, le test `test_second_loan_does_not_create_second_container`
l'impose, et le compte crédit est `unique(partner_id, company_id)`.

### Fichiers modifiés

| Fichier | Changement |
|---|---|
| `models/microfinance_savings_account.py` | nom du conteneur `AGENCE/IC/…` (`_get_container_sync_source`, `_build_container_name`, `_get_savings_container_name` avec erreurs explicites) ; `init()` pose l'index unique partiel `microfinance_savings_account_container_uniq_idx` sur `(partner_id, company_id) WHERE is_container`, **seulement si 0 doublon** (sinon warning journalisé avec les ids, rien posé) ; commentaires corrigés |
| `models/res_partner.py` | garde du compte principal : compte réel non clôturé pour partner + **company** ⇒ réutilisé ; garde du conteneur : réutilisation par partner + company + rattrapage d'un `IntegrityError` (création concurrente) ; paramètre `company` |
| `models/microfinance_loan_extension.py` | conteneur créé dans la société du **compte crédit / du crédit** (plus de `env.company`), un appel par couple client/société ; `return True` mort supprimé |
| `models/res_company.py` | aide du champ « Produit d'épargne par défaut » corrigée (ouverture à la création de la fiche client, plus « au premier dossier de crédit ») |
| `container_migration.py` (nouveau) | logique de renommage (dry-run par défaut, CSV, contrôle des références texte) |
| `migrations/17.0.1.4.0/post-migration.py` (nouveau) | appelle la logique ci-dessus ; en dry-run, une erreur est journalisée sans bloquer la mise à jour |
| `tests/common.py`, `tests/__init__.py`, `tests/test_savings_container_creation.py` | helper `_create_context_client` ; test existant corrigé (client **avec** `microfinance_context`, attente `AGENCE/IC/…`) |
| `tests/test_savings_container_numbering.py`, `tests/test_savings_container_migration.py` (nouveaux) | 8 + 5 tests, voir ci-dessous |

Écarts par rapport à la demande, à valider :
- Pas d'état `cancelled` sur ce modèle (états : brouillon / actif / dormant / clôturé) : l'index est
  filtré sur `WHERE is_container` seul (un conteneur ne peut être ni activé ni clôturé) ; la garde du
  compte principal exclut l'état `closed`.
- Garde du compte principal : **n'importe quel** compte réel non clôturé du client dans la société
  bloque la création (et non seulement un compte sur le produit par défaut) ; ne change rien en
  pratique, la méthode n'étant appelée qu'à la création de la fiche.
- Index unique **non posé** sur les comptes réels (un client peut en avoir plusieurs).
- `sudo()` : uniquement sur 3 recherches de lecture (garde du principal, garde du conteneur,
  unicité du nom) et sur les recherches de références texte de la migration ; jamais global.

### Migration (`post-migration`, idempotente)

- Cible : `is_container = True` dont le nom ≠ `AGENCE/IC/<compte crédit>` ; toutes sociétés ; seul
  champ écrit : `name` du conteneur (le suivi du champ laisse une ligne de chatter « ancien → nouveau »,
  vérifié). Aucun compte réel, montant, journal ni écriture touché.
- Paramètre système `microfinance_savings.migration_dry_run` : **créé à `True`** s'il est absent ;
  seul `False`/`0`/`no`/`non`/`f` autorise le renommage.
- Références en texte libre (`account.move` name/ref/payment_reference/narration, `account.move.line`,
  `mail.message` d'autres documents, `ir.sequence`, transactions épargne) : si l'ancien nom y figure,
  le conteneur **n'est pas renommé** (jamais de modification d'une écriture comptable) et le cas est
  consigné `IGNORE_REFERENCES_TEXTE` dans le CSV. Autres statuts : `IGNORE_NOM_EXISTANT`,
  `IGNORE_CIBLE_EN_DOUBLE`, `IGNORE_SOURCE_INTROUVABLE`.
- Trace : CSV `renommage_conteneurs_epargne_<base>_<horodatage>_<dryrun|reel>.csv` (colonnes id ;
  ancien_nom ; nouveau_nom ; credit_lie ; societe ; statut ; detail) dans
  `<dossier du logfile>/microfinance_migrations/` (paramètre facultatif
  `microfinance_savings.migration_log_dir` pour changer de dossier ; sur ce serveur :
  `/opt/odoo17_2/odoo/microfinance_migrations/`, propriétaire `odoo17_2`) + total dans le journal
  Odoo. En mode réel, le renommage est **refusé** si le CSV ne peut pas être écrit. Un fichier est
  aussi écrit pour une exécution annulée (rollback) : il atteste alors d'un plan, pas d'un résultat.
- **Le script ne se rejoue pas tout seul** au `-u` suivant (même version). Après bascule du paramètre
  à `False` par Micka :
  ```
  odoo-bin shell -c odoo.conf -d MOWGLI
  >>> from odoo.addons.microfinance_savings_management.container_migration import rename_misnumbered_containers
  >>> rename_misnumbered_containers(env); env.cr.commit()
  ```
  (ou basculer le paramètre AVANT le `-u` : la migration renomme alors directement.)
- Ordre de déploiement habituel : sauvegarde, redémarrage du service, puis `-u microfinance_savings_management`.

### Tests

Copie jetable de MOWGLI, `-u microfinance_savings_management --test-enable`, classes concernées
(41 tests : 28 existants + 13 nouveaux) : **39 OK, 2 échecs identiques à l'état de référence mesuré
avant toute modification** (`test_different_type_code_gets_its_own_sequence` : séquence G déjà
avancée par les données réelles ; `test_no_default_product_configured_skips_silently_at_creation` :
la société 1 a déjà un produit par défaut dans les données réelles) — non liés à ce correctif, non
corrigés. Les autres suites du module n'ont pas été relancées.

Nouveaux tests : client créé avec `microfinance_context` → 1 compte principal, 1er crédit → 1
conteneur `AGENCE/IC/<n° compte crédit>` ; collision forcée avec `AGENCE/I/<même suffixe>` sans
effet ; nom cible occupé → `ValidationError` ; idempotence du principal et du conteneur (2ᵉ appel,
2ᵉ crédit) ; principal clôturé ignoré par la garde ; société du conteneur = société cible, pas la
session ; index unique partiel refuse un 2ᵉ conteneur mais pas plusieurs comptes réels ; migration :
dry-run ne change rien et écrit le CSV, exécution réelle renomme le conteneur seul, relance sans
effet, nom cible occupé et référence texte signalés sans renommer, paramètre dry-run par défaut.
Je n'ai pas fait de test de mutation sur le code ancien : la collision est en revanche attestée
sur données réelles (§3) et le dry-run ci-dessous.

### Résultat du dry-run sur copie de MOWGLI (base jetable supprimée ensuite)

| | Résultat |
|---|---|
| Conteneurs en base / non conformes | 1 / 1 |
| Renommages proposés | **349 : `SY/I/000002` → `SY/IC/000001`** (crédit lié : compte crédit `SY/000001`, société CEFOR Ampitatafika) — statut `A_RENOMMER` |
| Violations de l'index unique | **0** (index posé sur la copie ; 0 groupe partner/société avec > 1 conteneur) |
| Références textuelles à `SY/I/000002` | **0** (contrôle de la migration + recomptage SQL direct sur MOWGLI : `account.move` name/ref/payment_reference, `account.move.line`, `mail.message` body/subject, `ir.sequence`, notes de transactions) |
| Exécution réelle sur la copie (paramètre `False`) | conteneur 349 renommé `SY/IC/000001` ; 2ᵉ exécution : 0 ligne ; compte réel 348 `SY/I/000001` inchangé ; 0 transaction, état/solde inchangés |
| Base réelle MOWGLI | **non modifiée** : index absent, conteneur 349 toujours `SY/I/000002`, paramètre non créé |

À la prochaine mise à jour du module sur MOWGLI : l'index sera posé (0 violation attendue), le
paramètre créé à `True`, et le CSV de dry-run écrit ; aucun nom ne change tant que Micka n'a pas
basculé le paramètre.

---

## 12. Déploiement sur MOWGLI — 2026-09-21 (à la demande de Micka : déploiement + renommage réel)

| Étape | Résultat |
|---|---|
| Sauvegarde | `/opt/odoo17_2/backups/MOWGLI_avant_conteneurs_IC_20260921_144317.dump` (15,3 Mo, lisible par `pg_restore -l`) |
| Redémarrage `odoo17_2` puis `-u microfinance_savings_management` | OK, module 17.0.1.4.0, aucune erreur (log : `/opt/odoo17_2/odoo/update_conteneurs_20260921_144317.log`) |
| Migration en dry-run (paramètre créé à `True`) | 1 conteneur non conforme : `349 SY/I/000002 → SY/IC/000001`, statut `A_RENOMMER` (CSV `…_144413_dryrun.csv`) |
| Index unique partiel | posé sur la base réelle (0 violation) |
| Paramètre `microfinance_savings.migration_dry_run` | basculé à **`False`** |
| Renommage réel (commit explicite) | conteneur 349 → **`SY/IC/000001`** ; message de suivi 14:45:24 « SY/I/000002 → SY/IC/000001 » ; 2ᵉ exécution : 0 ligne |
| Inchangés | compte réel 348 `SY/I/000001` (actif), 350, 351 ; 0 transaction ; état du conteneur toujours brouillon |

Dossier des traces : `/opt/odoo17_2/odoo/microfinance_migrations/`.

**Incident sur la trace CSV (corrigé)** : la 1ʳᵉ exécution réelle et la 2ᵉ (vérification d'idempotence)
ont eu lieu dans la même seconde et le 2ᵉ fichier a **écrasé** le CSV du renommage
(`…_144524_reel.csv` ne contient plus que l'en-tête). Le renommage lui-même est attesté par le
journal Odoo (`update_conteneurs_reel_20260921_144317.log`, ligne « RÉEL : 1 conteneur(s)… {'RENOMME': 1} »)
et par le message de suivi du conteneur. J'ai écrit `…_144524_reel_reconstitue.csv`, **reconstitué à la
main** (et signalé comme tel dans sa colonne `detail`), à partir de la sortie de la commande. Correctif
de code : `_prepare_csv` crée désormais le fichier en mode exclusif (suffixe `_1`, `_2`… si le nom existe) ;
test de non-régression `test_two_runs_never_overwrite_each_others_trace` ; 25 tests des classes
conteneur/numérotation/migration passent sur copie jetable. Ce correctif n'a pas eu à être redéployé
(`container_migration.py` n'est chargé que par la migration et la commande shell) ; il sera actif au
prochain import du module.

Le service `odoo17_2` a été redémarré avant la mise à jour, pas après : il tourne avec le code déjà
présent sur disque à ce moment-là ; aucun autre redémarrage nécessaire pour ce correctif.

---

## 13. Étape 0 — Confirmation du modèle avant codage (2026-09-24)

**Lecture seule, aucune donnée ni aucun code modifié.** Demande initiale de Micka : implémenter deux
compteurs indépendants par agence (COMPTES / CRÉDITS), un conteneur crédit+épargne créé en couple à
l'enregistrement du client (`IS/N` + `IS/I/N`), plus de « compte principal » séparé, et un crédit
(1er compris) numéroté `IS/M` sans jamais recréer de conteneur.

**Verdict : le modèle réel diffère du CONTEXTE fourni sur des points structurants. Je m'arrête ici,
sans coder, conformément à la consigne.** Deux causes à ce décalage :

1. Le CONTEXTE décrit l'état du code **avant** le correctif « Option A » (§11-12 ci-dessus), déjà
   **appliqué et déployé en production sur MOWGLI** le 2026-09-21 (sauvegarde, `-u`, renommage réel
   du conteneur ELIO en `SY/IC/000001`). Ce correctif a changé la règle de nommage du conteneur
   épargne, mais **n'a pas supprimé** le « compte principal » séparé — au contraire, l'audit de
   l'époque l'a explicitement validé comme voulu (« Option A : le compte principal et le conteneur
   coexistent »). La nouvelle règle de Micka (« plus de compte principal séparé ») **contredit
   directement cette décision déjà en production**.
2. Il existe, en plus du conteneur épargne (`microfinance.savings.account.is_container`), un
   **second conteneur** que le CONTEXTE ne mentionne pas du tout : `microfinance.loan.account`
   (« Compte crédit »), créé lui aussi à l'enregistrement du client, avec exactement la cardinalité
   demandée pour le futur conteneur crédit `IS/N` (1 par client et >par société, nom dérivé du numéro
   de compte permanent du client). Une partie de ce que Micka demande (le conteneur crédit `IS/N`)
   **existe donc déjà**, sous un autre nom et un mécanisme légèrement différent (dérivation directe
   du numéro permanent plutôt que tirage direct d'un compteur COMPTES au moment du couple).

### Réponses aux questions posées

**Quels modèles portent le conteneur crédit `IS/N` et le conteneur épargne `IS/I/N` ? `is_container`
existe-t-il sur les deux ?**

- Conteneur crédit ≈ `microfinance.loan.account` (`microfinance_loan_management/models/
  microfinance_loan_account.py`) : modèle dédié, **pas de champ `is_container`** (ce n'est pas le
  même modèle que les crédits eux-mêmes — `microfinance.loan`). Contrainte SQL
  `unique(partner_id, company_id)`. `name` = `partner.microfinance_account_number` tant que ce nom
  est libre (sinon repli sur une séquence indépendante `microfinance.loan.account`, cas résiduel).
  Créé à l'enregistrement du client (`res_partner.py:469`, dans `microfinance_context`) **et**
  paresseusement au premier crédit d'un client préexistant (`microfinance_loan.py:393`).
- Conteneur épargne = `microfinance.savings.account` avec `is_container=True` (même modèle que les
  comptes réels, distingué par ce booléen — `is_container` **n'existe que sur ce modèle**, pas sur
  `microfinance.loan.account`). Créé au **1er crédit** (`microfinance_loan_extension.py:279-294`),
  jamais à l'enregistrement du client. Nom dérivé (aucune séquence propre) :
  `AGENCE/IC/<suffixe du compte crédit>` — **pas** `AGENCE/I/N` comme le veut la nouvelle règle
  (lettre `IC` introduite par le correctif §11, à distinguer de `I` = type de produit épargne
  volontaire sur les comptes réels).
- **Un troisième objet** existe indépendamment de ces deux conteneurs : le « compte principal »
  (`microfinance.savings.account`, `is_container=False`), un compte épargne **réel** sur le produit
  par défaut de l'agence, créé lui aussi à l'enregistrement du client
  (`res_partner.py:19-35, 37-71`). C'est lui que la nouvelle règle supprime explicitement.

**Où le N du conteneur est-il stocké après l'enregistrement du client ?**

- Le N du conteneur crédit est le suffixe de `res.partner.microfinance_account_number`
  (`AGENCE/N`, format stocké tel quel sur le partenaire, attribué une seule fois via
  `_assign_microfinance_account_number()`, séquence `ir.sequence` code
  `microfinance.partner.account`, par société — déjà l'équivalent du futur compteur **COMPTES**,
  mais aujourd'hui il ne numérote QUE ce champ, pas encore les « autres produits d'épargne » de la
  règle 4). Le nom du conteneur crédit (`microfinance.loan.account.name`) et celui du conteneur
  épargne (`microfinance.savings.account.name` du conteneur) sont tous deux **dérivés** de ce champ
  à la création, jamais stockés comme un N indépendant sur le partenaire lui-même.
- Proposition (si la règle validée est confirmée telle quelle) : garder le stockage sur le
  partenaire, mais lui donner directement le rôle de compteur — c'est-à-dire ne plus faire des deux
  conteneurs des objets à nom dérivé d'un troisième champ, mais les créer **ensemble**, dans la
  transaction de couple, à partir d'un seul tirage du compteur COMPTES ; `microfinance_account_number`
  peut alors soit disparaître (remplacé par le nom du conteneur crédit `microfinance.loan.account`,
  qui porte déjà ce rôle), soit rester comme alias en lecture seule pointant vers ce nom — à trancher
  avec Micka, car `microfinance_account_number` est déjà référencé ailleurs (recherche caisse
  `search_caisse_clients`, numérotation du compte crédit, tests) et le faire disparaître a un rayon
  d'impact plus large que ce chantier.

**Quel est le lien actuel entre un crédit et son « EP lié au crédit » ? Comment garantir qu'il ne
pointe que vers l'épargne du conteneur ?**

- Lien actuel : `microfinance.savings.account.microfinance_loan_id` (« Crédit lié »), renseigné
  **manuellement** par l'agent (bouton « Épargne » du crédit, ou menu Épargne → Nouveau avec
  `default_microfinance_loan_id`) — **aucune automatisation ne le pose**. Il ne peut aujourd'hui
  pointer que vers un compte **réel** (`is_container=False`) : un conteneur ne peut recevoir ni
  produit, ni solde, ni transaction (`_create_transaction` lève une erreur si `is_container`), donc
  il ne peut techniquement pas remplir aujourd'hui le rôle d'« épargne liée au crédit » que la
  nouvelle règle 3 lui donne.
- **Contradiction de fond à trancher avant de coder** : la règle 3 demande que le conteneur `IS/I/N`
  *soit* l'épargne liée au crédit (recevable, avec produit et solde), alors que le modèle actuel fait
  du conteneur un enregistrement **volontairement vide**, jamais transactable, par construction et
  par décision documentée (`docs_dev/epargne_exigee_display/AUDIT_LOT0_conteneur_epargne.md`). Deux
  options, à trancher avec Micka avant l'étape 1 :
  - **Option 1** : le conteneur `IS/I/N` devient un compte transactable comme un compte réel (produit
    obligatoire dès sa création, ou attribué au premier rattachement) — remet en cause l'invariant
    « conteneur = jamais de produit/solde/transaction » posé par un chantier antérieur, avec impact
    sur `_check_product_required_unless_container`, `action_activate`/`action_close`,
    `_create_transaction`, et tous les tests qui vérifient qu'un conteneur ne peut pas transiger.
  - **Option 2** : le conteneur reste un coquille vide comme aujourd'hui, et « l'épargne liée au
    crédit » devient un compte réel **distinct**, automatiquement créé et rattaché au conteneur (=
    normalement le tout premier compte réel du client, celui qui remplaçait le « compte principal »)
    — se rapproche le plus de l'esprit du CONTEXTE (« Le compte principal et le conteneur sont la
    même chose ») en gardant la séparation technique conteneur/compte réel, mais alors le champ
    `is_container` change de sens (ce n'est plus littéralement `IS/I/N` qui reçoit les fonds).
  Contrainte demandée en 1.e (« l'épargne liée au crédit ne peut pointer que vers l'épargne du
  conteneur du client ») n'a de sens univoque que si l'option est tranchée : dans l'option 1 c'est
  une simple validation `microfinance_loan_id.savings_account_id == conteneur du partner` ; dans
  l'option 2 il faut définir formellement lequel des comptes réels du conteneur est « celui du
  conteneur » (par exemple : premier compte réel créé pour ce partner+société, marqué explicitement).

**Quels champs, contraintes, vues, séquences et tests dépendent de la création du conteneur au 1er
crédit et de la séquence unique actuelle ?**

- Séquences : `microfinance.partner.account` (numéro permanent, par société) ;
  `microfinance.loan.account` (repli résiduel du compte crédit) ; `microfinance.loan.agency`
  (numérotation de **chaque** crédit — **déjà** ce que la règle 2 demande pour le futur compteur
  CRÉDITS : tous clients confondus, par société, jamais réutilisé pour un conteneur) ;
  `microfinance.savings.account.I` / `.G` / `.T` (comptes épargne réels, par type de produit et par
  société — c'est l'espace que la règle 4 veut faire partager avec le compteur COMPTES). Toutes en
  implémentation standard (`_get_or_create_numbering_sequence`, `ir.sequence` par défaut = séquence
  Postgres atomique) : le point 1.a de la demande (implémentation « standard », pas « no_gap ») est
  déjà satisfait, rien à changer sur ce plan.
- Contraintes : `microfinance_loan_account.partner_company_unique` (`unique(partner_id, company_id)`
  sur le conteneur crédit) ; index partiel `microfinance_savings_account_container_uniq_idx`
  (`(partner_id, company_id) WHERE is_container`, posé conditionnellement par `init()`) ;
  `_check_product_required_unless_container` ; `_check_microfinance_loan_partner_match` ; aucune
  contrainte n'impose aujourd'hui qu'un seul compte réel par client soit « lié au crédit » (rule 3
  citée plus haut, non garantie).
- Vues/actions dépendantes du nommage `IC/` et du déclenchement au 1er crédit : formulaire crédit
  (bouton Épargne, `default_microfinance_loan_id`), `action_view_microfinance_savings`,
  `action_view_microfinance_loan_account`, guichet (`get_client_accounts_summary`,
  `search_caisse_clients` sur `microfinance_account_number`).
- Tests : `test_savings_container_creation.py`, `test_savings_container_numbering.py` (numérotation
  `IC/`), `test_savings_container_migration.py` (migration du renommage `I/000002 → IC/000001`,
  **désormais obsolète** si le format cible change encore), `test_savings_account_container.py`,
  `test_loan_account.py` (création du conteneur crédit à l'enregistrement, contrainte d'unicité). Le
  fichier `container_migration.py` et sa migration `17.0.1.4.0` (§11-12) sont eux aussi entièrement
  bâtis sur le format `IC/` : les réutiliser ou les remplacer est une décision à prendre explicitement
  (ce sont des livrables déjà déployés en prod, pas du code mort).

**Le champ de recherche « compte » filtre-t-il sur le bon modèle ? Le scénario de coexistence (règle
7) fonctionne-t-il déjà ?**

- Il n'existe pas de champ de recherche unique nommé « compte » couvrant à la fois le conteneur
  crédit et les produits de crédit individuels. `search_caisse_clients` (guichet) cherche sur
  `res.partner.microfinance_account_number` (= nom du conteneur crédit) OU sur le nom du client :
  il ne peut aujourd'hui **pas** renvoyer un produit de crédit individuel (`microfinance.loan.name`,
  séquence `microfinance.loan.agency`), donc la coexistence décrite en règle 7 (numéro de conteneur
  d'un client = numéro de produit de crédit d'un autre) **n'est pas testable en l'état** : il n'y a
  actuellement aucun champ de recherche qui mélangerait les deux espaces de noms, donc aucun risque
  actuel de collision visible — mais aussi aucune garantie que ce restera vrai une fois `IS/M` et
  `IS/N` construits avec des compteurs qui peuvent produire la même valeur numérique, si un futur
  écran de recherche interroge les deux modèles ensemble (ex. barre de recherche globale ou export).
  À vérifier explicitement dans les vues/wizards du module crédit une fois l'étape 1 lancée.

### Constat sur l'hypothèse (répartition du compteur COMPTES)

L'hypothèse de Micka (les « autres produits d'épargne » partagent le compteur COMPTES avec les
conteneurs) n'a **aucun équivalent actuel** : les comptes réels utilisent déjà une séquence dédiée
par **type de produit** (`microfinance.savings.account.I/G/T`), jamais celle du conteneur ou du
compte permanent. L'implémenter tel que demandé (un seul compteur pour conteneurs + « autres
produits d'épargne », séparable plus tard si besoin) est faisable en gardant `_get_or_create_
numbering_sequence` mais avec un `code` dédié (ex. `microfinance.savings.account.COMPTES`) plutôt que
`.I`/`.G`/`.T`, en réservant `.I`/`.G`/`.T` au type de produit affiché mais pas à la source du
numéro — changement de comportement pour tous les futurs comptes réels de type volontaire, à
signaler explicitement dans le rapport final comme demandé.

### Ce qui bloque le passage à l'étape 1

1. Le choix entre **Option 1** et **Option 2** ci-dessus (le conteneur `IS/I/N` devient-il
   transactable, ou reste-t-il une coquille et un compte réel distinct porte « l'épargne liée au
   crédit » ?) — ce point conditionne quels champs, contraintes et tests changent.
2. Confirmation explicite que la nouvelle règle **abroge** la décision « Option A » de l'audit
   §11-12, déjà déployée en production sur MOWGLI le 2026-09-21 (compte principal séparé + conteneur
   nommé `IC/`) — sans quoi je réintroduirais un revirement sur une décision livrée et actée par
   Micka il y a trois jours, avec migration de renommage à l'appui (le conteneur ELIO est déjà
   `SY/IC/000001`, pas `SY/I/000002` : la migration §12 devra être rejouée dans l'autre sens en plus
   de la nouvelle règle).
3. Sort de `microfinance.loan.account` : à réutiliser comme conteneur crédit `IS/N` (le plus proche
   de l'existant, la cardinalité correspond déjà), ou à remplacer par un nouveau mécanisme de couple
   — la demande ne le mentionne pas explicitement et ce modèle n'apparaît nulle part dans le
   CONTEXTE fourni.
4. Sort de `microfinance_account_number` (numéro de compte permanent du client) une fois le couple
   `IS/N` + `IS/I/N` en place : redondant avec le nom du conteneur crédit, mais référencé par
   plusieurs autres modules (guichet, tests, `microfinance_loan.py`) qu'il ne faut pas casser.

**Je m'arrête ici. Aucun code n'a été modifié.** Merci de trancher les 4 points ci-dessus (en
particulier 1 et 2) avant que je propose une conception détaillée pour l'étape 1.

---

## 14. Correctif appliqué — 2026-09-24 (abroge l'« Option A » du 21/09)

**Aucun commit.** Option 2 retenue (conteneur = coquille vide, jamais transactable ; l'épargne
« liée au crédit » reste un compte réel distinct, création manuelle inchangée). Manifeste
`17.0.1.4.0` → **17.0.1.5.0**. Aucun fichier de `microfinance_loan_management` touché.

### Investigation (point 1) : pourquoi aucun numéro n'apparaît à l'enregistrement

**Ce n'est pas un défaut d'attribution du numéro — le numéro est bien assigné — c'est une absence
totale d'affichage dans l'interface.**

- `microfinance_context` EST bien positionné dans le flux normal : le menu Clients pointe sur
  `action_microfinance_client` (`microfinance_partner_views.xml:280-285`), dont le `context` pose
  `'microfinance_context': True` — l'hypothèse « contexte absent hors tests » est donc écartée.
- Ordre d'exécution vérifié : `microfinance_savings_management` dépend de
  `microfinance_loan_management` (`__manifest__.py:13`), donc chargé après — son `create()`
  encadre celui de `microfinance_loan_management` (appelle `super().create()` qui y descend
  avant de remonter). Au moment où le code épargne s'exécute, `microfinance_account_number`
  (`res_partner.py:460`, loan_management) et le conteneur crédit (`:469`) sont déjà posés.
  Pas de bug d'ordonnancement.
- **Cause réelle** : `microfinance_account_number` n'était référencé dans **aucune vue** du module
  crédit ni du module épargne (`grep` exhaustif sur les deux modules) - seuls deux boutons
  statistiques (« Crédit », « Compte crédit ») affichent un **compteur**, pas le numéro, et
  seulement après avoir cliqué dessus pour ouvrir une liste séparée. Micka ne pouvait
  structurellement pas voir « IS/N » sur la fiche client.
- **Correctif (dans cette intervention, module épargne uniquement)** :
  `views/res_partner_views_inherit.xml` affiche désormais `microfinance_account_number` en
  lecture seule juste sous le nom du client (contexte microfinance uniquement). Comme le
  conteneur crédit ET le conteneur épargne portent tous deux ce même N, ce seul champ suffit à
  rendre les deux numéros visibles.

### Code (points 2-3)

- `microfinance_savings_account.py` : `CONTAINER_CODE='IC'`, `_get_container_sync_source`,
  `_build_container_name` supprimés. Nouvelle méthode `_get_container_target_name(company,
  partner)` : nom = `AGENCE/I/<suffixe de partner.microfinance_account_number>` - ne consomme
  aucune séquence. `_get_savings_container_name` lève toujours une `ValidationError` explicite si
  le nom cible est pris ou introuvable (**cf. §15, ce comportement bloque désormais
  l'enregistrement de nouveaux clients sur des données réelles - lire avant déploiement**).
- `res_partner.py` (savings) : `_get_or_create_microfinance_savings_principal_account` et
  `_notify_microfinance_savings_default_product_missing` supprimées. `create()` appelle
  désormais `_get_or_create_microfinance_savings_container()` (conteneur seul, à
  l'enregistrement). Le paramètre `company=` de `_get_or_create_microfinance_savings_container`
  est retiré (n'était utile qu'à l'appel depuis le crédit, supprimé ci-dessous) ; la méthode
  utilise `self.company_id or self.env.company`, comme `_get_or_create_microfinance_loan_account`
  côté crédit.
- `microfinance_loan_extension.py` : override `create()` de `microfinance.loan` **supprimé en
  entier** (son seul rôle était la création du conteneur au 1er crédit). Le crédit ne fait plus
  que ce qu'il faisait déjà côté numérotation (`microfinance.loan.agency`, inchangé).
- `res_company.py` : aide du champ « Produit d'épargne par défaut » corrigée (n'ouvre plus rien
  automatiquement ; champ inerte, conservé pour un usage manuel futur non implémenté).

### Migration (points 4, `migrations/17.0.1.5.0/post-migration.py`)

Deux fonctions dans `container_migration.py` (réécrit) :
- `rename_misnumbered_containers` : renomme `AGENCE/IC/...` → `AGENCE/I/N` (mêmes garanties
  qu'avant - dry-run par défaut via `microfinance_savings.migration_dry_run`, vérif. références
  texte, CSV horodaté en écriture exclusive). **Ne fusionne jamais**.
- `list_savings_duplicates` (nouvelle, toujours en lecture seule) : liste, par ligne de compte
  réel, chaque client ayant un conteneur ET un compte épargne réel dans la même société, avec une
  colonne `decision` vide et un indice `candidat_ancien_principal` (heuristique : créé le même
  jour que la fiche client). **Aucune fusion automatique dans ce correctif.**

### Tests

`common.py`, `test_savings_principal_account_on_create.py` (renommé conceptuellement -
conteneur, plus de compte principal), `test_savings_container_creation.py` (le crédit ne crée
plus de conteneur - **changement de comportement assumé** : un emprunteur non-client
(`test_borrower_without_client_type_never_gets_a_container`) n'a désormais plus jamais de
conteneur, alors qu'il en recevait un via le crédit avant ce correctif), `test_savings_container_
numbering.py`, `test_savings_container_migration.py` (+ classe `TestSavingsDuplicatesListing`)
réécrits.

### Dry-run sur copie de MOWGLI (base jetable créée puis supprimée)

`pg_dump`/`pg_restore` vers `MOWGLI_audit_tmp_20260924_025301`, `-u
microfinance_savings_management --test-enable`, puis suppression de la copie en fin
d'intervention.

| | Résultat |
|---|---|
| Tests module épargne | **2 échecs, 29 erreurs sur 203 tests - identiques à l'état de référence**, aucune régression du correctif. Détail : `test_search_by_name` (collision de nom sur données réelles) et `test_different_type_code_gets_its_own_sequence` (séquence G déjà avancée) - déjà documentés §11 avant ce correctif. Les 29 erreurs viennent toutes de `_check_fond_disponibilite` (fonds de crédit rotatif actif non sélectionné dans les fixtures de test, module non touché par ce correctif) et d'un arrondi d'échéancier dans `microfinance_data_reset_wizard` - sans rapport avec la numérotation épargne. |
| Renommage IC→I (conteneur 349, ELIO, SY) | **`IGNORE_NOM_EXISTANT`** : la cible `SY/I/000001` est déjà portée par le compte réel 348 (« EP lié au crédit », actif, solde 20 000). Aucun renommage automatique - conforme à la règle « pas de fusion automatique ». Non modifié en mode réel (vérifié). |
| Liste des doublons (`list_savings_duplicates`) | 1 ligne : partenaire 1640 (ELIO), conteneur 349 `SY/IC/000001`, compte réel 348 `SY/I/000001`, `candidat_ancien_principal=OUI`, `decision` vide - exactement le cas à trancher par Micka. |

### 🛑 Découverte bloquante du dry-run - À TRANCHER AVANT DÉPLOIEMENT

**L'enregistrement d'un nouveau client échoue déjà sur les données réelles de plusieurs agences**,
testé sur la copie : créer un client test dans l'agence SY (`company_id` réel) a levé
```
ValidationError: Le nom de conteneur épargne « SY/I/000004 » existe déjà : ...
```
Cause : le compteur COMPTES du conteneur (`microfinance.partner.account`) et la séquence des
comptes réels de type volontaire (`microfinance.savings.account.I`) sont **deux séquences
indépendantes qui tournent depuis longtemps sans coordination** - c'est exactement l'ancien bug
(§5) que ce correctif était censé refermer, mais il ré-ouvre le même risque par un autre chemin
puisque le conteneur reprend maintenant le N du compte permanent (qui n'a jamais été aligné sur
`.I`) au lieu de l'ancien nom dérivé du compte crédit (qui, lui, était protégé par
l'unicité `partner_company_unique` du compte crédit). Valeurs mesurées sur MOWGLI (`ir.sequence.
number_next_actual`) :

| Agence | `microfinance.partner.account` (prochain N) | `microfinance.savings.account.I` (prochain réel) | Écart |
|---|---|---|---|
| SY | 5 | 5 | **0 - collision immédiate au prochain client** |
| **IS** (944 crédits, agence principale) | 523 | **628** | **105 - tout nouveau client IS échouera tant que le compteur réel n'aura pas rattrapé son retard** |
| BD | 6 | 7 | 1 |

Avec le code tel quel, déployer ce correctif **casserait l'enregistrement de nouveaux clients**
dans au moins IS et SY dès le prochain client (IS en particulier : ~105 clients consécutifs
échoueraient). Ce n'est pas un cas limite de migration de données historiques : c'est le chemin
normal d'enregistrement, cassé en continu jusqu'à ce que l'écart se résorbe.

**Deux options, à trancher avec Micka avant tout déploiement (je n'ai rien déployé) :**

- **A. Réaligner les deux compteurs avant déploiement** (migration additionnelle) : pousser
  `microfinance.savings.account.I` et `microfinance.partner.account` de chaque société au même
  plancher = `max(les deux valeurs actuelles) + 1`. Résout le blocage immédiat, mais AUCUNE
  garantie durable : `.I` continuera d'avancer à chaque compte réel supplémentaire créé
  manuellement (2ᵉ produit épargne) pendant que le compteur COMPTES avance à chaque client, sans
  coordination entre les deux - l'écart peut se recreuser plus tard et rebloquer
  l'enregistrement dans quelques mois/années.
- **B. Fusionner les deux compteurs** (ce que l'hypothèse de la demande initiale envisageait déjà
  pour un chantier plus large - « compteur COMPTES » partagé entre conteneurs et autres produits
  d'épargne) : `microfinance.savings.account.I` ET `microfinance.partner.account` deviennent la
  MÊME séquence (`_get_or_create_numbering_sequence` avec un seul `code` pour les deux usages).
  Élimine la collision par construction, plus de rattrapage périodique nécessaire, mais change le
  comportement des comptes réels de type I (numérotation continue avec les conteneurs, trous
  compris) et touche la génération du numéro de compte permanent client
  (`microfinance_loan_management/models/res_partner.py:148-156`) - **fichier du module crédit,
  hors du périmètre que vous m'avez fixé pour cette intervention** ; nécessiterait votre feu vert
  explicite pour y toucher, ou un mécanisme de délégation depuis le module épargne.

**Je n'ai pas choisi à votre place** : le code de cette intervention est prêt (diff relisable,
tests verts, migration testée sur copie), mais je recommande de ne PAS le déployer sur MOWGLI tant
que A ou B n'est pas tranché et implémenté - sinon le prochain enregistrement d'un client IS ou SY
échouera en production dès la mise à jour du module.

## §16 - Option B implémentée - 2026-09-24 (choix : « B »)

Vous avez tranché pour l'option B (fusion définitive des deux compteurs). Contrainte respectée :
**aucun fichier du module crédit (`microfinance_loan_management`) n'a été touché** - la fusion est
faite entièrement depuis le module épargne, par délégation sur le même enregistrement
`ir.sequence`, sans modifier la génération du numéro de compte permanent côté crédit
(`microfinance_loan_management/models/res_partner.py:148-156`, inchangé).

### Principe

`microfinance_savings_account.py` : la séquence utilisée pour les comptes réels de type **I**
n'est plus `microfinance.savings.account.I` mais directement `microfinance.partner.account` (le
même code que celui déjà utilisé côté crédit pour le numéro de compte permanent N) :

```python
def _get_savings_sequence_code(self, type_code):
    if type_code == 'I':
        return SHARED_ACCOUNT_NUMBER_SEQUENCE_CODE  # 'microfinance.partner.account'
    return 'microfinance.savings.account.%s' % type_code

def _get_next_available_savings_account_name(self, company, type_code):
    while True:
        number = company._get_or_create_numbering_sequence(self._get_savings_sequence_code(type_code))
        candidate = '%s/%s/%s' % (company.agency_code, type_code, number)
        if not self.search_count([('name', '=', candidate)]):
            return candidate
```

Les autres types de compte épargne (G, ...) gardent chacun leur séquence propre, inchangée. Une
collision par construction n'est donc plus possible pour le type I : conteneur et compte réel
piochent désormais dans le même compteur.

### Migration de rattrapage : `align_savings_number_sequences`

Nouvelle fonction dans `container_migration.py`, appelée en premier dans
`migrations/17.0.1.5.0/post-migration.py` (avant `rename_misnumbered_containers`, pour que tout
nouveau compte réel créé entre les deux étapes utilise déjà la séquence à jour) :

- Pour chaque société ayant une séquence `microfinance.savings.account.I`, calcule
  `target_next = max(ancien_prochain_I, prochain_compte_permanent)`.
- Si le compteur permanent est déjà ≥ à l'ancien `.I` (`DEJA_ALIGNE`), rien à faire.
- Sinon, en mode réel : aligne le compteur permanent sur `target_next`, puis **désactive et
  renomme** (jamais supprime) l'ancienne séquence `.I` (`[OBSOLÈTE - fusionnée avec ... le
  2026-09-24] ...`) pour qu'elle ne puisse plus être réutilisée par erreur.
- Dry-run (paramètre système `microfinance_savings.migration_dry_run`, comme le reste) : CSV
  seul, aucune écriture. Idempotent : rejouer après un alignement réel ne fait plus rien
  (`DEJA_ALIGNE`).
- Restreint aux administrateurs (`base.group_system`), sinon `AccessError` en français.

### Deux bugs trouvés et corrigés pendant les tests de cette fonction (sur copie jetable)

1. **`number_next` vs `number_next_actual`** : écrire `number_next` sur un `ir.sequence` en
   implémentation « standard » ne modifie que le champ de conception stocké, **pas la vraie
   séquence PostgreSQL sous-jacente** - piège classique Odoo. La fusion a d'abord semblé
   fonctionner (pas d'erreur) mais le compteur réel n'avançait pas (`523 != 628` dans mon propre
   test `test_real_run_advances_shared_sequence_and_deactivates_old_one`). Corrigé en écrivant
   `number_next_actual`, qui a le bon inverse (`ALTER SEQUENCE`).
2. **Filtre `active_test`** : après désactivation de l'ancienne séquence `.I`
   (`active=False`), les recherches `ir.sequence.sudo().search(...)` l'excluaient
   silencieusement par défaut (comportement standard Odoo sur les enregistrements inactifs), ce
   qui cassait à la fois le ré-alignement idempotent (2ᵉ passage) et mes propres tests de
   vérification. Corrigé en ajoutant `.with_context(active_test=False)` sur le recordset
   `Sequence`, dans le code de migration **et** dans les tests.

### Tests

Nouvelle classe `TestSavingsSequenceAlignment` dans `test_savings_container_migration.py` (5 cas :
dry-run signale l'écart sans rien modifier, exécution réelle avance le compteur partagé et
désactive l'ancienne séquence, cas déjà aligné = no-op, 2ᵉ exécution réelle idempotente, un
nouveau compte réel créé après l'alignement ne collisionne plus jamais). Suite complète du module
épargne rejouée deux fois de plus après corrections : **2 échecs, 29 erreurs sur 208 tests -
identiques à l'état de référence (§11)**, aucune régression.

### Vérification de bout en bout sur une 2ᵉ copie jetable de MOWGLI

Copie `MOWGLI_audit_tmp_20260924_052017`, `-u microfinance_savings_management --test-enable`, puis
script d'intégration (`odoo-bin shell`) rejouant `align_savings_number_sequences` (dry-run puis
réel), `rename_misnumbered_containers` (réel), `list_savings_duplicates`, puis création d'un
nouveau client test dans **SY** et dans **IS** (les deux agences identifiées à risque au §15).

**Résultats :**

| Vérification | Résultat |
|---|---|
| Nouveau client SY | `SY/000005` (crédit) + `SY/I/000005` (conteneur) créés sans erreur - même N, aucune `ValidationError`. |
| Nouveau client IS | `IS/000759` (crédit) + `IS/I/000759` (conteneur) créés sans erreur - même N, aucune `ValidationError`. |
| Renommage IC→I | Conteneur 349 (ELIO, SY) toujours `IGNORE_NOM_EXISTANT` - non modifié, conforme (pas de fusion automatique). |
| Doublons ELIO | Toujours listé, `decision` vide, en attente d'arbitrage manuel par Micka - inchangé par cette étape. |

**Réserve méthodologique importante (transparence)** : les séquences PostgreSQL (`ir.sequence` en
implémentation standard) ne sont **pas transactionnelles** - lancer la suite de tests Odoo
(`--test-enable`) sur une copie fait avancer réellement les séquences même quand les données de
chaque test sont annulées en fin de transaction. Sur cette 2ᵉ copie, la suite de 208 tests venait
d'être rejouée juste avant la mesure finale, ce qui a fait avancer artificiellement le compteur
permanent d'IS au-delà de l'ancien `.I` **avant même l'appel d'alignement** - d'où le statut
`DEJA_ALIGNE` observé pour IS sur cette copie (`ancien_prochain_type_I=192,
ancien_prochain_compte_permanent=759`), qui ne reflète pas l'écart réel de production. **L'écart
de production fiable reste celui mesuré au §15 sur la 1ʳᵉ copie, avant toute exécution de tests**
(SY : 5 vs 5, écart 0 - IS : 523 vs 628, écart 105) - c'est cette mesure-là qui justifie la
migration, pas les chiffres de la 2ᵉ copie. Ce qui est solidement confirmé par la 2ᵉ copie,
indépendamment de cette réserve : les trois fonctions de migration s'exécutent sans erreur, le cas
ELIO reste correctement détecté et non fusionné automatiquement, et **l'enregistrement d'un
nouveau client dans SY et IS ne lève plus d'erreur** après le correctif complet.

### État final avant déploiement

Option B implémentée entièrement dans le module épargne, aucun fichier du module crédit modifié,
aucune régression de test, blocage du §15 levé et re-vérifié. Diff prêt à relire, aucun commit
automatique. Copies jetables et fichiers temporaires supprimés en fin d'intervention.

## §17 - Déploiement sur MOWGLI - 2026-09-24 18:14

Sur votre instruction (« reboot and update »), déployé selon l'ordre habituel : sauvegarde, puis
redémarrage du service, puis mise à jour.

1. `pg_dump -Fc MOWGLI` → `/opt/odoo17_2/backups/MOWGLI_before_epargne_container_option_b_20260924.dump`
   (15 Mo).
2. `systemctl restart odoo17_2` - reparti proprement (actif en 3s).
3. `odoo-bin -d MOWGLI -u microfinance_savings_management --stop-after-init --http-port=8096` -
   110 modules chargés, aucune erreur liée au module épargne (3 erreurs `_transient_vacuum` sur
   des rapports comptables sans rapport, préexistantes au redémarrage, non liées à ce correctif).
   Log complet : `/opt/odoo17_2/odoo/odoo.log` (fenêtre 18:14:32-18:15:12).
4. Migration `17.0.1.5.0` exécutée automatiquement **en mode réel** (le paramètre système
   `microfinance_savings.migration_dry_run` était déjà à `False` depuis le déploiement de
   l'Option A le 21/09) :
   - `align_savings_number_sequences` : 3 sociétés concernées (Isotry, Ambanidia, Ampitatafika -
     seules à avoir une séquence `.I`). Ambanidia et Ampitatafika réalignées (`ALIGNE`), Isotry
     `DEJA_ALIGNE` (compteur permanent déjà devant). CSV :
     `microfinance_migrations/alignement_sequences_epargne_MOWGLI_20260924_181509_reel.csv`.
   - `rename_misnumbered_containers` : 1 conteneur non conforme sur 1 (ELIO, SY),
     `IGNORE_NOM_EXISTANT` - non renommé, conforme (pas de fusion automatique). CSV :
     `renommage_conteneurs_epargne_MOWGLI_20260924_181509_reel.csv`.
   - `list_savings_duplicates` : 1 doublon listé (ELIO), `decision` vide, en attente de votre
     arbitrage. CSV : `doublons_comptes_epargne_MOWGLI_20260924_181509_dryrun.csv`.
5. Vérification en lecture seule (`odoo-bin shell`) des séquences réelles après migration :

   | Société | `microfinance.partner.account` (prochain) | `microfinance.savings.account.I` (ancienne, prochain) | État |
   |---|---|---|---|
   | Isotry (IS) | 246 → prochain compte réel **247** | 192 (inactive côté usage, jamais désactivée car déjà alignée) | Sûr : 246 ≥ 192 |
   | Ambanidia (BD) | 7 → prochain **8** | 7, désactivée et renommée `[OBSOLÈTE...]` | Sûr |
   | Ampitatafika (SY) | 5 → prochain **6** | 5, désactivée et renommée `[OBSOLÈTE...]` | Sûr |

   Service `odoo17_2` vérifié actif (`systemctl is-active` → `active`/`running`) après la mise à
   jour.

**Écart à noter avec transparence** : les chiffres réels d'Isotry mesurés ici après déploiement
(246 vs 192) sont très différents de ceux du §15 (523 vs 628, mesurés sur la 1ʳᵉ copie jetable
avant tout test). Je n'ai pas d'explication certaine de cet écart - la mesure du §15 n'était
peut-être pas aussi « propre » que je le pensais à l'époque (même piège de contamination par
tests que celui documenté pour la 2ᵉ copie au §16, ou dump pris à un instant différent). Cela ne
remet pas en cause la sécurité du déploiement : ce qui compte est l'état réel vérifié **après**
l'alignement (ci-dessus), qui montre le compteur partagé devant l'ancien compteur `.I` dans les
trois sociétés concernées - aucune collision possible désormais, puisque le code ne lit plus
jamais l'ancienne séquence `.I`.

**Non fait volontairement** : je n'ai pas créé de client de test sur MOWGLI pour vérifier
l'enregistrement en conditions réelles (cela aurait modifié des données de production au-delà de
la migration prévue). La vérification s'appuie sur l'état des séquences + l'absence d'erreur au
chargement du module ; le comportement du formulaire d'enregistrement a déjà été vérifié sur
copie (§16).

**Prochaine étape suggérée** : demander au premier utilisateur du formulaire d'enregistrement
dans n'importe quelle agence de confirmer que le numéro de compte s'affiche bien et qu'aucune
erreur n'apparaît - et transmettre le cas ELIO (SY) à Micka pour arbitrage manuel (`decision`
dans le CSV des doublons).

## §18 - Correctif « conteneur jamais en brouillon » - 2026-10-05

### Demande

Le conteneur épargne (`is_container=True`), créé en même temps que le compte crédit à
l'enregistrement du client, restait en `state='draft'` indéfiniment (aucun produit, donc jamais
activable). Demande : qu'il soit créé directement actif.

### Investigation (avant correctif)

- **État par défaut** : `draft` (`models/microfinance_savings_account.py:65`), jamais changé à la
  création - ni dans `create()` ni dans `res_partner.py._get_or_create_microfinance_savings_
  container`.
- **Cause du blocage** : ce n'est **pas** `_check_product_required_unless_container` (elle ne
  regarde que `is_container`/`product_id`, jamais `state`, et exempte déjà le conteneur). C'est
  `action_activate()` qui refuse explicitement tout conteneur (`UserError` dès que `is_container`
  est vrai) - le seul chemin possible est de poser `state` directement dans les `vals` de
  `create()`.
- **Pas de nouvel état nécessaire** : `'active'` existe déjà dans la `Selection`, sans sémantique
  liée au produit.
- **Non-régression transactionnelle confirmée** : `_create_transaction` et `action_close`
  vérifient `is_container` **avant** et **indépendamment** de `state` - un conteneur actif reste
  non transactable et non clôturable par ces méthodes.
- **Point additionnel trouvé en creusant** : `cron_detect_dormant_accounts` recherchait
  `state == 'active'` sans exclure `is_container`. Sans effet aujourd'hui (`is_dormant` reste
  `False` tant que le conteneur n'a ni transaction ni `opening_date`), mais fragile - durci en
  défense en profondeur dans ce correctif.
- **Vues** : `action_activate`/`action_close` et le statusbar `state` sont déjà
  `invisible="... or is_container"` - rien à changer côté vues. Seul effet cosmétique : la
  décoration `decoration-success="state == 'active'"` de la liste s'appliquera désormais aussi
  aux conteneurs (masqués par défaut via le filtre « Masquer les conteneurs »).

### Correctif appliqué

- `microfinance_savings_account.py.create()` : si `is_container` est vrai et qu'aucun `state`
  n'est fourni explicitement, pose `'state': 'active'` - posé au niveau du **modèle** (pas
  seulement chez l'appelant `res_partner.py`), pour garantir l'invariant quel que soit le point de
  création (tests, scripts, futurs appelants), conformément au « JAMAIS » de la demande.
- `cron_detect_dormant_accounts` : domaine durci avec `('is_container', '=', False)`, en défense
  en profondeur.
- Aucun fichier du module crédit touché.
- Aucune migration de données de schéma - uniquement une nouvelle fonction utilitaire
  `activate_draft_containers` dans `container_migration.py` (même patron dry-run/CSV que les
  opérations §11-16), pour régulariser les conteneurs déjà en base créés avant ce correctif.
  Écrit uniquement `state` (jamais `opening_date`, pour ne pas rendre le conteneur éligible à la
  dormance).

### Tests

- `test_savings_account_container.py` : nouveaux tests `test_container_created_active_not_draft`
  (conteneur actif dès `create()`), `test_container_explicit_state_respected` (un état fourni
  explicitement n'est pas écrasé) et `test_container_not_flagged_dormant_by_cron` (défense en
  profondeur du cron). Tests existants inchangés (`test_container_cannot_be_activated`,
  `test_container_cannot_be_closed`, `test_container_cannot_receive_transaction`,
  `test_real_account_without_product_raises`, `test_regular_account_flow_unaffected`) : aucun ne
  supposait un conteneur en brouillon, aucune régression.
- `test_savings_container_migration.py` : nouvelle classe
  `TestSavingsContainerActivationMigration` (dry-run n'écrit rien, run réel active puis devient
  idempotent, `opening_date` jamais écrit, un compte réel en brouillon n'est jamais touché).

### Dry-run sur copie jetable de MOWGLI

Copie créée via `pg_dump MOWGLI | psql test_container_fix_tmp` (pas de verrou sur les connexions
actives de production), module mis à jour (`-u microfinance_savings_management`), puis supprimée
en fin d'intervention.

- Suite de tests ciblée (17 tests du module, dont les nouveaux) : **0 échec, 0 erreur**.
- `activate_draft_containers(env, dry_run=True)` exécuté isolément (hors tests, `odoo-bin
  shell`) : **23 conteneurs en brouillon à régulariser** sur cette copie, répartis sur plusieurs
  agences (Isotry, Ambanidia, Ampitatafika, Andoharanofotsy, Mahitsy...) - majoritairement des
  clients de test/démo mais aussi des clients réels (ex. ELIO, RAKOTONALY Nanahary,
  RANDRIANASOLO Santatra). Rien écrit (dry-run par défaut, paramètre
  `microfinance_savings.migration_dry_run` non modifié).

### État avant déploiement

Diff + tests prêts à relire, aucun commit automatique. Aucune base de production touchée - seule
une copie jetable, supprimée. Migration de rattrapage (`activate_draft_containers`) disponible
mais **pas exécutée en mode réel sur MOWGLI** : à lancer explicitement après votre validation du
chiffre ci-dessus, selon le même ordre habituel (sauvegarde, redémarrage, puis mise à jour -
cf. §17).
