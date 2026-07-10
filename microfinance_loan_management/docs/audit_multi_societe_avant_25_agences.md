# Audit multi-société avant déploiement sur 25 agences (CEFOR)

**Périmètre** : `microfinance_loan_management`, `microfinance_savings_management`.
**Hors périmètre** : `plan_compta_pcec` (traité séparément).
**Nature** : audit uniquement — aucune modification de code, vue ou donnée effectuée.
**Date** : 2026-07-10.

---

## Résumé exécutif

Le socle multi-société est **partiellement en place** : la quasi-totalité des modèles porte déjà un champ `company_id` correctement configuré (`required=True`, `default=lambda self: self.env.company`). En revanche, **deux points bloquants** doivent être corrigés avant d'ouvrir la première agence pilote :

1. **Aucun filtrage par société sur les comptes comptables (`account.account`)** des produits crédit et épargne — un gestionnaire peut assigner à un produit de l'agence A un compte PCEC appartenant à l'agence B (Étape 2).
2. **Absence quasi générale de règles `ir.rule`** sur les modèles métier (crédit, épargne, garanties, remboursements...) — seuls 4 modèles sur ~25 sont protégés (Étape 2).

À cela s'ajoute un point à trancher côté métier : les séquences de numérotation sont actuellement **globales à l'instance**, pas par société (Étape 3), et **les clients (`res.partner`) sont partagés entre toutes les sociétés** par défaut Odoo, ce qui est probablement voulu mais doit être validé explicitement (Étape 1).

---

## Étape 1 — Présence et configuration du champ `company_id`

### 1.1 Produits

