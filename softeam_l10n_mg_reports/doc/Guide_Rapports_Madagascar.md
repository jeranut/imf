---
title: "Guide des Rapports Comptables Madagascar"
subtitle: "Déclaration TVA · Bilan PCG 2005 · Compte de Résultat — `softeam_l10n_mg_reports`"
author: "Softeam Mada (SofteamG) · Hoby RASAMIMISA"
date: "Mai 2026"
geometry: margin=2cm
papersize: a4
fontsize: 11pt
mainfont: "DejaVu Sans"
monofont: "DejaVu Sans Mono"
linkcolor: "purple"
urlcolor: "purple"
---

# 1. Présentation

`softeam_l10n_mg_reports` fournit les **rapports financiers conformes au PCG 2005**
Madagascar, basés sur le moteur `account.report` d'Odoo.

| Rapport | Description |
|---------|-------------|
| **Déclaration TVA** | CA taxable / non-taxable / export, TVA collectée 20 %, TVA déductible biens & services + immobilisations, calcul du solde à décaisser |
| **Bilan PCG 2005** | Actif (non-courant + courant) / Capitaux propres + Passifs non-courants + Passifs courants |
| **Compte de Résultat par nature** | Production de l'exercice, charges opérationnelles, résultat opérationnel, résultat financier, résultat net |

# 2. Prérequis

- **`softeam_l10n_mg`** installé (le PCG 2005 et les taxes Madagascar)
- **Plan Comptable chargé** sur la société active (Settings → Companies → Madagascar - PCG 2005)
- **Odoo 17.0, 18.0, 19.0** (Community ou Enterprise)
  - Pour Odoo 16, utiliser l'ancien module `softeam_l10n_mg` (legacy)

> 💡 **Note** : la **visualisation interactive** des rapports (filtres, drill-down,
> export PDF/Excel, comparaisons de périodes) requiert **Odoo Enterprise**
> (module `account_reports`). Sur Community, les records sont chargés mais le
> viewer n'est pas disponible. Les données peuvent toutefois être lues
> programmatiquement via l'API.

# 3. Installation

## Via les Apps

1. Aller dans **Apps**
2. Rechercher `softeam_l10n_mg_reports` ou `rapports madagascar`
3. Cliquer sur **Madagascar - Rapports comptables (PCG 2005)** → Install

## Via la CLI Docker

```bash
docker exec sr_v18_odoo odoo --config=/etc/odoo/odoo.conf \
    -d ma_base --init=softeam_l10n_mg_reports --stop-after-init
```

# 4. Déclaration TVA Madagascar

## 4.1. Accès

**Comptabilité → Reporting → Déclaration TVA - Madagascar**
(Enterprise uniquement pour la visualisation graphique)

## 4.2. Structure

Le rapport est divisé en **4 sections** :

### Section A — Chiffre d'affaires (HT)

| Ligne | Description | Formule |
|-------|-------------|---------|
| **A1** | CA local taxable 20 % (base HT) | tag `+VENTE_BASE_20` |
| **A2** | CA exportation (0 %) | tag `+EXPORT_BASE` |
| **A3** | CA exonéré | tag `+EXO_VENTE_BASE` |
| **A4** | TOTAL Chiffre d'affaires | A1 + A2 + A3 |

### Section B — TVA collectée

| Ligne | Description | Formule |
|-------|-------------|---------|
| **B1** | TVA collectée 20 % sur CA local | tag `+VENTE_TVA_20` |
| **B** | TOTAL TVA collectée | B1 |

### Section C — TVA déductible

| Ligne | Description | Formule |
|-------|-------------|---------|
| **C1** | Achats biens & services 20 % (base HT) | tag `+ACHAT_BS_BASE_20` |
| **C2** | TVA déductible biens & services 20 % | tag `+ACHAT_BS_TVA_20` |
| **C3** | Achats immobilisations 20 % (base HT) | tag `+ACHAT_IMMO_BASE_20` |
| **C4** | TVA déductible immobilisations 20 % | tag `+ACHAT_IMMO_TVA_20` |
| **C5** | Achats exonérés | tag `+EXO_ACHAT_BASE` |
| **C** | TOTAL TVA déductible | C2 + C4 |

