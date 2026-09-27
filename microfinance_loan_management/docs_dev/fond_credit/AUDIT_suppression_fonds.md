# Audit — Suppression des fonds de crédit (CEFOR)

Date : 2026-09-24. Lecture seule (aucune modification effectuée). Base auditée : `MOWGLI`
(production CEFOR, cluster Postgres partagé avec EAT/MIIA — cf. § Périmètre).

## 0. Précision de nommage

La demande mentionne le modèle `fond.credit`. Il n'existe pas sous ce nom : le modèle réel est
**`microfinance.fond.credit`** (fichier
[microfinance_fond_credit.py](../../models/microfinance_fond_credit.py)), module
`microfinance_loan_management`. C'est celui audité ci-dessous.

## 1. Modèle `microfinance.fond.credit` — champs, contraintes, ondelete, unlink

- Hérite de `mail.thread`, `mail.activity.mixin`, `microfinance.fond.parent.mixin`.
- Champs clés : `name`, `code` (séquence `microfinance.fond.credit`, unique SQL),
  `bailleur_id` (M2O `microfinance.bailleur.fonds`, `ondelete='restrict'`), `scope`
  (`single_company`/`multi_company`, figé après création), `company_id` (figé après création,
  requis si `single_company`, vide si `multi_company`), `date_debut`/`date_cloture`,
  `passer_gl`, `account_id` (compte GL bailleur, requis si `passer_gl`),
  `verification_disponibilite`, `active` (défaut `True`).
- Champs calculés stockés : `total_contributions`, `total_decaisse`, `total_rembourse`,
  `solde_disponible`, `reste_partageable`.
- Relations inverses (One2many) : `contribution_ids` → `microfinance.fond.contribution.fond_id`,
  `loan_ids` → `microfinance.loan.fond_credit_id`, `allocation_ids` →
  `microfinance.fond.allocation.fond_id`, `partage_ids` → `microfinance.fond.partage.fond_id`.
