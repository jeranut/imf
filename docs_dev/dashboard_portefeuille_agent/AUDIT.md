# LOT 0 — Audit : Dashboard Portefeuille par Agent de Crédit / Agence

Audit exploratoire en **lecture seule**. Aucune ligne de code métier, de vue, de données ou
de sécurité n'a été modifiée. Recensement des données réelles fait par requêtes SQL brutes en
lecture sur la base `SEFOR` (seule base où les modules microfinance sont installés ; la base
`CEFOR` ne contient pas ces modules).

> ⚠️ **Base de test, pas de production.** `SEFOR` ne contient que **4 crédits** (2 `approved`,
> 1 `avis_cdag`, 1 `active`), **4 emprunteurs distincts**, **tous rattachés à la société 1
> (CEFOR Isotry)**, **tous avec le même `officer_id` = user 2 (`Administrator`)**, et **11
> sociétés** (pas 25). Aucun constat statistique n'est possible : il n'existe aujourd'hui
> aucun cas de rang ≥ 2, aucun cas multi-agent, aucun cas cross-agence, aucun crédit clôturé
> ou en défaut. Les constats ci-dessous portent donc sur le **code** ; les vérifications sur
> données réelles sont marquées « non testable en l'état ».

---

## 1. Champ `officer_id` — état des lieux

### 1.1 Définition

`microfinance_loan.py:91` :

```python
officer_id = fields.Many2one('res.users', string='Agent crédit',
                             default=lambda self: self.env.user, tracking=True)
```

- Type : `Many2one` → `res.users`.
- `required` : **non** (confirmé aussi côté base : `ir_model_fields.required = f`).
- Domaine : **aucun**. Ni dans la définition du champ, ni dans la vue formulaire
  (`microfinance_loan_views.xml:192`, `<field name="officer_id"/>` nu, onglet *Dossier >
  Suivi*), ni via un `@api.onchange` (grep `officer_id` sur `microfinance_loan.py` : une seule
  occurrence, la ligne 91). **Rien ne filtre les utilisateurs proposés par la société du
  crédit.**
- `default` : l'utilisateur courant à la création — donc en pratique toujours renseigné, mais
  par un défaut technique, pas par un choix métier.
- Champs voisins de même nature, tout aussi libres : `manager_id` (`:92`),
  `finance_user_id` (`:93`), `collection_agent_id` (`:94`).

### 1.2 Taux de renseignement / dossiers orphelins

`SEFOR` : **4 / 4 crédits ont un `officer_id`** (0 orphelin). Mais l'échantillon est trivial
et 100 % pointent sur le super-utilisateur `Administrator`. **Non représentatif** : sur une
vraie base, `officer_id` n'étant pas `required`, des dossiers historiques sans agent sont
possibles — le Lot 1 devra prévoir un libellé « (non assigné) » et un bucket dédié dans les
agrégations plutôt que de les masquer.

### 1.3 Groupe(s) de sécurité des agents

Il **n'existe aucun groupe dédié « agent de crédit assignable »**. Le groupe le plus proche
est `group_microfinance_user` (`security/groups.xml:8`, libellé **« Agent crédit »**), qui est
le socle impliqué par presque tous les autres groupes microfinance. Conséquences :

- `officer_id` accepte **n'importe quel `res.users`** — y compris un utilisateur inactif, un
  utilisateur d'une autre agence, ou un utilisateur sans aucun groupe microfinance.
- Sur `SEFOR`, l'unique `officer_id` (user 2) est membre de 10 groupes microfinance
  (`Agent crédit`, `Manager crédit`, `Finance`, `Comptable`, `Caissier`, `Comité de crédit`,
  `Gestionnaire`, + les 3 rôles workflow). Impossible d'en déduire une convention.

Liste complète des groupes (`security/groups.xml`) : `group_microfinance_user` (Agent
crédit), `group_microfinance_manager` (Manager crédit, implique user),
`group_microfinance_finance` (implique user), `group_microfinance_collection_agent` (Agent
recouvrement, implique user), `group_microfinance_auditor` (autonome), `group_microfinance_
comptable` (autonome), `group_microfinance_cashier` (implique user), `group_microfinance_
credit_committee` (implique user), `group_microfinance_gestionnaire` (implique manager +
finance), `group_application_surveyor` / `group_application_ca` / `group_application_cdag`
(rôles du workflow d'instruction).

### 1.4 Cohérence `officer_id` ↔ agence

- **Aucune contrainte serveur.** Aucun `@api.constrains` de `microfinance_loan.py` ne vérifie
  que `officer_id` a accès à `company_id` (ni que `officer_id.company_ids` contient
  `loan.company_id`). Même constat que celui déjà signalé pour `loan.company_id` vs
  `partner_id.company_id` dans `docs_dev/carnet_remboursement/AUDIT_compteur_findramana_faha.md`
  §3 : la règle « un intervenant appartient à l'agence du dossier » est une règle métier non
  re-vérifiée techniquement au niveau du crédit.
- **Non testable sur données réelles** : les 4 crédits sont sur la société 1 et l'unique
  `officer_id` (Administrator) a les 11 sociétés dans `company_ids` — aucune violation
  constatable, mais rien ne l'empêche (import, changement de société courante à la création,
  réassignation manuelle).
- Le **cloisonnement multi-société du dashboard reste garanti** par ailleurs (cf. §8) : même
  si un `officer_id` « étranger » était posé, le crédit resterait rattaché à sa `company_id`
  et invisible hors de cette agence. Le risque est un agent qui apparaît dans le portefeuille
  d'une agence qui n'est pas la sienne, pas une fuite de données entre agences.

---

## 2. Encours — définition et disponibilité

### 2.1 Champs / méthodes existants

| Source | Sémantique | Stocké ? | Portée |
|---|---|---|---|
| `microfinance_loan.py:181` `balance_total` (compute `_compute_totals`) | `sum(installment_ids.residual_amount)` si échéancier généré, sinon `loan_amount`. **Inclut principal + intérêts + pénalités résiduels**, y compris les intérêts des échéances futures non encore courues. | **oui** (`store=True`) | par dossier |
| `microfinance_loan.py:1766` `_get_principal_outstanding()` | `sum(principal_amount) - sum(paid_principal)`, sinon `loan_amount`. **Principal restant dû uniquement.** | non (méthode) | par dossier |
| `microfinance_loan.py:182` `overdue_amount` | `sum(residual_amount)` des seules échéances `state == 'overdue'`. | **oui** | par dossier |
| `microfinance_loan.py` `provision_amount` (`_compute_provision`, `:713`) | `balance_total × taux` selon `microfinance.provision.rule` et jours de retard. | **oui** | par dossier |

