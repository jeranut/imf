# Workflow Création produit de crédit

## 1. Objectif métier
Ce workflow couvre le paramétrage des **produits de crédit** (`microfinance.loan.product`) : montants min/max, durées min/max, méthode de calcul des intérêts, mode et périodicité de remboursement, conditions d'éligibilité, pénalités de retard, frais de dossier, comptes comptables PCEC (principal, provisions, intérêts, pénalités, commissions, crédits en perte) et journaux comptables par défaut, ainsi que le volet épargne ajouté par `microfinance_savings_management` (prélèvement automatique, exigence d'apport/épargne cible). Ce qui N'est PAS couvert ici : la création d'un crédit individuel à partir d'un produit (voir `dossier_precredit`), le calcul de l'échéancier ou le décaissement (voir `comptabilite`), ni le paramétrage des produits d'épargne eux-mêmes (voir `creation_produit_epargne`).

## 2. Utilisateurs concernés
D'après `microfinance_loan_management/views/microfinance_menus.xml`, le menu `menu_microfinance_config` (qui contient "Produits de crédit") est restreint à `groups="microfinance_loan_management.group_microfinance_manager"` (Manager crédit). Par `implied_ids` (`security/groups.xml`), `group_microfinance_gestionnaire` (Gestionnaire) hérite de Manager crédit et voit donc aussi ce menu. D'après `ir.model.access.csv`, ont également un accès direct (lecture seule) au modèle sans nécessairement voir le menu (accès possible hors menu, ex. vue liée depuis un autre écran) : `group_microfinance_user` (Agent crédit, lecture seule) et `group_microfinance_comptable` (Comptable, lecture seule).

## 3. Menus utilisés
`Microfinance` (`menu_microfinance_root`) > `Configuration` (`menu_microfinance_config`, groupe Manager crédit uniquement) > `Produits de crédit` (`menu_microfinance_products`, action `action_microfinance_loan_product`).

## 4. Étapes principales
Le modèle ne porte aucun bouton `action_*` ni machine à états ; la séquence ci-dessous découle de l'ordre logique du formulaire (`view_microfinance_loan_product_form`) :
1. Manager crédit ouvre `Microfinance > Configuration > Produits de crédit` et clique sur "Nouveau".
2. Saisie de l'en-tête : nom, code (unique par société), société, devise (liée en lecture seule à la société), montant minimum/maximum, durée min./max.
3. Onglet **Calcul crédit** : taux d'intérêt annuel, méthode de calcul (Taux fixe / Solde dégressif), mode de périodicité (imposée ou au choix du client), périodicité(s) associée(s), délai de grâce.
4. Onglet **Éligibilité** : ancienneté minimum client, autorisation d'un 2ᵉ crédit actif et blocage si arriérés sur le 1ᵉʳ.
5. Onglet **Pénalités** : type de pénalité (montant fixe / pourcentage) et valeur associée.
6. Onglet **Comptabilité** : journaux de décaissement/remboursement/frais, type et montant des frais de dossier, puis l'ensemble des comptes PCEC (principal, provisions, intérêts, arriérés déclassifiés, pénalités et commissions, crédits en perte, comptes partagés).
7. Onglet **Épargne** (ajouté par `microfinance_savings_management`) : prélèvement automatique sur épargne et exigence d'épargne/apport liée au programme progressif.
8. Enregistrement : déclenche les contrôles de validation (section 7/8) ; en cas de succès, le produit devient sélectionnable lors de la création d'un crédit (workflow `dossier_precredit`, hors périmètre ici).

## 5. Champs importants
**En-tête** : `name` (Nom), `code` (Code, unique par société), `company_id` (Société), `currency_id` (Devise, `related` sur la société, lecture seule), `active` (Actif), `min_amount`/`max_amount` (Montant minimum/maximum), `min_term`/`max_term` (Durée min./max., défauts 1/12 — unité non précisée par un `help` dans le code).

**Onglet Calcul crédit** : `interest_rate` (Taux intérêt annuel (%)), `interest_method` (Méthode de calcul des intérêts : `flat` = Taux fixe, `reducing` = Solde dégressif), `repayment_frequency_mode` (Mode de périodicité de remboursement : `fixed` = Périodicité unique imposée, `client_choice` = Choix du client/agent), `repayment_frequency_id` (Périodicité de remboursement, requis si mode `fixed`), `allowed_repayment_frequency_ids` (Périodicités autorisées, requis si mode `client_choice`), `grace_period_days` (Délai de grâce en jours).

