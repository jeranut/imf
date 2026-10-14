# Balance d'ouverture — audit de l'existant (lecture seule)

Base **MOWGLI**, relevé du 2026-10-10. Aucune donnée ni aucun code modifié.

## 0. Quelles sont « les 3 sociétés » ?
MOWGLI contient 11 sociétés. Trois ont la structure de trésorerie Ampaly complète (journaux BMOI/BNI par usage,
caisse CAI, Mvola MVO, suspens 324100, journal AN) : **9 AGENCE ANALAKELY (AG3, société mère,
`microfinance.parent_company_id`)**, **1 AGENCE 67 Ha (AG1)** et **11 AGENCE AMBOHIBAO (AG2)**. Ce sont elles que
j'audite. Les 8 autres sociétés (CEFOR …) ont l'ancienne structure (BNK1/BQxx/CSH1 actifs, suspens 301000) et très peu
ou pas d'écritures : **à confirmer** si ce sont bien les 3 à conserver (la 2 CEFOR Ambanidia a 3 écritures comptabilisées).

## 1. Journaux et comptes de trésorerie (actifs)
| Journal | Type | Usage | Compte (default_account_id) | Suspens | Sociétés |
|---|---|---|---|---|---|
| CAI Caisse | cash | cash | 101000 Billets et monnaies | 324100 | 1, 9, 11 |
| BMCR / BNCR Banque BMOI / BNI – Crédit | bank | credit | 131101 / 131201 | 324100 | 1, 9, 11 |
| BMEP / BNEP – Épargne | bank | savings | 131102 / 131202 | 324100 | 1, 9, 11 |
| BMOP / BNOP – Exploitation | bank | operating | 131104 / 131204 | 324100 | 1, 9, 11 |
| FDBM / FDBN Fonds BMOI / BNI (avant partage) | bank | fund | 131103 / 131203 | 324100 | **9 seulement** |
| MVO Mobile money Mvola | bank | mobile | 141010 | 324100 | 1, 9, 11 |
| AN À-nouveaux, OD, VIR | general | — | sans compte par défaut | — | 1, 9, 11 |
| TRANS Transit inter-agences | general | — | 302000 | — | **inactif** dans 1, 9, 11 (actif dans les anciennes sociétés) |

Journaux archivés (BNK1, BQCR/BQEP/BQOP, CRE, CSH1, EPG) : ignorés. Aucun compte n'est partagé entre deux journaux actifs ;
aucun journal bank/cash actif sans compte. Journal **AN (À-nouveaux)** présent dans les 3 sociétés (id 6160 / 6153 / 6167) :
candidat naturel pour l'écriture d'ouverture.
Transit inter-agences : pas de journal actif ; les flux de liaison passent par des comptes créés automatiquement par agence
(**301010 « Liaison - AGENCE ANALAKELY »** dans 1 et 11 ; **301101 / 301102 « Liaison - AGENCE 67 Ha / AMBOHIBAO »** dans 9)
et le compte 302000 / 301000 existent dans le plan.

## 2. Comptes utilisés par les flux microfinance (existent dans les 3 sociétés sauf mention)
- **Encours de crédit** (défauts `_pcec_default` de `microfinance_loan_product.py:160-340`) : principal 203001 (indiv.) /
  203002 (groupe) ; intérêts échus 208001-208004 ; frais de dossier à recevoir 208005 ; arriérés déclassifiés 273001/2 ;
  provisions 293001/2 ; pénalités d'avance 325001/2 et leur revenu 326101/2 ; commissions échues 325003/4 ;
  commissions gagnées 717001/2 ; **frais 717003** (commission sur crédit) ; autres produits 707301/2 (intérêts reçus),
  749001/2, 741000, 641201/2, 682201/2 ; surpaiement 219001 ; chèques en attente 219000.
- **Épargne clients** (`microfinance_savings_product.py:114-210`) : 213001/2/3 ; charges à payer et intérêts d'avance
  218001-218006 ; intérêts payés 607301-607303 ; pénalités 749003 ; commission 717004.
- **Fonds de crédit reçus** : un compte par fonds (`microfinance.fond.credit.account_id`), créés automatiquement
  (« Fonds - FND/… » : 240101, 240102 dans la 9) ; compte bailleur par défaut de la société
  (`res.company.microfinance_fond_account_default_id` : **116000** dans la 9, **240000** dans 1 et 11).
- **Fonds d'exploitation** : subvention d'exploitation, paramètre `microfinance.fond_subvention_default_code` = 762
  (compte **762000**) ; avances via les comptes de liaison / banque d'exploitation.
