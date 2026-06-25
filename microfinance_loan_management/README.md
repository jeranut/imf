# Microfinance Loan Management - Odoo 17 Community

Module créé from scratch pour gérer les crédits clients d'une institution de microfinance.

## Fonctionnalités V1

- Produits de crédit configurables
- Méthodes d'intérêt : flat rate et reducing balance
- Workflow : brouillon, soumis, validation manager, validation finance, approbation, actif, clôturé, défaut
- Génération d'échéancier automatique
- Remboursement avec allocation : pénalité → intérêt → capital
- Comptabilité : décaissement et remboursement via `account.move`
- Pénalités de retard appliquées une seule fois après délai de grâce
- Visites de recouvrement
- Score de risque simple
- Groupes de sécurité : agent crédit, manager, finance, auditeur, recouvrement
- Multi-company

## Installation

Copier le dossier `microfinance_loan_management` dans votre `addons_path`, redémarrer Odoo, mettre à jour la liste des applications puis installer le module.

## Configuration minimale

Créer un produit de crédit et renseigner :

- Journal de décaissement
- Journal de remboursement
- Compte prêts clients
- Compte produits intérêts
- Compte produits pénalités

Les journaux doivent avoir un compte par défaut.

## Workflow conseillé

1. Créer le produit de crédit
2. Créer le dossier crédit
3. Soumettre
4. Valider manager
5. Valider finance
6. Approuver
7. Générer échéancier
8. Activer / Décaisser
9. Enregistrer les remboursements

## Points à tester en priorité

- Installation sur base Odoo 17 Community propre
- Création produit avec comptes comptables valides
- Génération échéancier flat et reducing
- Décaissement comptable
- Remboursement partiel
- Allocation automatique pénalité / intérêt / capital
- Application cron des pénalités
- Clôture automatique quand le solde est zéro

## Limites V1

- Pas encore de garanties/cautions
- Pas encore de gestion des groupes solidaires
- Pas encore de frais de dossier automatisés
- Annulation comptable des remboursements postés non automatisée
- Dashboard simple, améliorable en OWL ou client action