### 2.2 Agrégats d'encours déjà existants (doublons potentiels à connaître)

1. **`microfinance.dashboard._compute_dashboard`** (`microfinance_dashboard.py:25`) :
   `outstanding_amount = sum(active.mapped('balance_total'))` — **`state == 'active'` seul**,
   société courante.
2. **Contrôleur HTTP** `microfinance_dashboard_controller.py:39` :
   `outstanding_amount = sum(portfolio_loans.mapped('balance_total'))` avec
   `portfolio = state in ('active', 'defaulted')`.
3. **`get_par_buckets`** (`microfinance_loan.py:687-694`) : même définition de portefeuille
   (`active` + `defaulted`), `outstanding_amount` sert de dénominateur au PAR.
4. **`microfinance.fond.credit`** (`microfinance_fond_credit.py:211`) :
   `sum(loan._get_principal_outstanding())` sur `state in ('approved', 'active')` — **définition
   différente** (principal seul, périmètre différent).

➡️ **Deux définitions d'« encours » coexistent déjà dans le code** : `balance_total`
(principal + intérêts + pénalités) pour le dashboard/PAR, et `_get_principal_outstanding()`
(principal seul) pour le fonds bailleur. Le dashboard actuel valorise donc l'encours
**intérêts futurs compris** — visible sur `SEFOR` : un crédit `approved` de 500 000 affiche
`balance_total = 583 076,92` (= 500 000 principal + 83 076,92 d'intérêts sur 24 échéances).
Au regard de la règle **comptabilité en engagement de trésorerie** (pas de produit d'intérêt
couru non perçu), un encours de portefeuille devrait vraisemblablement être le **principal
restant dû** (`_get_principal_outstanding`), pas `balance_total`. → **Question bloquante n°5.**

### 2.3 Niveau d'agrégation : `microfinance.loan` vs `microfinance.loan.account`

- `microfinance.loan.account` (`microfinance_loan_account.py`) est un **conteneur vide** :
  `name`, `partner_id`, `company_id`, `loan_ids`, `loan_count`. **Aucun champ de solde, de
  montant, de statut** — absence volontaire, décision Micka documentée dans la docstring du
  modèle (« pas de solde, pas de transactions, pas de statut […] tant qu'aucune logique métier
  n'a été demandée dessus »).
- ➡️ **L'encours ne peut être calculé qu'au niveau `microfinance.loan`.** Le compte crédit
  n'apporte rien pour ce dashboard.
- **Plusieurs crédits actifs pour un même client/compte** : possible dans le modèle
  (`loan_ids` est un One2many sans contrainte limitant à un actif ; `partner_company_unique`
  ne contraint que l'unicité *du compte*, pas des crédits). **Aucun cas réel** dans `SEFOR`
  (chaque emprunteur a exactement 1 crédit). Impact sur l'agrégation par agent : nul si on
  somme au niveau `microfinance.loan` (chaque crédit porte son propre `officer_id`) ; à
  signaler seulement si Micka veut un « nombre de clients » distinct du « nombre de dossiers ».

---

## 3. PAR (Portfolio At Risk) — 30 / 60 / 90 jours

### 3.1 Données de datation des retards — déjà disponibles

- `microfinance.loan.installment.due_date` (Date, **indexée**, `:12`).
- `microfinance.loan.installment.state` : `pending` / `partial` / `paid` / `overdue`
  (`microfinance_loan_installment.py:21-26`), compute `_compute_state` (`:52`).
- `arrears_onset_date` / `arrears_cured_date` (`:28-39`) : **historique persistant** des
  épisodes de retard, posé/effacé par `_sync_arrears_state` (`:65`).
- Date de paiement effectif : `microfinance.loan.payment.payment_date` (`microfinance_loan_
  payment.py:35`).

### 3.2 « Jours de retard » — déjà calculé, mais non stocké

`microfinance_loan.py:624` `_get_max_overdue_days()` :

```python
overdue = self.installment_ids.filtered(lambda l: l.state == 'overdue')
max_days = max((today - line.due_date).days for line in overdue)   # sinon 0
```

**Méthode, pas de champ stocké.** Il n'existe **aucun champ « jours de retard »** en base, ni
sur `microfinance.loan`, ni sur `microfinance.loan.installment` (seul `arrears_onset_date` est
persisté). Pour un PAR performant à l'échelle (cf. §9), un champ `max_days_overdue` stocké et
rafraîchi par le cron quotidien serait à envisager en Lot 1.

### 3.3 PAR déjà implémenté — `get_par_buckets`

`microfinance_loan.py:686-710`. Tranches `1-30`, `31-60`, `61-90`, `90+`. Pour chaque crédit
`state in ('active', 'defaulted')` :

- si `_get_max_overdue_days() <= 0` → ignoré ;
- sinon, **la totalité de `balance_total`** du crédit est versée dans la tranche correspondant
  à son `max_days` ;
- valeur retournée = `montant_tranche / sum(balance_total du portefeuille) × 100`.

Testé par `tests/test_dashboard_par.py` (exclusion des `written_off` vérifiée).

**Écarts avec une définition PAR standard, à arbitrer :**

1. Numérateur et dénominateur en **`balance_total`** (principal + intérêts + pénalités), pas
   en principal restant dû. Le PAR réglementaire se calcule habituellement sur le **capital
   restant dû**.
2. Le crédit bascule **en entier** dès la 1ʳᵉ échéance en retard (comportement standard du PAR
   — « l'encours du prêt à risque », pas seulement l'échéance impayée). OK, mais à confirmer.
3. **Fraîcheur** : `installment.state` ne passe pas à `overdue` tout seul (aucun `@api.depends`
   sur « aujourd'hui », commentaire `microfinance_loan_installment.py:66`). Le passage est
   fait par le cron `cron_update_overdue_and_penalties` (`data/cron.xml`, **1 jour, actif,
   `numbercall = -1`**). Le PAR est donc juste à ~24 h près **tant que le cron tourne**.

### 3.4 Échéanciers obsolètes — statut à jour

Le prompt cite `IS/000289` et `IS/001076` comme porteurs d'échéanciers obsolètes
(`installment_ids readonly`). **Ce bug a été corrigé dans un lot antérieur** (`docs_dev/
echeancier_obsolete_readonly/STATUS.md` : `write()` régénère `installment_ids` sur les états
éditables). Vérification base `SEFOR` ce jour :

| Crédit | `state` | `term` | nb échéances | verdict |
|---|---|---|---|---|
| IS/000289 | avis_cdag | 24 | 24 | cohérent |
| IS/001076 | active | 24 | 24 | cohérent |
| IS/003362 | approved | 24 | 24 | cohérent |
| IS/003363 | approved | 24 | 24 | cohérent |

➡️ **Aucun échéancier obsolète à exclure aujourd'hui.** Le Lot 1 devra néanmoins garder un
garde-fou : flaguer (et non inclure silencieusement) tout crédit où `term ≠
len(installment_ids)` ou `state ∈ (active, defaulted)` sans échéancier.

### 3.5 Anomalie détectée — retards sur dossier non décaissé

`IS/000289` est en `state = 'avis_cdag'` (jamais décaissé, `disbursement_date` vide) mais
possède **24 échéances générées, dont 2 en `state = 'overdue'`** avec `arrears_onset_date`
posé, `overdue_amount = 50 000`, `balance_total = 583 076,92`. Un échéancier a été généré en
phase d'aperçu/test avec des `due_date` désormais dans le passé.

- `get_par_buckets` **l'exclut correctement** (portée `state in ('active', 'defaulted')`).
- **Mais** le contrôleur HTTP `microfinance_dashboard_controller.py` scanne les échéances par
  `Installment.state == 'overdue'` **sans filtrer sur `loan.state`** : `monthly_overdue`
  (`:62-70`), `overdue_installments` et surtout `top_overdue_loans` (`:137-157`). `IS/000289`
  et ses 50 000 **apparaissent donc dans le graphe « Évolution des impayés » et le top 10 des
  impayés du dashboard existant** alors que le crédit n'est pas décaissé. Bug **pré-existant**,
  hors périmètre de correction ici, mais **le Lot 1 doit filtrer `loan.state ∈ (active,
  defaulted)` dans tout calcul de retard par agent**, sinon le PAR par agent sera faussé de la
  même façon.
- La recherche « Avec impayés » de la vue liste (`microfinance_loan_views.xml:48`,
  `[('overdue_amount','>',0)]`) remonte elle aussi `IS/000289`.

### 3.6 Définition CSBF / PCEC 2005

**Introuvable dans le dépôt.** `grep -rn "PAR\|CSBF\|PCEC 2005\|portefeuille à risque"` sur
`docs_dev/` et le code : aucune définition réglementaire écrite. Les seules occurrences de
« PAR » sont la logique de `get_par_buckets` elle-même et des mentions incidentes dans des
audits sans rapport. → **Question bloquante n°1** (base de calcul officielle à fournir par
Micka).

---

## 4. Taux de remboursement

- **Indicateur déjà existant** : `_get_scoring_metrics` (`microfinance_loan.py:782`)
  `repayment_rate = total_paid / total_due × 100`, où
  `total_due = sum(installments.total_amount)` et
  `total_paid = sum(posted payments.amount)` — **par client, tous crédits, sans borne de
  période**.
- **Agrégat mensuel déjà existant** : contrôleur `microfinance_dashboard_controller.py:56-60`
  `monthly_repayment` = `sum(payment.amount)` groupé par mois de `payment_date`, sur
  `microfinance.loan.payment` `state == 'posted'`, société courante.
- **Données brutes disponibles** : `microfinance.loan.payment` (`payment_date`, `amount`,
  `state`, `loan_id` → `loan_id.officer_id`, `company_id` en `related` stocké). Reconstituer
  « montant perçu / montant dû par agent et par période » est donc faisable par jointure
  paiement → crédit → `officer_id`. `SEFOR` : 5 paiements `posted`, tous sur `IS/001076`.
- Ventilation principal / intérêt / pénalité disponible par paiement :
  `allocated_principal` / `allocated_interest` / `allocated_penalty` (`:45-47`, `readonly`),
  utile si Micka veut un taux de recouvrement du **capital** distinct du total encaissé.

---

## 5. Nombre de dossiers actifs / en retard

### 5.1 Valeurs de `state` (`microfinance_loan.py:79-90`)

`draft`, `enquete`, `avis_ca`, `avis_cdag`, `approved`, `active`, `closed`, `defaulted`,
`written_off`, `cancelled`.

### 5.2 Conventions « actif » déjà utilisées dans le code (divergentes)

| Endroit | Définition de « actif » / portefeuille |
|---|---|
| `microfinance_dashboard.py:19` | `state == 'active'` seul |
| `microfinance_dashboard_controller.py:27` (KPI « crédits actifs ») | `state == 'active'` seul |
| `microfinance_dashboard_controller.py:30`, `get_par_buckets` | portefeuille = `active` + `defaulted` |
| `microfinance_dashboard_controller.py:29` (« décaissé ») | `active` + `closed` + `defaulted` |
| `docs_dev/carnet_remboursement/…faha.md` §4 (« crédit engagé ») | `active` + `closed` + `defaulted` + `written_off` |

➡️ Pas de définition unique. → **Question bloquante n°2.**

### 5.3 « À jour » vs « en retard »

Disponible simplement : `overdue_amount > 0` (champ stocké, `microfinance_loan.py:182`). Déjà
utilisé comme `decoration-warning` de la vue liste (`microfinance_loan_views.xml:7`) et comme
filtre « Avec impayés » (`:48`). Alternative plus fine : `_get_max_overdue_days() > 0` (non
stocké). Attention au biais §3.5 (filtrer `loan.state`).

---

## 6. Rotation du portefeuille

- **Décaissements** : `disbursement_date` (Date, `readonly`, `microfinance_loan.py:61`),
  `loan_amount`. `disbursement_date` **vide tant que le crédit n'est pas décaissé**. Agrégat
  mensuel déjà présent (`microfinance_dashboard_controller.py:50-54`, `monthly_disbursement`).
- **Encours moyen sur période : INDISPONIBLE.** `balance_total` est un champ calculé
  *point-in-time* (valeur instantanée, `store=True` mais **pas d'historisation**). Il n'existe
  **aucun modèle de snapshot / valorisation périodique** du portefeuille. `arrears_onset_date`
  / `arrears_cured_date` historisent les épisodes de retard, pas le solde.
- **Aucune agrégation temporelle dans le modèle** : les séries « 12 derniers mois » du
  dashboard sont reconstruites à la volée dans le contrôleur à chaque requête (dictionnaires
  `dict.fromkeys(month_keys, 0.0)`), rien n'est persisté.
- Conséquence : une rotation « décaissements de la période / encours moyen de la période »
  n'est **pas calculable exactement** avec l'existant. Options pour le Lot 1 :
  (a) ajouter un **snapshot mensuel** de l'encours par agent (nouveau modèle + cron) ;
  (b) approximation grossière `(encours_fin + encours_début) / 2` — mais `encours_début` n'est
  pas récupérable rétroactivement ;
  (c) proxy « remboursements de capital de la période / encours courant ».
  → **Question bloquante n°3.**

---

## 7. Patterns de vue existants

- **Dashboard client OWL** : `action_microfinance_dashboard_client` (ir.actions.client, tag
  `microfinance_loan_dashboard`, `microfinance_dashboard_views.xml:30`). Composant
  `static/src/js/microfinance_loan_dashboard.js` + template `static/src/xml/microfinance_loan_
  dashboard.xml` (navigation **multi-onglets** par `topic`) + `scss`. Graphes via **ApexCharts**
  embarqué (`static/lib/apexcharts/apexcharts.min.js`). Données par un unique endpoint JSON
  `/microfinance/dashboard/data` (`microfinance_dashboard_controller.py`), **étendu par
  héritage** dans `microfinance_savings_management` (`microfinance_savings_dashboard_
  controller.py`, `super().dashboard_data()` + ajout de KPI épargne). **C'est le patron à
  reprendre** pour un nouveau dashboard riche.
- **Dashboard « form » minimaliste** : `microfinance.dashboard` (`microfinance_dashboard_
  views.xml:4`), 5 KPI en lecture seule, singleton.
- **Dashboard caisse** : `microfinance_caisse_pos*` (autre client action).
- **Kanban** : `view_microfinance_loan_kanban` (`microfinance_loan_views.xml:19`,
  `default_group_by="state"`). **Aucune vue `graph` ni `pivot`** n'existe pour
  `microfinance.loan`, `microfinance.loan.installment` ou `microfinance.loan.payment` dans
  aucun des deux modules.
- **`read_group`** déjà employé dans le contrôleur (`microfinance_dashboard_controller.py:43`,
  répartition par `state`).
- **Regrouper par « Agent »** déjà présent : `microfinance_loan_views.xml:53`
  `<filter name="group_agent" context="{'group_by':'officer_id'}"/>`.
- **Filtre « mes dossiers » / « mon agence » : INEXISTANT.** Aucun `search_default` ni filtre
  `[('officer_id','=',uid)]`. Le seul cloisonnement est le sélecteur de société standard +
  `ir.rule` (§8). Patron réutilisable pour un filtre société explicite :
  `microfinance_savings_account_views.xml:36`
  `<filter name="group_company" … groups="base.group_multi_company"/>`.

---

## 8. Sécurité et scope d'accès

### 8.1 Cloisonnement multi-société — solide

`security/microfinance_company_rules.xml` : `ir.rule` `domain_force =
[('company_id', 'in', company_ids)]`, **`groups` vide** (donc appliquée à *tous* les
internes, managers et auditeurs compris, non contournable) sur `microfinance.loan`,
`microfinance.loan.installment`, `microfinance.loan.payment`, `microfinance.loan.account`,
`microfinance.loan.guarantee`, `microfinance.collection.visit`, `microfinance.loan.reschedule.
history(.line)`, caisse, etc. **Aucune vue existante ne fuit entre agences** par domaine
erroné — vérifié sur `microfinance_loan_views.xml` (recherche sans domaine société implicite,
c'est l'`ir.rule` qui borne).

### 8.2 Exception assumée — matrice fonds bailleur

`microfinance_dashboard_controller.py:95` :
`fond_matrix = FondCredit.get_fond_matrix(env.user.company_ids.ids)` — **volontairement
multi-société** (toutes les agences de l'utilisateur, pas seulement la courante), documenté
dans la docstring de `get_fond_matrix`. C'est le **seul** panneau du dashboard qui montre du
cross-agence. ⚠️ **Un futur panneau « par agent » ne doit surtout pas copier ce patron** : il
doit rester scié sur `company.id`.

### 8.3 Accès `microfinance.dashboard` / dashboard client

- `ir.model.access.csv:44` : `access_microfinance_dashboard_user` → `group_microfinance_user`,
  **lecture seule**. Pas d'autre ligne (managers/auditeurs y accèdent via l'implication de
  `group_microfinance_user`, sauf `group_microfinance_auditor` qui est **autonome** et n'a
  donc **pas** accès au modèle `microfinance.dashboard` aujourd'hui — à vérifier si un
  auditeur doit voir le nouveau dashboard).
- `_compute_dashboard` et le contrôleur travaillent tous deux sur `self.env.company`
  (société active) — **aucun filtrage par agent nulle part**.

### 8.4 Périmètres proposés (constat, pas décision)

| Rôle | Groupe candidat | Périmètre proposé |
|---|---|---|
| Agent de crédit | `group_microfinance_user` **seul** (sans `manager`) | son propre `officer_id` uniquement, dans son agence |
| Gestionnaire d'agence | `group_microfinance_manager` / `group_microfinance_gestionnaire` | tous les agents de l'agence active |
| Manager réseau / Auditeur / Direction | `group_microfinance_auditor` ou **nouveau groupe** `group_microfinance_direction` | toutes les agences de `env.user.company_ids` |

Points ouverts : (a) « agent seul » n'est pas distinguable proprement aujourd'hui puisque
`manager` **implique** `user` — il faudra tester `group_microfinance_manager` en négatif, ou
introduire un groupe explicite ; (b) la restriction « son propre portefeuille » n'existe pas
et nécessitera soit un `ir.rule` conditionnel, soit un domaine `[('officer_id','=',uid)]`
injecté côté action/contrôleur. → **Question bloquante n°4.**

---

## 9. Volumétrie et performance

- **`SEFOR` (test)** : 4 crédits, 96 échéances, 5 paiements, 4 emprunteurs, 11 sociétés.
  Négligeable.
- **Cible production** : 25 agences. Ordre de grandeur attendu : quelques milliers de crédits
  actifs toutes agences confondues.
- Coût d'un dashboard par agent :
  - `read_group` sur `microfinance.loan` par `officer_id` avec `sum` de `balance_total`,
    `overdue_amount`, `provision_amount`, `loan_amount` → **bon marché** (ces 4 champs sont
    `store=True`).
  - PAR par agent : nécessite `_get_max_overdue_days()` **par crédit** → **non stocké**, itère
    les échéances de chaque crédit. O(nb échéances) par crédit. À quelques milliers de crédits
    × ~20 échéances, un calcul Python à la volée par requête HTTP devient sensible.
- Recommandation Lot 1 : envisager un **champ stocké `max_days_overdue`** (ou `days_overdue`)
  sur `microfinance.loan`, rafraîchi par le cron quotidien déjà en place
  (`cron_update_overdue_and_penalties`), ce qui rend le PAR par agent calculable en pur
  `read_group`. Une vue SQL n'est pas nécessaire à ce volume si ce champ existe. Au volume
  `SEFOR` actuel, l'ORM à la volée suffit — la décision dépend de la volumétrie réelle cible à
  confirmer.

---

## Anomalies détectées (récapitulatif)

| # | Objet | Constat | Gravité | Action |
|---|---|---|---|---|
| A1 | `IS/000289` | `state = avis_cdag` (non décaissé) mais 24 échéances générées dont 2 `overdue`, `overdue_amount = 50 000`. Remonte à tort dans « top impayés » et « évolution des impayés » du dashboard existant (contrôleur ne filtre pas `loan.state`). | Moyenne (pré-existant) | Ne pas corriger ici. **Lot 1 : filtrer `loan.state ∈ (active, defaulted)` dans tout calcul de retard.** |
| A2 | `officer_id` | Aucune contrainte serveur `officer_id` ↔ `company_id` ; `Many2one` libre vers tout `res.users`, non `required`, sans domaine. | Faible (aucun cas réel) | Signalement à Micka. |
| A3 | Encours | Deux définitions concurrentes dans le code : `balance_total` (principal + intérêts + pénalités) vs `_get_principal_outstanding()` (principal seul). Dashboard/PAR utilisent `balance_total` → encours gonflé des intérêts non courus, en tension avec la compta cash-basis. | Moyenne | → Question bloquante n°5. |
| A4 | PAR | `get_par_buckets` = seul calcul PAR existant ; basé sur `balance_total`, aucune définition CSBF/PCEC 2005 écrite dans le dépôt. | Moyenne | → Question bloquante n°1. |
| A5 | Fraîcheur retards | `installment.state → overdue` dépend du cron quotidien `cron_update_overdue_and_penalties` (actif). Si le cron est arrêté, PAR et « en retard » se figent silencieusement. | Faible | Vérifier l'exécution du cron avant mise en prod du dashboard. |
| A6 | Accès | `group_microfinance_auditor` est autonome et n'a pas accès au modèle `microfinance.dashboard` (ligne CSV réservée à `group_microfinance_user`). | Faible | À trancher avec le scope (question n°4). |
| A7 | Rotation | Aucune historisation de l'encours ; rotation exacte non calculable sans nouveau snapshot. | Moyenne | → Question bloquante n°3. |

---

## Questions bloquantes à valider par Micka (avant tout Lot 1)

1. **Définition exacte du PAR.** Base de calcul : (a) **capital restant dû** en retard /
   encours capital total (définition réglementaire usuelle), ou (b) `balance_total` en retard
   / `sum(balance_total)` comme le fait déjà `get_par_buckets` ? Fournir la référence
   CSBF / PCEC 2005 applicable. Tranches confirmées `1-30 / 31-60 / 61-90 / 90+` ? Un crédit
   bascule-t-il **en entier** dès la 1ʳᵉ échéance en retard (comportement actuel) ?

2. **Valeurs de `state` comptant comme « dossier actif »** pour ce dashboard :
   `active` seul, ou `active` + `defaulted` ? Les `defaulted` restent-ils dans le portefeuille
   de l'agent ? Les `written_off` sont exclus (confirmé par l'existant).

3. **Rotation du portefeuille** : granularité (mensuelle / trimestrielle / annuelle) et
   méthode. Accepte-t-on d'ajouter un **modèle de snapshot mensuel de l'encours par agent**
   (+ cron) en Lot 1, ou se contente-t-on d'un proxy « remboursements de capital de la période
   / encours courant » ? Numérateur = décaissements ou remboursements ?

4. **Scope d'accès par groupe** (qui voit quoi) :
   - Un agent (`group_microfinance_user` seul) voit-il **uniquement son `officer_id`** ?
     Restriction par `ir.rule` ou par domaine d'action ?
   - Un gestionnaire d'agence voit-il **tous les agents de son agence active** ?
   - Qui voit **toutes les agences** : `group_microfinance_auditor`, `group_microfinance_
     gestionnaire`, ou faut-il **créer un groupe `group_microfinance_direction`** ?
   - Faut-il un groupe explicite « agent de crédit assignable » pour cadrer `officer_id` ?

5. **Niveau et définition de l'encours** :
   - Agrégation au niveau `microfinance.loan` (seul possible : `loan.account` est un conteneur
     vide) — **confirmer**.
   - Encours = **principal restant dû** (`_get_principal_outstanding`, cohérent cash-basis) ou
     **`balance_total`** (principal + intérêts + pénalités, comme le dashboard actuel) ?
   - Traitement des dossiers **sans `officer_id`** : bucket « (non assigné) » visible, ou
     exclus ?

**Aucune implémentation ne doit démarrer avant validation explicite de ces cinq points.**

---

*Audit réalisé le 2026-09-06. Aucune modification de code, de vue, de données ou de sécurité.*

---
---

# LOT 0 bis — Audit complémentaire (version enrichie du dashboard)

Additif à l'audit du 2026-09-06 (sections 1 à 9 ci-dessus **inchangées**). Périmètre étendu :
PAR cumulatif, agrégats mensuels, panneau échéances, sélecteur d'agent, table paginée,
boutons de raccourci. **Lecture seule, aucune modification.**

> **État des données `SEFOR` re-constaté le 2026-09-07** (via `odoo shell`, lecture) :
> **4 crédits**, tous `officer_id = Administrator` (user 2), tous **société 1 (CEFOR Isotry)**,
> **2 avec `disbursement_date`** renseignée sur 4, **11 sociétés**, **5 paiements `posted`**
> (tous datés du 2026-09-05), **5 échéances `paid`**. `user 2.tz = Indian/Antananarivo`
> (UTC+3, pas de changement d'heure). Toujours **aucun cas multi-agent ni cross-agence** →
> le point 4 (sélecteur d'agent) n'est **pas testable sur données réelles**, à couvrir par
> des tests forgés en Lot 1.
>
> **Rappel d'état du code** : aucune des méthodes du Lot 1 précédent n'existe encore —
> `grep` sur les deux modules : `_get_agent_portfolio_scope`, `get_par_buckets_by_agent`,
> `get_available_agents`, `get_agent_*` → **0 occurrence**. `officer_id` n'existe que sur
> `microfinance.loan` (`microfinance_loan.py:102`), **pas** en related sur
> `microfinance.loan.installment` ni `microfinance.loan.payment`. Le Lot 1 n'a pas démarré.

---

## B1. Faisabilité PAR cumulatif (point 1)

### B1.1 `_get_max_overdue_days()` réutilisable tel quel — **confirmé**

`microfinance_loan.py:643-651` :

```python
def _get_max_overdue_days(self):
    self.ensure_one()
    today = fields.Date.context_today(self)
    overdue = self.installment_ids.filtered(lambda l: l.state == 'overdue')
    max_days = 0
    for line in overdue:
        if line.due_date:
            max_days = max(max_days, (today - line.due_date).days)
    return max_days
```

- **Fonction pure**, retourne un scalaire `int`. **Aucun cache, aucun `@api.depends`, aucune
  mémoïsation, aucun `@tools.ormcache`.** Recalculée intégralement à chaque appel.
- **Aucune hypothèse d'usage « en tranches exclusives ».** Ses deux seuls appelants
  actuels :
  - `get_par_buckets` (`microfinance_loan.py:718-726`) : la logique `for label, min_days,
    max_days_bound in tranches: … break` qui range le crédit dans **une** tranche est **locale
    à cette méthode**, posée *au-dessus* du scalaire — ce n'est pas une propriété de
    `_get_max_overdue_days`.
  - `_compute_provision` (`microfinance_loan.py:743`) : compare `max_days` à des bornes de
    règle, usage cumulatif de fait (`min_days <= max_days`).
- ➡️ Pour un **PAR cumulatif** : `days = loan._get_max_overdue_days()` ; pour chaque seuil
  `t ∈ (30, 60, 90, 120)`, numérateur `PAR(t) = Σ balance_total` des crédits où `days >= t`.
  Indépendant par seuil, **monotone décroissant** (`PAR30 ≥ PAR60 ≥ PAR90 ≥ PAR120`).
  **Réutilisation directe, zéro modification de `_get_max_overdue_days`.**

### B1.2 Base commune donut / cartes cumulatives

`get_par_buckets` a été **durci depuis l'audit initial** : le domaine du portefeuille est
désormais `state in ('active','defaulted')` **ET `('disbursement_date','!=',False)`**
(`microfinance_loan.py:712-717`, mitigation de l'anomalie A1). `get_cumulative_par_by_agent`
(§1.7) et `get_par_buckets_by_agent` **doivent recopier ces trois filtres** + `officer_id`
renseigné. Dénominateur commun = `Σ balance_total` du même périmètre.

### B1.3 Réserves

- **Performance** (identique à §9) : `_get_max_overdue_days()` **non stocké**, itère les
  échéances de chaque crédit, à chaque requête HTTP. Deux calculs PAR (exclusif + cumulatif)
  = risque de **double itération**. → **Reco : un seul passage** dans l'endpoint agent qui
  calcule `days` une fois par crédit et alimente *à la fois* le donut et les 4 cartes ; ne
  pas exposer deux méthodes qui rescannent chacune. → renforce la **Question bloquante n°9**
  (champ stocké `max_days_overdue`).
- **Base monétaire** : `balance_total` (principal + intérêts + pénalités) vs capital restant
  dû (`_get_principal_outstanding`) — **non tranché** (A3 / Question bloquante n°5), s'applique
  identiquement au PAR cumulatif.

---

## B2. Agrégats « ce mois » (point 2)

### B2.1 `disbursement_date` — OK

`Date` (pas `Datetime`), `readonly` (`microfinance_loan.py:61`), écrit uniquement par
`action_process_disbursement` (confirmé `docs_dev/guichet_caisse/AUDIT_decaissement.md`).
**Aucune composante horaire → aucune ambiguïté de fuseau sur le champ lui-même.**

### B2.2 « Mois courant » côté serveur

Le contrôleur existant utilise déjà `today = fields.Date.context_today(env.user)` puis
`month_start = today.replace(day=1)` (`microfinance_dashboard_controller.py:16-17`).
`user 2.tz = Indian/Antananarivo` (UTC+3, pas de DST). → **Reco : réutiliser
`fields.Date.context_today(env.user)`, pas `datetime.now()` nu** — cohérence avec l'existant
et robustesse si le serveur tourne en UTC. Fenêtre : `month_start = today.replace(day=1)` ;
`next_month = month_start + relativedelta(months=1)` ; domaine
`[('disbursement_date','>=',month_start),('disbursement_date','<',next_month)]`.

### B2.3 `read_group` — cohérent

- L'existant **n'utilise pas** `read_group` pour les séries mensuelles : il `search()` puis
  bucketise en Python par `strftime('%Y-%m')` (`microfinance_dashboard_controller.py:56-66`).
- Pour un **chiffre unique « mois courant »**, `read_group([… domaine mois + scope agent],
  ['loan_amount:sum'], [])` (ou `['__count']`) est **valide et bon marché** :
  `disbursement_date`, `loan_amount`, `officer_id` sont tous `store=True`. `disbursement_date`
  étant un `Date`, un `groupby` `disbursement_date:month` ne provoque **aucun décalage de
  fuseau**. Cohérent.
- `nb_credits_decaisses` / `montant_decaisse` : `read_group` direct sur `microfinance.loan`,
  OK.
- `remboursement_attendu` = `Σ installment.total_amount` où `due_date` dans le mois :
  **`microfinance.loan.installment` n'a pas de `officer_id`** (uniquement `partner_id`,
  `company_id`, `currency_id` en related — `microfinance_loan_installment.py:41-43`). Deux
  options : (a) domaine dotté `[('loan_id.officer_id','in',ids)]` — fonctionne en `search` et
  en filtre `read_group` (mais pas en `groupby`) ; (b) **ajouter le related stocké**
  (Lot 1 §1.1). → **Reco (b)** : le même champ sert le donut, le PAR, le panneau et les
  agrégats — un seul ajout.
- `remboursement_encaisse` = `Σ payment.amount`, `state='posted'`, `payment_date` dans le
  mois : **`microfinance.loan.payment` n'a pas de `officer_id`** non plus
  (`microfinance_loan_payment.py:32-51` : `partner_id`, `company_id` en related, pas
  `officer_id`). → **même reco : `officer_id = related('loan_id.officer_id', store=True)` à
  ajouter aussi sur `payment`** (le prompt Lot 1 §1.1 ne le prévoit que sur `installment`).
- `montant_en_retard` = réutiliser `overdue_amount` stocké (`microfinance_loan.py:182`) :
  `read_group ['overdue_amount:sum']`. **Mais** `overdue_amount` est non nul sur un crédit
  **non décaissé** porteur d'un échéancier d'aperçu (anomalie A1 — `IS/000289` :
  `overdue_amount = 50 000`). → filtrer `state in ('active','defaulted')` **ET**
  `disbursement_date != False`.

---

## B3. Panneau Échéances + « encaissé du jour » (point 3)

### B3.1 Filtres `due_date` — index OK

`microfinance.loan.installment.due_date` : `Date`, **`index=True`**
(`microfinance_loan_installment.py:12`). `('due_date','=',today)` et
`('due_date','>=',today+1),('due_date','<=',today+7)` sont tous deux servis par cet index.

### B3.2 `get_due_today` **ne convient pas tel quel**

`microfinance_loan_installment.py:82-93` :

```python
return self.search([
    ('company_id', '=', company_id),
    ('due_date', '=', today),
    ('state', '!=', 'paid'),
], order='due_date, loan_id')
```

- **Aucun filtre `loan_id.state`, aucun filtre `disbursement_date`** → **exposé à l'anomalie
  A1** : les échéances d'aperçu d'un crédit non décaissé remontent dans le panneau
  « Échéances du jour » du dashboard existant.
- À l'inverse, `get_pending_or_late` (guichet, `microfinance_loan_installment.py:95-132`)
  filtre **`loan_id.state in ('active','defaulted')` ET `loan_id.disbursement_date != False`**
  (docstring `:103-110`, explicitement « Ne pas l'omettre »).
- ➡️ `get_agent_due_dates_panel` (§1.9) **doit adopter les filtres stricts de
  `get_pending_or_late`**, pas réutiliser `get_due_today`.

### B3.3 Scope agent

`officer_id` absent d'`installment` → domaine dotté `[('loan_id.officer_id','in',ids)]` (le
panneau fait un `search` + agrégation Python sur un volume d'un jour / 7 jours par agent → le
dotté suffit ici même sans le related stocké). Cohérence : préférer quand même le related
stocké de B2.

- « nb clients concernés » = `len(set(installments.mapped('partner_id')))` — `partner_id`
  stocké related sur `installment` ✓.
- « montant attendu » = `Σ total_amount` ; « reste à recouvrer » : soit `Σ residual_amount`
  (déjà net des paiements partiels, calculé/stocké), soit `attendu − encaissé` (dépend de la
  définition « encaissé » ci-dessous). À trancher avec la définition retenue en B3.4.

### B3.4 « Montant encaissé du jour » — **deux définitions divergentes, divergence observée sur SEFOR**

| # | Définition | Calcul |
|---|---|---|
| **(a)** Flux de caisse du jour | `Σ payment.amount` où `state='posted'` **ET `payment_date = today`** (+ scope agent via `loan_id.officer_id`). Mesure **l'argent entré aujourd'hui**, quelle que soit l'échéance qu'il solde. |
| **(b)** Échéances du jour soldées | `Σ total_amount` (ou `paid_*`) des `installment` où **`due_date = today` ET `state = 'paid'`** (+ filtres A1). Mesure la **valeur faciale des échéances dues aujourd'hui** désormais réglées — a pu être payée plusieurs jours avant. |

**Divergence structurelle, pas un cas limite** — et **matérialisée dans les données `SEFOR`** :
les 5 paiements `posted` sont **tous datés du 2026-09-05** et soldent des échéances dues les
**2026-09-01 / 09-08 / 09-15 / 09-22 / 09-29**.

> Exemple concret : **au 2026-09-08**, le panneau afficherait « montant attendu » = 25 000
> (l'échéance due ce jour-là) ; « montant encaissé » vaut **0** selon (a) (aucun paiement daté
> du 09-08) mais **25 000** selon (b) (cette échéance est `paid`, réglée par anticipation le
> 09-05). Écart de 100 % sur le même jour.

- (a) correspond au sens opérationnel « ce que l'agent a encaissé aujourd'hui » ; le libellé
  du mockup (« montant encaissé ») penche pour (a).
- (b) correspond à « taux de tenue de l'échéancier du jour ».
- ➡️ **Point à trancher avec Micka avant de coder §1.9.** (Question bloquante n°6 ci-dessous.)

---

## B4. Sélecteur d'agent + contrôle serveur du scope (point 4)

### B4.1 `_get_agent_portfolio_scope()` — à créer (n'existe pas)

Logique cible : agent → `[self.env.user.id]` ; manager/gestionnaire → agents de la société
active ; auditeur → agents de toutes les `self.env.user.company_ids`.

- **« Agent seul » non distinguable proprement** : `group_microfinance_manager` **implique**
  `group_microfinance_user` (`security/groups.xml:15`) — un manager *est* un user. Détecter
  « uniquement agent » impose un test en négatif fragile
  (`has_group('…user') and not has_group('…manager') and not has_group('…gestionnaire')
  and not has_group('…auditor')`). → **Reco : groupe explicite** (déjà Question bloquante
  n°4 de l'audit initial), **non résolu**.

### B4.2 `get_available_agents()` — faisable, bon marché

`read_group` sur `microfinance.loan` par `officer_id`, domaine `state in ('active',
'defaulted')` (+ `disbursement_date != False` à confirmer), `company_id in <scope>`.
`officer_id` **stocké** → `read_group` peu coûteux. Pour l'auditeur multi-société : ajouter
`company_id` au `groupby` → un agent ayant des dossiers dans 2 agences ressort **une ligne par
agence** (comportement voulu par le prompt « avec indication d'agence »).

### B4.3 Contrôle serveur du scope — **obligatoire et faisable**

Chaque méthode §1.7 à §1.9 doit :

1. calculer `allowed = get_available_agents()` **pour `self.env.user`** (jamais un paramètre
   client) ;
2. si un `officer_id_filter` est transmis : vérifier `officer_id_filter in allowed` →
   sinon `raise AccessError`, **avant** toute injection dans un domaine.

L'`ir.rule` `company_id in company_ids` (audit initial §8.1) borne la **société** mais
**n'empêche pas** un manager de la société A de demander l'agent X (société A) qui n'est pas
« le sien » : c'est `get_available_agents()` qui borne à l'intérieur d'une agence, d'où
l'obligation de la confrontation serveur. **Non contournable par paramètre d'URL/RPC** si la
confrontation est faite dans chaque méthode.

Sur `SEFOR` : **non testable** (1 agent, 1 société avec dossiers) → tests forgés Lot 1
requis (≥ 2 agents, ≥ 2 sociétés, un utilisateur agent essayant de forcer l'`officer_id`
d'un collègue → `AccessError`).

---

## B5. Table clients paginée (point 5)

- **Aucune action de liste existante ne fait de pagination serveur custom.**
  `action_microfinance_loan` (`microfinance_loan_views.xml:361`) = vue `tree` standard,
  `search_default_active`, filtre `group_agent` déjà présent (`:53`), **pas d'endpoint JSON**.
- Le rendu du mockup (recherche inline, pagination numérotée « 1 2 3 … 13 », colonnes
  spécifiques) n'est pas réalisable proprement avec une vue `tree` embarquée.
- Volume cible (audit initial §9) : « quelques milliers de crédits actifs toutes agences »,
  quelques centaines par agent — voire × N agents si le scope est « toute l'agence » pour un
  manager. Un chargement complet côté client serait (a) coûteux à ce cumul, (b) incohérent
  avec le reste de l'écran (KPI/PAR déjà agrégés serveur).
- ➡️ **Nouvel endpoint dédié, pagination serveur.** Signature type :
  `get_agent_portfolio_table(company_ids, officer_id_filter, search=None, offset=0,
  limit=20, order=None)` → `{'rows': [...], 'total': <search_count>, 'offset', 'limit'}`.
  `search()` + `search_count()` sur `microfinance.loan`, domaine scope + `officer_id` +
  `ilike` sur `name` / `partner_id.name`. Champs de ligne (`balance_total`, `overdue_amount`,
  `loan_amount`, `disbursement_date`, `state`, `partner_id`) tous `store=True` → pas de
  calcul par ligne, **sauf** `_get_max_overdue_days()` si une colonne « jours de retard » est
  demandée → argument de plus pour un `max_days_overdue` stocké (Question bloquante n°9).

---

## B6. Boutons de raccourci — actions existantes (point 6)

Recensement (xmlids `microfinance_loan_management.*`) :

| Bouton (mockup) | Action existante réutilisable | Remarque |
|---|---|---|
| Nouveau client | `action_microfinance_client` (`microfinance_partner_views.xml:279`) | + `context` de création ; pas de nouvelle vue |
| Nouvelle demande de crédit | `action_microfinance_loan_application` (`microfinance_loan_application_views.xml:764`) | dossier d'instruction |
| Mes clients | `action_microfinance_client` + `domain`/`context` scope agent | **aucun filtre « mes » existant** sur res.partner → à passer via `context` du bouton |
| Mes crédits | `action_microfinance_loan` (`microfinance_loan_views.xml:361`) + `domain=[('officer_id','=',<agent>)]` | filtre `group_agent` existe, **pas de `search_default` « mes dossiers »** |
| Mes remboursements | `action_microfinance_payment` (`microfinance_loan_payment_views.xml:26`) + `domain=[('loan_id.officer_id','=',<agent>)]` | |
| Mes impayés | `action_microfinance_loan` + `domain=[('officer_id','=',<agent>),('overdue_amount','>',0)]` | le filtre `overdue` (`[('overdue_amount','>',0)]`) existe déjà (`microfinance_loan_views.xml:48`) |
| Mes échéances | `action_microfinance_installment` (`microfinance_loan_installment_views.xml:65`) + `domain=[('loan_id.officer_id','=',<agent>)]` | |
| Mes visites | `action_microfinance_visit` (`microfinance_collection_visit_views.xml:6`) + `domain=[('agent_id','=',<agent>)]` | champ = **`agent_id`** (`microfinance_collection_visit.py:13`), **pas** `officer_id` |

- **Aucune nouvelle `ir.actions.act_window` à créer.** Tous les boutons = action existante +
  `domain`/`context` passés à l'ouverture (`this.actionService.doAction` avec
  `additional_context` / `domain`, patron déjà employé dans le dashboard OWL).
- Le scope des boutons « Mes X » doit suivre le **sélecteur d'agent** (si un manager consulte
  l'agent X, « Mes crédits » → crédits de X), donc `domain` **paramétré par l'`officer_id`
  affiché**, pas figé sur `uid`.

---

## B7. Anomalies / points additionnels

| # | Objet | Constat | Action |
|---|---|---|---|
| A8 | `get_due_today` | Ne filtre ni `loan_id.state` ni `disbursement_date` → panneau « Échéances du jour » du dashboard existant exposé à l'anomalie A1 (échéances d'aperçu d'un crédit non décaissé). Pré-existant. | Ne pas corriger ici. **§1.9 doit reprendre les filtres stricts de `get_pending_or_late`.** |
| A9 | `officer_id` absent d'`installment` et de `payment` | Empêche tout `read_group` performant des agrégats mensuels / du panneau par agent. Lot 1 §1.1 ne le prévoit que sur `installment`. | **Ajouter `officer_id = related('loan_id.officer_id', store=True)` sur `installment` ET `payment`.** |
| A10 | « Encaissé du jour » | (a) `payment_date=today` vs (b) `installment.due_date=today` + `state='paid'` divergent — divergence **observée sur SEFOR** (5 paiements du 09-05 soldant des échéances du 09-01 au 09-29). | → Question bloquante n°6. |
| A11 | 2 calculs PAR | Donut exclusif + cartes cumulatives = 2 balayages `_get_max_overdue_days()` non stockés si implémentés séparément. | → Question bloquante n°9 (`max_days_overdue` stocké) + un seul passage dans l'endpoint. |

---

## B8. Questions bloquantes complémentaires (en plus des 5 de l'audit initial)

6. **« Montant encaissé du jour » du panneau Échéances** : définition **(a)** flux de
   paiements `payment_date = today`, ou **(b)** échéances `due_date = today` passées à
   `paid` ? Divergence structurelle démontrée sur données réelles `SEFOR` (cf. B3.4). À
   trancher **avant** de coder §1.9. En découle aussi la définition de « reste à recouvrer »
   (différence, ou `Σ residual_amount`).

7. **PAR cumulatif — base monétaire** : les cartes PAR30/60/90/120 et le donut de répartition
   partagent-ils la **même base d'encours** (à définir en Question bloquante n°5 :
   `balance_total` vs capital restant dû) ? Le prompt les veut « deux mesures différentes »
   mais ne précise pas si la base *monétaire* diffère. **Reco : même base monétaire, seule la
   logique de tranche change** (exclusive pour le donut, cumulative ≥ t pour les cartes).

8. **Graphe d'évolution du PAR (§2.1.6)** : aucune historisation n'existe (confirmé, audit
   initial §6 / A7). Chantier de snapshot mensuel à valider séparément — **point d'arrêt déjà
   prévu au Lot 2**. Si non validé : **omettre ce graphe de la V1**, le reste de l'écran est
   autonome.

9. **Champ `max_days_overdue` stocké** sur `microfinance.loan`, rafraîchi par le cron
   quotidien `cron_update_overdue_and_penalties` : désormais **3 consommateurs** en
   dépendent (PAR exclusif par agent, PAR cumulatif par agent, colonne « jours de retard » de
   la table paginée). Décision à acter en Lot 1 (esquissée §9 de l'audit initial).

10. **`officer_id` related stocké sur `payment`** (en plus d'`installment` prévu §1.1) :
    requis pour `remboursement_encaisse` par agent en `read_group`. À intégrer au §1.1.

---

*Audit complémentaire réalisé le 2026-09-07. Lecture seule — aucune modification de code, de
vue, de données ou de sécurité, aucun commit.*
