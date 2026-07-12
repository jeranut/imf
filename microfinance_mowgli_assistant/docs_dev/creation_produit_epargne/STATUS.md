# Statut dev — creation_produit_epargne
Dernière inspection : 2026-07-11

## Fait
- [x] Comptes PCEC et journaux pré-remplis par recherche automatique (code + société courante, jamais par référence XML statique), retournent un recordset vide si le compte n'existe pas encore pour la société — `microfinance_savings_management/models/microfinance_savings_product.py:6-26` (`_pcec_default`, `_journal_default`).
- [x] Sélection dynamique du compte comptable épargne/intérêt selon le type de client (individuel/groupe/entreprise), utilisée par le module épargne pour les écritures de transactions (hors périmètre du workflow `creation_produit_epargne`, utile pour le workflow `comptabilite`) — `microfinance_savings_management/models/microfinance_savings_product.py:215-223` (`_get_account`).
- [x] Contraintes de validation sur les montants/taux/pénalité/durée, déclenchées à la sauvegarde — `microfinance_savings_management/models/microfinance_savings_product.py:198-213` (`_check_values`).
- [x] Contrainte SQL d'unicité du code produit par société — `microfinance_savings_management/models/microfinance_savings_product.py:194-196` (`code_company_unique`).
- [x] Formulaire (`view_microfinance_savings_product_form`) sans aucun bouton `type="object"` ; le modèle ne définit aucune méthode `action_*` — cohérent avec l'absence de state machine sur ce modèle — `microfinance_savings_management/views/microfinance_savings_product_views.xml` (aucune balise `<button>`), `microfinance_savings_management/models/microfinance_savings_product.py` (aucune méthode `action_*`).

## À faire / incomplet
- [ ] Aucun tableau de bord dédié aux produits d'épargne : aucune référence à `savings_product`, `microfinance.savings.product` dans le dashboard de portefeuille crédit — `microfinance_loan_management/models/microfinance_dashboard.py` (grep sans résultat).
- [ ] Aucun rapport PDF dédié au produit d'épargne : seul `savings_receipt_report.xml` existe côté épargne, et il concerne les reçus de transaction, pas le produit — `microfinance_savings_management/report/savings_receipt_report.xml`.

## Incohérences relevées
- Champ `account_commission_id` — le texte d'aide indique "Requis uniquement si des frais sont prélevés pour ce produit", mais ni le modèle (pas de `required` conditionnel) ni la vue (pas de `required=` dynamique) n'appliquent réellement cette exigence : un produit avec frais de tenue de compte peut être enregistré sans ce compte configuré — `microfinance_savings_management/models/microfinance_savings_product.py:155-160`, `microfinance_savings_management/views/microfinance_savings_product_views.xml:81` — impact: faible.