- **`unlink()`** (ligne 146) : appelle uniquement `self._check_parent_only()` — garde « société
  mère microfinance uniquement », **aucune protection propre** au-delà (pas de vérification
  d'absence de crédits/contributions dans ce override). Toute protection réelle contre une
  suppression avec dépendances vient donc **des contraintes FK Postgres** ci-dessous.
- `write()` interdit de changer `scope`/`company_id` après la première sauvegarde.
- `_check_parent_only()` (mixin) lève `UserError` si la société courante n'est pas la société
  mère désignée par le paramètre système `microfinance.parent_company_id` — **sauf** si le
  contexte porte `microfinance_skip_parent_check` (prévu pour les migrations/scripts).

### Modèles référençant `microfinance.fond.credit` (Many2one) et leur `ondelete`

| Modèle | Champ | `ondelete` | Effet sur `unlink()` d'un fonds |
|---|---|---|---|
| `microfinance.fond.contribution` | `fond_id` | **`restrict`** | **Bloque** la suppression SQL si ≥1 contribution existe (quel que soit son état) |
| `microfinance.fond.allocation` | `fond_id` | **`restrict`** | **Bloque** si ≥1 allocation existe (fonds partagés gérés par allocation) |
| `microfinance.fond.partage` | `fond_id` | **`restrict`** | **Bloque** si ≥1 partage existe (fonds `multi_company`) |
| `microfinance.loan` | `fond_credit_id` | *(non précisé → défaut Odoo `set null`)* | Ne bloque pas côté FK ; supprimerait silencieusement la référence sur les crédits existants |
| `res.company` | `microfinance_fond_credit_default_id` | *(non précisé → défaut `set null`)* | Ne bloque pas ; viderait le fonds par défaut de l'agence |

**Constat majeur, plus large que prévu dans la demande initiale** : la demande anticipait
uniquement un blocage via les crédits (`microfinance.loan`). En réalité, **trois relations en
`ondelete='restrict'`** (contributions, allocations, partages) rendent `unlink()` sur
`microfinance.fond.credit` **impossible dès qu'une seule contribution existe** — et c'est le cas
de tous les fonds actuellement en base (§4). Purger ces lignes filles pour débloquer la
suppression détruirait l'historique des mouvements bailleur (dépôts/retraits), même si les
`account.move` sous-jacents restent physiquement intacts (leur champ de rattachement passe juste
à NULL). Voir recommandation en fin de rapport.

## 2. `_check_fond_disponibilite` et dépendances à un fonds actif

Dans [microfinance_loan.py](../../models/microfinance_loan.py) :

- `microfinance.loan.fond_credit_id` (l.28) : M2O vers `microfinance.fond.credit`, **non
  required**, domaine dynamique (fonds actifs, non clôturés, visibles pour la société du
  crédit).
- `has_active_fond` (compute, l.41) : vrai si un fonds actif est visible pour la société du
  crédit ; sert uniquement à rendre `fond_credit_id` visuellement requis côté formulaire.
- `_check_fond_credit_id_locked_after_disbursement` (contrainte, l.2535) : **interdit de
  modifier `fond_credit_id` dès que `disbursement_date` est renseigné** (crédit décaissé). Donc
  un `unlink()` du fonds qui mettrait `fond_credit_id` à `NULL` via `ondelete='set null'`
  **contournerait cette contrainte métier par la bande** (le `write()` ORM normal est bloqué,
  mais le FK `ON DELETE SET NULL` agit au niveau SQL, hors de tout passage par la couche
  contrainte Python) — incohérence comptable potentielle si un crédit déjà décaissé perdait sa
  référence au fonds qui a financé son décaissement.
- `_check_fond_disponibilite()` (l.2554), appelée uniquement depuis `action_disburse()` : si
  `verification_disponibilite == 'at_disbursement'`, bloque le décaissement si le fonds est
  clôturé/pas encore actif/solde insuffisant. Si le crédit n'a **aucun** `fond_credit_id` alors
  qu'un fonds actif existe pour sa société, le décaissement est bloqué par précaution (« oubli
  probable »). **Conséquence** : supprimer/désactiver tous les fonds d'une société ne bloque pas
  les crédits déjà rattachés (le champ est déjà renseigné), mais change le comportement de
  `has_active_fond` pour les *nouveaux* crédits (le rattachement ne sera plus proposé, et le
  garde-fou « fonds actif existant mais non sélectionné » disparaît — comportement mutualiste
  normal selon le commentaire du code).

## 3. `account.move` / `account.move.line` liés aux fonds — jamais à supprimer

Deux points d'entrée comptables identifiés, **à préserver intégralement** :

1. `microfinance.fond.contribution.move_id` → `account.move` : généré par
   `action_post()`/`_prepare_contribution_move()` (module `microfinance_fond_contribution.py`,
   l.100-141) pour chaque dépôt/retrait bailleur si `fond_id.passer_gl` est actif. Champ inverse
   sur `account.move` : `microfinance_fond_contribution_id` (`ondelete` par défaut `set null`,
   donc l'écriture survit même si la contribution est supprimée — mais devient alors
   « orpheline » du point de vue de la traçabilité fonds).
2. Décaissements de crédits rattachés à un fonds (`microfinance.loan.fond_credit_id`) : les
   écritures de décaissement (`action_disburse()`/`action_process_disbursement()`) ne portent
   pas de champ dédié au fonds — leur lien passe uniquement par `loan_id` → `fond_credit_id`. Ces
   écritures ne sont touchées par aucun code du modèle `microfinance.fond.credit` lui-même.

Le script de purge (Étape 1) ne doit **jamais** manipuler `account.move`/`account.move.line`
directement, et ne doit jamais passer une écriture postée en brouillon.

## 4. Périmètre : sociétés retenues

### Constat sur la hiérarchie société mère / filiales

