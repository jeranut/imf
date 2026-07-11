# Workflow Gestion des utilisateurs

## 1. Objectif métier

Créer, configurer et désactiver les comptes utilisateurs (`res.users`, modèle standard Odoo) qui accèdent aux modules Microfinance, et leur attribuer les groupes de sécurité (`res.groups`) qui déterminent leurs droits sur les modèles métier de `microfinance_loan_management` (MLM) et `microfinance_savings_management` (MSM).

Ce workflow ne couvre **pas** : la configuration des sociétés/agences et du cloisonnement multi-société (voir workflow `administration`), ni les workflows métier eux-mêmes (crédit, épargne, recouvrement) que ces groupes autorisent. Il ne couvre pas non plus la création de sociétés ou la configuration technique du framework Odoo (Réglages > Technique) hors du périmètre utilisateurs/groupes.

## 2. Utilisateurs concernés

- Administrateur / Réglages (groupe standard Odoo `base.group_system`, hors modules Microfinance) : seul profil habilité à créer/modifier des utilisateurs et à leur attribuer des groupes, via Réglages > Utilisateurs et Sociétés.
- Les 9 groupes définis par `microfinance_loan_management/security/groups.xml` (catégorie « Microfinance ») auxquels un utilisateur peut être rattaché : Agent crédit, Manager crédit, Finance microfinance, Agent recouvrement, Auditeur microfinance, Comptable, Caissier, Comité de crédit, Gestionnaire.
- Les 2 groupes définis par `microfinance_savings_management/security/savings_security.xml` : Agent épargne, Manager épargne.

## 3. Menus utilisés

Réglages > Utilisateurs et Sociétés > Utilisateurs (menu standard Odoo ; aucune vue ni menu propre aux modules Microfinance pour la gestion des utilisateurs eux-mêmes).

## 4. Étapes principales

1. Réglages > Utilisateurs et Sociétés > Utilisateurs > Nouveau.
2. Renseigner Nom, Adresse e-mail (sert de login par défaut).
3. Onglet « Droits d'accès » : dans la section « Microfinance », cocher le(s) groupe(s) métier pertinent(s) (ex. Agent crédit, Manager crédit, Agent épargne, etc.). Les cases à cocher reflètent la hiérarchie `implied_ids` décrite en section 12.
4. Enregistrer : Odoo envoie éventuellement une invitation par e-mail au nouvel utilisateur.
5. Pour retirer l'accès d'un utilisateur qui quitte l'institution : décocher ses groupes Microfinance et/ou archiver le compte (champ standard `active`).

## 5. Champs importants

Formulaire `res.users` standard Odoo (aucun champ ajouté par les modules Microfinance) :
- Nom, Login/E-mail : identification et authentification.
- Onglet « Droits d'accès » > catégorie « Microfinance » : sélection des groupes `group_microfinance_*` et `group_savings_*`.
- Société(s) : périmètre multi-société de l'utilisateur (combiné au cloisonnement `ir.rule` décrit dans le workflow `administration`).
- Actif (`active`) : champ standard permettant d'archiver un compte.

## 6. Boutons et actions

Les actions standard d'Odoo sont disponibles sur la fiche utilisateur : Archiver/Désarchiver, Changer le mot de passe, Envoyer un e-mail d'invitation. À compléter si des actions spécifiques aux modules Microfinance sont ajoutées.

## 7. Règles métier

- Hiérarchie des groupes MLM (`implied_ids`, source `microfinance_loan_management/security/groups.xml`) : `group_microfinance_manager`, `group_microfinance_finance`, `group_microfinance_collection_agent` et `group_microfinance_credit_committee` impliquent chacun `group_microfinance_user`. `group_microfinance_gestionnaire` implique à la fois `group_microfinance_manager` et `group_microfinance_finance` (et donc, par transitivité, `group_microfinance_user`). `group_microfinance_auditor`, `group_microfinance_comptable` et `group_microfinance_cashier` (ce dernier implique `group_microfinance_user`) sont sinon indépendants.
- Hiérarchie des groupes MSM : `group_savings_manager` implique `group_savings_agent`.
- Cocher un groupe « supérieur » (ex. Gestionnaire) attribue automatiquement les droits des groupes impliqués sans action supplémentaire.
- Seules les contraintes standard d'Odoo s'appliquent à la création d'un compte (ex. unicité du login).