**Onglet Éligibilité** : `min_membership_days` (Ancienneté minimum client en jours), `allow_second_loan` (Autoriser un 2ᵉ crédit actif), `block_second_if_arrears` (Bloquer le 2ᵉ crédit si le 1ᵉʳ a des arriérés, visible seulement si `allow_second_loan`).

**Onglet Pénalités** : `penalty_type` (Type de pénalité : `fixed`/`percentage`), `penalty_amount` (Pénalité fixe), `penalty_rate` (Taux pénalité (%)).

**Onglet Comptabilité** : `disbursement_journal_id`/`payment_journal_id`/`fee_journal_id` (journaux décaissement/remboursement/frais, domaine banque ou caisse, défaut = journal de code `CRE` de la société), `fee_type`/`fee_amount`/`fee_rate` (type et montant des frais de dossier), `fee_charged_before_disbursement` (Frais exigés avant décaissement — bloque le décaissement tant que les frais dus ne sont pas encaissés), puis les paires de comptes individuel/groupe : `account_principal_*`, `account_provision_*`, `account_provision_cout_*`, `account_interets_recus_*`, `account_interets_echus_*`, `account_interets_echus_recevoir_*`, `account_arrieres_declassifies_*`, `account_penalites_avance_*`, `account_revenu_penalites_avance_*`, `account_commissions_echues_*`, `account_commissions_accumulees_*`, `account_credits_perte_*`, plus les comptes partagés `account_recouvrement_id`, `account_commission_credit_id`, `account_penalites_id`, `account_papeterie_id`, `account_surpaiement_id`. Chaque compte est pré-rempli automatiquement à l'ouverture d'un nouveau produit à partir du code PCEC correspondant, recherché dans le plan comptable de la société active (voir section 7).

**Onglet Épargne** (module `microfinance_savings_management`) : `allow_savings_auto_debit` (Autoriser le prélèvement automatique sur épargne), `auto_debit_grace_days` (Délai de grâce avant prélèvement, jours), `auto_debit_respect_minimum_balance` (Respecter le solde minimum épargne), `savings_requirement_type` (Exigence épargne : `none`/`target_during_loan`/`upfront_apport`), `savings_product_id` (Produit d'épargne du programme), `savings_target_ratio` (Ratio épargne cible (%), défaut 20.0), `savings_apport_ratio` (Ratio d'apport (%)), `savings_amount_threshold` (Seuil de montant, informatif uniquement).

## 6. Boutons et actions
Aucun bouton `type="object"` : le formulaire n'a pas de `<header>`/statusbar. Seuls les boutons standard du chatter (`<chatter/>`, hérité de `mail.thread`/`mail.activity.mixin`) sont présents (suivre, envoyer un message, planifier une activité), sans logique métier spécifique à ce module.

## 7. Règles métier
- Contrainte SQL : `code_company_unique` — le code produit doit être unique par société (`unique(code, company_id)`).
- Contrôles de validation automatiques sur `min_amount`, `max_amount`, `min_term`, `max_term`, `interest_rate`, `grace_period_days`, `min_membership_days`, `min_guarantee_ratio`, `fee_amount`, `fee_rate` : voir messages d'erreur exacts en section 8.
- Contrôle de cohérence automatique entre `repayment_frequency_mode`, `repayment_frequency_id` et `allowed_repayment_frequency_ids` : le mode choisi et la périodicité renseignée doivent être cohérents.
- Valeurs par défaut automatiques : tous les comptes PCEC sont pré-remplis en recherchant, pour la société active, le compte dont le code correspond au code PCEC attendu (ex. 203001 pour le principal individuel) ; les journaux de décaissement/remboursement/frais sont pré-remplis de la même façon avec le code journal `CRE`. Si le compte ou le journal n'existe pas encore pour la société (plan PCEC non chargé), le champ concerné reste simplement vide et doit être renseigné manuellement (voir section 14).
- Pour chaque famille de compte comptable, le système choisit automatiquement la variante Individuel ou Groupe selon le type de client du crédit (particulier/société vs groupe à caution solidaire) au moment des écritures comptables du crédit (hors périmètre de ce README, voir workflow `comptabilite`).
- Les valeurs par défaut du volet épargne (`savings_target_ratio=20.0`, etc.) sont explicitement documentées dans le code comme des hypothèses de configuration à valider avec l'équipe métier, pas des constantes universelles.

