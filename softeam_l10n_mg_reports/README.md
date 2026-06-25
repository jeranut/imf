# Madagascar - Rapports comptables (`softeam_l10n_mg_reports`)

Rapports financiers conformes au **Plan Comptable Général 2005** Malagasy
(décret n°2004-272 du 18 février 2004), basés sur le moteur `account.report`
d'Odoo.

## Contenu

| Rapport | Description |
|---------|-------------|
| **Déclaration TVA** | CA taxable / non-taxable / export, TVA collectée 20%, TVA déductible biens & services + immobilisations, calcul du solde à décaisser |
| **Bilan PCG 2005** | Actif (non-courant + courant) / Capitaux propres & passifs (CP + PNC + PC) avec totaux et sous-totaux |
| **Compte de Résultat par nature** | Production de l'exercice, charges opérationnelles, résultat opérationnel, résultat financier, résultat net |

## Compatibilité

Compatible Odoo **17 / 18 / 19** (Community + Enterprise) — la définition des
records `account.report` est universelle. La **visualisation interactive**
(filtres, drill-down, export PDF/Excel) nécessite **Odoo Enterprise** via
le module `account_reports`.

Sur Community, les records existent et peuvent être lus programmatiquement.

Pour Odoo 16, utilisez l'ancien module `softeam_l10n_mg` (legacy XML report).

## Dépendances

* `softeam_l10n_mg` — plan comptable PCG 2005 (codes 6 chiffres, taxes TVA, positions fiscales)
* `account` — comptabilité Odoo

## Architecture

* **Engine `tax_tags`** pour le rapport TVA — exploite les tags auto-créés
  par les repartition lines de `softeam_l10n_mg/data/template/account.tax.csv`
* **Engine `account_codes`** pour le Bilan et le CR — agrège par préfixes
  PCG (1, 2, 3, …, 21, 41, 70, etc.)
* **Engine `aggregation`** pour les totaux et sous-totaux

## License

LGPL-3.0

## Support

* Email : support@softeamg.com
* Web : https://softeamg.com
