---
title: "Guide d'installation et d'utilisation"
subtitle: "Plan Comptable Général 2005 Madagascar — `softeam_l10n_mg`"
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

`softeam_l10n_mg` est la **localisation comptable Madagascar pour Odoo**, conforme au
**Plan Comptable Général 2005** (décret n°2004-272 du 18 février 2004). Il fournit :

- **468 comptes** des 7 classes du PCG 2005 (Annexe I officielle)
- **Codes à 6 chiffres** (préfixes officiels paddés à droite par des zéros : `1011` → `101100`)
- **6 taxes TVA** Madagascar (collectée 20 %, déductible B&S, déductible immobilisations,
  export 0 %, exonérée vente, exonérée achat)
- **3 positions fiscales** (National assujetti / non-assujetti / Reste du monde)
- **Devise MGA** (Ariary Malagasy, ISO 4217)

Compatible **Odoo 16, 17, 18, 19** — éditions Community et Enterprise.

# 2. Installation

## 2.1. Prérequis

- Odoo installé (Community ou Enterprise) sur Docker, serveur ou Odoo.sh
- Module **Comptabilité** (`account`) installé

## 2.2. Installation du module

### Via les Apps

1. Aller dans **Apps**
2. Enlever le filtre par défaut « Apps »
3. Rechercher : `compta malagasy` ou `madagascar` ou `PCG 2005`
4. Cliquer sur **Madagascar - Comptabilité Malagasy (PCG 2005)** → Install

### Via la CLI Docker (test)

```bash
docker exec sr_v18_odoo odoo --config=/etc/odoo/odoo.conf \
    -d ma_base --init=base,softeam_l10n_mg --stop-after-init
```

# 3. Chargement du Plan Comptable

Le module charge automatiquement le PCG 2005 quand :

1. Vous créez une nouvelle base de données avec **Country = Madagascar**, OU
2. Vous sélectionnez manuellement le plan dans **Comptabilité → Configuration → Sociétés**

## 3.1. Vérification

Une fois chargé :

| Vérification | Chemin Odoo | Attendu |
|--------------|-------------|---------|
| Comptes | Comptabilité → Configuration → Plan Comptable | **468 comptes** à 6 chiffres |
| Taxes | Comptabilité → Configuration → Taxes | **6 taxes** (4 ventes, 2 achats) |
| Positions fiscales | Comptabilité → Configuration → Positions fiscales | **3 positions** |
| Devise société | Settings → Companies → Madagascar | **MGA** (Ariary) |
| Compte client défaut | Settings → Companies → Madagascar | **4111** Clients Malagasy |
| Compte fournisseur défaut | Settings → Companies → Madagascar | **4011** Fournisseurs Malagasy |

> ⚠️ **Important** : le plan comptable doit être chargé sur une société **vide
> de toute écriture**. Une fois chargé, il ne peut plus être remplacé.

# 4. Structure du PCG 2005

Les **7 classes officielles** :

| Classe | Intitulé | Préfixe codes | Exemple |
|--------|----------|---------------|---------|
| 1 | Capitaux propres et passifs non-courants | 1xxxxx | `101300` Capital appelé versé |
| 2 | Comptes d'immobilisations | 2xxxxx | `213000` Constructions |
| 3 | Comptes de stocks et en-cours | 3xxxxx | `370000` Stocks de marchandises |
| 4 | Comptes de tiers | 4xxxxx | `411100` Clients Malagasy |
| 5 | Comptes financiers | 5xxxxx | `531100` Caisse en MGA |
| 6 | Comptes de charges | 6xxxxx | `607000` Achats de marchandises |
| 7 | Comptes de produits | 7xxxxx | `707000` Ventes de marchandises |

## 4.1. Sous-divisions notables (4 et 5 chiffres)