## 8. Contrôles et blocages
Messages d'erreur exacts levés par `_check_values` (`ValidationError`) :
- Montants incohérents (`min_amount < 0`, `max_amount <= 0`, ou `max_amount < min_amount`) : "Vérifiez les montants minimum et maximum."
- Durées incohérentes (`min_term <= 0` ou `max_term < min_term`) : "Vérifiez les durées minimum et maximum."
- Taux d'intérêt négatif : "Le taux intérêt ne peut pas être négatif."
- Délai de grâce négatif : "Le délai de grâce ne peut pas être négatif."
- Ancienneté minimum négative : "L'ancienneté minimum ne peut pas être négative."
- Ratio minimum de garantie négatif : "Le ratio minimum de garantie ne peut pas être négatif."
- Frais de dossier négatifs (`fee_amount` ou `fee_rate`) : "Les frais de dossier ne peuvent pas être négatifs."

Messages levés par `_check_repayment_frequency_mode` :
- Mode `fixed` sans `repayment_frequency_id` renseigné : "Choisissez la périodicité de remboursement imposée par ce produit."
- Mode `client_choice` sans aucune `allowed_repayment_frequency_ids` : "Autorisez au moins une périodicité pour un produit à choix du client."

Contrainte SQL : "Le code produit doit être unique par société." si le couple code+société existe déjà.

Champs requis structurellement (`required=True`) bloquant l'enregistrement si vides : `name`, `code`, `min_amount`, `max_amount`, `min_term`, `max_term`, `interest_rate`, `interest_method`, `repayment_frequency_mode`, `company_id`, `fee_type`, `penalty_type`, `account_principal_individuel_id`, `account_principal_groupe_id`, `account_interets_recus_individuel_id`, `account_interets_recus_groupe_id`.

## 9. Statuts
Le modèle `microfinance.loan.product` **n'a pas de champ `state`** ni de machine à états. Le seul champ proche d'un statut est `active` (booléen, défaut `True`), qui contrôle l'archivage standard Odoo (masquage du produit des listes par défaut) sans transition ni bouton dédié : il se bascule via le menu contextuel "Archiver/Désarchiver" standard, pas par un bouton `action_*` métier.

## 10. Rapports ou PDF
Aucun rapport dédié à ce jour.

## 11. Tableaux de bord
Le modèle `microfinance.dashboard` (workflow `dashboard`) agrège ses indicateurs par crédit (`microfinance.loan`) et par état, jamais par produit de crédit sous-jacent : aucun indicateur du dashboard n'est actuellement ventilé par `microfinance.loan.product`.

## 12. Sécurité et groupes utilisateurs
D'après `microfinance_loan_management/security/ir.model.access.csv`, pour le modèle `microfinance.loan.product` :

| Groupe | Lecture | Écriture | Création | Suppression |
|---|---|---|---|---|
| Agent crédit (`group_microfinance_user`) | Oui | Non | Non | Non |
| Manager crédit (`group_microfinance_manager`) | Oui | Oui | Oui | Oui |
| Comptable (`group_microfinance_comptable`) | Oui | Non | Non | Non |

Par `implied_ids` : Finance microfinance, Agent recouvrement, Caissier et Comité de crédit héritent de `group_microfinance_user` (lecture seule) ; le Gestionnaire hérite de Manager crédit + Finance, donc accès complet (lecture/écriture/création/suppression) comme un Manager. L'Auditeur microfinance n'a **aucune** ligne d'accès sur ce modèle (aucune ligne dans `ir.model.access.csv`, pas d'`implied_ids`) : il ne peut pas consulter les produits de crédit.

Règle multi-société `microfinance_loan_product_company_rule` (`security/microfinance_company_rules.xml`) : `domain_force = [('company_id', 'in', company_ids)]`, avec `groups` vide — s'applique à **tous** les utilisateurs internes sans exception (y compris Manager et Gestionnaire), cloisonnement non contournable par société/agence.

