# Gestion des crédits microfinance

Ce module permet à une institution de microfinance de gérer l'ensemble du cycle de vie
d'un crédit : configuration des produits, instruction du dossier, validation, décaissement,
suivi des remboursements, incidents (retard, rééchelonnement, radiation) et pilotage du
portefeuille.

## Installation

Depuis Apps, rechercher « Gestion des crédits microfinance » et cliquer sur Installer.

Ce module s'appuie sur les états financiers fournis par le module **Comptabilité** installé
avec Odoo. Avant de créer vos produits de crédit, assurez-vous que votre plan comptable
général est en place (comptes de créances, de produits d'intérêts, de charges, etc.).

## Mettre en place un produit de crédit

Menu **Microfinance > Configuration > Produits de crédit**.

Un produit de crédit regroupe toutes les règles qui s'appliqueront aux dossiers créés à
partir de lui (un « crédit express », un « crédit agricole », etc.). Le code du produit
(ex. `CR00001`) est généré automatiquement à la création — préfixe configurable par société
(Paramètres > Sociétés, champ « Préfixe code produit crédit », par défaut `CR`), verrouillé
dès le premier produit créé pour cette société afin de ne jamais mélanger deux styles de code
dans l'historique.

**Onglet Calcul crédit**
- Taux d'intérêt annuel, et méthode de calcul (taux fixe ou solde dégressif)
- Périodicité de remboursement : soit imposée par le produit (ex. toujours hebdomadaire),
  soit au choix de l'agent parmi une liste de périodicités autorisées à la création du crédit
- Délai de grâce éventuel avant la première échéance

**Onglet Éligibilité**
- Ancienneté minimum exigée du client
- Autoriser ou non un second crédit actif en parallèle, et le bloquer si le premier a des
  arriérés

**Onglet Pénalités**
- Pénalité de retard fixe ou en pourcentage

**Onglet Comptabilité**

C'est ici que le service comptable/finance configure, pour ce produit, quels comptes du
plan comptable général recevoir les écritures générées automatiquement par les opérations
de crédit (décaissement, remboursement, frais, pénalités, radiation, provisions). La plupart
des postes sont **ventilés séparément pour les clients individuels et pour les groupes**
(un crédit accordé à un groupe solidaire est comptabilisé sur ses propres comptes), certains
comptes restant communs à tous les types de client (frais, pénalités, chèques, etc.).

Seuls le compte du principal en cours et le compte des intérêts reçus sont obligatoires pour
pouvoir enregistrer le premier crédit sur ce produit ; tous les autres postes (provisions,
crédits en perte, intérêts échus, commissions, comptes partagés) peuvent rester vides tant
que l'institution n'utilise pas le mécanisme correspondant — un message d'aide l'indique sur
chaque champ. Ces comptes doivent déjà exister dans votre plan comptable avant de les
sélectionner ici.

Renseignez également les journaux de décaissement et de remboursement (avec un compte par
défaut sur chacun).

## Le parcours d'un dossier de crédit

Un crédit (`microfinance.loan`) ne se crée **jamais directement** : il ne peut naître que
depuis un **dossier d'instruction** (`microfinance.loan.application`, menu **Microfinance >
Crédits > Dossiers d'instruction**) accepté, via le bouton **Créer le crédit**. Toute tentative
de création directe (API, import, ORM) sans passer par ce chemin est bloquée par un verrou
serveur (`microfinance.loan.create()`), quel que soit le rôle de l'utilisateur — le menu
**Crédits** ne sert plus qu'à consulter/suivre les crédits déjà créés (aucun bouton de
création).

### 1. Instruction du dossier

1. **Création du dossier** : sélection du client, du produit visé (`loan_product_id`), et
   des informations d'enquête (date, enquêteur, agence…).
2. **Enquête terrain**, **Analyse**, **Soumission au comité**, **Avis CA**, **Avis CDAG** :
   le dossier passe par ces étapes successives, chacune réservée au rôle correspondant
   (enquêteur, membre du comité, membre CA, membre CDAG).
3. **Acceptation** (avec ou sans condition) ou **Refus** par le CDAG.

### 2. Création et validation du crédit

4. **Créer le crédit** : depuis un dossier accepté, ce bouton ouvre un wizard minimal
   (produit pré-rempli depuis le dossier, montant, durée) qui crée le crédit
   (`microfinance.loan`, état initial *brouillon*) et le relie au dossier.
5. **Soumission** du crédit : le système vérifie automatiquement les règles d'éligibilité du
   produit (ancienneté, second crédit, arriérés du co-emprunteur…) et calcule le score de
   crédit.
6. **Validation manager**, puis **validation finance**.
7. **Approbation**.
8. **Génération de l'échéancier** et **décaissement** : si des frais de dossier sont dus et
   exigés avant décaissement, ils doivent d'abord être encaissés.
