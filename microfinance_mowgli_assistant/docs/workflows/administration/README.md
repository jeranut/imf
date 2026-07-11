# Workflow Administration

## 1. Objectif métier

Paramétrage transverse du crédit, hors création des produits eux-mêmes : périodicités de remboursement (`microfinance.repayment.frequency`), règles de provisionnement selon l'ancienneté des arriérés (`microfinance.provision.rule`), cloisonnement multi-société/multi-agence (`ir.rule`), numérotation automatique (séquences), tâches planifiées (cron) et hook d'installation qui crée les sous-comptes et journaux PCEC dédiés.

Ce workflow ne couvre **pas** : la création des produits de crédit/épargne eux-mêmes (voir `creation_produit_credit` et `creation_produit_epargne`), ni la gestion des utilisateurs et l'attribution des groupes (voir `gestion_utilisateurs`). Le plan comptable PCEC lui-même est fourni par le module externe `plan_compta_pcec`, non une dépendance dure de `microfinance_loan_management` ; il n'est mentionné ici que parce que le hook d'installation y fait explicitement référence.

## 2. Utilisateurs concernés

- `group_microfinance_manager` (Manager crédit) : seul groupe donnant accès au menu « Configuration » ; droits complets (lecture/écriture/création/suppression) sur les périodicités de remboursement et les règles de provisionnement.
- `group_microfinance_finance` (Finance microfinance) et `group_microfinance_user` (Agent crédit) : lecture seule sur les périodicités et les règles de provisionnement.
- `group_microfinance_auditor` (Auditeur microfinance) : lecture seule sur les périodicités de remboursement (aucun accès listé sur les règles de provisionnement dans `ir.model.access.csv`).
- `group_microfinance_manager` et `group_microfinance_finance` : seuls groupes autorisés à déclencher l'action serveur « Comptabiliser les provisions ».
- Administrateur technique (hors groupes Microfinance) : exécute l'installation du module qui déclenche `post_init_hook`, et configure au besoin les séquences/cron via Réglages > Technique (fonctionnalités standard Odoo).

## 3. Menus utilisés

- Microfinance > Configuration > Périodicités de remboursement (`menu_microfinance_root` > `menu_microfinance_config` > `menu_microfinance_repayment_frequency`).
- Microfinance > Configuration > Règles de provisionnement (`menu_microfinance_root` > `menu_microfinance_config` > `menu_microfinance_provision_rule`).
- `menu_microfinance_config` n'est visible que pour le groupe `group_microfinance_manager` (attribut `groups` du `<menuitem>`).
- Les séquences (`ir.sequence`) et tâches planifiées (`ir.cron`) ne disposent d'aucun menu propre aux modules Microfinance ; elles se gèrent via les menus techniques standard d'Odoo (Réglages > Technique), hors périmètre des vues auditées ici.

## 4. Étapes principales

