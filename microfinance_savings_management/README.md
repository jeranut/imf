# Gestion de l'épargne microfinance

Ce module ajoute la gestion des comptes d'épargne à une institution de microfinance déjà
équipée du module **Gestion des crédits microfinance**, dont il dépend.

## Installation

Depuis Apps, rechercher « Gestion de l'épargne microfinance » et cliquer sur Installer. Le
module **Gestion des crédits microfinance** doit déjà être installé.

## Mettre en place un produit d'épargne

Menu **Microfinance > Configuration > Produits d'épargne**.

Trois types de produits sont disponibles : obligatoire (liée à un crédit), volontaire, ou à
terme (dépôt bloqué sur une durée fixe). Le code du produit (ex. `EP00001`) est généré
automatiquement à la création — préfixe configurable par société (Paramètres > Sociétés,
champ « Préfixe code produit épargne », par défaut `EP`), verrouillé dès le premier produit
créé pour cette société.

**Onglet Intérêts** : taux d'intérêt annuel, méthode de calcul du solde de référence pour la
capitalisation (solde minimum, moyen, ou de clôture de période) et fréquence de
capitalisation (mensuelle, trimestrielle, annuelle).

**Onglet Limites** : montant minimum d'ouverture, solde minimum à maintenir (un retrait ne
peut pas faire descendre le compte en dessous, sauf dérogation explicite), plafond de retrait
par transaction (dérogation possible, distincte de celle du solde minimum), frais de tenue de
compte (non implémenté pour l'instant — champ grisé). Pénalité de retrait anticipé : appliquée
automatiquement avant la date d'échéance d'un produit à terme, et/ou avant un délai minimum de
rétention en jours configurable sur n'importe quel produit (y compris l'épargne libre).

**Onglet Comptabilité** : configuration, par le service comptable/finance, des comptes du
plan comptable général qui recevront les écritures générées par les opérations d'épargne
(dépôts, retraits, intérêts, frais). Comme pour les produits de crédit, la plupart des postes
sont ventilés séparément pour les clients individuels, les groupes et les entreprises ; seul
le compte d'épargne (compte passif recevant les dépôts des clients) est obligatoire pour
pouvoir activer le produit, les autres postes restant optionnels tant que le mécanisme
correspondant n'est pas utilisé par l'institution. Renseignez également les journaux de
dépôt et de retrait.

## Gérer un compte d'épargne

Un compte d'épargne suit un cycle de vie simple : brouillon → actif → clôturé, avec détection
automatique des comptes devenus dormants (sans mouvement depuis longtemps). Le solde est
recalculé automatiquement à partir des transactions (dépôt, retrait, intérêt crédité, frais
prélevés, prélèvement automatique, virement) ; chaque transaction validée génère
automatiquement son écriture comptable.

## Intégration avec le crédit

- **Prélèvement automatique sur épargne** : si le produit de crédit l'autorise, une échéance
  de crédit impayée peut être prélevée automatiquement sur le compte d'épargne du client
  (tâche planifiée quotidienne), en respectant le solde minimum du produit d'épargne sauf
  dérogation explicite pour ce produit de crédit.
- **Éligibilité progressive au crédit basée sur l'épargne** : un produit de crédit peut exiger
  une épargne cible à atteindre pendant le remboursement, condition pour qu'un prêt suivant
  puisse être soumis (indépendant de la garantie ci-dessous).
- **Épargne garantie de crédit** (mécanisme LPF) : un produit de crédit peut exiger qu'un
  pourcentage du montant demandé soit disponible sur le solde du client dans un produit
  d'épargne dédié (ex. « Épargne garantie de crédit »), tous deux configurables sur le produit
  de crédit. Vérifié dès la demande de crédit (soumission), pas seulement au décaissement — si
  le solde est insuffisant, la demande est rejetée avec le montant manquant. Non applicable aux
  clients de type Société.

## À venir

Le virement entre deux comptes d'épargne est prévu dans le modèle de données mais ne
dispose pas encore d'un assistant dédié dans l'interface ; à mettre en place si ce besoin se
confirme auprès de l'institution.

Les seuils par défaut de l'éligibilité progressive sont des valeurs de départ à valider et
ajuster avec l'institution avant mise en production.