9. **Remboursements** : à la sélection du crédit (formulaire ou assistant), le montant et le
   journal se préremplissent automatiquement — montant dû (échéances déjà en retard cumulées,
   ou à défaut la prochaine échéance), journal configuré sur le produit — librement modifiables
   pour un remboursement partiel ou anticipé. Chaque versement est ensuite automatiquement
   réparti entre pénalité, intérêt et capital de l'échéance la plus ancienne encore due. Un
   remboursement comptabilisé peut être annulé (contre-passation) si besoin, par exemple en cas
   d'erreur de saisie.
10. **Clôture automatique** dès que le solde restant dû atteint zéro.

En cours de route, un crédit actif peut être **rééchelonné** (nouvelle durée et/ou nouvelle
date de première échéance restante) : l'ancien échéancier reste consultable dans l'historique
du crédit, avec le motif et l'auteur de chaque rééchelonnement.

Un crédit qui devient irrécouvrable peut être **radié** (passé en perte) : il sort alors du
suivi de risque actif.

## Garanties

Un crédit peut être adossé à une ou plusieurs garanties (terrain, véhicule, maison, meuble,
salaire, caution personnelle, autre). Le produit de crédit peut exiger qu'au moins une
garantie soit validée avant soumission, et/ou qu'un ratio minimum du montant du crédit soit
couvert. Chaque type de garantie peut être décoté par une règle de valorisation (par exemple,
un véhicule n'est reconnu qu'à 70 % de sa valeur estimée) ; c'est cette valeur reconnue,
et non la valeur brute déclarée, qui sert au calcul de la couverture exigée. Les garanties
sont automatiquement libérées à la clôture du crédit.

## Score de crédit et portefeuille à risque

Chaque crédit reçoit un score sur 100 (plus il est élevé, plus le risque est faible), calculé
à partir de règles configurables (Microfinance > Configuration > Scoring crédit) : retards,
montants en retard, échéances partiellement payées, etc. Ce score détermine un niveau de
risque (faible/moyen/élevé/critique) et une recommandation (accord recommandé, revue
manuelle, rejet), visibles sur le crédit et dans le tableau de bord.

Le tableau de bord Microfinance affiche également le **portefeuille à risque (PAR)**, réparti
par ancienneté de retard (1-30, 31-60, 61-90, plus de 90 jours), pour suivre la qualité du
portefeuille dans le temps.

## Provisionnement des créances douteuses

Selon l'ancienneté du retard de chaque crédit, un taux de provision est appliqué au solde
restant dû (règles configurables par tranche d'ancienneté, Microfinance > Configuration >
Règles de provisionnement). Ces tranches sont livrées avec des valeurs indicatives par défaut
et doivent être ajustées avec votre institution si une norme réglementaire spécifique
s'applique. La comptabilisation de la provision (dotation ou reprise) se fait crédit par
crédit, pour rester facilement traçable, et peut être automatisée par une tâche planifiée
mensuelle.

## Visites de recouvrement

Les agents de recouvrement peuvent enregistrer leurs visites clients directement dans le
module, pour garder une trace du suivi effectué sur les dossiers en difficulté.

## Fiche client (contact partagé)

Le formulaire Contact standard est enrichi en contexte microfinance uniquement (menu
**Microfinance > Clients**) : toutes ces modifications sont invisibles pour les autres usages
de l'instance (EAT, immobilier) qui partagent le même contact.

- Si le client est marié, le nom et le téléphone du conjoint deviennent obligatoires (la
  profession du conjoint reste facultative).
- La profession est saisie par autocomplete sur une liste configurable (**Microfinance >
  Configuration > Professions**), plutôt qu'une liste figée dans le code — livrée avec une
  quinzaine de professions courantes pour le contexte malgache, modifiable ensuite librement.
- Le numéro de CIN s'affiche par blocs de 3 chiffres pour la lisibilité (ex.
  `123 456 789 012`) ; la valeur brute (12 chiffres) reste seule stockée et validée.
- Le champ "Issu du groupe" et la section "Suivi (commun)" (référence interne, catégories,
  date/motif de sortie) ont été retirés du formulaire, jugés obsolètes.

## Qui peut faire quoi

Le module définit des groupes d'accès dédiés : **Agent crédit** (saisie des dossiers),
**Manager crédit** et **Finance microfinance** (validations), **Agent recouvrement**
(visites de recouvrement) et **Auditeur microfinance** (consultation). Le module fonctionne
également en environnement multi-société.

## Module complémentaire : Épargne

Le module **Gestion de l'épargne microfinance** (`microfinance_savings_management`), à
installer séparément si votre institution propose des produits d'épargne, ajoute notamment
le prélèvement automatique sur épargne pour couvrir une échéance de crédit impayée, ainsi que
des conditions d'éligibilité au crédit basées sur l'épargne du client.

## À venir

La gestion dédiée des groupes solidaires (au-delà de la ventilation comptable déjà disponible
par type de client) fait partie des évolutions prévues.
