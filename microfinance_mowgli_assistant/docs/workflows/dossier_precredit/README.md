# Workflow Dossier précrédit

## 1. Objectif métier
Ce workflow couvre, tel qu'actif dans l'instance MOWGLI aujourd'hui, deux volets :
**(A)** l'instruction/validation d'un crédit avant décaissement, portée directement par `microfinance.loan` à travers ses états `draft` → `submitted` → `manager_validated` → `finance_validated` → `approved` (le décaissement lui-même, `action_disburse`, appartient au workflow `comptabilite`) ;
**(B)** la qualification/vetting du client, gérée depuis la fiche partenaire (`res.partner`) : catégories de classification, liste noire, représentants/comité et membres de groupe.
**Important** : le code contient un modèle bien plus riche et dédié à l'instruction de crédit, `microfinance.loan.application` (enquête terrain, analyse financière, comité, avis CA/CDAG, acceptation sous condition), mais ce modèle **n'est pas activé** dans l'instance actuelle (non importé dans le registre Odoo — voir section 5 « Code présent mais non activé »). Il est documenté ici à titre d'inventaire du code, jamais comme fonctionnalité utilisable. Ce workflow ne couvre pas le décaissement, les remboursements ni la comptabilité (voir `comptabilite`), ni le recouvrement des impayés (voir `par_reporting`), ni les garanties/scoring (voir `garanties_scoring`).

## 2. Utilisateurs concernés
D'après `security/groups.xml` et les `groups=` des boutons de `microfinance_loan_views.xml` :
- **Agent crédit** (`group_microfinance_user`) : crée et soumet un dossier crédit (`action_submit`), gère les fiches client (catégories, liste noire, représentants, membres) avec droits lecture/écriture/création (pas de suppression).
- **Manager crédit** (`group_microfinance_manager`) : valide le dossier au niveau manager (`action_manager_validate`) et approuve après validation finance (`action_approve`) ; droits complets (y compris suppression) sur les entités de qualification client.
- **Finance microfinance** (`group_microfinance_finance`) : valide le dossier au niveau finance (`action_finance_validate`) ; lecture/écriture sur `microfinance.loan` mais pas de création ; accès en lecture seule aux entités de qualification client.
- **Auditeur microfinance** (`group_microfinance_auditor`) : lecture seule sur `microfinance.loan` et sur les entités de qualification client.
- **Gestionnaire** (`group_microfinance_gestionnaire`) : hérite de `group_microfinance_manager` et `group_microfinance_finance` (`implied_ids`), cumule donc les capacités de validation manager et finance.
- Le champ `officer_id` (Agent crédit, défaut `self.env.user`), `manager_id` (Manager), `finance_user_id` (Utilisateur finance) sur `microfinance.loan` tracent qui a réalisé chaque étape.

