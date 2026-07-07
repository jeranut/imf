# Microfinance Savings Management

Module épargne pour institutions de microfinance (Odoo 17 Community), complémentaire à
`microfinance_loan_management` (dont il dépend). Couvre :

- **Produits d'épargne** (`microfinance.savings.product`) : obligatoire / volontaire / à terme,
  méthode de calcul du solde de référence (minimum / moyen / clôture), périodicité de
  capitalisation des intérêts, montants minimums, plafonds de retrait, frais de tenue de compte,
  pénalité de retrait anticipé (dépôt à terme).
- **Comptes épargne** (`microfinance.savings.account`) : cycle de vie brouillon → actif →
  dormant → clôturé, solde calculé depuis les transactions, détection automatique de dormance
  (cron), lien optionnel vers un crédit pour une épargne obligatoire.
- **Transactions** (`microfinance.savings.transaction`) : dépôt, retrait, intérêt crédité, frais
  prélevés, prélèvement automatique, virement. Chaque transaction comptabilisée génère une
  écriture (`account.move`), et un retrait ne peut pas descendre sous le solde minimum du produit
  sauf dérogation explicite (`bypass_min_balance`).
- **Intégration crédit** (ajoutée par extension sur les modèles de `microfinance_loan_management`,
  jamais l'inverse — voir la section dédiée dans le README de ce dernier) :
  - Prélèvement automatique sur épargne pour couvrir une échéance impayée (cron quotidien),
    réutilisant `microfinance.loan.payment._allocate_to_installments()` sans dupliquer
    l'allocation pénalité → intérêt → capital.
  - Éligibilité progressive au crédit basée sur l'épargne (cible pendant le remboursement, ou
    apport en amont bloquant l'approbation), paramétrable par produit de crédit.

## Prérequis de configuration

Pour chaque produit d'épargne : compte passif épargne clients et compte charge intérêts versés
(obligatoires), journal de dépôt et de retrait, compte produit frais si des frais sont prélevés.

Pour activer le prélèvement automatique sur un produit de crédit : `allow_savings_auto_debit`,
`auto_debit_grace_days`, `auto_debit_respect_minimum_balance`, puis renseigner
`savings_account_id` sur le crédit concerné.

## Points à tester en priorité

Voir la section « Points à tester en priorité » du prompt de spécification — couverts par les
tests automatisés du dossier `tests/` : cycle de vie du compte, blocage du solde minimum, les 3
méthodes de calcul d'intérêt, clôture (blocage crédit lié actif / retrait total automatique),
comptabilisation par type de transaction, prélèvement automatique (nominal / partiel / solde nul,
avec et sans dérogation au solde minimum, isolation multi-société, non-propagation d'un échec sur
un crédit aux autres traités par le même cron), éligibilité progressive et apport en amont
(indépendants l'un de l'autre).

## Limites V1

- Le type de transaction `transfer` (virement entre comptes épargne) est prévu dans le modèle
  mais ne dispose pas encore d'un assistant dédié créant les deux écritures pairées
  (source/destination) : à compléter si ce besoin se confirme.
- Les ratios/seuils par défaut de l'éligibilité progressive (`savings_target_ratio`,
  `savings_apport_ratio`, `savings_amount_threshold`) sont des hypothèses de configuration à
  valider avec l'institution avant mise en production, pas des constantes métier universelles.
