# Changelog

## 19.0.1.0.0 — 2026-05-08

### Initial release

* Plan comptable PCG 2005 Madagascar (Annexe I — 7 classes, **468 comptes** détaillés à 6 chiffres : préfixes 3/4/5-digits du PCG officiel paddés à droite par des zéros, ex. `1011` → `101100`, `4111` → `411100`)
* Caisse en MGA (au lieu d'Ariary) suivant la dénomination ISO/Banque Centrale
* Taxes TVA Madagascar (20 % collectée / déductible biens & services / déductible immobilisations / 0 % export / exonérée)
* Positions fiscales (National assujetti / non-assujetti / Reste du monde)
* Groupes de comptes 2 chiffres alignés sur la nomenclature officielle
* Tests unitaires (5 tests : chargement chart, comptes, receivable/payable, taxes, positions fiscales)
* Traductions FR (source) + MG (Malagasy)
* Compatible Odoo 19.0 — branches auto-générées pour 18.0 / 17.0 / 16.0

### Source

Décret n°2004-272 du 18 février 2004 — Conseil Supérieur de la Comptabilité de Madagascar.
