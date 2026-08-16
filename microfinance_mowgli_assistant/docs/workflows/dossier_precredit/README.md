# Workflow Dossier précrédit

## 1. Objectif métier
Ce workflow couvre deux volets, **totalement indépendants l'un de l'autre** depuis la
réversion du "point d'entrée unique" (2026-08-16, voir
`microfinance_loan_management/docs_dev/creation_credit_directe/STATUS.md`) :
**(A)** le crédit (`microfinance.loan`), créé **directement** depuis le menu **Crédits** (état
initial `draft`) et validé à travers ses propres états `draft` → `enquete` → `avis_ca` →
`avis_cdag` → `approved` (le décaissement lui-même, `action_disburse`, appartient au workflow
`comptabilite`) ; le dossier d'instruction (`microfinance.loan.application`) n'est ni un
prérequis ni un point de passage pour créer ou faire avancer un crédit ;
**(B)** la qualification/vetting du client, gérée depuis la fiche partenaire (`res.partner`) : catégories de classification, liste noire, représentants/comité et membres de groupe.
Ce workflow ne couvre pas le décaissement, les remboursements ni la comptabilité (voir `comptabilite`), ni le recouvrement des impayés (voir `par_reporting`), ni les garanties/scoring (voir `garanties_scoring`), ni le suivi visite/contre-visite du dossier d'instruction lui-même (`microfinance.loan.application`, recentré sur ce seul rôle — voir son propre workflow si besoin).

## 2. Utilisateurs concernés
D'après `security/groups.xml` et les `groups=` des boutons de `microfinance_loan_views.xml` :
- **Agent crédit** (`group_microfinance_user`) : crée un crédit (droits standards de création sur le modèle, aucun wizard ni dossier préalable requis), gère les fiches client (catégories, liste noire, représentants, membres) avec droits lecture/écriture/création (pas de suppression).
- **Comité de crédit** (`group_microfinance_credit_committee`) : donne l'avis CA (`action_ca_review`) puis l'avis CDAG (`action_cdag_review`).
- **Manager crédit** (`group_microfinance_manager`) : approuve le crédit après avis CDAG (`action_approve`) ; droits complets (y compris suppression) sur les entités de qualification client.
- **Finance microfinance** (`group_microfinance_finance`) : décaisse le crédit approuvé (`action_disburse`, workflow `comptabilite`) ; lecture/écriture sur `microfinance.loan` mais pas de création ; accès en lecture seule aux entités de qualification client.
- **Auditeur microfinance** (`group_microfinance_auditor`) : lecture seule sur `microfinance.loan` et sur les entités de qualification client.
- **Gestionnaire** (`group_microfinance_gestionnaire`) : hérite de `group_microfinance_manager` et `group_microfinance_finance` (`implied_ids`), cumule donc les capacités d'approbation et de décaissement.
- Le champ `officer_id` (Agent crédit, défaut `self.env.user`), `manager_id` (renseigné par `action_ca_review`), `finance_user_id` (renseigné par `action_cdag_review`) sur `microfinance.loan` tracent qui a réalisé chaque étape.

## 3. Menus utilisés
Chemins reconstruits depuis `microfinance_menus.xml` et `microfinance_partner_views.xml` :
- `Microfinance > Clients` (`menu_clients_root`, parent `menu_microfinance_root`, action `action_microfinance_client` — ouvre `res.partner` en tree/form/kanban avec contexte `microfinance_context: True`). C'est ici que sont gérées les fiches client, y compris les entités de qualification (catégories, liste noire, représentants, membres de groupe), embarquées comme listes éditables dans le formulaire partenaire — aucun menu séparé n'existe pour `microfinance.client.category`, `microfinance.client.blacklist`, `microfinance.client.representative` ou `microfinance.client.group.member`.
- `Microfinance > Crédits > Compte crédit` (`menu_microfinance_loan_accounts`, en tête de sous-menu) : conteneur historique par client, consultation seule (`create="0"` sur les vues).
- `Microfinance > Crédits > Dossiers d'instruction` (`menu_microfinance_loan_applications` parent `menu_credits_root`, action `action_microfinance_loan_application`) : ouvre la liste/formulaire de `microfinance.loan.application`, suivi de la visite/contre-visite de terrain uniquement (`draft → visite → contre_visite → fait`) — sans lien de création vers `microfinance.loan` (un crédit peut être rattaché a posteriori via son champ `loan_id`, en lecture seule, mais rien ne le fait automatiquement).
- `Microfinance > Crédits > Crédits` (`menu_microfinance_loans` parent `menu_credits_root`, action `action_microfinance_loan`) : création directe et suivi du cycle complet `draft → approved` (et au-delà).

