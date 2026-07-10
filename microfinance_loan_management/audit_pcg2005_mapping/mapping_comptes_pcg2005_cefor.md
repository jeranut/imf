# Mapping proposé — Comptes `account.account` des produits microfinance vs plan comptable PCG 2005 chargé (CEFOR)

**Statut : audit / proposition uniquement. Aucune valeur n'a été assignée sur les fiches produit, aucun compte n'a été créé, aucun code n'a été modifié.**

## 0. Méthodologie et sources

- **Pack de localisation identifié** : module tiers **`softeam_l10n_mg`** (éditeur Softeam, version `17.0.1.0.0`), installé avec son module compagnon `softeam_l10n_mg_reports`. Il s'agit bien du pack "Madagascar - PCG 2005" visible dans Comptabilité / Configuration / Paramètres / Localisation fiscale. Fichiers source : `/opt/odoo17/imf_git/softeam_l10n_mg/`.
- **Base inspectée** : la base Postgres **`SEFOR`** est la seule instance où les trois modules `softeam_l10n_mg`, `microfinance_loan_management` et `microfinance_savings_management` sont à l'état `installed` simultanément — c'est donc l'instance opérationnelle de CEFOR (la société y est encore nommée "My Company", à renommer séparément si besoin). Les autres bases présentes sur le serveur (`BASE`, `DATA`, `EATDA`, `CEFOR`, `PACKIMMO`, `PACKS`, `imf_test_dev`, etc.) n'ont pas cette combinaison complète et n'ont pas été retenues.
- **Extraction** : requête directe sur la table `account_account` de `SEFOR` (société id=1), 474 comptes, tous actifs (`deprecated = false`). Résultat complet dans [`plan_comptable_extrait.md`](./plan_comptable_extrait.md), trié par code.
- **Champs recensés** : lecture intégrale de `microfinance_loan_management/models/microfinance_loan_product.py` (31 champs `account.account` : 24 segmentés Individuel/Groupe + 7 partagés) et `microfinance_savings_management/models/microfinance_savings_product.py` (21 champs : 15 segmentés Individuel/Groupe/Entreprise + 6 partagés).

## Constat majeur (à lire avant le tableau)

Le plan comptable réellement chargé par `softeam_l10n_mg` est une **transposition générique du PCG 2005 malgache pour une entreprise commerciale/industrielle classique** (classes 1 à 8 de type OHADA/PCG standard : achats, ventes de produits/marchandises, immobilisations, comptes de tiers génériques « Clients »/« Fournisseurs »). Il **ne contient aucun compte dédié à une activité d'établissement de microfinance** :

- Aucun compte « épargne », « dépôts clients », « encours de crédit », « provisions pour créances en souffrance » au sens réglementaire IMF.
- **Aucune segmentation native Individuel / Groupe / Entreprise** sur quelque poste que ce soit — la classe 45 « Groupe et Associés » du PCG désigne les opérations avec un groupe de sociétés (holding/filiales), **pas** les groupes de clients solidaires d'un crédit de groupe. C'est un faux-ami à ne pas confondre : elle n'a **pas** été retenue comme candidate pour les comptes de crédit de groupe.
- Le principal des crédits ne se trouve dans **aucune classe dédiée** : la classe 2 (immobilisations financières, ex. 274xxx « Prêts ») est de type `asset_fixed` (incompatible avec le domaine `asset_receivable`/`asset_current` du champ) et la classe 4 ne contient que des comptes clients génériques (411100 « Clients Malagasy », etc.) sans lien sémantique avec une activité de crédit. La classe identifiée par correspondance de type est donc la **classe 41 (Clients et comptes rattachés)**, mais aucun de ses intitulés ne mentionne le crédit ou le prêt — confiance faible, à traiter comme candidat de type uniquement.
- Conséquence pratique : **la quasi-totalité des postes obligatoires nécessiteront la création de comptes dédiés** par le comptable CEFOR ; le tableau ci-dessous ne propose que des candidats de **repli** (type compatible, intitulé le plus proche) destinés à orienter la réflexion, jamais des correspondances définitives.