## 8. Contrôles et blocages

Les blocages observés sont ceux du framework Odoo : identifiant (login) déjà utilisé, adresse e-mail invalide, etc.

## 9. Statuts

Un compte utilisateur n'a pas de statuts multiples. Le champ standard `active` (booléen) permet de l'archiver/désarchiver (via l'action « Archiver »), ce qui bloque la connexion sans supprimer les données associées.

## 10. Rapports ou PDF

Aucun rapport dédié à ce jour.

## 11. Tableaux de bord

Aucun tableau de bord dédié à ce jour.

## 12. Sécurité et groupes utilisateurs

### 12.1 Groupes définis

**MLM — `microfinance_loan_management/security/groups.xml`** (catégorie `module_category_microfinance` = « Microfinance ») :

| Groupe (id technique) | Nom affiché | `implied_ids` (groupes impliqués) |
|---|---|---|
| `group_microfinance_user` | Agent crédit | — |
| `group_microfinance_manager` | Manager crédit | `group_microfinance_user` |
| `group_microfinance_finance` | Finance microfinance | `group_microfinance_user` |
| `group_microfinance_collection_agent` | Agent recouvrement | `group_microfinance_user` |
| `group_microfinance_auditor` | Auditeur microfinance | — |
| `group_microfinance_comptable` | Comptable | — |
| `group_microfinance_cashier` | Caissier | `group_microfinance_user` |
| `group_microfinance_credit_committee` | Comité de crédit | `group_microfinance_user` |
| `group_microfinance_gestionnaire` | Gestionnaire | `group_microfinance_manager`, `group_microfinance_finance` |

**MSM — `microfinance_savings_management/security/savings_security.xml`** (même catégorie) :

| Groupe (id technique) | Nom affiché | `implied_ids` |
|---|---|---|
| `group_savings_agent` | Agent épargne | — |
| `group_savings_manager` | Manager épargne | `group_savings_agent` |

### 12.2 Droits par modèle (issus des `ir.model.access.csv`)

Seules les lignes réellement présentes dans les CSV sont listées ; un groupe absent d'un tableau n'a aucun droit sur ce modèle. L=Lecture, É=Écriture, C=Création, S=Suppression.

**`ir.model.access.csv` de MLM :**

| Modèle | Groupe | L | É | C | S |
|---|---|---|---|---|---|
| microfinance.loan.product | group_microfinance_user | 1 | 0 | 0 | 0 |
| microfinance.loan.product | group_microfinance_manager | 1 | 1 | 1 | 1 |
| microfinance.loan.product | group_microfinance_comptable | 1 | 0 | 0 | 0 |
| microfinance.repayment.frequency | group_microfinance_user | 1 | 0 | 0 | 0 |
| microfinance.repayment.frequency | group_microfinance_manager | 1 | 1 | 1 | 1 |
| microfinance.repayment.frequency | group_microfinance_finance | 1 | 0 | 0 | 0 |
| microfinance.repayment.frequency | group_microfinance_auditor | 1 | 0 | 0 | 0 |
| microfinance.provision.rule | group_microfinance_user | 1 | 0 | 0 | 0 |
| microfinance.provision.rule | group_microfinance_manager | 1 | 1 | 1 | 1 |
| microfinance.provision.rule | group_microfinance_finance | 1 | 0 | 0 | 0 |
| microfinance.loan | group_microfinance_user | 1 | 1 | 1 | 0 |
| microfinance.loan | group_microfinance_manager | 1 | 1 | 1 | 1 |
| microfinance.loan | group_microfinance_finance | 1 | 1 | 0 | 0 |
| microfinance.loan | group_microfinance_auditor | 1 | 0 | 0 | 0 |
| microfinance.loan | group_microfinance_comptable | 1 | 0 | 0 | 0 |
| microfinance.loan | group_microfinance_cashier | 1 | 0 | 0 | 0 |
| microfinance.loan | group_microfinance_credit_committee | 1 | 0 | 0 | 0 |
| microfinance.loan.guarantee | group_microfinance_user | 1 | 1 | 1 | 0 |
| microfinance.loan.guarantee | group_microfinance_manager | 1 | 1 | 1 | 1 |
| microfinance.loan.guarantee | group_microfinance_finance | 1 | 0 | 0 | 0 |
| microfinance.loan.guarantee | group_microfinance_auditor | 1 | 0 | 0 | 0 |
| microfinance.loan.installment | group_microfinance_user | 1 | 0 | 0 | 0 |
| microfinance.loan.installment | group_microfinance_manager | 1 | 1 | 1 | 1 |
| microfinance.loan.installment | group_microfinance_finance | 1 | 1 | 0 | 0 |
| microfinance.loan.payment | group_microfinance_user | 1 | 0 | 0 | 0 |
| microfinance.loan.payment | group_microfinance_finance | 1 | 1 | 1 | 0 |
| microfinance.loan.payment | group_microfinance_manager | 1 | 1 | 1 | 1 |
| microfinance.loan.payment | group_microfinance_cashier | 1 | 1 | 1 | 0 |
| microfinance.collection.visit | group_microfinance_collection_agent | 1 | 1 | 1 | 0 |
| microfinance.collection.visit | group_microfinance_user | 1 | 0 | 0 | 0 |
| microfinance.collection.visit | group_microfinance_manager | 1 | 1 | 1 | 1 |
| microfinance.dashboard | group_microfinance_user | 1 | 0 | 0 | 0 |
| microfinance.loan.payment.wizard | group_microfinance_user | 1 | 1 | 1 | 1 |
| microfinance.loan.reschedule.wizard | group_microfinance_manager | 1 | 1 | 1 | 1 |
| microfinance.loan.writeoff.wizard | group_microfinance_manager | 1 | 1 | 1 | 1 |
| microfinance.loan.writeoff.wizard | group_microfinance_finance | 1 | 1 | 1 | 1 |
| microfinance.loan.payment.cancel.wizard | group_microfinance_manager | 1 | 1 | 1 | 1 |
| microfinance.loan.payment.cancel.wizard | group_microfinance_finance | 1 | 1 | 1 | 1 |
| microfinance.scoring.profile | group_microfinance_user | 1 | 0 | 0 | 0 |
| microfinance.scoring.profile | group_microfinance_manager | 1 | 1 | 1 | 1 |
| microfinance.scoring.profile | group_microfinance_auditor | 1 | 0 | 0 | 0 |
| microfinance.scoring.rule | group_microfinance_user | 1 | 0 | 0 | 0 |
| microfinance.scoring.rule | group_microfinance_manager | 1 | 1 | 1 | 1 |
| microfinance.scoring.rule | group_microfinance_auditor | 1 | 0 | 0 | 0 |
| microfinance.scoring.line | group_microfinance_user | 1 | 1 | 1 | 1 |
| microfinance.scoring.line | group_microfinance_manager | 1 | 1 | 1 | 1 |
| microfinance.scoring.line | group_microfinance_auditor | 1 | 0 | 0 | 0 |
| microfinance.guarantee.valuation.rule | group_microfinance_user | 1 | 0 | 0 | 0 |
| microfinance.guarantee.valuation.rule | group_microfinance_manager | 1 | 1 | 1 | 1 |
| microfinance.guarantee.valuation.rule | group_microfinance_finance | 1 | 0 | 0 | 0 |
| microfinance.loan.reschedule.history | group_microfinance_user | 1 | 0 | 0 | 0 |
| microfinance.loan.reschedule.history | group_microfinance_manager | 1 | 1 | 1 | 0 |
| microfinance.loan.reschedule.history | group_microfinance_finance | 1 | 0 | 0 | 0 |
| microfinance.loan.reschedule.history | group_microfinance_auditor | 1 | 0 | 0 | 0 |
| microfinance.loan.reschedule.history.line | group_microfinance_user | 1 | 0 | 0 | 0 |
| microfinance.loan.reschedule.history.line | group_microfinance_manager | 1 | 1 | 1 | 0 |
| microfinance.loan.reschedule.history.line | group_microfinance_finance | 1 | 0 | 0 | 0 |
| microfinance.loan.reschedule.history.line | group_microfinance_auditor | 1 | 0 | 0 | 0 |
| microfinance.client.group.member | group_microfinance_user | 1 | 1 | 1 | 0 |
| microfinance.client.group.member | group_microfinance_manager | 1 | 1 | 1 | 1 |
| microfinance.client.group.member | group_microfinance_finance | 1 | 0 | 0 | 0 |
| microfinance.client.group.member | group_microfinance_auditor | 1 | 0 | 0 | 0 |
| microfinance.client.representative | group_microfinance_user | 1 | 1 | 1 | 0 |
| microfinance.client.representative | group_microfinance_manager | 1 | 1 | 1 | 1 |
| microfinance.client.representative | group_microfinance_finance | 1 | 0 | 0 | 0 |
| microfinance.client.representative | group_microfinance_auditor | 1 | 0 | 0 | 0 |
| microfinance.client.blacklist | group_microfinance_user | 1 | 0 | 0 | 0 |
| microfinance.client.blacklist | group_microfinance_manager | 1 | 1 | 1 | 1 |
| microfinance.client.blacklist | group_microfinance_finance | 1 | 0 | 0 | 0 |
| microfinance.client.blacklist | group_microfinance_auditor | 1 | 0 | 0 | 0 |
| microfinance.client.category | group_microfinance_user | 1 | 0 | 0 | 0 |
| microfinance.client.category | group_microfinance_manager | 1 | 1 | 1 | 1 |
| microfinance.client.category | group_microfinance_finance | 1 | 0 | 0 | 0 |
| microfinance.client.category | group_microfinance_auditor | 1 | 0 | 0 | 0 |

**`ir.model.access.csv` de MSM** (les groupes `microfinance_loan_management.group_microfinance_*` y sont référencés directement) :

| Modèle | Groupe | L | É | C | S |
|---|---|---|---|---|---|
| microfinance.savings.product | group_savings_agent | 1 | 0 | 0 | 0 |
| microfinance.savings.product | group_savings_manager | 1 | 1 | 1 | 1 |
| microfinance.savings.product | group_microfinance_manager (MLM) | 1 | 0 | 0 | 0 |
| microfinance.savings.product | group_microfinance_auditor (MLM) | 1 | 0 | 0 | 0 |
| microfinance.savings.account | group_savings_agent | 1 | 1 | 1 | 0 |
| microfinance.savings.account | group_savings_manager | 1 | 1 | 1 | 1 |
| microfinance.savings.account | group_microfinance_manager (MLM) | 1 | 0 | 0 | 0 |
| microfinance.savings.account | group_microfinance_finance (MLM) | 1 | 0 | 0 | 0 |
| microfinance.savings.account | group_microfinance_auditor (MLM) | 1 | 0 | 0 | 0 |
| microfinance.savings.transaction | group_savings_agent | 1 | 1 | 1 | 0 |
| microfinance.savings.transaction | group_savings_manager | 1 | 1 | 1 | 1 |
| microfinance.savings.transaction | group_microfinance_manager (MLM) | 1 | 0 | 0 | 0 |
| microfinance.savings.transaction | group_microfinance_auditor (MLM) | 1 | 0 | 0 | 0 |

### 12.3 Autres règles de sécurité liées aux groupes

`microfinance_loan_management/security/groups.xml` définit également 4 `ir.rule` de cloisonnement par société ciblant explicitement les groupes `group_microfinance_user`, `group_microfinance_manager`, `group_microfinance_finance` et `group_microfinance_auditor` (domaine `[('company_id', 'in', company_ids)]`) sur les modèles `microfinance.scoring.profile`, `microfinance.scoring.rule`, `microfinance.scoring.line` et `microfinance.provision.rule` — voir le workflow `administration` pour le détail des règles de cloisonnement multi-société.

## 13. Cas d'utilisation complets

1. **Créer un agent crédit** : Réglages > Utilisateurs et Sociétés > Utilisateurs > Nouveau > renseigner Nom/E-mail > onglet Droits d'accès > cocher « Agent crédit » (catégorie Microfinance) > Enregistrer. L'utilisateur voit le menu racine « Microfinance » (accès par `group_microfinance_user`) mais pas « Configuration » (réservé au Manager crédit).
2. **Créer un gestionnaire multi-casquette (crédit + épargne)** : créer l'utilisateur, cocher « Gestionnaire » (implique automatiquement Manager crédit et Finance microfinance) puis, si l'agence gère aussi l'épargne, cocher également « Manager épargne » (implique Agent épargne).
3. **Retirer l'accès d'un utilisateur qui quitte l'institution** : ouvrir sa fiche > décocher tous les groupes Microfinance et/ou utiliser l'action « Archiver » du framework (champ `active` à faux) pour bloquer sa connexion sans perdre l'historique des enregistrements qu'il a créés/modifiés.

## 14. Erreurs fréquentes

- Un utilisateur sans aucun groupe de la catégorie « Microfinance » ne voit pas le menu racine « Microfinance » (`menu_microfinance_root` exige l'un des 5 groupes `group_microfinance_user/manager/finance/auditor/collection_agent`).
- Un utilisateur avec uniquement « Finance microfinance » ou « Auditeur microfinance » ne voit pas le menu « Configuration » (`menu_microfinance_config` exige spécifiquement `group_microfinance_manager`) même s'il a des droits de lecture sur les périodicités et règles de provisionnement.
- Attribuer « Comptable » ou « Caissier » ne donne accès qu'aux modèles explicitement listés pour ces groupes dans `ir.model.access.csv` (ex. `microfinance.loan` en lecture seule pour Comptable) ; ces deux groupes n'apparaissent dans aucune relation `implied_ids`.

## 15. Bonnes pratiques

- Attribuer le groupe le plus spécifique nécessaire plutôt que « Gestionnaire » par défaut, pour limiter les droits d'écriture/suppression aux besoins réels de l'utilisateur.
- Vérifier les droits obtenus par transitivité (`implied_ids`) avant d'ajouter un groupe supplémentaire redondant.
- Pour un utilisateur intervenant à la fois sur le crédit et l'épargne, attribuer explicitement un groupe de chaque catégorie (les hiérarchies MLM et MSM sont indépendantes, sauf pour les accès croisés en lecture accordés aux groupes MLM sur les modèles MSM, cf. section 12.2).
- Archiver plutôt que supprimer un utilisateur sortant, pour préserver la traçabilité des enregistrements qu'il a créés ou validés.

## 16. Questions/Réponses MOWGLI potentielles

1. Comment créer un compte pour un nouvel agent crédit ?
2. Quels groupes dois-je cocher pour qu'un utilisateur puisse valider les crédits en tant que manager ?
3. Pourquoi ce comptable ne voit-il pas le menu Configuration ?
4. Quelle est la différence entre le groupe « Gestionnaire » et « Manager crédit » ?
5. Comment retirer l'accès d'un employé qui a quitté l'institution ?
6. Un agent épargne peut-il aussi voir les crédits ?
7. Le groupe « Auditeur microfinance » a-t-il le droit de modifier des données ?
8. Comment donner à un utilisateur le droit de comptabiliser les provisions ?
9. Quels sont les 9 groupes définis pour le module crédit microfinance ?
10. Pourquoi un caissier ne peut-il pas créer de nouveaux crédits ?