| Code | Intitulé | Usage |
|------|----------|-------|
| `4011` Fournisseurs Malagasy | `4012` Fournisseurs étranger | Distinction local/étranger |
| `4111` Clients Malagasy | `4112` Clients étrangers | Distinction local/étranger |
| `5311` Caisse en MGA | `5314` Caisse en devise | Multi-devise |
| `5121` Banque compte courant local | `5124` Banque compte en devise | Multi-devise |
| `44561` à `44568` | TVA déductible (catégories d'achats) | Granularité TVA |
| `44571` `44572` | TVA collectée (assujettis / non assujettis) | Granularité TVA |

# 5. Taxes TVA Madagascar

| ID | Nom | Type | Taux | Compte | Position fiscale |
|----|-----|------|------|--------|------------------|
| `tva_collectee_20` | TVA collectée 20 % | Vente | 20 % | `4451` (`445100`) | par défaut |
| `tva_deductible_bs_20` | TVA déductible biens & services 20 % | Achat | 20 % | `4452` | par défaut |
| `tva_deductible_immo_20` | TVA déductible immobilisations 20 % | Achat | 20 % | `4453` | sur immo |
| `tva_collectee_export_0` | TVA exportation 0 % | Vente | 0 % | `4451` | Reste du monde |
| `tva_exoneree_0` | TVA exonérée | Vente | 0 % | — | National non-assujetti |
| `tva_achat_exoneree_0` | TVA achat exonérée | Achat | 0 % | — | National non-assujetti |

## 5.1. Tags TVA pour la déclaration

Les repartition lines des taxes sont automatiquement taguées :

- `+VENTE_BASE_20`, `+VENTE_TVA_20` (collectée)
- `+ACHAT_BS_BASE_20`, `+ACHAT_BS_TVA_20` (déductible biens & services)
- `+ACHAT_IMMO_BASE_20`, `+ACHAT_IMMO_TVA_20` (déductible immobilisations)
- `+EXPORT_BASE` (export)
- `+EXO_VENTE_BASE`, `+EXO_ACHAT_BASE` (exonérations)

Ces tags alimentent la **Déclaration TVA Madagascar** du module
`softeam_l10n_mg_reports`.

# 6. Positions fiscales

| Position | Application | Effet sur les taxes |
|----------|-------------|---------------------|
| **National assujetti** | Clients/fournisseurs Madagascar soumis à la TVA | TVA 20 % standard |
| **National non assujetti** | Clients/fournisseurs MG hors champ TVA | TVA 20 % → Exonérée |
| **Reste du monde** (auto) | Clients étrangers / opérations export | TVA 20 % → 0 % export |

# 7. Premières étapes après installation

1. **Créer ou mettre à jour vos partenaires** :
   - Pour un client local Malagasy → laisser la position fiscale par défaut (« National assujetti »)
   - Pour un client étranger → assigner « Reste du monde »
   - Pour un client local non assujetti → assigner « National non assujetti »

2. **Créer une première facture client** :
   - Choisir le journal de ventes
   - Sélectionner le partenaire → la TVA s'applique automatiquement selon sa position fiscale
   - La ligne d'imputation utilisera le compte `707000` (Ventes marchandises) par défaut

3. **Créer une première facture fournisseur** :
   - Journal d'achats
   - Sélectionner le partenaire → TVA déductible appliquée
   - Compte `607000` (Achats marchandises) par défaut

4. **Vérifier le journal général** : Comptabilité → Comptabilité → Écritures comptables

# 8. Personnalisation

Le code utilise des comptes standards à 6 chiffres. Pour ajouter des **comptes
auxiliaires** (par ex. `4011001 Fournisseur ABC`, `4111002 Client XYZ`),
créer le compte via **Comptabilité → Configuration → Plan Comptable → Créer**
avec un code commençant par le préfixe approprié.

# 9. Compatibilité multi-version

| Version | Status | Moteur chart_template |
|---------|--------|----------------------|
| Odoo 19.0 | ✅ | `@template` + CSV (moderne) |
| Odoo 18.0 | ✅ | `@template` + CSV (moderne) |
| Odoo 17.0 | ✅ | `@template` + CSV (moderne) |
| Odoo 16.0 | ✅ | XML records legacy (auto-converti) |

Les branches `16.0` / `17.0` / `18.0` du dépôt sont auto-générées depuis
`main` (v19) par `scripts/build_versions.py`.

# 10. Sources & références

- **Décret n°2004-272 du 18 février 2004** — Plan Comptable Général 2005
- Ministère de l'Économie, des Finances et du Budget de Madagascar
- Conseil Supérieur de la Comptabilité (CSC)
- Ordre des Experts Comptables et Financiers de Madagascar (OECFM)
- Institut National de la Statistique (INSTAT)
- Cohérent avec les normes IAS/IFRS

# 11. Support

- Email : <support@softeamg.com>
- Web : <https://softeamg.com>
- Repository : <https://github.com/hrasamimisa/softeam_odoo_apps>
- License : LGPL-3

---

*Module développé et maintenu par* **Softeam Mada (SofteamG)** *et*
**Hoby RASAMIMISA**.