---

## 1. Tableau de correspondance — Crédit (`microfinance.loan.product`)

| Champ module | Libellé FR | Domaine `account_type` | Oblig. | Compte(s) candidat(s) — Code / Intitulé (type réel) | Confiance |
|---|---|---|---|---|---|
| `account_principal_individuel_id` | Principal en cours - Individuel | asset_receivable, asset_current | Oui | 411100 Clients Malagasy (asset_receivable) — type compatible, intitulé générique non lié au crédit | À confirmer |
| `account_principal_groupe_id` | Principal en cours - Groupe | asset_receivable, asset_current | Oui | Aucun compte candidat — création nécessaire (411100 est déjà proposé pour l'individuel ; aucune 2ᵉ variante « groupe » n'existe dans le plan) | À confirmer |
| `account_provision_individuel_id` | Provision mauvaises créances - Individuel | liability_current, asset_current | Non | 491000 Pertes de valeur sur comptes de clients (asset_current, lettrable) | Moyenne |
| `account_provision_groupe_id` | Provision mauvaises créances - Groupe | liability_current, asset_current | Non | Aucun compte candidat distinct — création nécessaire | À confirmer |
| `account_provision_cout_individuel_id` | Provision coûts des mauvaises créances - Individuel | expense | Non | 685000 Dotations - actifs courants (expense) | Moyenne |
| `account_provision_cout_groupe_id` | Provision coûts des mauvaises créances - Groupe | expense | Non | Aucun compte candidat distinct — création nécessaire | À confirmer |
| `account_interets_recus_individuel_id` | Intérêts reçus sur crédits - Individuel | income | Oui | 762600 Revenus des prêts (income, classe 76 Produits financiers) | Élevée |
| `account_interets_recus_groupe_id` | Intérêts reçus sur crédits - Groupe | income | Oui | 762600 Revenus des prêts (income) — même compte que ci-dessus, aucune variante « groupe » | À confirmer |
| `account_interets_echus_individuel_id` | Intérêts échus - Individuel | asset_current, income | Non | 418200 Clients intérêts courus (asset_current, lettrable, classe 41) | Moyenne |
| `account_interets_echus_groupe_id` | Intérêts échus - Groupe | asset_current, income | Non | Aucun compte candidat distinct — création nécessaire | À confirmer |
| `account_interets_echus_recevoir_individuel_id` | Intérêts échus à recevoir - Individuel | asset_receivable, asset_current | Non | 418200 Clients intérêts courus (asset_current) — même compte que « intérêts échus », risque de confusion si les deux mécanismes sont actifs simultanément | À confirmer |
| `account_interets_echus_recevoir_groupe_id` | Intérêts échus à recevoir - Groupe | asset_receivable, asset_current | Non | Aucun compte candidat distinct — création nécessaire | À confirmer |
| `account_arrieres_declassifies_individuel_id` | Crédits en arriérés déclassifiés - Individuel | asset_current | Non | 416000 Clients douteux (asset_current, lettrable, classe 41) | Moyenne |
| `account_arrieres_declassifies_groupe_id` | Crédits en arriérés déclassifiés - Groupe | asset_current | Non | Aucun compte candidat distinct — création nécessaire | À confirmer |
| `account_penalites_avance_individuel_id` | Pénalités comptabilisées d'avance - Individuel | liability_current | Non | 487000 Produits constatés d'avance (liability_current, lettrable, classe 48) | Moyenne |
| `account_penalites_avance_groupe_id` | Pénalités comptabilisées d'avance - Groupe | liability_current | Non | 487000 Produits constatés d'avance (liability_current) — même compte, à sous-compter | À confirmer |
| `account_revenu_penalites_avance_individuel_id` | Revenu des pénalités comptabilisées d'avance - Individuel | income | Non | Aucun compte candidat clair — aucun compte de produit « pénalités » distinct de la commission dans le PCG chargé (voir 757000 en repli) | À confirmer |
| `account_revenu_penalites_avance_groupe_id` | Revenu des pénalités comptabilisées d'avance - Groupe | income | Non | Aucun compte candidat — création nécessaire | À confirmer |
| `account_commissions_echues_individuel_id` | Commissions échues accumulées - Individuel | liability_current | Non | 487000 Produits constatés d'avance (liability_current) — même compte que les pénalités d'avance, conflit potentiel | À confirmer |
| `account_commissions_echues_groupe_id` | Commissions échues accumulées - Groupe | liability_current | Non | Aucun compte candidat distinct — création nécessaire | À confirmer |
| `account_commissions_accumulees_individuel_id` | Commissions accumulées gagnées - Individuel | income | Non | 708200 Commissions et courtages (income, classe 70) | Moyenne |
| `account_commissions_accumulees_groupe_id` | Commissions accumulées gagnées - Groupe | income | Non | 708200 Commissions et courtages (income) — même compte, à sous-compter | À confirmer |
| `account_credits_perte_individuel_id` | Crédits passés en perte - Individuel | expense | Non (requis à la radiation) | 654000 Pertes sur créances irrécouvrables (expense, classe 65) | Élevée |
| `account_credits_perte_groupe_id` | Crédits passés en perte - Groupe | expense | Non (requis à la radiation) | 654000 Pertes sur créances irrécouvrables (expense) — même compte, à sous-compter si le suivi analytique individuel/groupe est requis | Moyenne |
| `account_recouvrement_id` | Recouvrement des créances | income | Non | 756000 Libéralités perçues, rentrées sur créances amorties (income, classe 75) | Moyenne |
| `account_commission_credit_id` | Commission sur crédit | income | Non (requis si frais encaissés) | 708200 Commissions et courtages (income) | Moyenne |
| `account_papeterie_id` | Papeterie | income | Non | Aucun compte candidat clair — aucun compte de produit « frais de dossier/papeterie » distinct ; repli possible sur 708800 Autres produits des activités annexes (income) | À confirmer |
| `account_penalites_id` | Pénalités crédits | income | Non (requis si pénalités perçues) | Aucun compte candidat direct — repli possible sur 757000 Produits exceptionnels sur opérations de gestion (income, classe 75) | À confirmer |
| `account_cheques_id` | Comptes chèques | asset_current | Non | **Incohérence de domaine** : les comptes chèques réels du PCG (511200 Chèques à encaisser, 517100 Centre Chèques Postaux) sont de type `asset_cash`, pas `asset_current`. Aucun compte `asset_current` ne correspond au libellé « chèques ». À arbitrer : élargir le domaine du champ ou créer un compte intermédiaire dédié | À confirmer |
| `account_surpaiement_id` | Surpaiement | liability_current | Non | Aucun compte candidat — création nécessaire | À confirmer |
| `account_diff_monnaie_id` | Différences de monnaie | income, expense | Non | 766000 Gains de change (income) / 666000 Pertes de change (expense) — le champ est unique alors qu'il faudrait un compte de gain **et** un compte de perte distincts | À confirmer |