À noter : même si Comptable a un accès en lecture au modèle, le menu "Produits de crédit" est réservé au groupe Manager crédit (section 2/3) — un Comptable pur ne voit pas ce menu et ne peut consulter les produits que via un autre écran les référençant.

## 13. Cas d'utilisation complets
1. **Manager crédit crée un nouveau produit** : `Microfinance > Configuration > Produits de crédit` → "Nouveau" → saisie nom/code/montants/durées → onglet "Calcul crédit" (taux, méthode, périodicité) → onglet "Comptabilité" (vérification/ajustement des comptes PCEC pré-remplis par défaut et des journaux) → Enregistrer. Si le code existe déjà pour la société, l'enregistrement échoue avec le message de contrainte SQL.
2. **Manager crédit configure un produit à périodicité au choix du client** : ouverture d'un produit existant → onglet "Calcul crédit" → bascule `repayment_frequency_mode` sur "Choix du client/agent parmi une liste autorisée" → renseignement d'au moins une valeur dans `allowed_repayment_frequency_ids` (sinon blocage à l'enregistrement) → Enregistrer.
3. **Gestionnaire active le prélèvement automatique sur épargne pour un produit** : ouverture d'un produit → onglet "Épargne" → coche `allow_savings_auto_debit` → saisie du délai de grâce et du choix de respecter ou non le solde minimum → Enregistrer (aucune contrainte serveur spécifique à ce sous-bloc, hors les contraintes générales de la section 8).

## 14. Erreurs fréquentes
- Blocage à l'enregistrement avec "Vérifiez les montants minimum et maximum." : montant maximum ≤ 0, ou montant maximum inférieur au minimum.
- Blocage avec "Vérifiez les durées minimum et maximum." : durée maximum inférieure à la durée minimum, ou durée minimum ≤ 0.
- Blocage avec "Choisissez la périodicité de remboursement imposée par ce produit." : mode "Périodicité unique imposée" sélectionné sans avoir renseigné `repayment_frequency_id`.
- Blocage avec "Autorisez au moins une périodicité pour un produit à choix du client." : mode "Choix du client/agent" sans aucune périodicité autorisée cochée.
- Blocage à l'enregistrement d'un second produit avec le même code dans la même société : violation de la contrainte SQL d'unicité.
- Comptes PCEC vides après création : le plan comptable PCEC n'est pas encore chargé pour la société (aucun compte trouvé avec le code PCEC attendu pour cette société), les champs concernés restent vides et doivent être renseignés manuellement.
- Un utilisateur Comptable ne trouve pas le menu "Produits de crédit" : accès en lecture au modèle mais pas au menu, réservé au groupe Manager crédit.

## 15. Bonnes pratiques
- Vérifier après création d'un produit que les comptes PCEC obligatoires (`account_principal_*`, `account_interets_recus_*`) sont bien renseignés, ces champs étant `required=True` et donc bloquants si le plan PCEC de la société n'est pas encore chargé au moment de la création.
- Garder `code` cohérent et stable une fois le produit utilisé par des crédits actifs, car il est contraint à l'unicité par société mais librement modifiable ensuite (pas de verrouillage après première utilisation détecté dans le code).
- Documenter en dehors de l'outil les hypothèses de configuration du volet épargne (`savings_target_ratio`, `savings_apport_ratio`, `savings_amount_threshold`) : le code lui-même indique que ces valeurs par défaut ne sont pas des constantes métier universelles et doivent être validées institution par institution.
- Ne pas confondre `savings_amount_threshold` avec un contrôle actif : le code précise explicitement qu'il est purement informatif, seul `savings_requirement_type` pilote le contrôle réel.

## 16. Questions/Réponses MOWGLI potentielles
- Comment créer un nouveau produit de crédit ?
- Quel est le montant maximum autorisé pour le produit X ?
- Comment configurer un produit avec un taux d'intérêt dégressif ?
- Où sont paramétrés les comptes comptables PCEC d'un produit de crédit ?
- Pourquoi mon enregistrement de produit de crédit est-il refusé ?
- Comment autoriser le client à choisir sa périodicité de remboursement ?
- Quels comptes sont utilisés pour la provision d'un crédit de groupe ?
- Comment activer le prélèvement automatique sur l'épargne pour un produit ?
- Qui a le droit de modifier les produits de crédit ?
- Pourquoi je ne vois pas le menu Produits de crédit dans mon compte ?