### Section D — Calcul de la TVA

| Ligne | Description | Formule |
|-------|-------------|---------|
| **D** | TVA à décaisser (B − C) | B_total − C_total |

> Si D est négatif, c'est un **crédit de TVA reportable** sur le mois suivant
> (compte `4456` Crédit TVA à reporter).

# 5. Bilan PCG 2005

## 5.1. Accès

**Comptabilité → Reporting → Bilan - Madagascar (PCG 2005)**

## 5.2. Structure

### ACTIF

| Section | Lignes | Préfixes comptes |
|---------|--------|------------------|
| **ACTIFS NON COURANTS** | Immobilisations incorporelles | 20 |
| | Immobilisations corporelles | 21 |
| | Immobilisations en concession | 22 |
| | Immobilisations en cours | 23 |
| | Participations et créances rattachées | 26 |
| | Autres immobilisations financières | 27 |
| | Amortissements et pertes de valeur | 28, 29 |
| | Impôts différés actif | 133 |
| **ACTIFS COURANTS** | Stocks et en-cours | 3 |
| | Clients et comptes rattachés | 41 |
| | État, créances | 44 (débiteur) |
| | Autres débiteurs | 40D, 42D, 46D |
| | Charges constatées d'avance | 486 |
| | Valeurs mobilières de placement | 50 |
| | Banques et caisse | 51, 53, 54, 58 |

### CAPITAUX PROPRES & PASSIFS

| Section | Lignes | Préfixes comptes |
|---------|--------|------------------|
| **CAPITAUX PROPRES** | Capital | 10 |
| | Report à nouveau | 11 |
| | Résultat de l'exercice | 12 |
| **PASSIFS NON COURANTS** | Subventions / produits différés | 13 |
| | Provisions pour charges | 15 |
| | Emprunts et dettes assimilées | 16, 17, 18 |
| **PASSIFS COURANTS** | Fournisseurs | 40 (créditeur) |
| | Personnel | 42 (créditeur) |
| | Organismes sociaux | 43 (créditeur) |
| | État, dettes | 44 (créditeur) |
| | Autres créditeurs | 45, 46 (créditeur) |
| | Provisions / produits constatés d'avance | 481, 487 |
| | Concours bancaires | 519 |

# 6. Compte de Résultat par Nature

## 6.1. Accès

**Comptabilité → Reporting → Compte de Résultat par Nature - Madagascar**

## 6.2. Structure

### I. Activité opérationnelle

| Ligne | Préfixe |
|-------|---------|
| Chiffre d'affaires | 70 |
| Variation des stocks de produits finis & en-cours | 71 |
| Production immobilisée | 72 |
| Subventions d'exploitation | 74 |
| Autres produits opérationnels | 75 |
| Reprises sur provisions | 78 |
| **I. PRODUCTION DE L'EXERCICE** | (somme) |
| Achats consommés | 60 |
| Services extérieurs et autres consommations | 61, 62 |
| Charges de personnel | 64 |
| Impôts, taxes et versements assimilés | 63 |
| Autres charges opérationnelles | 65 |
| Dotations aux amortissements et provisions | 68 |
| **II. RÉSULTAT OPÉRATIONNEL** | (Production − Charges) |

### III. Activité financière

| Ligne | Préfixe |
|-------|---------|
| Produits financiers | 76 |
| Charges financières | 66 |
| **III. RÉSULTAT FINANCIER** | 76 − 66 |

### IV-V. Résultat net

