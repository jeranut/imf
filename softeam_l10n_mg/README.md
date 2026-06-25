# Madagascar - Plan Comptable Général 2005 (`softeam_l10n_mg`)

Localisation comptable Malagasy pour Odoo, basée sur le **Plan Comptable
Général 2005** (décret n°2004-272 du 18 février 2004), cohérent avec les
normes IAS/IFRS.

## Contenu

* **Plan comptable** des 7 classes du PCG 2005 (Annexe I officielle) — **468 comptes** à 6 chiffres (préfixes officiels 3/4/5-digits paddés à droite par des zéros : `1011` → `101100`, `4111` → `411100`, etc.)
* **Taxes TVA Madagascar** : 20 % collectée / déductible (B&S, Immo), 0 % export, exonérée
* **Positions fiscales** : National assujetti / National non-assujetti / Reste du monde
* **Groupes de comptes** alignés sur la nomenclature à deux chiffres (10, 11, 20, 21, …)
* **Compte de résultat par nature** (analyse par nature obligatoire selon PCG 2005)

## Compatibilité

| Odoo | Edition | Source |
|------|---------|--------|
| 19.0 | Community / Enterprise | Branche `main` (ce code) |
| 18.0 | Community / Enterprise | Branche `18.0` — auto-générée |
| 17.0 | Community / Enterprise | Branche `17.0` — auto-générée |
| 16.0 | Community / Enterprise | Branche `16.0` — auto-générée |

Les branches 16/17/18 sont produites par `scripts/build_versions.py`.

## Installation

1. Installer le module **Comptabilité** d'Odoo
2. Installer ce module (`softeam_l10n_mg`)
3. Aller sur **Comptabilité → Configuration → Sociétés**, sélectionner « Madagascar - PCG 2005 »

> ⚠️ Le plan comptable doit être chargé sur une société **vide de toute écriture**.

## Personnalisation

Le code par défaut utilise des comptes à 3 chiffres (préfixe officiel PCG).
Pour ajouter des comptes auxiliaires sur 6 chiffres (ex. `4011001` Fournisseur X),
utilisez **Comptabilité → Configuration → Plan comptable → Créer**.

## Source officielle

* Décret n°2004-272 du 18 février 2004
* Ministère de l'Economie, des Finances et du Budget
* Conseil Supérieur de la Comptabilité (CSC)
* Ordre des Experts Comptables et Financiers de Madagascar (OECFM)

## License

LGPL-3.0 — voir `LICENSE` à la racine du dépôt.

## Support

* Email : support@softeamg.com
* Web : https://softeamg.com
