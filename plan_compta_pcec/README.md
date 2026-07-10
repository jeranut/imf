# Madagascar - Plan Comptable des Établissements de Crédit 2005 (`plan_compta_pcec`)

Localisation comptable Malagasy sectorielle pour Odoo, basée sur le **Plan Comptable des
Établissements de Crédit 2005** (Arrêté n°20469/2004 du 27 octobre 2004, Commission de
Supervision Bancaire et Financière — CSBF), cohérent avec les normes IAS/IFRS.

## Indépendance vis-à-vis de `softeam_l10n_mg`

Ce module est un **pack de localisation indépendant** du PCG générique `softeam_l10n_mg` :
aucune dépendance entre les deux modules, aucun compte partagé (les identifiants XML sont
préfixés `pcec_` ici, `pcg_` dans le module PCG — voir `doc/comptes_a_verifier.md`). Les
sociétés utilisant déjà `softeam_l10n_mg` (EAT, immobilier) ne sont pas affectées par
l'installation de ce module.

## Contenu

* **Plan comptable** des classes 1 à 7 du PCEC 2005 (Titre II — Nomenclature des comptes) —
  305 comptes à 6 chiffres. La **classe 9 (hors-bilan)** n'est **pas incluse** dans cette
  première version (itération dédiée au reporting d'engagements CSBF si besoin).
* **Taxes TVA Madagascar** : mêmes règles que `softeam_l10n_mg` (20 % collectée / déductible,
  0 % export, exonérée), repointées vers des comptes créés spécifiquement sous la rubrique 31
  "Débiteurs divers et créditeurs divers" (317x) — la nomenclature PCEC classes 1-7 fournie
  n'a pas de poste TVA dédié, contrairement au PCG générique (445x).
* **Positions fiscales** : identiques au régime général Malagasy (National assujetti /
  National non assujetti / Reste du monde).
* **Groupes de comptes** alignés sur la nomenclature PCEC à deux chiffres.

## ⚠️ Intitulés déduits par analogie — à faire valider par un comptable CSBF

Une partie substantielle des libellés de comptes (marqués d'un **`*`** en fin de nom dans le
CSV) n'était pas donnée explicitement dans la nomenclature source utilisée pour construire ce
module — seuls les numéros de compte l'étaient pour plusieurs sections. Ces libellés ont été
déduits par analogie structurelle avec les sections intégralement décrites (11 Banque
Centrale et 13 Établissements de crédit, qui suivent un schéma positionnel régulier
X1/X2/X3/X5/X6/X8/X9 repris pour 14 et 16). **Voir `doc/comptes_a_verifier.md` pour le détail
et la liste complète des comptes à valider contre le texte officiel de l'arrêté avant mise en
production.**

De même, `account_type` a été reconstruit compte par compte selon la nature économique
déduite du libellé (et non copié depuis `softeam_l10n_mg`), avec une attention particulière à
l'inversion classe 1 (trésorerie, actif **et** passif selon le sous-compte) / classe 5
(capitaux propres et passifs non courants) propre au PCEC par rapport au PCG générique.

## Compatibilité

Odoo 17.0 — mécanisme `@template('mg_pcec')`, `depends: ['account']`.

## Installation

1. Installer le module **Comptabilité** d'Odoo
2. Installer ce module (`plan_compta_pcec`)
3. Aller sur **Comptabilité → Configuration → Sociétés**, sélectionner « PCEC 2005 »

> ⚠️ Le plan comptable doit être chargé sur une société **vide de toute écriture**, et
> uniquement sur une société correspondant à un établissement de crédit agréé CSBF (les
> autres sociétés de l'instance doivent continuer à utiliser `softeam_l10n_mg`).

## Hors périmètre de cette version

* Classe 9 (hors-bilan / engagements).
* Assignation automatique des comptes PCEC sur les produits de crédit/épargne
  (`microfinance_loan_management` / `microfinance_savings_management`) — configuration
  manuelle, une fois ce module installé et les libellés validés.

## Source officielle

Arrêté n°20469/2004 du 27 octobre 2004 — Commission de Supervision Bancaire et Financière
(CSBF), Madagascar.

## Support

support@softeamg.com · softeamg.com