## 3. Menus utilisés
Chemins reconstruits depuis `microfinance_menus.xml` et `microfinance_partner_views.xml` :
- `Microfinance > Clients` (`menu_clients_root`, parent `menu_microfinance_root`, action `action_microfinance_client` — ouvre `res.partner` en tree/form/kanban avec contexte `microfinance_context: True`). C'est ici que sont gérées les fiches client, y compris les entités de qualification (catégories, liste noire, représentants, membres de groupe), embarquées comme listes éditables dans le formulaire partenaire — **aucun menu séparé** n'existe pour `microfinance.client.category`, `microfinance.client.blacklist`, `microfinance.client.representative` ou `microfinance.client.group.member` (vérifié : ces modèles n'apparaissent dans aucun `<menuitem>`).
- `Microfinance > Crédits > Demande de crédit` (`menu_credits_root` parent `menu_microfinance_root` ; `menu_microfinance_loans` parent `menu_credits_root`, action `action_microfinance_loan`) : ouvre la liste/formulaire de `microfinance.loan`, où se déroule tout le cycle draft → approved.

## 4. Étapes principales
**(A) Cycle `microfinance.loan`**, dérivé des boutons `action_*` du formulaire (`microfinance_loan_views.xml` en-tête) et de `microfinance_loan.py` :
1. Créer un crédit (`Microfinance > Crédits > Demande de crédit`, nouveau) : état initial `draft`. Renseigner `partner_id`, `product_id`, `loan_amount`, `term`, `repayment_frequency_id` (si le produit laisse le choix), `co_borrower_id` (optionnel).
2. (Optionnel avant soumission) Générer l'échéancier prévisionnel avec **Générer échéancier** (`action_generate_schedule`, disponible tant que `state` est dans `draft, submitted, manager_validated, finance_validated, approved`).
3. Cliquer sur **Soumettre** (`action_submit`) : exécute `_check_eligibility()` puis `action_calculate_scoring(silent=True)`, passe l'état à `submitted`.
4. Le manager clique sur **Valider manager** (`action_manager_validate`) : état `manager_validated`, `manager_id` renseigné à l'utilisateur courant.
5. L'utilisateur finance clique sur **Valider finance** (`action_finance_validate`) : état `finance_validated`, `finance_user_id` renseigné.
6. Le manager clique sur **Approuver** (`action_approve`) : état `approved`, `approval_date` renseignée à la date du jour.
7. (Suite hors périmètre de ce workflow) Encaissement des frais de dossier et décaissement (`action_charge_fee`, `action_disburse`) font passer le crédit à l'état `active` — voir workflow `comptabilite`.

**(B) Qualification client**, dérivée de `microfinance_partner_views.xml` :
1. Ouvrir/créer une fiche client via `Microfinance > Clients`.
2. Choisir le type de client (`microfinance_client_type` : Particulier/Société/Groupe, widget radio).
3. Renseigner les blocs de champs spécifiques au type (Identification, Famille et compte pour un particulier ; Identité légale, Activité et finances, Localisation étendue pour une société ; Groupe pour un groupe).
4. Ajouter des lignes dans **Comité** (`microfinance_representative_ids`, pour société/groupe) et **Membres du groupe** (`microfinance_member_ids`, pour groupe uniquement).
5. Affecter jusqu'à 3 catégories de classification (`microfinance_category_1/2/3`, depuis `microfinance.client.category`).
6. Ajouter le cas échéant une entrée dans **Liste noire** (`microfinance_blacklist_ids`), avec motif et dates de début/fin.

## 5. Champs importants

### (A) `microfinance.loan` — dossier crédit (extrait pertinent à l'instruction)
- `partner_id` (Emprunteur), `product_id` (Produit), `co_borrower_id` (Co-emprunteur) : identification des parties.
- `loan_amount` (Montant crédit), `term` (Nombre échéances), `repayment_frequency_id` (Périodicité de remboursement).
- `application_date` (Date de demande), `approval_date` (Date d'approbation, readonly, renseignée par `action_approve`).
- `officer_id` (Agent crédit), `manager_id` (Manager), `finance_user_id` (Utilisateur finance) : traçabilité des acteurs de la validation.
- `state` (État) : voir section 9.
- `internal_score`, `risk_level`, `scoring_decision` : calculés par `action_calculate_scoring`, déclenché automatiquement (silencieux) lors de `action_submit`.
- `scoring_profile_id` : profil de scoring utilisé (voir workflow `garanties_scoring`).

### (B) Fiche partenaire — qualification client (`res_partner.py`, `microfinance_partner_views.xml`)
- `microfinance_client_type` (Type de client) : Particulier / Société / Groupe — pilote l'affichage conditionnel des blocs de champs (`invisible=`).
- `microfinance_internal_reference`, `microfinance_statistical_number` : identifiants internes.
- `microfinance_category_1/2/3` : catégories de classification (Many2one vers `microfinance.client.category`).
- `microfinance_exit_date`, `microfinance_exit_reason` : sortie du client.
- `microfinance_blacklist_ids` (Liste noire) : One2many vers `microfinance.client.blacklist` (champs `date_start`, `date_end`, `reason`, `active`).
- `microfinance_is_blacklisted` (calculé, stocké) : vrai si au moins une entrée de liste noire est `active` et non expirée (`date_end` vide ou ≥ aujourd'hui). **Constat de vérification** : ce champ est uniquement informatif — aucune contrainte ni contrôle dans `microfinance_loan.py` ou `microfinance_loan_product.py` ne bloque la création/soumission d'un crédit pour un client blacklisté.
- `microfinance_representative_ids` (Comité) : One2many vers `microfinance.client.representative` (société/groupe).
- `microfinance_member_ids` (Membres du groupe) : One2many vers `microfinance.client.group.member` (groupe uniquement).
- Champs d'identification particulier : `microfinance_id_type`, `microfinance_id_number` (avec contrainte CIN, voir section 7), `microfinance_birthdate`, `microfinance_gender`, `microfinance_marital_status`, `microfinance_profession`.
- Champs société : `microfinance_nif` (avec contrainte, voir section 7), `microfinance_stat`, `microfinance_rcs`, `microfinance_enterprise_type`, `microfinance_share_capital`, `microfinance_estimated_turnover`.
- `microfinance_loan_ids` / `microfinance_loan_count` : crédits liés au partenaire, avec bouton statistique et onglet **Crédit** dédié.
- Module épargne (`microfinance_savings_management/models/res_partner.py`) : `microfinance_savings_account_ids` / `microfinance_savings_count`, bouton statistique **Épargne**.

### Code présent mais non activé (non importé dans `models/__init__.py`, aucune vue/menu/droit d'accès)
Champs de `microfinance.loan.application` (`microfinance_loan_application.py`), regroupés en blocs A à F dans le fichier source :
- En-tête : `name`, `application_date`, `surveyor_id` (Enquêteur), `ca_responsible_id` (Chargé de compte responsable), `partner_id`, `loan_sequence_number` (Rang de prêt, calculé), `is_first_loan`, `loan_tier_id`/`loan_tier_label` (Palier de prêt, via le modèle également non câblé `microfinance.loan.application.tier`), `loan_id` (Crédit créé une fois transformé).
- Bloc A — Identité complète (KYC figée à l'enquête) : `partner_surname`, `partner_id_card_number`, `partner_current_address`, `partner_fokontany`, `partner_housing_status`, données du conjoint (`spouse_*`), `dependent_ids`, `guarantor_line_ids`, `document_line_ids`.
- Bloc B — Analyse de viabilité de l'activité : `activity_description`, `activity_sector`, `sale_location_status/type/enclosed`, `formalization_level`, `has_existing_debt`, `debt_amount`, etc.
- Bloc C — Analyse financière : `income_line_ids`, `safety_margin_current/forecast`, totaux calculés (`total_family_income_current/forecast`, `repayment_capacity_monthly/weekly_current/forecast`).
- Bloc D — Visites terrain pré-octroi : `field_visit_ids`, `field_visit_count`.
- Bloc E — Avis CA/CDAG : `requested_amount`, `ca_amount`, `cdag_amount`, `previous_loan_repayment_behavior`.
- Bloc F — Catégorisation sociale : `social_score_ids`.
- **Remarque supplémentaire de vérification** : plusieurs de ces One2many (`dependent_ids`, `guarantor_line_ids`, `document_line_ids`, `income_line_ids`, `field_visit_ids`, `social_score_ids`) et le wizard cité par `action_create_loan` (`microfinance.loan.application.create.loan.wizard`) référencent des modèles co-modèles qui ne sont définis nulle part ailleurs dans le module (recherche exhaustive sans résultat) : même en imaginant ce fichier importé, le module ne se chargerait pas correctement sans ces définitions manquantes.

## 6. Boutons et actions

### (A) `microfinance.loan` (`microfinance_loan_views.xml`, en-tête, ceux relatifs à l'instruction précrédit)
- `action_submit` — **Soumettre** : `type="object"`, classe `btn-primary`, `invisible="state != 'draft'"`.
- `action_manager_validate` — **Valider manager** : `type="object"`, `groups="microfinance_loan_management.group_microfinance_manager"`, `invisible="state != 'submitted'"`.
- `action_finance_validate` — **Valider finance** : `type="object"`, `groups="microfinance_loan_management.group_microfinance_finance"`, `invisible="state != 'manager_validated'"`.
- `action_approve` — **Approuver** : `type="object"`, `groups="microfinance_loan_management.group_microfinance_manager"`, `invisible="state != 'finance_validated'"`.
- `action_generate_schedule` — **Générer échéancier** : `type="object"`, `invisible="state not in ('draft','submitted','manager_validated','finance_validated','approved')"`.
- `action_recompute_risk` — **Recalculer le score** : `type="object"`, toujours visible.

### (B) Fiche partenaire (`microfinance_partner_views.xml`)
- `action_view_microfinance_loans` — bouton statistique **Crédit** (`oe_stat_button`), `invisible="not context.get('microfinance_context')"`.
- `action_view_microfinance_savings` (module épargne) — bouton statistique **Épargne**, même condition.

### Code présent mais non activé
Boutons d'étape de `microfinance.loan.application` (existent dans le code Python comme méthodes, aucune vue XML ne les expose donc aucun bouton visible en pratique) : `action_start_field_survey`, `action_start_analysis`, `action_submit_committee`, `action_ca_review`, `action_cdag_review`, `action_accept`, `action_accept_condition`, `action_refuse`, `action_reset_to_draft`, `action_sync_partner`, `action_create_loan`, `action_view_loan`.

## 7. Règles métier

### (A) `microfinance.loan`
Dérivées de `_check_eligibility()` (appelée par `action_submit`, `microfinance_loan.py` ~L380-424) :
- Ancienneté client minimale : si `product.min_membership_days` défini, la fiche client (`partner_id.create_date`) doit avoir cette ancienneté, sinon blocage (voir section 8).
- Un seul crédit actif à la fois par défaut : si le client a déjà un crédit `active` dans la même société, refus sauf si `product.allow_second_loan` est activé.
- Si `product.allow_second_loan` mais `product.block_second_if_arrears` activé, refus si le client a un crédit actif avec des échéances en retard (`overdue_installment_count > 0`).
- Le co-emprunteur (`co_borrower_id`) ne peut pas avoir lui-même un crédit actif en cours dans la même société.
- Garantie obligatoire (`product.guarantee_required`) : au moins une garantie validée requise avant soumission.
- Ratio de garantie minimum (`product.min_guarantee_ratio`) : le total des garanties validées (`guarantee_total`) doit couvrir ce pourcentage du montant du crédit.
- `action_submit` déclenche aussi `action_calculate_scoring(silent=True)` : calcul automatique du score interne avant passage à `submitted`.

### (B) Qualification client (`res_partner.py`)
- `_check_microfinance_company_required` (`@api.constrains`) : la société (agence, `company_id`) est obligatoire pour un client créé en contexte microfinance (`microfinance_context`).
- `_check_cin_format` (`@api.constrains`) : si `microfinance_id_type == 'cin'`, le numéro de pièce d'identité doit contenir exactement 12 chiffres (les caractères non numériques sont ignorés dans le comptage).
- `_check_nif_format` (`@api.constrains`) : pour un client de type `company`, le NIF doit contenir exactement 12 chiffres.
- `_compute_microfinance_is_blacklisted` : calcul automatique et stocké, dépendant de `microfinance_blacklist_ids.active` et `.date_end` (voir section 5, non bloquant).
- `_onchange_microfinance_client_type` : synchronise `is_company` natif Odoo (`True` pour société/groupe) au changement de `microfinance_client_type`.

### Code présent mais non activé
Règles de `microfinance.loan.application` (jamais exécutées dans l'instance actuelle) : machine à états stricte via `ALLOWED_TRANSITIONS` (dictionnaire de transitions autorisées par état) et `STATE_TARGET_GROUP` (rôle minimum requis par état cible, contrôlé dans `write()`/`_check_state_transition`) ; contrôle d'éligibilité au comité (`_check_committee_eligibility`, sans effet pour un premier prêt) ; calcul du rang de prêt (`loan_sequence_number`) à partir des crédits antérieurs décaissés du même partenaire ; calcul du palier de prêt (`loan_tier_id`/`loan_tier_label`) ; totaux financiers automatiques (`_compute_financial_totals`, majorations de sécurité 5%/10% sur les dépenses familiales).

## 8. Contrôles et blocages

### (A) `microfinance.loan`
- *« Ancienneté client insuffisante pour ce produit : il manque X jour(s)... »* — client trop récent pour le produit choisi.
- *« Ce client a déjà un crédit actif. Ce produit n'autorise pas de second crédit en parallèle. »*
- *« Ce client a déjà un crédit actif en arriérés. Un second crédit ne peut pas être soumis. »*
- *« Le co-emprunteur a déjà un crédit actif en cours. »*
- *« Ce produit exige une garantie validée avant soumission. »*
- *« Garanties insuffisantes : il manque X pour atteindre le ratio minimum requis... »*
- *« Choisissez une périodicité de remboursement avant de générer l'échéancier. »* (`action_generate_schedule` / `_period_delta` / `_period_interest_factor`).
- *« Échéancier autorisé avant activation seulement. »* (`action_generate_schedule` hors des états `draft` à `approved`).
- Boutons de validation masqués (donc action impossible depuis l'UI) si l'utilisateur n'a pas le groupe requis (`group_microfinance_manager` pour manager/approbation, `group_microfinance_finance` pour la validation finance) ou si l'état du crédit ne correspond pas à l'étape attendue.

### (B) Qualification client
- *« La société (agence) est obligatoire pour un client microfinance. »* — création/modification sans `company_id` en contexte microfinance.
- *« Le numéro de CIN doit contenir exactement 12 chiffres. »*
- *« Le NIF doit contenir exactement 12 chiffres. »*

### Code présent mais non activé
*« Transition invalide : impossible de passer de "X" à "Y". Étape(s) suivante(s) possible(s) : ... »* et *« Vous n'avez pas le rôle requis pour amener un dossier à l'étape "X". »* (`microfinance.loan.application._check_state_transition`) : ces messages n'apparaîtront jamais dans l'instance actuelle puisque le modèle n'est pas chargé.

## 9. Statuts

### (A) `microfinance.loan.state` (champ réel, actif)
Selection (`microfinance_loan.py` ~L39-50), `statusbar_visible="draft,submitted,manager_validated,finance_validated,approved,active,closed,defaulted,written_off"` :
| Valeur | Libellé | Déclenché par |
|---|---|---|
| `draft` | Brouillon | Valeur par défaut à la création |
| `submitted` | Soumis | `action_submit` |
| `manager_validated` | Validé manager | `action_manager_validate` |
| `finance_validated` | Validé finance | `action_finance_validate` |
| `approved` | Approuvé | `action_approve` |
| `active` | Actif | `action_disburse` (hors périmètre — workflow `comptabilite`) |
| `closed` | Clôturé | `action_close` (hors périmètre) |
| `defaulted` | Défaut | `action_mark_default` (hors périmètre — workflow `par_reporting`) |
| `written_off` | Radié | `action_write_off`/`action_confirm_write_off` (hors périmètre) |
| `cancelled` | Annulé | Non visible dans la barre de statut (`statusbar_visible` ne le liste pas) ; aucune méthode `action_*` trouvée dans le périmètre lu qui l'atteigne — À compléter |

### Code présent mais non activé — `microfinance.loan.application.state`
Selection définie dans le fichier (jamais instanciable dans l'instance actuelle) : `draft` (Brouillon) → `field_survey` (Enquête terrain) → `analysis` (Analyse) → `committee` (Soumis comité) → `ca_review` (Avis CA) → `cdag_review` (Avis CDAG) → `accepted` (Accepté) / `accepted_condition` (Accepté sous condition) / `refused` (Refusé) → `loan_created` (Transformé en crédit), avec transitions strictement encadrées par `ALLOWED_TRANSITIONS`.

## 10. Rapports ou PDF
Aucun rapport dédié à ce jour pour l'instruction du dossier crédit (`microfinance.loan` avant décaissement) ni pour les entités de qualification client. Le reçu de décaissement (`microfinance_loan_disbursement_receipt.xml`) existe mais appartient au workflow `comptabilite` (imprimable seulement une fois le crédit décaissé).

## 11. Tableaux de bord
Aucun indicateur spécifique à l'instruction précrédit ou à la qualification client identifié dans `microfinance_dashboard.py` dans le périmètre de fichiers lu pour ce workflow — À compléter (vérification à faire dans le workflow `dashboard` dédié).

## 12. Sécurité et groupes utilisateurs

### (A) `microfinance.loan` (extrait de `ir.model.access.csv`)
| Groupe | Lecture | Écriture | Création | Suppression |
|---|---|---|---|---|
| Agent crédit (`group_microfinance_user`) | 1 | 1 | 1 | 0 |
| Manager crédit (`group_microfinance_manager`) | 1 | 1 | 1 | 1 |
| Finance microfinance (`group_microfinance_finance`) | 1 | 1 | 0 | 0 |
| Auditeur microfinance (`group_microfinance_auditor`) | 1 | 0 | 0 | 0 |

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

### `microfinance.loan.application` — Aucun menu / Aucun droit d'accès : modèle non câblé dans le registre Odoo
Vérification faite dans `ir.model.access.csv` (aucune ligne `model_microfinance_loan_application*`) et dans `security/microfinance_company_rules.xml`, dont le commentaire (L23-27) confirme explicitement : *« microfinance.loan.application (dossier d'instruction) n'est pas encore câblé dans le module (absent de models/__init__.py, d'ir.model.access.csv et de toute vue) : le modèle n'existe pas dans le registre Odoo tant que cet import manque. »* Les groupes référencés dans le code (`group_application_surveyor`, `group_application_ca`, `group_application_cdag`) ne sont définis nulle part dans `security/groups.xml` ni ailleurs : ce ne sont que des chaînes de référence externe (`XML-ID`) qui échoueraient si le code tentait de les résoudre.

## 13. Cas d'utilisation complets
1. **Instruction complète d'un crédit standard** : l'agent crédit ouvre `Microfinance > Crédits > Demande de crédit`, crée un nouveau crédit, sélectionne `partner_id` et `product_id`, saisit `loan_amount` et `term`, clique sur **Soumettre** (passe en `submitted`, score calculé automatiquement). Le manager ouvre le crédit et clique sur **Valider manager** (`manager_validated`). L'utilisateur finance clique sur **Valider finance** (`finance_validated`). Le manager clique sur **Approuver** (`approved`, `approval_date` renseignée). Le crédit est prêt pour le décaissement (workflow `comptabilite`).
2. **Création d'une fiche client société avec comité** : l'agent ouvre `Microfinance > Clients`, crée une fiche, choisit `microfinance_client_type = 'company'`, renseigne `microfinance_nif` (12 chiffres, sinon `ValidationError`), remplit les blocs Identité légale / Activité et finances / Localisation étendue, puis ajoute des lignes dans **Comité** (représentant légal, président, etc.) via `microfinance_representative_ids`.
3. **Blocage d'un second crédit sur client en arriérés** : l'agent tente de soumettre un nouveau crédit pour un client ayant déjà un crédit `active` avec des échéances en retard, sur un produit configuré avec `allow_second_loan=True` mais `block_second_if_arrears=True`. Le clic sur **Soumettre** échoue avec *« Ce client a déjà un crédit actif en arriérés. Un second crédit ne peut pas être soumis. »* — le dossier reste en `draft` jusqu'à régularisation.

## 14. Erreurs fréquentes
- *« Ancienneté client insuffisante pour ce produit... »* — client créé trop récemment par rapport à `product.min_membership_days`.
- *« Ce client a déjà un crédit actif... »* / *« ...en arriérés... »* — cumul de crédits non autorisé par le produit.
- *« Ce produit exige une garantie validée avant soumission. »* / *« Garanties insuffisantes... »* — dossier de garanties incomplet (voir workflow `garanties_scoring`).
- *« Le numéro de CIN doit contenir exactement 12 chiffres. »* / *« Le NIF doit contenir exactement 12 chiffres. »* — format de pièce d'identité ou NIF incorrect sur la fiche client.
- *« La société (agence) est obligatoire pour un client microfinance. »* — fiche client créée sans agence en contexte microfinance.
- Boutons de validation absents pour l'utilisateur connecté — vérifier son groupe (`group_microfinance_manager`/`group_microfinance_finance`) et l'état courant du crédit.

## 15. Bonnes pratiques
- Vérifier `microfinance_is_blacklisted` sur la fiche client avant de soumettre un crédit : le champ existe et est visible, mais n'étant pas un contrôle bloquant dans le code, sa vérification reste manuelle à ce jour.
- Générer l'échéancier prévisionnel (`action_generate_schedule`) avant soumission pour visualiser l'impact réel du `term` et de la `repayment_frequency_id` choisis, plutôt qu'après approbation.
- Compléter les catégories de classification (`microfinance_category_1/2/3`) et les données d'identité dès la création de la fiche client, car plusieurs contraintes (`_check_cin_format`, `_check_nif_format`) ne se déclenchent qu'à l'enregistrement — mieux vaut les découvrir immédiatement qu'au moment de soumettre un crédit.
- Pour les clients de type Groupe, renseigner systématiquement `microfinance_member_ids` (avec `income` et `planned_periodic_savings`) : ce sont les seules données structurées disponibles sur les membres, en l'absence du module d'enquête terrain plus riche (`microfinance.loan.application`, non activé).
- Ne pas confondre le cycle actif (`microfinance.loan.state`) avec les états riches lus dans `microfinance_loan_application.py` (enquête terrain, comité, avis CA/CDAG) : ces derniers ne sont pas disponibles dans l'instance et ne doivent pas être évoqués comme une fonctionnalité existante auprès des utilisateurs.

## 16. Questions/Réponses MOWGLI potentielles
1. Comment soumettre un nouveau dossier de crédit pour validation ?
2. Qui valide un crédit après l'agent, le manager ou la finance en premier ?
3. Pourquoi je ne peux pas soumettre un crédit pour ce client ?
4. Comment ajouter un client à la liste noire ?
5. Où gérer les représentants d'une société ou d'un groupe de clients ?
6. Le système bloque-t-il automatiquement les crédits pour un client blacklisté ?
7. Quelles sont les étapes de validation d'un crédit chez MOWGLI, de la création au décaissement ?
8. Comment corriger une erreur de format sur le NIF ou le CIN d'un client ?
9. Existe-t-il un module d'enquête terrain avec comité et avis CA/CDAG dans MOWGLI ?
10. Que signifie chaque état de la barre de statut d'un crédit (brouillon, soumis, validé manager...) ?
