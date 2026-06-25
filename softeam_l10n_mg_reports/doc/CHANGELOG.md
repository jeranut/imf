# Changelog

## 19.0.1.0.0 — 2026-05-08

### Initial release

* Déclaration TVA Madagascar (sections A/B/C/D, ~12 lignes)
  * A. CA taxable 20% / Export 0% / Exonéré / TOTAL
  * B. TVA collectée 20%
  * C. TVA déductible Biens & Services + Immobilisations
  * D. Calcul TVA à décaisser
* Bilan PCG 2005 (Actif + Capitaux propres & Passifs)
  * ACTIFS NON COURANTS : 20, 21, 22, 23, 26, 27, 28, 29, 133
  * ACTIFS COURANTS : 3, 41, 44D, 40D+42D+46D, 486, 50, 51+53+54+58
  * CAPITAUX PROPRES : 10, 11, 12
  * PASSIFS NON COURANTS : 13, 15, 16+17+18
  * PASSIFS COURANTS : 40C, 42C, 43C, 44C, 45C+46C, 481+487, 519
* Compte de Résultat par nature PCG 2005
  * PRODUCTION DE L'EXERCICE : 70, 71, 72, 74, 75, 78
  * Charges : 60, 61+62, 63, 64, 65, 68
  * RÉSULTAT OPÉRATIONNEL
  * RÉSULTAT FINANCIER : 76 - 66
  * Éléments extraordinaires : 77 - 67
  * Impôts : 69
  * RÉSULTAT NET
* Tests post-install : 5 tests (module installé, 3 rapports chargés, country filter)
* Tags TVA auto-créés via repartition lines (VENTE_BASE_20, VENTE_TVA_20, etc.)

### Source

Décret n°2004-272 du 18 février 2004 — Conseil Supérieur de la Comptabilité de Madagascar.