`res.company.parent_id` **n'est utilisé par aucune des 11 sociétés de MOWGLI** (toutes ont
`parent_id` vide — vérifié en base). Le concept de « société mère » pour les fonds bailleurs
n'est **pas** porté par la hiérarchie standard `parent_id`/`child_ids`, mais par le paramètre
système `microfinance.parent_company_id` (actuellement = **1, CEFOR Isotry**), lu par
`res.company._get_microfinance_parent()`. Ce paramètre ne sert qu'à la garde `_check_parent_only`
(qui peut configurer/gérer les fonds), pas à un filtrage de périmètre de sociétés.

### Sociétés CEFOR présentes dans MOWGLI (11, toutes actives)

| id | Nom | agency_code | parent_id |
|---|---|---|---|
| 1 | CEFOR Isotry (société mère microfinance) | IS | — |
| 2 | CEFOR Ambanidia | BD | — |
| 3 | CEFOR Ampitatafika | SY | — |
| 4 | CEFOR Andranonahoatra | TA | — |
| 5 | CEFOR Sabotsy Namehana | SB | — |
| 6 | CEFOR Mahitsy | MA | — |
| 7 | CEFOR Tsaramasay | TS | — |
| 8 | CEFOR Ambohitrimanjaka | KA | — |
| 9 | CEFOR Andoharanofotsy | AD | — |
| 10 | CEFOR Ambohimanarina | BM | — |
| 11 | CEFOR Andravoahangy | GY | — |

### EAT / MIIA : absentes de cette base, pas seulement hors périmètre

Recherche `res.company`/`res.partner` (`is_company=True`) sur MOWGLI : **aucune ligne** ne
correspond à EAT ou MIIA. Ces activités tournent sur des bases Postgres **distinctes**
(`EATDATA`, `EATDATA2`, `EATDATA_FROM_2024` — visibles dans `psql -l` du même cluster, propriétaire
`odoo17`, pas `odoo17_2`). La mention « instance partagée » dans le manifest de
`microfinance_data_reset_wizard` renvoie au partage du **cluster Postgres** (d'où la clé
d'advisory lock dédiée `_LOCK_KEY = 823476513`, différente de celle du RAZ générique EAT/MIIA),
pas à des sociétés co-existant dans la même base. **Aucun risque de toucher EAT/MIIA depuis un
script exécuté sur la connexion MOWGLI** : la question ne se pose pas au niveau `company_id`, la
séparation est déjà au niveau base de données.

**Périmètre retenu, non ambigu : les 11 sociétés `id IN (1..11)` ci-dessus (= toute la base
MOWGLI).** Pas d'exclusion à appliquer en pratique (EAT/MIIA n'y existent pas), mais le script
gardera quand même un domaine explicite `company_id in (...)` par défense en profondeur, comme
demandé.

## 5. Volumétrie réelle (MOWGLI, au 2026-09-24)

### Fonds par société et par état

| id fonds | Code | Société | scope | actif | contributions | allocations | partage |
|---|---|---|---|---|---|---|---|
| 1 | FND/2026/00001 (AID) | CEFOR Isotry (1) | single_company | oui | 1 (postée) | — | — |
| 91 | FND/2026/00091 (MFS) | CEFOR Ambanidia (2) | single_company | oui | 2 (postées) | — | — |
| 138 | FND/2026/00138 (BBM2) | CEFOR Isotry (1) | single_company | oui | 1 (postée) | — | — |
| 141 | FND/2026/00141 (BB007) | — (multi-agences) | multi_company | oui | 1 (postée) | 11 (une par agence) | 1 validé (80 000 000) |

- **4 fonds au total**, tous actifs (aucun fonds archivé actuellement — `active=False` : 0
  ligne). `with_context(active_test=False)` n'a donc aucun effet sur le volume aujourd'hui, mais
  reste requis par construction pour être correct si un fonds est archivé entre-temps.
- Aucun fonds hors périmètre (EAT/MIIA) par construction (§4).

### Crédits référençant un fonds