- **Fonds propres** (classe 5, 13 comptes de type equity) : 563000 capital versé, 566000 réserve légale, 567000/568000
  autres réserves, 581000 / 589000 report à nouveau, 591000 / 598000 résultat.
- **Paie** (mowgli_payroll_pcec) : règles avec comptes uniquement dans les sociétés **1** (crédit 315000 pour CNAPS, IRSA,
  LOAN, NET, OSTIE ; 5 règles sans compte) et **9** (BASIC débit 652100 ; 3 règles sans compte) ; **aucune règle en 11**.
- **Caisse** : écarts de caisse 324000 (déficit) / 329100 (excédent), identiques dans les 3 sociétés.
- Soldes existants (comptabilisés) : uniquement des écritures de simulation datées **2026-10-10 et 2026-10-11**
  (1 : 3 écritures, 9 : 15, 11 : 2) ; aucune avant le 2026-10-10 ; aucun solde d'ouverture.

## 3. Anomalies et différences
1. **Plan comptable inégal** : 379 comptes en 9 (dont 1 déprécié), 378 en 1, 374 en 11. Absents d'une société :
   131103 / 131203 (fonds avant partage), 240101 / 240102 (fonds), 301101 / 301102 (liaisons) → **seulement dans la 9** ;
   301010 → **absent de la 9** (présent en 1 et 11) ; 325005-325007 et 335001 → **seulement dans la 1**.
2. **Libellés/types divergents du compte parent** entre sociétés : 325000, 326100, 607300, 641200, 707300, 717000, 719000,
   **741000** (société 1 : « Produits sur crédit-bail * », sociétés 9 et 11 : « Récupération sur créances apurées »).
   Le défaut `account_recouvrement_id` = 741000 est donc sémantiquement faux dans la société 1.
3. **Banque bailleur de fonds** : les journaux « fonds » n'existent que dans la 9 ; les fonds propres/avances des agences
   passent par les comptes de liaison, d'où des soldes de liaison croisés (9 : +36 313 680 / +30 666 640 ; 1 : −36 313 680 ;
   11 : −30 666 640) qui devront être repris à l'ouverture de façon cohérente entre sociétés.
4. **Écriture d'ouverture native déjà amorcée dans la société 11** : `res.company.account_opening_move_id` = 4722
   (`OD/2025/12/0001`, brouillon, 2025-12-31, **0 ligne**). Les sociétés 1 et 9 n'en ont pas. À neutraliser ou réutiliser
   (le champ natif est le point d'accroche d'Odoo pour une écriture d'ouverture ; la V1 doit décider de l'alimenter ou non).
5. **Suspens 324100** (opérations bancaires en attente) utilisé comme compte d'attente de tous les journaux : il doit rester
   à 0 à l'ouverture.
6. **Compte du transit inter-agences** : journal TRANS inactif partout où la structure Ampaly est en place alors que les
   anciennes sociétés l'utilisent.
7. **Aucun conflit** de comptes entre journaux, ni de compte hors société sur les produits crédit.

## 4. Existant à réutiliser
- **Patron relevé bancaire papier** : modèle `account.bank.statement` hérité (`models/microfinance_bank_statement.py`) avec
  `mf_state` (brouillon / validé), verrou par `LOCKED_FIELDS` + contexte `mf_allow`, réouverture avec motif (comptable),
  chatter via `mail.thread` + `tracking=True`, lignes `microfinance.bank.statement.entry`.
  Vues : `views/microfinance_bank_statement_views.xml` ; menu **Comptabilité > Banque > Relevés bancaires**
  (`menu_microfinance_bank_section` sous `account.menu_finance_entries`, séquence 5, groupes Finance, Comptable, Auditeur,
  gestionnaire comptable). Droits : `security/ir.model.access.csv:261-268` (finance lecture/écriture/création, comptable
  tout, auditeur lecture) et règle de société `security/microfinance_bank_rules.xml` (`company_ids`).
- **Relevé suivant** : `balance_start` du premier relevé = solde final du précédent ; `_onchange_mf_previous_balance`
  (`microfinance_bank_statement.py`) — à étendre pour lire la balance d'ouverture comme « précédent » quand il n'y a pas
  de relevé.
- **Journal AN** (à-nouveaux) dans chaque société pour porter l'écriture unique.
- **Fiche de caisse** (`microfinance_caisse_fiche_journee.py:95-125`) : le solde d'ouverture de la première fiche est le
  solde comptable du compte caisse avant la date → la balance d'ouverture alimente déjà le caisse sans changement.