## 2. Tableau de correspondance — Épargne (`microfinance.savings.product`)

| Champ module | Libellé FR | Domaine `account_type` | Oblig. | Compte(s) candidat(s) — Code / Intitulé (type réel) | Confiance |
|---|---|---|---|---|---|
| `account_epargne_individuel_id` | Épargne - Individuel | liability_current | Oui | 165000 Dépôts et cautionnements reçus (liability_current, classe 16) | Moyenne |
| `account_epargne_groupe_id` | Épargne - Groupe | liability_current | Oui | 165000 Dépôts et cautionnements reçus (liability_current) — même compte, aucune variante « groupe » | À confirmer |
| `account_epargne_entreprise_id` | Épargne - Entreprise | liability_current | Oui | 165000 Dépôts et cautionnements reçus (liability_current) — même compte, aucune variante « entreprise » | À confirmer |
| `account_interet_paye_individuel_id` | Intérêt payé - Individuel | expense | Non | 661500 Intérêts des comptes courants et des dépôts créditeurs (expense, classe 66) | Élevée |
| `account_interet_paye_groupe_id` | Intérêt payé - Groupe | expense | Non | 661500 Intérêts des comptes courants et des dépôts créditeurs (expense) — même compte, à sous-compter | Moyenne |
| `account_interet_paye_entreprise_id` | Intérêt payé - Entreprise | expense | Non | 661500 Intérêts des comptes courants et des dépôts créditeurs (expense) — même compte, à sous-compter | Moyenne |
| `account_interets_avance_individuel_id` | Intérêts comptabilisés d'avance - Individuel | liability_current | Non | 487000 Produits constatés d'avance (liability_current, classe 48) | Moyenne |
| `account_interets_avance_groupe_id` | Intérêts comptabilisés d'avance - Groupe | liability_current | Non | 487000 Produits constatés d'avance (liability_current) — même compte | À confirmer |
| `account_interets_avance_entreprise_id` | Intérêts comptabilisés d'avance - Entreprise | liability_current | Non | 487000 Produits constatés d'avance (liability_current) — même compte | À confirmer |
| `account_cout_interet_payer_individuel_id` | Coût de l'intérêt à payer - Individuel | liability_current | Non | 168800 Intérêts courus (liability_current, classe 16 Emprunts et dettes assimilés) | Moyenne |
| `account_cout_interet_payer_groupe_id` | Coût de l'intérêt à payer - Groupe | liability_current | Non | 168800 Intérêts courus (liability_current) — même compte | À confirmer |
| `account_cout_interet_payer_entreprise_id` | Coût de l'intérêt à payer - Entreprise | liability_current | Non | 168800 Intérêts courus (liability_current) — même compte | À confirmer |
| `account_charge_interet_negatif_individuel_id` | Charge de l'intérêt négative - Individuel | income | Non | Aucun compte candidat — mécanisme spécifique (taux négatif) absent du PCG standard, création nécessaire | À confirmer |
| `account_charge_interet_negatif_groupe_id` | Charge de l'intérêt négative - Groupe | income | Non | Aucun compte candidat — création nécessaire | À confirmer |
| `account_charge_interet_negatif_entreprise_id` | Charge de l'intérêt négative - Entreprise | income | Non | Aucun compte candidat — création nécessaire | À confirmer |
| `account_penalites_id` | Pénalités sur épargne | income | Non | Repli possible sur 757000 Produits exceptionnels sur opérations de gestion (income) | À confirmer |
| `account_commission_id` | Commission sur épargne | income | Non (requis si frais prélevés) | 708200 Commissions et courtages (income) | Moyenne |
| `account_cheques_id` | Comptes chèques | asset_current | Non | Même incohérence de domaine que côté crédit (comptes chèques réels = `asset_cash`) — à arbitrer | À confirmer |
| `account_commission_cheques_rejetes_id` | Commission sur chèques rejetés | income | Non | Repli possible sur 708400 Frais accessoires refacturés (income) | À confirmer |
| `account_retenue_taxe_id` | Retenue de taxe | liability_current | Non | 447000 Autres impôts, taxes et versements assimilés (liability_current, lettrable, classe 44) | Moyenne |
| `account_papeterie_id` | Papeterie pour l'épargne | income | Non | Repli possible sur 708800 Autres produits des activités annexes (income) | À confirmer |

