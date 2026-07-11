# Statut dev — creation_produit_credit
Dernière inspection : 2026-07-11

## Fait
- [x] Formulaire produit de crédit complet avec 4 onglets (Calcul crédit, Éligibilité, Pénalités, Comptabilité), plus onglet Épargne ajouté par héritage de vue — `microfinance_loan_management/views/microfinance_loan_product_views.xml:44-119`, `microfinance_savings_management/views/microfinance_loan_product_views_inherit.xml:8-24`
- [x] Contraintes de validation actives (`_check_values`, `_check_repayment_frequency_mode`) couvrant montants, durées, taux, délais, ratio de garantie, frais et cohérence de périodicité — `microfinance_loan_management/models/microfinance_loan_product.py:296-321`
- [x] Comptes PCEC et journaux pré-remplis automatiquement par recherche `code` + `company_id` courant (`_pcec_default`, `_journal_default`) — `microfinance_loan_management/models/microfinance_loan_product.py:6-27`
- [x] Sélection dynamique du compte comptable Individuel/Groupe selon `partner.microfinance_client_type` via `_get_account(kind, partner)`, utilisée par les écritures du crédit — `microfinance_loan_management/models/microfinance_loan_product.py:323-331`
- [x] `guarantee_required`/`min_guarantee_ratio` sont effectivement appliqués côté crédit : blocage de `action_submit` si garantie validée manquante ou garanties insuffisantes par rapport au ratio minimum — `microfinance_loan_management/models/microfinance_loan.py:415-424`

## À faire / incomplet
- [ ] `savings_amount_threshold` (Onglet Épargne) n'est lu nulle part dans le code au-delà de sa propre déclaration : le champ est affiché et modifiable, mais ne pilote aucun contrôle serveur, conformément à son propre texte d'aide ("purement informatif ici : c'est bien savings_requirement_type qui pilote le contrôle, pas ce seuil") — `microfinance_savings_management/models/microfinance_loan_product_extension.py:32-37` (aucune autre occurrence dans le dépôt hors déclaration).

## Incohérences relevées
- `guarantee_required` (Garantie obligatoire) et `min_guarantee_ratio` (Ratio minimum de garantie (%)) existent sur le modèle, sont contraints par `_check_values`, et sont réellement appliqués lors de la soumission d'un crédit (`microfinance_loan.py:415-424`), mais ne sont affichés dans **aucune vue** du produit de crédit (ni `view_microfinance_loan_product_tree`, ni `view_microfinance_loan_product_form`, ni l'héritage épargne) — `microfinance_loan_management/models/microfinance_loan_product.py:69-74` ; confirmé par absence totale de ces deux noms de champ dans les fichiers XML du dépôt — impact: moyen (un Manager crédit ne peut pas activer ces contrôles via l'interface standard ; ils ne sont accessibles qu'en modifiant la donnée hors UI, par exemple par import ou accès développeur).