1. Microfinance > Configuration > Périodicités de remboursement : ajouter une ligne dans la liste éditable (nom, code technique, unité de période Jours/Mois, valeur, séquence d'affichage).
2. Microfinance > Configuration > Règles de provisionnement : ajouter une tranche (société, jours de retard min., jours de retard max. — 0 = illimité, taux de provision en %).
3. Le hook `post_init_hook` s'exécute automatiquement à l'installation du module, sans action utilisateur : pour chaque société dont `chart_template == 'mg_pcec'`, il crée les sous-comptes PCEC dédiés (`LOAN_NEW_SUBACCOUNTS`) puis les 7 journaux standards (`JOURNALS`) s'ils n'existent pas déjà.
4. Au quotidien, le cron `ir_cron_microfinance_overdue_penalties` (actif par défaut) applique les pénalités de retard et recalcule le scoring des crédits actifs, sans intervention manuelle.
5. Mensuellement (si le cron `ir_cron_microfinance_post_provisions` est activé — il est **inactif par défaut**) ou manuellement via l'action serveur « Comptabiliser les provisions » sur la liste des crédits, la comptabilisation des provisions est effectuée.

## 5. Champs importants

**`microfinance.repayment.frequency`** :
- Nom (`name`, requis, traduisible).
- Code (`code`, requis, unique) : « identifiant technique stable, référencé par la migration ».
- Unité de période (`period_kind`) : sélection Jours / Mois.
- Valeur de la période (`period_value`, requis, défaut 1) : doit être strictement positive.
- Séquence (`sequence`, défaut 10) : ordre d'affichage.

**`microfinance.provision.rule`** :
- Nom (`name`) : calculé automatiquement (`_compute_name`, stocké) à partir de min/max/taux.
- Jours de retard min. (`min_days`, requis, défaut 0).
- Jours de retard max. (`max_days`, défaut 0 = illimité).
- Taux de provision % (`provision_rate`, requis, défaut 0.0).
- Société (`company_id`, requis, défaut société courante) : chaque société doit configurer ses propres tranches.

**`res.company` (extension MSM)** :
- Épargne : mois d'inactivité avant dormance (`savings_dormancy_months`, entier, défaut 6) — utilisé dans `microfinance_savings_account.py` (lignes 81 et 212) pour déterminer la dormance d'un compte épargne (`account.company_id.savings_dormancy_months or 6`).

## 6. Boutons et actions

Aucun bouton `type="object"` n'est défini dans `microfinance_repayment_frequency_views.xml` ni `microfinance_provision_rule_views.xml` (formulaires/listes de champs simples).

L'action serveur `action_server_microfinance_post_provisions` (« Comptabiliser les provisions », `microfinance_loan_management/data/provision_server_action.xml`) est liée à la vue liste du modèle `microfinance.loan` (`binding_view_types="list"`) et exécute `records.action_post_provisions()`. Elle est restreinte aux groupes `group_microfinance_manager` et `group_microfinance_finance` (`groups_id`).

## 7. Règles métier

- **Unicité du code de périodicité** : contrainte SQL `unique(code)` sur `microfinance.repayment.frequency`.
- **`period_value` positif** : `@api.constrains('period_value')` lève une erreur si `period_value <= 0`.
- **`microfinance.repayment.frequency` n'a pas de champ `company_id`** : les périodicités sont partagées globalement entre toutes les sociétés/agences (pas de cloisonnement possible sur ce modèle, confirmé par l'absence de `ir.rule` le ciblant).
- **Tranches de provisionnement non chevauchantes** : `@api.constrains('min_days', 'max_days', 'company_id')` (`_check_no_overlap`) compare chaque règle à ses « siblings » de la même société et lève une erreur en cas de chevauchement.
- **Bornes de `microfinance.provision.rule`** : `min_days >= 0`, `max_days` (si non nul) `>= min_days`, `provision_rate` entre 0 et 100 (`_check_values`).
- **`company_id` par défaut = société courante** (`env.company`) : chaque société doit paramétrer ses propres tranches ; les données de démonstration (`provision_rules_data.xml`) ne préchargent des tranches indicatives (0-30j : 0%, 31-60j : 25%, 61-90j : 50%, 91-180j : 75%, 181j+ : 100%) que pour `base.main_company`, avec le commentaire explicite : « chaque société additionnelle configure les siennes ».
- **Séquences globales** : `seq_microfinance_loan` (préfixe `CR/%(year)s/`, padding 5) et `seq_microfinance_payment` (préfixe `PAY/%(year)s/`, padding 5) ont `company_id` à `False` : numérotation partagée entre toutes les sociétés, non cloisonnée par agence.
- **Tâches planifiées (`data/cron.xml`)** : `cron_update_overdue_and_penalties` (quotidien, actif par défaut) applique les pénalités aux échéances `pending`/`partial`/`overdue` puis recalcule silencieusement le scoring des crédits `active`. `cron_post_provisions` (mensuel) appelle `action_post_provisions()` sur les crédits `active`/`defaulted`, mais est **inactif par défaut** (`active = False`) : doit être activé manuellement pour s'exécuter automatiquement.
- **`action_post_provisions`** (`microfinance_loan.py`) : pour chaque crédit sélectionné à l'état `active` ou `defaulted`, calcule l'écart entre `provision_amount` (dû) et `provision_posted_amount` (déjà comptabilisé), ignore les écarts inférieurs à 0.01, crée et poste une écriture comptable (`account.move`) par crédit, puis met à jour `provision_posted_amount` et journalise l'opération dans le chatter.
- **Hook d'installation `post_init_hook`** : ne s'applique qu'aux sociétés dont `chart_template == 'mg_pcec'` ; crée les sous-comptes PCEC dédiés de `LOAN_NEW_SUBACCOUNTS` (un compte par segment Individuel/Groupe) puis les 7 journaux de `JOURNALS` (BQOP, BQEP, BQCR, CAI, CRE, EPG, OD), de façon idempotente (`search_count` avant `create`, aucune duplication en cas de ré-exécution).
- **Cloisonnement multi-société (`ir.rule`, `groups=[]`) — non contournable par groupe** : les règles définies dans `microfinance_loan_management/security/microfinance_company_rules.xml` et `microfinance_savings_management/security/microfinance_company_rules.xml` ont toutes `domain_force=[('company_id', 'in', company_ids)]` et `groups` vide, ce qui les applique à **tous** les utilisateurs internes sans exception, y compris les managers et les auditeurs. Modèles concernés, réellement présents dans ces deux fichiers :
  - MLM : `microfinance.loan.product`, `microfinance.loan`, `microfinance.loan.installment`, `microfinance.loan.payment`, `microfinance.loan.guarantee`, `microfinance.guarantee.valuation.rule`, `microfinance.loan.reschedule.history` (par `company_id`), `microfinance.loan.reschedule.history.line` (par `history_id.company_id`, car ce modèle n'a pas son propre `company_id`), `microfinance.collection.visit`.
  - MSM : `microfinance.savings.product`, `microfinance.savings.account`, `microfinance.savings.transaction`.
  - Une note dans le fichier MLM précise explicitement que `microfinance.loan.application` (dossier d'instruction) est volontairement omis de ce fichier car le modèle n'est pas câblé dans le registre Odoo (absent de `models/__init__.py`, d'`ir.model.access.csv` et de toute vue).
  - À la différence de ces règles, les `ir.rule` de cloisonnement par société définies dans `groups.xml` (sur `microfinance.scoring.profile`, `microfinance.scoring.rule`, `microfinance.scoring.line` et `microfinance.provision.rule`) ciblent explicitement des groupes (`group_microfinance_user/manager/finance/auditor`) et non `groups=[]`.

## 8. Contrôles et blocages

- Code de périodicité déjà utilisé → violation de la contrainte SQL `unique(code)` (message standard Odoo).
- `period_value <= 0` → « La valeur de la période doit être strictement positive. »
- `min_days < 0` → « Le nombre de jours minimum ne peut pas être négatif. »
- `max_days` non nul et `< min_days` → « Le nombre de jours maximum doit être supérieur ou égal au minimum (ou 0 pour illimité). »
- `provision_rate` hors de [0, 100] → « Le taux de provision doit être compris entre 0 et 100. »
- Chevauchement de deux tranches de provisionnement pour la même société → « Les tranches de provisionnement ne doivent pas se chevaucher (conflit entre "%(rule)s" et "%(other)s"). »
- Un utilisateur sans `group_microfinance_manager` ne voit pas le menu Configuration et n'a pas les droits d'écriture/création/suppression sur les périodicités ni les règles de provisionnement (lecture seule pour Agent crédit et Finance microfinance ; aucun accès pour Auditeur sur les règles de provisionnement, cf. section 12).
- Si un compte PCEC attendu (ex. `131001`) est introuvable lors de la création d'un journal par le hook, un simple avertissement est journalisé (pas de blocage de l'installation) : « Microfinance PCEC : compte %s introuvable pour la société %s (id=%s) — le journal ou le champ correspondant restera sans compte par défaut. Le plan PCEC (plan_compta_pcec) est-il bien chargé sur cette société ? »

## 9. Statuts

Aucun des modèles de ce workflow (`microfinance.repayment.frequency`, `microfinance.provision.rule`) ne comporte de champ `state`. Aucune machine à états n'est définie ici.

## 10. Rapports ou PDF

Aucun rapport dédié à ce jour.

## 11. Tableaux de bord

Aucun indicateur de `microfinance.dashboard` n'est directement lié aux périodicités, règles de provisionnement, séquences, cron ou au hook d'installation (le tableau de bord porte sur le portefeuille de crédit, cf. workflow `dashboard`). À compléter si un indicateur dédié est ajouté.

## 12. Sécurité et groupes utilisateurs

**`microfinance.repayment.frequency`** (`ir.model.access.csv` de MLM) :

| Groupe | Lecture | Écriture | Création | Suppression |
|---|---|---|---|---|
| group_microfinance_user | 1 | 0 | 0 | 0 |
| group_microfinance_manager | 1 | 1 | 1 | 1 |
| group_microfinance_finance | 1 | 0 | 0 | 0 |
| group_microfinance_auditor | 1 | 0 | 0 | 0 |

**`microfinance.provision.rule`** (`ir.model.access.csv` de MLM) :

| Groupe | Lecture | Écriture | Création | Suppression |
|---|---|---|---|---|
| group_microfinance_user | 1 | 0 | 0 | 0 |
| group_microfinance_manager | 1 | 1 | 1 | 1 |
| group_microfinance_finance | 1 | 0 | 0 | 0 |

(Aucune ligne pour `group_microfinance_auditor` sur `microfinance.provision.rule` dans le CSV : ce groupe n'a aucun accès à ce modèle, contrairement aux périodicités de remboursement.)

Le cloisonnement multi-société (`ir.rule`, `groups=[]`) décrit en section 7 s'ajoute à ces droits par modèle et s'applique de façon non contournable à tous les groupes, y compris `group_microfinance_manager` et `group_microfinance_auditor`, sur l'ensemble des modèles listés en section 7 (mais pas sur `microfinance.repayment.frequency`, qui n'a pas de `company_id`).

## 13. Cas d'utilisation complets

1. **Ajouter une nouvelle périodicité de remboursement** : un Manager crédit va dans Microfinance > Configuration > Périodicités de remboursement, ajoute une ligne dans la liste éditable, saisit un code unique, choisit l'unité (Jours/Mois) et la valeur, puis enregistre.
2. **Paramétrer les tranches de provisionnement d'une nouvelle agence** : après création d'une nouvelle société, un Manager crédit va dans Microfinance > Configuration > Règles de provisionnement et ajoute ses propres tranches (les tranches par défaut ne sont chargées que pour la société principale) ; le système bloque toute tranche qui chevaucherait une tranche existante pour la même société.
3. **Comptabiliser les provisions du mois** : un Manager crédit ou un utilisateur du groupe Finance microfinance sélectionne les crédits concernés dans la liste des crédits, puis déclenche l'action « Comptabiliser les provisions » (menu Actions de la liste) pour poster les écritures comptables correspondant à l'écart de provisionnement ; alternativement, active le cron mensuel `ir_cron_microfinance_post_provisions` (inactif par défaut) pour automatiser ce traitement.

## 14. Erreurs fréquentes

- Chevauchement de deux tranches de provisionnement pour la même société (message d'erreur cité en section 8).
- Code de périodicité dupliqué (contrainte SQL unique).
- Valeur de période ou taux de provision hors bornes autorisées (voir messages en section 8).
- Oublier de configurer les tranches de provisionnement pour une nouvelle société : aucune tranche n'est préchargée automatiquement en dehors de `base.main_company`.
- S'attendre à ce que le cron mensuel de provisionnement s'exécute automatiquement alors qu'il est inactif par défaut.
- S'attendre à ce que le hook crée des sous-comptes/journaux PCEC sur une société dont le plan comptable n'est pas `mg_pcec` : le hook ignore silencieusement ces sociétés.

## 15. Bonnes pratiques

- Configurer les tranches de provisionnement dès la création de chaque nouvelle société/agence, car elles ne sont pas héritées automatiquement.
- Garder les codes de périodicité stables une fois utilisés, le champ d'aide du modèle précisant qu'ils sont « référencés par la migration ».
- Vérifier que `chart_template == 'mg_pcec'` avant de s'attendre à ce que les sous-comptes et journaux dédiés soient créés automatiquement à l'installation.
- Activer consciemment le cron mensuel de provisionnement si un traitement automatique est souhaité, plutôt que de compter sur un déclenchement manuel systématique.
- Ne pas chercher à contourner le cloisonnement multi-société via l'attribution d'un groupe : les règles à `groups=[]` s'appliquent à tout utilisateur interne, quel que soit son groupe.

## 16. Questions/Réponses MOWGLI potentielles

1. Comment ajouter une nouvelle périodicité de remboursement ?
2. Pourquoi la règle de provisionnement que je crée est-elle refusée ?
3. Comment configurer les tranches de provisionnement pour une nouvelle agence ?
4. Le cron de comptabilisation des provisions tourne-t-il automatiquement chaque mois ?
5. Pourquoi les périodicités de remboursement sont-elles les mêmes pour toutes les agences ?
6. Comment déclencher manuellement la comptabilisation des provisions ?
7. Un manager d'une agence peut-il voir les crédits d'une autre agence ?
8. Que fait le hook d'installation du module sur le plan comptable PCEC ?
9. Pourquoi le journal Banque Épargne n'a-t-il pas de compte par défaut sur ma société ?
10. Quel taux de provisionnement s'applique à un crédit en retard de 100 jours ?
