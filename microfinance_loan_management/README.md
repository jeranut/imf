# Microfinance Loan Management - Odoo 17 Community

Module créé from scratch pour gérer les crédits clients d'une institution de microfinance.

## Fonctionnalités V1

- Produits de crédit configurables
- Méthodes d'intérêt : flat rate et reducing balance
- Workflow : brouillon, soumis, validation manager, validation finance, approbation, actif, clôturé, défaut, radié
- Génération d'échéancier automatique, avec prise en compte du délai de grâce (`grace_period_days`) : première échéance décalée d'autant, et intérêt couru pendant un délai de grâce supérieur à une période capturé dans une échéance dédiée
- Remboursement avec allocation : pénalité → intérêt → capital
- Comptabilité : décaissement et remboursement via `account.move`
- Pénalités de retard appliquées une seule fois après délai de grâce
- Rééchelonnement de crédit actif (nouvelle durée et/ou nouvelle date de première échéance restante), historisé via `reschedule_count` et le chatter
- Règles de blocage à la demande de crédit : ancienneté client minimum, second crédit actif autorisé ou non, blocage si arriérés, blocage si le co-emprunteur a déjà un crédit actif
- Radiation / passage en perte d'un crédit actif ou en défaut, avec écriture comptable dédiée et exclusion du calcul de risque/PAR actif
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

Le compte de pertes sur créances irrécouvrables (`write_off_account_id`) est optionnel à la
configuration du produit, mais devient obligatoire au moment de radier un crédit de ce produit
(un journal des opérations diverses doit aussi exister pour la société).

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
- Génération échéancier flat et reducing, avec et sans délai de grâce
- Décaissement comptable
- Remboursement partiel
- Allocation automatique pénalité / intérêt / capital
- Application cron des pénalités
- Clôture automatique quand le solde est zéro
- Rééchelonnement d'un crédit actif (durée et/ou date de première échéance restante)
- Règles de blocage à la soumission (ancienneté, second crédit, arriérés, co-emprunteur)
- Radiation d'un crédit actif avec solde restant

## Limites V1

- Pas encore de garanties/cautions
- Pas encore de gestion des groupes solidaires
- Pas encore de frais de dossier automatisés
- Annulation comptable des remboursements postés non automatisée
- Dashboard simple, améliorable en OWL ou client action