- **Natif Odoo** : `res.company.account_opening_move_id` / `account_opening_date`, verrous de période (`fiscalyear_lock_date`).
- **Tests** : `MicrofinanceNoFundMixin` (`tests/common.py:179`) neutralise les fonds actifs de la base réelle ;
  `MicrofinanceCommon` pour les fixtures.
- **Export/import Excel** : `xlsxwriter` déjà utilisé par les contrôleurs de rapports (Grand livre, Balance, Contrôle des
  journaux) ; `openpyxl` à vérifier pour l'import (lecture).

## 5. Proposition de liste de comptes du TEMPLATE (par société, montants à zéro)
Règle : la liste est calculée par société (les comptes absents sont ignorés et signalés), sans code écrit en dur dans le
modèle : elle vient (a) des comptes des journaux bank/cash actifs, (b) des champs de comptes des produits et de la
configuration, (c) d'une liste de comptes configurable (paramètre / table de modèle).

| Bloc | Comptes | Justification |
|---|---|---|
| Trésorerie | 101000 ; 131101, 131102, 131104, 131201, 131202, 131204 ; 141010 ; **131103, 131203 (9 seulement)** | `default_account_id` des journaux actifs ; les soldes bancaires saisis servent de point de départ au 1er relevé |
| Attente | 324100 (laisser vide), 324000 / 329100 | contrepartie des relevés / écarts de caisse ; à 0 normalement, listés pour contrôle seulement |
| Inter-agences | 301000, 302000, comptes « Liaison - … » existants | flux de liaison siège/agences à reprendre de façon cohérente entre les 3 sociétés |
| Crédit | 203001/2, 208001-208005, 273001/2 | encours, intérêts et frais à recevoir, arriérés (champs du produit crédit) |
| Provisions et réserves de crédit | 293001/2, 325001-325004, 326101/2 | provisions, produits constatés d'avance / réservés repris à l'ouverture |
| Épargne | 213001/2/3, 218001-218006 | dépôts clients, charges à payer et intérêts d'avance (produit épargne) |
| Autres sommes dues | 219000, 219001 | chèques en attente, surpaiements |
| Fonds | compte bailleur par défaut (116000 en 9, 240000 en 1 et 11) + comptes « Fonds - FND/… » existants | fonds de crédit reçus, solde des bailleurs |
| Fonds propres | 563000, 566000, 567000, 568000, 569000, 581000, 589000 | capital, réserves, subventions d'investissement, report à nouveau. Le résultat (591000/598000) se reprend via le report à nouveau |
| Immobilisations | classe 42x (421xxx, 422xxx), 482000 amortissements, 493000 | immobilisations et amortissements ; à confirmer selon les besoins |
| Paie | 315000 (créditeurs divers) ; 652100 si utilisé | comptes des règles de paie (sociétés 1 et 9) |
| Partenaires | colonne partenaire optionnelle | pour les comptes de tiers (3xx/4xx) ; les clients et épargnes restent hors V1 |

## 6. Points à valider avant la phase 2
1. Les 3 sociétés sont-elles bien 9, 1 et 11 ?
2. Écritures existantes (2026-10-10 et 10-11) : la contrainte « refus de valider s'il existe des écritures comptabilisées
   antérieures à la date d'ouverture » ne bloquera pas si l'ouverture est datée du 2026-10-10 (aucune écriture avant) ;
   mais ces écritures de simulation seront dans les soldes **après** l'ouverture : faut-il les purger avant de saisir ?
3. Écriture d'ouverture native (société 11, brouillon vide 4722) : l'ignorer, ou y rattacher la balance validée
   (`account_opening_move_id`) ?
4. Journal de l'écriture : **AN** (recommandé) ou OD.
5. Anomalies du plan à corriger **avant** (hors module) : comptes absents d'une société, libellé de 741000 (société 1).
6. Liste du template : valider/ajuster le tableau du §5 (notamment fonds propres, immobilisations, comptes de liaison).

## 7. Décisions (2026-10-10)
- Purge des écritures de simulation faite par l'utilisateur : plus aucune écriture dans les sociétés 1, 9 et 11.
- Point 4 : comptes de la société 1 alignés sur les valeurs des sociétés 9 et 11 (nom et type) : 325000, 326100, 607300,
  641200, 707300, 717000, 719000, 741000 (aucune ligne d'écriture sur ces comptes). Les comptes présents dans une seule
  société (fonds, liaisons, 325005-7, 335001) sont des comptes de flux créés automatiquement : non touchés.
- Point 2 : écriture d'ouverture native vide OD/2025/12/0001 (id 4722, société 11) supprimée ;
  `account_opening_move_id` de la société 11 est maintenant vide.
- Restent à confirmer : les 3 sociétés (9, 1, 11), le journal AN, la liste du template du §5.