| Crédit | Société | État | `fond_credit_id` | Décaissé | Montant |
|---|---|---|---|---|---|
| 745 (SY/000001) | CEFOR Ampitatafika (3) | `enquete` | 141 (BB007) | non (`disbursement_date` vide) | 500 000 |

**1 seul crédit référence un fonds**, et c'est le fonds partagé `141`. Ce crédit est encore en
instruction (`enquete`), donc pas décaissé — pas d'écriture comptable de décaissement à protéger
pour ce cas précis, mais le rattachement `fond_credit_id` existe et doit être traité selon la
règle de l'étape 1 (ne pas cascader silencieusement).

### Dépendances bloquantes (résumé)

| Fonds | Bloqué par FK `restrict` (contributions/allocations/partages) | Bloqué par un crédit rattaché |
|---|---|---|
| 1 (AID) | **oui** (1 contribution) | non |
| 91 (MFS) | **oui** (2 contributions) | non |
| 138 (BBM2) | **oui** (1 contribution) | non |
| 141 (BB007) | **oui** (1 contribution + 11 allocations + 1 partage) | **oui** (crédit 745) |

**Les 4 fonds sont bloqués à 100 % par les contraintes FK `restrict`** sur
`fond.contribution`/`fond.allocation`/`fond.partage` — indépendamment de la question des crédits.
Un `unlink()` brut échouera systématiquement avec une `IntegrityError` Postgres tant que ces
lignes filles existent, quel que soit le fonds visé.

## 6. Recommandation avant d'écrire le script d'Étape 1

Compte tenu du §1/§5, la suppression physique (`unlink()`) de **n'importe lequel** des 4 fonds
existants implique nécessairement l'une de ces deux options, à trancher fonds par fonds :

- **(a) Purge en cascade des lignes filles non comptables** (`fond.contribution`,
  `fond.allocation`, `fond.partage`) avant `unlink()` du fonds. Les `account.move` déjà postés
  restent physiquement intacts (champ `microfinance_fond_contribution_id` mis à `NULL`), mais
  deviennent orphelins de tout point de vue fonctionnel côté module fonds — perte de traçabilité
  applicative du mouvement bailleur, même si l'écriture comptable elle-même subsiste.
- **(b) Archivage (`active=False`)** à la place d'un `unlink()` réel : conserve l'intégralité de
  l'historique (contributions, allocations, partages, lien `account.move`), le fonds disparaît
  des vues/domaines actifs (recherches `fond_credit_id`, dashboards) mais reste consultable et
  réversible.

Le fonds 141 a de plus un crédit actif rattaché (745) : la règle de l'énoncé s'applique
explicitement ici — **le script doit lister ce cas et s'arrêter**, sauf choix explicite entre
délier `fond_credit_id` sur ce crédit ou archiver le fonds au lieu de le supprimer.

