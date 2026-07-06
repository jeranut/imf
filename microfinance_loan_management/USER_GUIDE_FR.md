# Guide Utilisateur - Microfinance Loan Management
## Odoo 17 Community Edition

---

## Table des matières

1. [Introduction](#introduction)
2. [Installation et Configuration](#installation-et-configuration)
3. [Concepts clés](#concepts-clés)
4. [Workflow complet d'un crédit](#workflow-complet-dun-crédit)
5. [Gestion des produits de crédit](#gestion-des-produits-de-crédit)
6. [Gestion des dossiers de crédit](#gestion-des-dossiers-de-crédit)
7. [Génération automatique de l'échéancier](#génération-automatique-de-léchéancier)
8. [Enregistrement des remboursements](#enregistrement-des-remboursements)
9. [Gestion des pénalités](#gestion-des-pénalités)
10. [Visites de recouvrement](#visites-de-recouvrement)
11. [Tableau de bord et rapports](#tableau-de-bord-et-rapports)
12. [Foire aux questions](#foire-aux-questions)

---

## Introduction

Le module **Microfinance Loan Management** est conçu pour gérer complètement le cycle de vie des crédits clients dans une institution de microfinance. Il permet de :

- **Créer et gérer** des produits de crédit flexibles
- **Suivre** les demandes de crédit à travers un workflow d'approbation
- **Générer** automatiquement les échéanciers de remboursement
- **Enregistrer** les remboursements avec allocation automatique
- **Appliquer** des pénalités de retard
- **Suivre** les visites de recouvrement
- **Calculer** un score de risque par emprunteur
- **Gérer** la comptabilité via des écritures automatiques

### Public cible

- Agents de crédit
- Managers d'agence
- Contrôleurs financiers
- Responsables du recouvrement
- Directeurs généraux

---

## Installation et Configuration

### Étape 1 : Installation du module

1. Copier le dossier `microfinance_loan_management` dans le répertoire `addons`
2. **Redémarrer Odoo** pour que le module soit détecté
3. Aller à **Applications** → **Mettre à jour la liste des applications**
4. Rechercher "Microfinance" et cliquer sur **Installer**

### Étape 2 : Configuration des paramètres de base

Avant de créer un crédit, vous devez configurer les journaux comptables et les comptes.

#### 2.1 Créer/vérifier les journaux

Aller à **Comptabilité** → **Configuration** → **Journaux** et vérifier que vous avez :

- **Journal de banque** (ou de caisse) pour les décaissements
- **Journal de banque** (ou de caisse) pour les remboursements

Chaque journal doit avoir un **compte par défaut** renseigné.

#### 2.2 Vérifier les comptes comptables

Assurez-vous que les comptes suivants existent dans votre plan comptable :

- **Compte prêts clients** (ex: 1400 - Créances clients)
- **Compte produits intérêts** (ex: 7050 - Intérêts reçus)
- **Compte produits pénalités** (ex: 7051 - Pénalités reçues)

### Étape 3 : Créer le premier produit de crédit

Voir la section [Gestion des produits de crédit](#gestion-des-produits-de-crédit).

---

## Concepts clés

### 1. Produit de crédit

Un **produit de crédit** définit les règles générales pour une catégorie de prêts :
- Montants min/max
- Durées min/max
- Taux d'intérêt
- Méthode de calcul des intérêts
- Fréquence de remboursement
- Pénalités de retard

### 2. Dossier de crédit

Un **dossier de crédit** est une demande individuelle d'un emprunteur pour un montant et une durée spécifiques.

### 3. Échéancier

L'**échéancier** est la liste des dates d'échéance avec le montant de capital, d'intérêt et de pénalité dus à chaque date.

### 4. Remboursement

Un **remboursement** est une transaction individuelle de paiement qui est automatiquement répartie entre pénalités, intérêts et capital.

### 5. État de risque

Le **score de risque** est une note de 0 à 100 calculée automatiquement basée sur :
- Nombre d'échéances en retard
- Nombre de jours de retard
- Montant en retard (%)
- Nombre de remboursements partiels

### 6. État du dossier

Les états possibles d'un dossier de crédit sont :

| État | Signification |
|------|---------------|
| **Brouillon** | Créé, en attente de soumission |
| **Soumis** | Soumis pour validation manager |
| **Validé manager** | Approuvé par le manager |
| **Validé finance** | Approuvé par le contrôleur financier |
| **Approuvé** | Prêt pour activation et décaissement |
| **Actif** | Crédit décaissé, en phase de remboursement |
| **Clôturé** | Entièrement remboursé |
| **Défaut** | Crédit en défaut de paiement |
| **Annulé** | Crédit annulé |

---

## Workflow complet d'un crédit

Voici le flux recommandé pour gérer un crédit du début à la fin :

```
1. CRÉER le produit de crédit
   ↓
2. CRÉER le dossier de crédit (Brouillon)
   ↓
3. SOUMETTRE le dossier
   ↓
4. VALIDER par le manager (Manager Validated)
   ↓
5. VALIDER par la finance (Finance Validated)
   ↓
6. APPROUVER le dossier (Approved)
   ↓
7. GÉNÉRER l'échéancier
   ↓
8. DÉCAISSER le crédit (Actif)
   ↓
9. ENREGISTRER les remboursements
   ↓
10. GÉRER les pénalités (automatique via cron)
    ↓
11. FERMER le dossier (Clôturé)
```

---

## Gestion des produits de crédit

### Créer un produit de crédit

1. Aller à **Microfinance** → **Configuration** → **Produits de crédit**
2. Cliquer sur **Créer**
3. Remplir les champs suivants :

#### Informations générales

| Champ | Description | Exemple |
|-------|-------------|---------|
| **Nom** | Nom du produit | PME Court Terme |
| **Code** | Code unique | PME-CT-001 |

#### Limites de montant

| Champ | Description | Exemple |
|-------|-------------|---------|
| **Montant minimum** | Montant minimum empruntable | 100 000 |
| **Montant maximum** | Montant maximum empruntable | 5 000 000 |

#### Limites de durée

| Champ | Description | Exemple |
|-------|-------------|---------|
| **Durée min.** | Nombre minimum d'échéances | 3 |
| **Durée max.** | Nombre maximum d'échéances | 12 |

#### Intérêts

| Champ | Description | Exemple |
|-------|-------------|---------|
| **Taux intérêt annuel (%)** | Taux d'intérêt par an | 18.0 |
| **Méthode d'intérêt** | Flat rate ou Reducing balance | Flat rate |

- **Flat rate** : Les intérêts sont calculés sur le montant initial pour toute la durée
- **Reducing balance** : Les intérêts sont calculés chaque mois sur le capital restant

#### Remboursement

| Champ | Description | Exemple |
|-------|-------------|---------|
| **Fréquence de remboursement** | Journalier, Hebdomadaire, Mensuel | Mensuel |

#### Pénalités

| Champ | Description | Exemple |
|-------|-------------|---------|
| **Délai de grâce (jours)** | Jours avant d'appliquer une pénalité | 3 |
| **Type de pénalité** | Montant fixe ou Pourcentage | Montant fixe |
| **Pénalité fixe** | Si montant fixe | 50 000 |
| **Taux pénalité (%)** | Si pourcentage | 5.0 |

#### Comptes comptables

| Champ | Description | Obligatoire |
|-------|-------------|------------|
| **Journal décaissement** | Journal pour débourser le crédit | ✓ |
| **Journal remboursement** | Journal pour enregistrer les remboursements | ✓ |
| **Compte prêts clients** | Compte bilan pour les crédits | ✓ |
| **Compte intérêts** | Compte de produits pour intérêts | ✓ |
| **Compte pénalités** | Compte de produits pour pénalités | ✓ |

4. Cliquer sur **Enregistrer**

---

## Gestion des dossiers de crédit

### Créer un dossier de crédit

1. Aller à **Microfinance** → **Demandes de crédit** → **Dossiers de crédit**
2. Cliquer sur **Créer**
3. Remplir les champs suivants :

#### Informations principales

| Champ | Description | Obligatoire |
|-------|-------------|------------|
| **Emprunteur** | Sélectionner le client | ✓ |
| **Produit** | Sélectionner le produit de crédit | ✓ |
| **Montant crédit** | Montant demandé (doit être entre min/max du produit) | ✓ |
| **Nombre échéances** | Nombre de remboursements | ✓ |
| **Date de candidature** | Date de soumission | ✓ |
| **Taux intérêt annuel (%)** | Peut être modifié (hérité du produit) | |
| **Remarque** | Notes libres | |

4. Cliquer sur **Enregistrer**

### États du dossier et actions

Le dossier passe par plusieurs états. À chaque étape, des boutons d'action apparaissent :

#### Étape 1 : Soumettre (Brouillon → Soumis)
- Bouton : **Soumettre**
- Rôle : Agent de crédit

#### Étape 2 : Valider manager (Soumis → Validé manager)
- Bouton : **Valider par le manager**
- Rôle : Manager d'agence

#### Étape 3 : Valider finance (Validé manager → Validé finance)
- Bouton : **Valider par la finance**
- Rôle : Contrôleur financier

#### Étape 4 : Approuver (Validé finance → Approuvé)
- Bouton : **Approuver**
- Rôle : Directeur ou Manager senior

#### Étape 5 : Générer l'échéancier (Approuvé → État inchangé)
- Bouton : **Générer l'échéancier**
- Rôle : Agent de crédit ou manager

**Important** : Ceci crée la liste des paiements futurs. Peut être régénéré jusqu'au décaissement.

#### Étape 6 : Décaisser (Approuvé → Actif)
- Bouton : **Décaisser**
- Rôle : Agent de crédit
- Effet : Crée une écriture comptable de décaissement

---

## Génération automatique de l'échéancier

### Comprendre l'échéancier

L'échéancier est la liste de toutes les dates d'échéance avec les montants dus. Il se divise en trois composantes :

- **Capital** : Montant principal (loan_amount / nombre d'échéances)
- **Intérêt** : Dépend de la méthode (flat ou reducing)
- **Pénalité** : Appliquée automatiquement après le délai de grâce

### Exemple d'échéancier

Crédit de 1 000 000 sur 12 mois à 18% flat rate :

| Échéance | Due Date | Capital | Intérêt | Pénalité | Total |
|----------|----------|---------|---------|----------|-------|
| 1 | 2024-02-15 | 83 333 | 15 000 | 0 | 98 333 |
| 2 | 2024-03-15 | 83 333 | 15 000 | 0 | 98 333 |
| ... | ... | ... | ... | ... | ... |
| 12 | 2025-01-15 | 83 333 | 15 000 | 0 | 98 333 |

**Total Capital** : 1 000 000  
**Total Intérêts** : 180 000  
**Total** : 1 180 000

### Méthodes de calcul d'intérêts

#### Flat Rate
- Intérêt mensuel = (Montant initial × Taux annuel) / 12
- **Avantage** : Facile à comprendre et à expliquer
- **Désavantage** : Moins favorable pour le client qui paie aussi sur le capital remboursé

Exemple : 1M à 18% pendant 12 mois = 15 000 / mois pendant 12 mois

#### Reducing Balance
- Intérêt mensuel = (Capital restant × Taux annuel) / 12
- **Avantage** : Plus juste pour le client
- **Désavantage** : Plus complexe à comprendre

Exemple : 1M à 18% pendant 12 mois :
- Mois 1 : (1 000 000 × 18%) / 12 = 15 000
- Mois 2 : (916 667 × 18%) / 12 = 13 750
- Mois 3 : (833 333 × 18%) / 12 = 12 500
- ...

---

## Enregistrement des remboursements

### Enregistrer un remboursement

1. Ouvrir le dossier de crédit en état **Actif**
2. Cliquer sur le bouton **Enregistrer remboursement**
3. Une fenêtre de dialogue s'ouvre

#### Remplir les informations

| Champ | Description | Obligatoire |
|-------|-------------|------------|
| **Crédit** | Pré-rempli avec le dossier | ✓ |
| **Date de paiement** | Date du remboursement | ✓ |
| **Montant** | Montant payé | ✓ |
| **Journal** | Journal de caisse/banque utilisé | ✓ |
| **Remarque** | Notes | |

### Allocation automatique

Le montant payé est **automatiquement réparti** dans cet ordre de priorité :

1. **Pénalités en retard** (les plus anciennes d'abord)
2. **Intérêts dus**
3. **Capital dû** (principal)

**Exemple** :
- Échéance 1 (en retard) : Capital 100k, Intérêt 10k, Pénalité 5k = 115k total
- Remboursement de 60k
- Allocation : Pénalité 5k → Intérêt 10k → Capital 45k

### Remboursements partiels

Vous pouvez enregistrer un remboursement partiel. L'échéance reste en état **Partiel** jusqu'au remboursement complet.

### Remboursements multiples

Vous pouvez enregistrer plusieurs remboursements pour une même échéance si le client paie en plusieurs fois.

---

## Gestion des pénalités

### Calcul des pénalités

Les pénalités sont appliquées **automatiquement** par un job cron tous les jours.

**Conditions d'application** :
1. L'échéance est en retard (Due Date < Aujourd'hui)
2. Le délai de grâce est écoulé (Due Date + Grace Period < Aujourd'hui)
3. La pénalité n'a pas déjà été appliquée

### Types de pénalités

#### Pénalité fixe
- Montant fixe appliqué une seule fois
- Exemple : 50 000 par échéance en retard

#### Pénalité en pourcentage
- Calculée comme % du montant résiduel (capital + intérêt - pénalité)
- Exemple : 5% de 110k = 5 500

### Exemple

Crédit de 1M à 18% pendant 12 mois, pénalité fixe de 50k, délai de grâce 3 jours :

- **Échéance 1** : Due 2024-02-15 (capital 83k, intérêt 15k)
- **Date de pénalité** : 2024-02-18 (due date + 3 jours)
- Si pas de remboursement avant 2024-02-18 : Pénalité de 50k ajoutée
- **Nouveau total dû** : 148k

### Configuration des pénalités

Les pénalités sont configurées au niveau du **Produit de crédit**. Voir [Gestion des produits de crédit](#gestion-des-produits-de-crédit).

---

## Visites de recouvrement

### Créer une visite de recouvrement

1. Ouvrir le dossier de crédit
2. Aller à l'onglet **Visites**
3. Cliquer sur **Ajouter une ligne**

#### Informations

| Champ | Description |
|-------|-------------|
| **Agent terrain** | Responsable de la visite |
| **Date de visite** | Date/heure de la visite |
| **Statut** | Planifiée, Réalisée, Manquée, Annulée |
| **Remarques** | Observations pendant la visite |
| **Promesse de paiement** | Date promise pour le remboursement |
| **Montant promis** | Montant promis par le client |

### Suivi des visites

Les visites permettent de suivre le contactage du client et les engagements de remboursement.

---

## Tableau de bord et rapports

### Tableau de bord principal

Aller à **Microfinance** → **Tableau de bord**

Affiche :
- Nombre de crédits actifs
- Montant total décaissé
- Montant en retard
- Taux de défaut
- Montant en souffrance

### Vue analytique

Aller à **Microfinance** → **Analyse des immobilisations**

Permet une analyse détaillée par :
- Produit
- Emprunteur
- État
- Période

### Score de risque

Le score de risque de chaque crédit est visible en **Lecture seule** dans le dossier.

**Calcul** :
- +15 points par échéance en retard
- +1.2 point par jour de retard
- +40 points × (montant retard / montant crédit)
- +5 points par remboursement partiel

**Interprétation** :
- **0-20** : Risque très faible
- **20-40** : Risque faible
- **40-60** : Risque modéré
- **60-80** : Risque élevé
- **80-100** : Risque très élevé

---

## Foire aux questions

### Q1 : Comment modifier le produit d'un crédit après sa création ?

**R** : Vous pouvez modifier les champs suivants dans un crédit en brouillon/soumis :
- Montant crédit
- Nombre d'échéances
- Taux intérêt annuel

Une fois approuvé, vous ne pouvez plus modifier le produit de base. Vous devez annuler et créer un nouveau crédit.

### Q2 : Puis-je régénérer l'échéancier après l'avoir créé ?

**R** : Oui, **jusqu'au décaissement**. Une fois le crédit décaissé (état Actif), l'échéancier est figé.

Cliquer sur **Générer l'échéancier** remplace l'ancien échéancier par un nouveau.

### Q3 : Comment fermer automatiquement un crédit quand le solde atteint zéro ?

**R** : Lors de l'enregistrement du dernier remboursement, si le solde restant devient ≤ 0.01, le crédit passe automatiquement à l'état **Clôturé**.

### Q4 : Que se passe-t-il si un client paye trop ?

**R** : Un surpaiement est rejeté lors de l'enregistrement du remboursement. Le système affiche un message d'erreur : "Surpaiement interdit. Solde restant : XXX".

### Q5 : Comment gérer un crédit en défaut de paiement ?

**R** : 
1. Lorsque la situation est désespérée, cliquer sur **Marquer en défaut**
2. L'état devient **Défaut**
3. Vous pouvez toujours enregistrer des remboursements
4. Passer à **Clôturé** une fois entièrement remboursé

### Q6 : Comment annuler un crédit ?

**R** : 
1. En état **Brouillon ou Approuvé** : Cliquer sur **Annuler**
2. Une fois **Actif** : Contacter l'administrateur pour annulation manuelle

### Q7 : Peut-on modifier les comptes comptables après création du produit ?

**R** : Oui, vous pouvez modifier les comptes comptables à tout moment. Les modifications s'appliquent aux futurs remboursements. Les écritures existantes ne sont pas modifiées rétroactivement.

### Q8 : Quelle est la fréquence de calcul des pénalités ?

**R** : Les pénalités sont calculées quotidiennement via un **Cron job** automatique. Elles apparaissent donc la nuit (selon la configuration du serveur).

Vous pouvez aussi relancer manuellement via : **Microfinance** → **Actions** → **Calculer pénalités**.

### Q9 : Comment exporter une liste de crédits ?

**R** :
1. Aller à **Microfinance** → **Demandes de crédit** → **Dossiers de crédit**
2. Appliquer les filtres souhaités
3. Cliquer sur le menu ⋮ (trois points)
4. Choisir **Exporter**

### Q10 : Quelle est la différence entre "Validé finance" et "Approuvé" ?

**R** :
- **Validé finance** : La demande a été vérifiée par le contrôle financier (montants, ratios, etc.)
- **Approuvé** : L'autorité compétente (DG, Manager senior) a approuvé la demande
- Un crédit doit être en état **Approuvé** pour pouvoir être décaissé

---

## Dépannage

### Problème : "Le montant doit respecter les limites du produit"

**Solution** :
- Vérifier que le montant du crédit est entre le min et max du produit
- Ajuster le montant ou modifier les limites du produit

### Problème : "Impossible de clôturer : solde restant à payer"

**Solution** :
- Enregistrer un dernier remboursement pour le solde restant
- Vérifier qu'il n'y a pas de petites différences (arrondi d'intérêt)
- Utiliser un remboursement d'ajustement si nécessaire

### Problème : L'échéancier n'apparaît pas

**Solution** :
- Vérifier que le crédit est en état **Approuvé** au minimum
- Cliquer sur **Générer l'échéancier**
- Actualiser la page (F5)

### Problème : Les pénalités ne s'appliquent pas

**Solution** :
- Vérifier que le délai de grâce est écoulé (due date + grace period days)
- Attendre que le cron job se lance (quotidiennement)
- Ou relancer manuellement via les actions

### Problème : Les écritures comptables ne sont pas créées

**Solution** :
- Vérifier que les comptes comptables sont configurés dans le produit
- Vérifier que les journaux ont un compte par défaut
- Vérifier les logs Odoo pour les erreurs détaillées

---

## Contact et support

Pour plus d'informations ou pour signaler des bugs :

- **Email** : support@sysadaptpro.com
- **Website** : https://sysadaptpro.com
- **Documentation** : Voir README.md dans le dossier du module

---

**Version** : 1.0  
**Date** : Juin 2026  
**Licence** : LGPL-3