| Modèle | `company_id` | `required` | `default=env.company` | Vue liste/formulaire |
|---|---|---|---|---|
| `microfinance.loan.product` | ✅ ([microfinance_loan_product.py:238](../models/microfinance_loan_product.py#L238)) | ✅ | ✅ | ✅ affiché, `groups="base.group_multi_company"` ([microfinance_loan_product_views.xml:30](../views/microfinance_loan_product_views.xml#L30)) |
| `microfinance.savings.product` | ✅ ([microfinance_savings_product.py:163](../../microfinance_savings_management/models/microfinance_savings_product.py#L163)) | ✅ | ✅ | ✅ affiché, `groups="base.group_multi_company"` |

Contrainte SQL `unique(code, company_id)` présente sur les deux — bon signe : le code produit est déjà pensé comme unique **par société**, pas globalement.

**Effort correctif** : aucun — déjà conforme.

### 1.2 Modèles satellites (crédit)

| Modèle | `company_id` | Mode |
|---|---|---|
| `microfinance.loan` | ✅ réel, `required=True` ([microfinance_loan.py:16](../models/microfinance_loan.py#L16)) | champ propre |
| `microfinance.loan.application` | ✅ réel, `required=True` ([microfinance_loan_application.py:79](../models/microfinance_loan_application.py#L79)) | champ propre |
| `microfinance.loan.installment` | ✅ ([microfinance_loan_installment.py:30](../models/microfinance_loan_installment.py#L30)) | `related='loan_id.company_id', store=True` |
| `microfinance.loan.payment` | ✅ ([microfinance_loan_payment.py:19](../models/microfinance_loan_payment.py#L19)) | related, store |
| `microfinance.loan.guarantee` | ✅ ([microfinance_loan_guarantee.py:36](../models/microfinance_loan_guarantee.py#L36)) | related, store |
| `microfinance.guarantee.valuation.rule` | ✅ réel, `required=True` ([microfinance_loan_guarantee.py:81](../models/microfinance_loan_guarantee.py#L81)) | champ propre, contrainte unique(type, company) |
| `microfinance.loan.reschedule.history` | ✅ ([microfinance_loan_reschedule_history.py:11](../models/microfinance_loan_reschedule_history.py#L11)) | related, store |
| `microfinance.collection.visit` | ✅ ([microfinance_collection_visit.py:20](../models/microfinance_collection_visit.py#L20)) | related, store |
| `microfinance.scoring.profile` | ✅ réel, `required=True` ([microfinance_scoring.py:14](../models/microfinance_scoring.py#L14)) | champ propre |
| `microfinance.scoring.rule` | ✅ ([microfinance_scoring.py:95](../models/microfinance_scoring.py#L95)) | related, store |
| `microfinance.scoring.line` | ✅ ([microfinance_scoring.py:173](../models/microfinance_scoring.py#L173)) | related, store |
| `microfinance.provision.rule` | ✅ réel, `required=True` ([microfinance_provision_rule.py:15](../models/microfinance_provision_rule.py#L15)) | champ propre |
| `microfinance.repayment.frequency` | ❌ absent | modèle de référence, potentiellement volontairement partagé (à clarifier, cf. 1.4) |
| `microfinance.loan.application.tier` | ⚠️ présent mais **non requis** ([microfinance_loan_application.py:28](../models/microfinance_loan_application.py#L28)) — champ documenté « laisser vide pour un palier commun à toutes les sociétés » | conception délibérée, cohérente |
| `microfinance.client.blacklist` | ❌ absent | rattaché à `partner_id`, pas de société |
| `microfinance.client.category` | ❌ absent | référentiel partagé |
| `microfinance.client.representative` | ❌ absent | rattaché à `partner_id` |
| `microfinance.client.group.member` | ❌ absent | rattaché à `group_id` (partner) |

### 1.3 Modèles satellites (épargne)

| Modèle | `company_id` | Mode |
|---|---|---|
| `microfinance.savings.account` | ✅ réel, `required=True` ([microfinance_savings_account.py:17](../../microfinance_savings_management/models/microfinance_savings_account.py#L17)) | champ propre |
| `microfinance.savings.transaction` | ✅ ([microfinance_savings_transaction.py:49](../../microfinance_savings_management/models/microfinance_savings_transaction.py#L49)) | `related='account_id.company_id', store=True` |

### 1.4 `res.partner` (extension `microfinance_context`)

**Constat** : ni `microfinance_loan_management/models/res_partner.py` ni `microfinance_savings_management/models/res_partner.py` ne surchargent ou ne restreignent le `company_id` natif de `res.partner` (qui est optionnel et non renseigné par défaut sur ce modèle standard Odoo). **Les clients sont donc partagés entre toutes les sociétés** : un même `res.partner` peut avoir des crédits ouverts dans l'agence A et des dépôts dans l'agence B sans qu'aucune barrière logicielle ne s'y oppose.

**Point à trancher explicitement avec le métier CEFOR, pas par ce rapport** :
- Si chaque agence doit avoir sa **propre base de clients isolée** (un client de l'agence A ne doit jamais apparaître dans le sélecteur partenaire de l'agence B) → il faut soit renseigner `company_id` sur `res.partner` (Odoo supporte nativement ce cas : un partner avec `company_id` vide reste visible partout, un partner avec `company_id` fixé n'est visible que par cette société), soit ajouter une `ir.rule`.
- Si un client peut légitimement être actif dans **plusieurs agences** (cas courant en microfinance si un client déménage ou est domicilié dans deux zones), le partage actuel est correct et il ne faut **rien changer** ici — le cloisonnement doit alors porter uniquement sur les crédits/comptes épargne (déjà `company_id` correct), pas sur le partenaire.

**Risque si non tranché** : ambiguïté opérationnelle (un agent de l'agence A peut sélectionner n'importe quel client des 24 autres agences en note de crédit), mais ce n'est pas nécessairement un défaut — cela dépend du modèle métier voulu.

**Effort estimé** : faible à moyen selon la décision (ajout de `company_id` + règle sur `res.partner` si isolement strict requis).

---

## Étape 2 — Domaines et règles de sécurité

### 2.1 Règles `ir.rule` existantes

Seules **4 règles** sur l'ensemble des deux modules, toutes dans [groups.xml](../security/groups.xml) :

- `rule_microfinance_scoring_profile_company` → `microfinance.scoring.profile`
- `rule_microfinance_scoring_rule_company` → `microfinance.scoring.rule`
- `rule_microfinance_scoring_line_company` → `microfinance.scoring.line`
- `rule_microfinance_provision_rule_company` → `microfinance.provision.rule`

Toutes au format `[('company_id', 'in', company_ids)]`, correctement appliquées aux 5 groupes métier.

### 2.2 Modèles **sans** `ir.rule` alors qu'ils portent `company_id`

**Risque avéré** (Odoo ne filtre jamais automatiquement par société sans règle explicite — avoir un champ `company_id` sur un modèle ne restreint rien par lui-même) :

- `microfinance.loan.product`, `microfinance.savings.product`
- `microfinance.loan`, `microfinance.loan.application`
- `microfinance.loan.installment`, `microfinance.loan.payment`
- `microfinance.loan.guarantee`, `microfinance.guarantee.valuation.rule`
- `microfinance.loan.reschedule.history` (+ `.line`)
- `microfinance.collection.visit`
- `microfinance.savings.account`, `microfinance.savings.transaction`

**Conséquence concrète** : un « Agent crédit » ou « Manager crédit » de l'agence A qui connaît (ou devine) l'ID d'un dossier de crédit de l'agence B peut aujourd'hui le consulter, voire le modifier selon les droits `perm_write` du groupe (`ir.model.access.csv` accorde `perm_write=1` à `group_microfinance_user` sur `microfinance.loan` par exemple) — via une URL directe, un rapport, ou tout écran qui ne filtre pas explicitement par `company_id` dans son domaine de vue. Avec 1 seule société active, ce trou est invisible ; avec 25 sociétés et des utilisateurs multi-agences ou des ID prévisibles, il devient exploitable.

**Effort estimé** : **moyen** — le pattern existe déjà (4 règles à dupliquer/adapter), mais il faut le décliner sur ~13 modèles, en distinguant les modèles à `company_id` réel (filtre direct) des modèles à `company_id` related (filtre équivalent, `store=True` donc indexable).

### 2.3 Domaines des champs `account.account` sur les produits — **point le plus critique**

**Constat** : tous les champs `Many2one('account.account', ...)` des deux modèles produits (26 champs sur `microfinance.loan.product`, 20 sur `microfinance.savings.product`) ne filtrent que par `account_type` (ex. `[('account_type', '=', 'income')]`). **Aucun ne filtre par `company_id`**, ni celui du produit en cours d'édition, ni celui de l'utilisateur.

Exemples : [microfinance_loan_product.py:61-64](../models/microfinance_loan_product.py#L61-L64), [microfinance_savings_product.py:54-57](../../microfinance_savings_management/models/microfinance_savings_product.py#L54-L57), et tous les champs comptables suivants dans ces deux fichiers.

**Risque avéré, conforme à l'hypothèse du prompt** : lors de la création du produit de crédit de l'agence B, le champ « Principal en cours - Individuel » proposera **tous les comptes PCEC de toutes les sociétés confondues**, y compris ceux de l'agence A. Une erreur de sélection (facilitée par des libellés de comptes souvent similaires entre agences si le plan comptable PCEC est dupliqué par société) entraînerait une écriture comptable de l'agence B sur un compte appartenant à l'agence A — erreur difficile à détecter a posteriori et à fort impact (états financiers faussés pour deux agences).

**Effort estimé** : **faible** — il s'agit d'ajouter `('company_id', '=', company_id)` (ou `current_company_id` selon contexte formulaire) à chacun des ~46 domaines. Mécanique et répétitif, mais aucune ambiguïté de conception : c'est un correctif de domaine de champ, pas une refonte.

---

## Étape 3 — Séquences et données numérotées

Toutes les séquences identifiées sont **globales à l'instance** (`company_id eval="False"`) :

| Séquence (`ir.sequence`) | Code | Fichier |
|---|---|---|
| Crédit microfinance (`CR/%(year)s/`) | `microfinance.loan` | [sequence.xml:3-9](../data/sequence.xml#L3-L9) |
| Remboursement microfinance (`PAY/%(year)s/`) | `microfinance.loan.payment` | [sequence.xml:10-16](../data/sequence.xml#L10-L16) |
| Compte épargne microfinance (`EP/%(year)s/`) | `microfinance.savings.account` | [ir_sequence_data.xml:3-9](../../microfinance_savings_management/data/ir_sequence_data.xml#L3-L9) |

Le dossier de crédit (`microfinance.loan.application`, champ `name`) utilise également `ir.sequence.next_by_code('microfinance.loan.application')` ([microfinance_loan_application.py:398](../models/microfinance_loan_application.py#L398)) — même mécanisme global ; la définition `ir.sequence` correspondante n'a pas été localisée dans un fichier de données dédié lors de cet audit et devra être vérifiée séparément (soit elle est absente et Odoo utilisera une séquence générique, soit elle existe ailleurs dans le module).

**Conséquence** : avec `company_id=False`, un seul compteur est partagé par les 25 agences. Concrètement, la numérotation `CR/2026/00001`, `CR/2026/00002`... s'incrémentera au fil de l'eau **toutes agences confondues**, dans l'ordre de création réel des dossiers, pas par agence. Une agence pilote isolée ne verra pas le problème ; il apparaîtra dès l'activation simultanée de plusieurs sociétés.

Ce point est **conforme à l'hypothèse du prompt** : un numéro de dossier de crédit propre à chaque agence (ex. reprise à 1 par agence, ou préfixe incluant un code agence) est l'attente usuelle en microfinance multi-agences, notamment pour la lecture terrain des numéros de dossier (les agents et clients associent souvent un numéro bas à « dossier ancien de l'agence », ce qui devient trompeur avec un compteur partagé).

**Effort estimé** : **faible** — Odoo supporte nativement les séquences par société : soit dupliquer chaque `ir.sequence` avec un `company_id` renseigné par agence (mécanisme standard `next_by_code` qui sélectionne la séquence correspondant à la société courante), soit ajouter `use_company_id` / un préfixe dynamique incluant le code société. Pas de refonte de modèle nécessaire, mais implique une décision produit (faut-il repartir de 1 par agence, ou garder un numéro unique global mais préfixé par agence ?) à valider avec CEFOR avant correction.

---

## Étape 4 — Impact sur les vues et menus

### 4.1 Tableau de bord — hypothèse mono-société assumée

Le modèle `microfinance.dashboard` ([microfinance_dashboard.py:19-20](../models/microfinance_dashboard.py#L19-L20)) et le contrôleur JSON `/microfinance/dashboard/data` ([microfinance_dashboard_controller.py:15,26](../controllers/microfinance_dashboard_controller.py#L15)) filtrent systématiquement sur `self.env.company` / `env.company` — c'est-à-dire **une seule société à la fois**, même si l'utilisateur a plusieurs sociétés cochées dans le sélecteur multi-société Odoo. `get_par_buckets(company_id)` ([microfinance_loan.py:210](../models/microfinance_loan.py#L210)) suit le même principe.

**Ce n'est pas un bug** en soi — pour un agent d'agence qui ne travaille que sur sa société, le comportement est correct et même souhaitable (pas de mélange de chiffres entre agences). **Mais** cela signifie qu'**aucune vue consolidée multi-agences n'existe** : un responsable de réseau qui veut voir le portefeuille total des 25 agences devra soit basculer société par société (changer 25 fois le sélecteur), soit s'appuyer sur un reporting externe (Odoo `read_group` standard, module BI, etc.) qui n'est pas couvert par ce dashboard custom.

**Effort estimé** : **élevé** si une vue consolidée est requise dès le pilote (nouvelle logique d'agrégation, choix du périmètre de droits pour la voir) — **nul** si le besoin HQ n'existe pas encore et peut attendre un prompt dédié.

### 4.2 Menus et actions

Aucun `search_default` ni domaine figé sur une société particulière n'a été trouvé dans [microfinance_menus.xml](../views/microfinance_menus.xml) ni [microfinance_savings_menus.xml](../../microfinance_savings_management/views/microfinance_savings_menus.xml) — les menus reposent uniquement sur des groupes (`groups="..."`), pas sur un filtre société. C'est le comportement Odoo standard : sans `ir.rule`, ces vues afficheront **toutes les sociétés mélangées** dès qu'un utilisateur (notamment "Manager crédit" ou "Auditeur", qui ont souvent accès à plusieurs sociétés) aura plus d'une société autorisée — ce qui recoupe directement le gap de l'étape 2.2 : c'est la contrepartie visible en interface du manque de `ir.rule`.

### 4.3 Champ `company_id` masqué en mono-société

Les vues formulaire de `microfinance.loan.product` et `microfinance.savings.product` affichent `company_id` avec `groups="base.group_multi_company"` — comportement standard Odoo, correct : le champ n'apparaîtra que lorsque le mode multi-société sera activé (plus d'une société existante), donc invisible aujourd'hui mais prêt pour le déploiement. Aucune action requise ici.

**Effort estimé** : faible — la correction des menus/vues découle mécaniquement de la mise en place des `ir.rule` (étape 2.2) ; il n'y a pas de correctif de vue indépendant à faire.

---

## Synthèse des efforts avant l'agence pilote

| # | Point | Risque | Effort |
|---|---|---|---|
| 2.3 | Domaines `account.account` non filtrés par société sur les produits | **Élevé** (erreur comptable inter-agences) | Faible |
| 2.2 | `ir.rule` manquantes sur ~13 modèles métier | **Élevé** (fuite de données inter-agences) | Moyen |
| 3 | Séquences `ir.sequence` globales, non par société | Moyen (numérotation trompeuse) | Faible (+ décision métier) |
| 1.4 | `res.partner` partagé entre sociétés | À trancher, pas un défaut en soi | Faible à moyen selon décision |
| 4.1 | Pas de vue consolidée multi-agences | Faible si non requis au pilote | Élevé si requis |
| 1.2 / 1.3 | `company_id` sur modèles satellites crédit/épargne | Aucun — déjà conforme | — |

**Recommandation d'ordre de traitement** (à valider) : 2.3 → 2.2 → 3 → décision sur 1.4 → 4.1 si besoin exprimé par CEFOR.