**Point à valider avant d'écrire le script d'Étape 1** : la demande initiale visait une
suppression physique de tous les fonds. Vu que 100 % des fonds existants sont bloqués par des FK
`restrict` sur des données non comptables mais historiques (contributions/allocations/partages),
je recommande **l'archivage (option b)** comme comportement par défaut du mode « exécution »
(conserve tout, réversible, aucune perte de traçabilité), avec la purge en cascade (option a)
disponible uniquement en option explicite fonds par fonds si l'archivage ne convient pas pour un
usage précis (ex. remise à zéro complète d'une base de test). Le script (Étape 1) implémentera
les deux modes ; le choix du mode par défaut et le traitement du fonds 141 (crédit 745) restent à
confirmer avant toute exécution réelle.

## 6bis. Décisions validées par l'utilisateur (2026-09-24)

- **Mode de purge : cascade complète** (pas d'archivage) — contributions, allocations et
  partages sont supprimés avec le fonds à chaque exécution réelle. Les `account.move` déjà
  postés restent toujours intacts.
- **Fonds BB007 (id 141) / crédit SY/000001 (id 745)** : le crédit est un crédit de test —
  suppression du crédit lui-même (pas un simple délien de `fond_credit_id`), implémentée via
  l'option `blocking_loan_action = 'delete_test_loan'` du wizard, avec garde-fou : ne supprime
  jamais un crédit ayant des remboursements ou des transferts inter-agences existants (lignes
  filles en `ondelete='restrict'`).
- **« rotas » = ce serveur** hébergeant MOWGLI. Backup pris avec `pg_dump` sur ce serveur avant
  toute modification de schéma (cf. §7bis).

## 6ter. Deux garde-fous supplémentaires découverts uniquement par le dry-run réel

L'audit statique (§1-§5) n'avait identifié que les 3 contraintes FK `restrict`. Le dry-run
exécuté sur MOWGLI (voir §7bis) a révélé **deux blocages métier supplémentaires**, propres au
code, invisibles à la seule lecture des `ondelete` :

1. `microfinance.fond.allocation.unlink()` refuse toute suppression directe hors du contexte
   technique `fond_partage_technique` (posé uniquement par `microfinance.fond.partage`) :
   « Une allocation ne se modifie pas directement : passez par « Partage des fonds ». »
2. `microfinance.fond.partage.unlink()` refuse de supprimer un partage à l'état `validated` :
   « Un partage validé ne peut pas être supprimé : annulez-le d'abord. » Il faut d'abord appeler
   `action_cancel()`, qui réduit/supprime proprement les allocations correspondantes — et
   **bloque lui-même** si une agence a déjà consommé sa part (`montant_utilise > 0`), auquel cas
   le fonds reste légitimement protégé (pas de contournement ajouté).

Le wizard (Étape 1) a été corrigé pour suivre ce chemin légitime (`action_cancel()` puis
`unlink()` des partages, avec le contexte technique pour les allocations), plutôt que de
supprimer les lignes filles brutalement. Ce constat illustre l'intérêt d'un vrai dry-run
au-delà de la lecture de code : deux blocages réels n'avaient pas été anticipés par l'audit
statique initial.

## 7. Base pour le dry-run

- `MOWGLI_fondtest` existe déjà comme copie de travail sur ce même cluster (visible dans
  `psql -l`, propriétaire `odoo17_2`) — à utiliser comme « copie jetable » pour le dry-run,
  conformément à la méthode habituelle (cf. mémoire *Vérifier un PDF sur copie jetable* pour
  l'esprit de la démarche, adapté ici à un contrôle de volumétrie plutôt qu'à un PDF). À
  vérifier avant usage qu'elle est bien une copie récente de `MOWGLI` (nombre de fonds/crédits
  identique) avant de s'y fier pour le dry-run.
- `rotas` n'est pas un nom de base visible dans ce cluster (`psql -l` : CUFSIG, EATDATA*,
  MOWGLI, MOWGLI_fondtest, SIGCUF, SYSADAPTPRO, SYSADPATPRO, TEST_BLOCAGE_TMP). Confirmé par
  l'utilisateur : `rotas` = ce serveur.
- `MOWGLI_fondtest` s'est révélée être une copie **obsolète** de MOWGLI (2 fonds au lieu de 4,
  crédit différent, module de purge pas encore présent) : elle ne reflète pas l'état réel de
  production. Le rafraîchissement (drop + restore) a été bloqué par le classifieur de
  permissions ; l'utilisateur a autorisé, à la place, l'exécution du dry-run **directement sur
  MOWGLI**, le mode dry-run n'écrivant jamais (savepoint puis rollback systématique, y compris
  en cas d'erreur — vérifié par une lecture du nombre de fonds/crédits avant/après, inchangé).

## 7bis. Résultat du dry-run réel sur MOWGLI (2026-09-24, 00:52)

Backup complet pris avant toute intervention (`pg_dump -Fc`, copié dans
`/opt/odoo17_2/backups/MOWGLI_avant_purge_fond_credit_*.dump`, ~9,3 Mo). Le service `odoo17_2`
a été redémarré puis le module `microfinance_data_reset_wizard` mis à jour (`-u`, schéma
uniquement : nouvelle table pour le wizard, aucune donnée fonds/crédit touchée) avant de lancer
le dry-run, conformément à l'ordre de déploiement habituel.