| Ligne | Calcul |
|-------|--------|
| **IV. RÉSULTAT AVANT IMPÔTS** | II + III |
| Éléments extraordinaires | 77 − 67 |
| Impôts sur les bénéfices | 69 |
| **V. RÉSULTAT NET DE L'EXERCICE** | IV − Extra − Impôts |

# 7. Données démo

Le module installe **3 partenaires démo** lors de l'activation du mode démo :

- **TANA SARL (démo Madagascar)** — Client local Antananarivo
- **USA Trading Inc. (démo export)** — Client étranger New York
- **FANIRY Sarl (démo Madagascar)** — Fournisseur Toamasina

## 7.1. Génération de factures démo

Pour générer des factures démo couvrant les principaux cas TVA, exécuter le
script `scripts/seed_demo_invoices.py` via odoo shell :

```bash
docker exec -i sr_v18_odoo odoo shell --config=/etc/odoo/odoo.conf \
    -d <database> --no-http <<'EOF'
exec(open('/mnt/extra-addons/softeam_l10n_mg_reports/scripts/seed_demo_invoices.py').read())
EOF
```

Le script crée 4 factures :

| Référence | Type | Partenaire | Montant HT | TVA |
|-----------|------|------------|------------|-----|
| `MG-DEMO-V001` | Vente locale | TANA SARL | 1 000 000 MGA | 20 % collectée |
| `MG-DEMO-V002` | Vente export | USA Trading | 800 000 MGA | 0 % export |
| `MG-DEMO-A001` | Achat B&S | FANIRY Sarl | 500 000 MGA | 20 % déductible |
| `MG-DEMO-A002` | Achat immo | FANIRY Sarl | 2 000 000 MGA | 20 % déd. immo |

Après exécution, ouvrir la **Déclaration TVA** et vérifier les montants.

## 7.2. Vérification attendue

| Ligne | Valeur attendue |
|-------|----------------|
| A1 | 1 000 000 |
| A2 | 800 000 |
| A4 (Total CA) | 1 800 000 |
| B1 (TVA collectée) | 200 000 |
| C1 (Base achats B&S) | 500 000 |
| C2 (TVA déd. B&S) | 100 000 |
| C3 (Base achats Immo) | 2 000 000 |
| C4 (TVA déd. Immo) | 400 000 |
| **D (TVA à décaisser)** | **−300 000** (crédit de TVA) |

# 8. Personnalisation

Les rapports utilisent les engines `account.report` standard d'Odoo :

- **engine `tax_tags`** pour la déclaration TVA — exploite les tags
  auto-créés par les repartition lines de `softeam_l10n_mg/data/template/account.tax.csv`
- **engine `account_codes`** pour le Bilan et le CR — agrège par préfixes
  PCG (1, 2, 3, 21, 41, 70, etc.)
- **engine `aggregation`** pour les totaux et sous-totaux

Pour ajouter une ligne au rapport, créer un `account.report.line` avec
`parent_id` pointant vers la section appropriée.

# 9. Limitations Community

Sur **Odoo Community**, le moteur `account.report` est défini mais le
**viewer interactif** n'est pas disponible (Enterprise uniquement, via
`account_reports`). Pour utiliser les rapports en Community :

1. Lire les données programmatiquement via l'ORM :
   ```python
   report = env.ref('softeam_l10n_mg_reports.tax_report')
   options = report.get_options(...)
   lines = report._get_lines(options)
   ```
2. Ou installer Odoo Enterprise pour la visualisation native.

# 10. Sources & références

- Décret n°2004-272 du 18 février 2004
- Annexe I PCG 2005 (modèles d'états financiers)
- Conseil Supérieur de la Comptabilité de Madagascar
- Convention IAS/IFRS

# 11. Support

- Email : <support@softeamg.com>
- Web : <https://softeamg.com>
- Repository : <https://github.com/hrasamimisa/softeam_odoo_apps>
- License : LGPL-3

---

*Module développé et maintenu par* **Softeam Mada (SofteamG)** *et*
**Hoby RASAMIMISA**.