---

## 3. Synthèse — postes sans compte candidat sérieux (création nécessaire)

Aucun intitulé du plan chargé ne correspond, même approximativement, à ces postes :

- `account_principal_groupe_id` (crédit, **obligatoire**)
- `account_provision_groupe_id`, `account_provision_cout_groupe_id`
- `account_interets_echus_groupe_id`, `account_interets_echus_recevoir_groupe_id`
- `account_arrieres_declassifies_groupe_id`
- `account_revenu_penalites_avance_individuel_id`, `account_revenu_penalites_avance_groupe_id`
- `account_commissions_echues_groupe_id`
- `account_surpaiement_id`
- `account_charge_interet_negatif_individuel_id`, `_groupe_id`, `_entreprise_id` (épargne)

Ces champs devront recevoir un compte dédié créé par le comptable CEFOR, en cohérence avec le plan comptable réel plutôt qu'avec des repères théoriques.

## 4. Points nécessitant arbitrage du comptable CEFOR

1. **Granularité Individuel / Groupe / Entreprise absente du PCG chargé.** Pour presque tous les postes segmentés, le plan ne propose qu'un seul compte générique candidat par type de mouvement (ex. 411100 pour tout le principal, 165000 pour toute l'épargne, 708200 pour toute commission). CEFOR doit décider : (a) créer de véritables sous-comptes par segment (ex. 411110/411120, sur le modèle historique LPF évoqué), ou (b) accepter que plusieurs champs du module pointent temporairement vers le même compte PCG en distinguant les segments uniquement par analytique/dimension Odoo. Cette décision structure tout le paramétrage à venir.
2. **Absence totale de comptes « épargne »/« encours de crédit » dédiés.** Le pack `softeam_l10n_mg` est un plan comptable général ; il n'a manifestement pas été enrichi pour une activité de microfinance. Le comptable doit valider s'il faut demander une extension du plan (nouveaux comptes sous 41x, 45x ou une classe dédiée) plutôt que de forcer les mouvements de crédit/épargne dans des comptes « Clients »/« Fournisseurs » génériques dont les libellés ne correspondent pas à l'activité.
3. **Faux-ami classe 45 « Groupe et Associés ».** À écarter explicitly des comptes de « crédit de groupe » — signalé dans le constat majeur pour éviter toute confusion lors de la validation.
4. **Domaine `asset_current` des champs "Comptes chèques"** (crédit et épargne) ne correspond à aucun compte réel : les comptes chèques du PCG chargé sont typés `asset_cash`. À trancher : élargir le domaine du champ (nécessite une modification de code, hors périmètre de cet audit) ou faire créer par le comptable un compte de transit `asset_current` dédié.
5. **Champ unique `account_diff_monnaie_id` pour gains et pertes de change.** Le PCG distingue 766000 (gain) et 666000 (perte) ; le module n'a qu'un seul champ. À arbitrer entre extension du modèle (hors périmètre ici) ou usage d'un compte de transit unique.
6. **Chevauchements potentiels** entre plusieurs champs pointant vers le même compte candidat générique (ex. 487000 pour « pénalités d'avance » ET « commissions échues » côté crédit, et « intérêts d'avance » côté épargne ; 708200 pour plusieurs lignes de commission) : si CEFOR active plusieurs de ces mécanismes simultanément sur un même produit, un compte partagé empêchera la ventilation analytique fine — à surveiller lors de la validation finale.

---

## 5. Livrables produits

- [`plan_comptable_extrait.md`](./plan_comptable_extrait.md) — extrait complet des 474 comptes actifs de la base SEFOR (étape 2).
- Le présent fichier — mapping et rapport d'audit (étapes 3 à 5).

**Emplacement** : `microfinance_loan_management/audit_pcg2005_mapping/` (racine du dépôt `/opt/odoo17/imf_git` non accessible en écriture avec les droits actuels — voir note ci-dessous).

**Rappel du périmètre** : aucune création de compte, aucune assignation de valeur sur les champs `account_id` des produits, aucune modification du code des modules n'a été effectuée dans le cadre de cet audit.