Périmètre : les 11 sociétés CEFOR. Option crédits bloquants : `delete_test_loan`. Journal complet
obtenu (mode simulation, tout annulé par rollback) :

```
[1] FND/2026/00001 : 1 contribution(s) supprimée(s) (account.move déjà postés conservés, juste déliés)
[1] FND/2026/00001 « AID » (CEFOR Isotry) : fonds supprimé
[141] FND/2026/00141 : 1 crédit(s) de test supprimé(s) (SY/000001)
[141] FND/2026/00141 : 1 contribution(s) supprimée(s) (account.move déjà postés conservés, juste déliés)
[141] FND/2026/00141 : 1 partage(s) supprimé(s) (1 annulé(s) au préalable)
[141] FND/2026/00141 « BB007 » (Multi-agences) : fonds supprimé
[138] FND/2026/00138 : 1 contribution(s) supprimée(s) (account.move déjà postés conservés, juste déliés)
[138] FND/2026/00138 « BBM2 » (CEFOR Isotry) : fonds supprimé
[91] FND/2026/00091 : 2 contribution(s) supprimée(s) (account.move déjà postés conservés, juste déliés)
[91] FND/2026/00091 « MFS » (CEFOR Ambanidia) : fonds supprimé
SIMULATION TERMINÉE (rollback, rien de modifié)
Résumé : CEFOR Isotry : 2 fonds supprimé(s), Multi-agences : 1 fonds supprimé(s), CEFOR Ambanidia : 1 fonds supprimé(s)
```

Vérification après rollback : `microfinance.fond.credit` = 4 (inchangé), `microfinance.loan` = 1
(inchangé). **Les 4 fonds sont supprimables sans blocage restant**, en purgeant leurs 5
contributions, 11 allocations (via l'annulation du partage) et 1 partage, et en supprimant le
seul crédit de test (745) qui référençait le fonds partagé. Aucune écriture comptable touchée.

## 8. Exécution réelle (validée par l'utilisateur, 2026-09-24, 00:55)

Feu vert donné après lecture du rapport et du dry-run ci-dessus. Backup pris avant toute
intervention (§7bis) toujours valide (aucune donnée fonds/crédit modifiée entre-temps, vérifié).
`ir.config_parameter microfinance.fond_credit_purge_apply` activé à `True` le temps de
l'exécution, puis **remis à `False` immédiatement après** (dry-run par défaut restauré).

Résultat, identique au dry-run, cette fois validé (commit) :

```
Résumé : CEFOR Isotry : 2 fonds supprimé(s), Multi-agences : 1 fonds supprimé(s), CEFOR Ambanidia : 1 fonds supprimé(s)
```

Vérifications post-exécution :

| Contrôle | Résultat |
|---|---|
| `microfinance.fond.credit` restants (les 11 sociétés + multi-agences) | **0** (attendu : 0) |
| `microfinance.loan` restants | **0** (le seul crédit du périmètre était le crédit de test 745, supprimé) |
| `microfinance.fond.contribution` / `.allocation` / `.partage` restants | 0 / 0 / 0 |
| `account.move` des 5 contributions (ids 1610, 1639, 2101, 2102, 2103) | **toujours présents, état `posted`** — seul leur champ `microfinance_fond_contribution_id` est passé à `NULL` (`ondelete='set null'`, comportement documenté et voulu, pas une suppression) |
| `ir.config_parameter microfinance.fond_credit_purge_apply` après coup | `False` (remis par défaut) |
| Service `odoo17_2` | actif |

**Purge terminée avec succès sur MOWGLI, périmètre CEFOR complet.** Aucune société EAT/MIIA
concernée (aucune n'existe dans cette base). Aucune écriture comptable supprimée.