## 4. Étapes principales
**(A) Cycle `microfinance.loan`, indépendant du dossier d'instruction**, dérivé des boutons
`action_*` de `microfinance_loan_views.xml` (en-tête) et de `microfinance_loan.py` :
1. Créer un crédit (`Microfinance > Crédits > Crédits`, nouveau) : état initial `draft`. Renseigner `partner_id`, `product_id`, `loan_amount`, `term`. Droits d'accès standards du modèle uniquement — aucun contexte ni wizard requis.
2. (Optionnel, disponible dès `draft` et jusqu'à `approved` inclus) Générer l'échéancier prévisionnel avec **Générer échéancier** (`action_generate_schedule`).
3. Cliquer sur **Démarrer l'enquête** (`action_start_enquete`) : exécute `_check_eligibility()` puis `action_calculate_scoring(silent=True)`, passe l'état à `enquete`.
4. Le comité de crédit clique sur **Avis CA** (`action_ca_review`) : état `avis_ca`, `manager_id` renseigné à l'utilisateur courant.
5. Le comité de crédit clique sur **Avis CDAG** (`action_cdag_review`) : état `avis_cdag`, `finance_user_id` renseigné.
6. Le manager clique sur **Approuver** (`action_approve`) : état `approved`, `approval_date` renseignée à la date du jour.
7. (Suite hors périmètre de ce workflow) Encaissement des frais de dossier et décaissement (`action_charge_fee`, `action_disburse`) font passer le crédit à l'état `active` — voir workflow `comptabilite`.

**(A bis) Dossier d'instruction, suivi terrain indépendant**, dérivé de
`microfinance_loan_application_views.xml` (en-tête) :
1. Créer un dossier (`Microfinance > Crédits > Dossiers d'instruction`, nouveau ou repris automatiquement depuis la fiche client si un produit y est sélectionné) : état initial `draft`.
2. **Démarrer la visite** (`action_start_visite`, état `visite`), puis **Démarrer la contre-visite** (`action_start_contre_visite`, état `contre_visite`). Le bouton **Repasser en brouillon** reste disponible depuis `visite`.
3. **Marquer fait** (`action_mark_fait`, état `fait`).
4. Aucun contrôle de rôle sur ces transitions (uniquement les droits d'accès standards du modèle).

**(B) Qualification client**, dérivée de `microfinance_partner_views.xml` :
1. Ouvrir/créer une fiche client via `Microfinance > Clients`.
2. Choisir le type de client (`microfinance_client_type` : Particulier/Société/Groupe, widget radio).
3. Renseigner les blocs de champs spécifiques au type (Identification, Famille et compte pour un particulier ; Identité légale, Activité et finances, Localisation étendue pour une société ; Groupe pour un groupe).
4. Ajouter des lignes dans **Comité** (`microfinance_representative_ids`, pour société/groupe) et **Membres du groupe** (`microfinance_member_ids`, pour groupe uniquement).
5. Affecter jusqu'à 3 catégories de classification (`microfinance_category_1/2/3`, depuis `microfinance.client.category`).
6. Ajouter le cas échéant une entrée dans **Liste noire** (`microfinance_blacklist_ids`), avec motif et dates de début/fin.

## 5. Champs importants

### (A) `microfinance.loan` — extrait pertinent à l'instruction
- `partner_id` (Emprunteur), `product_id` (Produit), `co_borrower_id` (Co-emprunteur) : identification des parties.
- `loan_amount` (Montant crédit), `term` (Nombre échéances), `repayment_frequency_id` (Périodicité de remboursement).
- `application_date` (Date de demande), `approval_date` (Date d'approbation, readonly, renseignée par `action_approve`).
- `officer_id` (Agent crédit), `manager_id` (renseigné par `action_ca_review`), `finance_user_id` (renseigné par `action_cdag_review`) : traçabilité des acteurs de la validation.
- `state` (État) : voir section 9.
- `internal_score`, `risk_level`, `scoring_decision` : calculés par `action_calculate_scoring`, déclenché automatiquement (silencieux) lors de `action_start_enquete`.
- `scoring_profile_id` : profil de scoring utilisé (voir workflow `garanties_scoring`).

### (A bis) `microfinance.loan.application` — dossier d'instruction (visite/contre-visite)
- `state` (Brouillon/Visite/Contre-visite/Fait) : suivi terrain, sans effet sur `microfinance.loan`.
- `loan_id` (Crédit créé) : Many2one vers `microfinance.loan`, **readonly** (vue et modèle) — peut être rattaché manuellement (ORM/mode développeur) mais aucun mécanisme UI ne le fait plus depuis la suppression du wizard.

### (B) Fiche partenaire — qualification client (`res_partner.py`, `microfinance_partner_views.xml`)
- `microfinance_client_type` (Type de client) : Particulier / Société / Groupe — pilote l'affichage conditionnel des blocs de champs (`invisible=`).
- `microfinance_internal_reference`, `microfinance_statistical_number` : identifiants internes.
- `microfinance_category_1/2/3` : catégories de classification (Many2one vers `microfinance.client.category`).
- `microfinance_exit_date`, `microfinance_exit_reason` : sortie du client.
- `microfinance_blacklist_ids` (Liste noire) : One2many vers `microfinance.client.blacklist` (champs `date_start`, `date_end`, `reason`, `active`).
- `microfinance_is_blacklisted` (calculé, stocké) : vrai si au moins une entrée de liste noire est `active` et non expirée (`date_end` vide ou ≥ aujourd'hui). Ce champ est informatif : il n'empêche pas en lui-même la création ou la soumission d'un crédit pour le client concerné.
- `microfinance_representative_ids` (Comité) : One2many vers `microfinance.client.representative` (société/groupe).
- `microfinance_member_ids` (Membres du groupe) : One2many vers `microfinance.client.group.member` (groupe uniquement).
- Champs d'identification particulier : `microfinance_id_type`, `microfinance_id_number` (avec contrainte CIN, voir section 7), `microfinance_birthdate`, `microfinance_gender`, `microfinance_marital_status`, `microfinance_profession`.
- Champs société : `microfinance_nif` (avec contrainte, voir section 7), `microfinance_stat`, `microfinance_rcs`, `microfinance_enterprise_type`, `microfinance_share_capital`, `microfinance_estimated_turnover`.
- `microfinance_loan_ids` / `microfinance_loan_count` : crédits liés au partenaire, avec bouton statistique et onglet **Crédit** dédié.
- Module épargne (`microfinance_savings_management/models/res_partner.py`) : `microfinance_savings_account_ids` / `microfinance_savings_count`, bouton statistique **Épargne**.

## 6. Boutons et actions

### (A) `microfinance.loan` (`microfinance_loan_views.xml`, en-tête, ceux relatifs à l'instruction précrédit)
- `action_start_enquete` — **Démarrer l'enquête** : `type="object"`, classe `btn-primary`, `invisible="state != 'draft'"`.
- `action_ca_review` — **Avis CA** : `type="object"`, `groups="microfinance_loan_management.group_microfinance_credit_committee"`, `invisible="state != 'enquete'"`.
- `action_cdag_review` — **Avis CDAG** : `type="object"`, `groups="microfinance_loan_management.group_microfinance_credit_committee"`, `invisible="state != 'avis_ca'"`.
- `action_approve` — **Approuver** : `type="object"`, `groups="microfinance_loan_management.group_microfinance_manager"`, `invisible="state != 'avis_cdag'"`.
- `action_generate_schedule` — **Générer échéancier** : `type="object"`, `invisible="state not in ('draft','enquete','avis_ca','avis_cdag','approved')"`.
- `action_recompute_risk` — **Recalculer le score** : `type="object"`, toujours visible.

### (A bis) `microfinance.loan.application` (`microfinance_loan_application_views.xml`, en-tête)
- `action_start_visite` — **Démarrer la visite** : `type="object"`, classe `btn-primary`, `invisible="state != 'draft'"`.
- `action_reset_to_draft` — **Repasser en brouillon** : `type="object"`, `invisible="state != 'visite'"`.
- `action_start_contre_visite` — **Démarrer la contre-visite** : `type="object"`, classe `btn-primary`, `invisible="state != 'visite'"`.
- `action_mark_fait` — **Marquer fait** : `type="object"`, classe `btn-primary`, `invisible="state != 'contre_visite'"`.
- `action_view_loan` — smart button **Crédit** (`oe_stat_button`), `invisible="not loan_id"` : ouvre le crédit rattaché s'il y en a un.
- Aucun de ces boutons ne porte de `groups=` — seuls les droits d'accès standards du modèle s'appliquent.

### (B) Fiche partenaire (`microfinance_partner_views.xml`)
- `action_view_microfinance_loans` — bouton statistique **Crédit** (`oe_stat_button`), `invisible="not context.get('microfinance_context')"`.
- `action_view_microfinance_savings` (module épargne) — bouton statistique **Épargne**, même condition.

## 7. Règles métier

### (A) `microfinance.loan`
Dérivées de `_check_eligibility()` (appelée par `action_start_enquete`) :
- Ancienneté client minimale : si `product.min_membership_days` défini, la fiche client (`partner_id.create_date`) doit avoir cette ancienneté, sinon blocage (voir section 8).
- Un seul crédit actif à la fois par défaut : si le client a déjà un crédit `active` dans la même société, refus sauf si `product.allow_second_loan` est activé.
- Si `product.allow_second_loan` mais `product.block_second_if_arrears` activé, refus si le client a un crédit actif avec des échéances en retard (`overdue_installment_count > 0`).
- Le co-emprunteur (`co_borrower_id`) ne peut pas avoir lui-même un crédit actif en cours dans la même société.
- Garantie obligatoire (`product.guarantee_required`) : au moins une garantie validée requise avant l'enquête.
- Ratio de garantie minimum (`product.min_guarantee_ratio`) : le total des garanties validées (`guarantee_total`) doit couvrir ce pourcentage du montant du crédit.
- `action_start_enquete` déclenche aussi `action_calculate_scoring(silent=True)` : calcul automatique du score interne avant passage à `enquete`.

### (B) Qualification client (`res_partner.py`)
- `_check_microfinance_company_required` (`@api.constrains`) : la société (agence, `company_id`) est obligatoire pour un client créé en contexte microfinance (`microfinance_context`).
- `_check_cin_format` (`@api.constrains`) : si `microfinance_id_type == 'cin'`, le numéro de pièce d'identité doit contenir exactement 12 chiffres (les caractères non numériques sont ignorés dans le comptage).
- `_check_nif_format` (`@api.constrains`) : pour un client de type `company`, le NIF doit contenir exactement 12 chiffres.
- `_compute_microfinance_is_blacklisted` : calcul automatique et stocké, dépendant de `microfinance_blacklist_ids.active` et `.date_end` (voir section 5).
- `_onchange_microfinance_client_type` : synchronise `is_company` natif Odoo (`True` pour société/groupe) au changement de `microfinance_client_type`.

## 8. Contrôles et blocages

### (A) `microfinance.loan` / `microfinance.loan.application`
- *« Ancienneté client insuffisante pour ce produit : il manque X jour(s)... »* — client trop récent pour le produit choisi.
- *« Ce client a déjà un crédit actif. Ce produit n'autorise pas de second crédit en parallèle. »*
- *« Ce client a déjà un crédit actif en arriérés. Un second crédit ne peut pas être soumis. »*
- *« Le co-emprunteur a déjà un crédit actif en cours. »*
- *« Ce produit exige une garantie validée avant soumission. »*
- *« Garanties insuffisantes : il manque X pour atteindre le ratio minimum requis... »*
- *« Choisissez une périodicité de remboursement avant de générer l'échéancier. »* (`action_generate_schedule` / `_period_delta` / `_period_interest_factor`).
- *« Échéancier autorisé avant activation seulement. »* (`action_generate_schedule` hors des états `draft` à `approved`).
- *« Transition invalide : impossible de passer de "X" à "Y". »* — tentative de sauter une étape du cycle du dossier d'instruction (`ALLOWED_TRANSITIONS`).
- Boutons de validation masqués (donc action impossible depuis l'UI) si l'utilisateur n'a pas le groupe requis (`group_microfinance_credit_committee` pour les avis CA/CDAG, `group_microfinance_manager` pour l'approbation, `group_microfinance_finance` pour le décaissement) ou si l'état du crédit ne correspond pas à l'étape attendue — aucun contrôle de rôle équivalent côté dossier d'instruction (visite/contre-visite/fait).

### (B) Qualification client
- *« La société (agence) est obligatoire pour un client microfinance. »* — création/modification sans `company_id` en contexte microfinance.
- *« Le numéro de CIN doit contenir exactement 12 chiffres. »*
- *« Le NIF doit contenir exactement 12 chiffres. »*

## 9. Statuts

### `microfinance.loan.state`
Selection (`microfinance_loan.py`), `statusbar_visible="draft,enquete,avis_ca,avis_cdag,approved,active,closed,defaulted,written_off"` :
| Valeur | Libellé | Déclenché par |
|---|---|---|
| `draft` | Brouillon | Valeur par défaut à la création (création directe, menu Crédits) |
| `enquete` | Enquête | `action_start_enquete` |
| `avis_ca` | Avis CA | `action_ca_review` |
| `avis_cdag` | Avis CDAG | `action_cdag_review` |
| `approved` | Approuvé | `action_approve` |
| `active` | Actif | `action_disburse` (hors périmètre — workflow `comptabilite`) |
| `closed` | Clôturé | `action_close` (hors périmètre) |
| `defaulted` | Défaut | `action_mark_default` (hors périmètre — workflow `par_reporting`) |
| `written_off` | Radié | `action_write_off`/`action_confirm_write_off` (hors périmètre) |
| `cancelled` | Annulé | À compléter |

### `microfinance.loan.application.state`
Selection (`microfinance_loan_application.py`), `statusbar_visible="draft,visite,contre_visite,fait"` :
| Valeur | Libellé | Déclenché par |
|---|---|---|
| `draft` | Brouillon | Valeur par défaut à la création |
| `visite` | Visite | `action_start_visite` |
| `contre_visite` | Contre-Visite | `action_start_contre_visite` |
| `fait` | Fait | `action_mark_fait` |

## 10. Rapports ou PDF
Aucun rapport dédié à ce jour pour l'instruction du dossier crédit (`microfinance.loan` avant décaissement) ni pour les entités de qualification client. Le reçu de décaissement (`microfinance_loan_disbursement_receipt.xml`) existe mais appartient au workflow `comptabilite` (imprimable seulement une fois le crédit décaissé).

## 11. Tableaux de bord
Aucun indicateur spécifique à l'instruction précrédit ou à la qualification client identifié dans `microfinance_dashboard.py` dans le périmètre de fichiers lu pour ce workflow — À compléter (vérification à faire dans le workflow `dashboard` dédié). Le bouton **Nouveau prêt** du tableau de bord ouvre directement un formulaire `microfinance.loan` vierge (`openNewLoan()`).

## 12. Sécurité et groupes utilisateurs

### (A) `microfinance.loan` (extrait de `ir.model.access.csv`)
| Groupe | Lecture | Écriture | Création | Suppression |
|---|---|---|---|---|
| Agent crédit (`group_microfinance_user`) | 1 | 1 | 1 | 0 |
| Manager crédit (`group_microfinance_manager`) | 1 | 1 | 1 | 1 |
| Finance microfinance (`group_microfinance_finance`) | 1 | 1 | 0 | 0 |
| Auditeur microfinance (`group_microfinance_auditor`) | 1 | 0 | 0 | 0 |
| Comptable microfinance (`group_microfinance_comptable`) | 1 | 0 | 0 | 0 |
| Caissier microfinance (`group_microfinance_cashier`) | 1 | 0 | 0 | 0 |
| Comité de crédit (`group_microfinance_credit_committee`) | 1 | 0 | 0 | 0 |

### (B) Entités de qualification client (`ir.model.access.csv`)
| Modèle | Groupe | Lecture | Écriture | Création | Suppression |
|---|---|---|---|---|---|
| `microfinance.client.category` | Agent crédit | 1 | 0 | 0 | 0 |
| `microfinance.client.category` | Manager crédit | 1 | 1 | 1 | 1 |
| `microfinance.client.category` | Finance microfinance | 1 | 0 | 0 | 0 |
| `microfinance.client.category` | Auditeur microfinance | 1 | 0 | 0 | 0 |
| `microfinance.client.blacklist` | Agent crédit | 1 | 0 | 0 | 0 |
| `microfinance.client.blacklist` | Manager crédit | 1 | 1 | 1 | 1 |
| `microfinance.client.blacklist` | Finance microfinance | 1 | 0 | 0 | 0 |
| `microfinance.client.blacklist` | Auditeur microfinance | 1 | 0 | 0 | 0 |
| `microfinance.client.representative` | Agent crédit | 1 | 1 | 1 | 0 |
| `microfinance.client.representative` | Manager crédit | 1 | 1 | 1 | 1 |
| `microfinance.client.representative` | Finance microfinance | 1 | 0 | 0 | 0 |
| `microfinance.client.representative` | Auditeur microfinance | 1 | 0 | 0 | 0 |
| `microfinance.client.group.member` | Agent crédit | 1 | 1 | 1 | 0 |
| `microfinance.client.group.member` | Manager crédit | 1 | 1 | 1 | 1 |
| `microfinance.client.group.member` | Finance microfinance | 1 | 0 | 0 | 0 |
| `microfinance.client.group.member` | Auditeur microfinance | 1 | 0 | 0 | 0 |

Cloisonnement multi-société : `microfinance_loan_company_rule` (`security/microfinance_company_rules.xml`) restreint `microfinance.loan` à `company_id in company_ids`, sans groupe ciblé (`groups=[]`), donc appliqué à tous les utilisateurs internes sans exception.

## 13. Cas d'utilisation complets
1. **Instruction complète d'un crédit standard** : l'agent crédit ouvre `Microfinance > Crédits > Crédits`, crée un crédit, sélectionne `partner_id` et `product_id`, saisit `loan_amount` et `term`. Il clique sur **Démarrer l'enquête** (passe en `enquete`, score calculé automatiquement). Le comité de crédit clique sur **Avis CA** (`avis_ca`), puis **Avis CDAG** (`avis_cdag`). Le manager clique sur **Approuver** (`approved`, `approval_date` renseignée). Le crédit est prêt pour le décaissement (workflow `comptabilite`). Indépendamment, l'enquêteur peut suivre un dossier d'instruction pour ce même client (visite/contre-visite/fait) et, s'il le souhaite, rattacher manuellement le crédit créé au dossier via `loan_id` (aucune automatisation UI à ce jour).
2. **Création d'une fiche client société avec comité** : l'agent ouvre `Microfinance > Clients`, crée une fiche, choisit `microfinance_client_type = 'company'`, renseigne `microfinance_nif` (12 chiffres, sinon `ValidationError`), remplit les blocs Identité légale / Activité et finances / Localisation étendue, puis ajoute des lignes dans **Comité** (représentant légal, président, etc.) via `microfinance_representative_ids`.
3. **Blocage d'un second crédit sur client en arriérés** : l'agent tente de démarrer l'enquête d'un nouveau crédit pour un client ayant déjà un crédit `active` avec des échéances en retard, sur un produit configuré avec `allow_second_loan=True` mais `block_second_if_arrears=True`. Le clic sur **Démarrer l'enquête** échoue avec *« Ce client a déjà un crédit actif en arriérés. Un second crédit ne peut pas être soumis. »* — le crédit reste en `draft` jusqu'à régularisation.

## 14. Erreurs fréquentes
- *« Transition invalide... »* — étape du dossier d'instruction sautée (voir section 8).
- *« Ancienneté client insuffisante pour ce produit... »* — client créé trop récemment par rapport à `product.min_membership_days`.
- *« Ce client a déjà un crédit actif... »* / *« ...en arriérés... »* — cumul de crédits non autorisé par le produit.
- *« Ce produit exige une garantie validée avant soumission. »* / *« Garanties insuffisantes... »* — dossier de garanties incomplet (voir workflow `garanties_scoring`).
- *« Le numéro de CIN doit contenir exactement 12 chiffres. »* / *« Le NIF doit contenir exactement 12 chiffres. »* — format de pièce d'identité ou NIF incorrect sur la fiche client.
- *« La société (agence) est obligatoire pour un client microfinance. »* — fiche client créée sans agence en contexte microfinance.
- Boutons de validation absents pour l'utilisateur connecté — vérifier son groupe (`group_microfinance_credit_committee`/`group_microfinance_manager`/`group_microfinance_finance`) et l'état courant du crédit.

## 15. Bonnes pratiques
- Vérifier `microfinance_is_blacklisted` sur la fiche client avant de créer un crédit : le champ existe et est visible, mais sa vérification reste manuelle à ce jour.
- Générer l'échéancier prévisionnel (`action_generate_schedule`) avant l'enquête pour visualiser l'impact réel du `term` et de la `repayment_frequency_id` choisis, plutôt qu'après approbation.
- Compléter les catégories de classification (`microfinance_category_1/2/3`) et les données d'identité dès la création de la fiche client, car plusieurs contraintes (`_check_cin_format`, `_check_nif_format`) ne se déclenchent qu'à l'enregistrement — mieux vaut les découvrir immédiatement qu'au moment de créer un crédit.
- Pour les clients de type Groupe, renseigner systématiquement `microfinance_member_ids` (avec `income` et `planned_periodic_savings`) : ce sont les seules données structurées disponibles sur les membres du groupe.
- Ne pas confondre les étapes de validation du crédit (`microfinance.loan.state`) avec le suivi terrain du dossier d'instruction (`microfinance.loan.application.state`, visite/contre-visite/fait) ni avec la qualification du client sur la fiche partenaire : ce sont trois volets indépendants, chacun avec son propre cycle.

## 16. Questions/Réponses MOWGLI potentielles
1. Comment créer un nouveau crédit ?
2. Qui donne son avis sur un crédit après l'agent, le comité de crédit ou le manager en premier ?
3. Pourquoi je ne peux pas démarrer l'enquête d'un crédit pour ce client ?
4. Comment ajouter un client à la liste noire ?
5. Où gérer les représentants d'une société ou d'un groupe de clients ?
6. Le système bloque-t-il automatiquement les crédits pour un client blacklisté ?
7. Quelles sont les étapes de validation d'un crédit chez MOWGLI, de la création au décaissement ?
8. Comment corriger une erreur de format sur le NIF ou le CIN d'un client ?
9. Comment générer l'échéancier prévisionnel d'un crédit avant l'enquête ?
10. Que signifie chaque état de la barre de statut d'un crédit (brouillon, enquête, avis CA, avis CDAG...) ?
11. Le dossier d'instruction est-il obligatoire pour créer un crédit ?
12. À quoi sert le dossier d'instruction maintenant qu'il ne conditionne plus la création du crédit ?
