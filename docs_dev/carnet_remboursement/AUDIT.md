# LOT 0 — Audit : Structure du tableau "Carnet de remboursement"

Audit en lecture seule. Aucune modification de code, de vue ou de données.

## 1. Fichier et action de rapport

- **Template** : `microfinance_loan_management/report/report_carnet_remboursement.xml`
  - `<template id="report_carnet_remboursement_document">` (page recto + verso)
  - `<template id="report_carnet_verso_bloc">` (sous-template factorisé, appelé deux fois
    sur la page verso)
- **Action de rapport** : `action_report_carnet_remboursement` (même fichier), modèle
  `microfinance.loan`, `report_type='qweb-pdf'`.
- **Paperformat dédié** : `paperformat_carnet_remboursement` (custom, 297×150mm paysage).
- **Bouton déclencheur** : `action_print_carnet_remboursement` sur `microfinance.loan`
  (`models/microfinance_loan.py`) — poste le PDF dans le chatter, bouton header
  "Imprimer le carnet" (regroupé dans le menu déroulant "Imprimer").

## 2. XML actuel du tableau — extrait complet

**Recto** (`report_carnet_remboursement_document`, colonne de gauche) :

```xml
<table class="carnet-table">
    <thead>
        <tr>
            <th rowspan="2">Volana</th>
            <th colspan="2">Fandoavana natao</th>
            <th rowspan="2">Vola voaray</th>
            <th rowspan="2">Totaly voaloa</th>
            <th colspan="2">Sonia</th>
        </tr>
        <tr>
            <th>Daty</th>
            <th>Rosia n°</th>
            <th>CEFOR</th>
            <th>Mpindrana</th>
        </tr>
    </thead>
    <tbody>
        <t t-foreach="range(4)" t-as="carnet_group">
            <t t-foreach="range(6)" t-as="carnet_row">
                <tr t-attf-class="#{'carnet-group' if carnet_row == 5 else ''}">
                    <td>&#160;</td><td>&#160;</td><td>&#160;</td>
                    <td>&#160;</td><td>&#160;</td><td>&#160;</td><td>&#160;</td>
                </tr>
            </t>
        </t>
    </tbody>
</table>
```

**Verso** (`report_carnet_verso_bloc`, appelé deux fois côte à côte sur la page 2) : **structure
identique caractère pour caractère** à celle du recto ci-dessus (mêmes `<thead>`, même double
`t-foreach range(4)`/`range(6)`, mêmes 7 `<td>&#160;</td>` par ligne) — seuls les noms des
variables de boucle diffèrent (`carnet_group2`/`carnet_row2`).

CSS associé (partagé recto/verso, dans le `<style>` du template principal) :

```css
table.carnet-table { width:100%; border-collapse: collapse; }
table.carnet-table th, table.carnet-table td { border: 1px solid #000; text-align:center; padding:2px; height: 16px; font-size:10px; }
table.carnet-table th { font-weight: bold; }
.carnet-group td { border-bottom: 2.5px solid #000; }
```

## 3. Écarts précis avec la structure cible

### 3.a En-tête — **conforme, aucun écart**

L'en-tête à deux niveaux existant correspond exactement à la cible : `Volana`/`Vola
voaray`/`Totaly voaloa` en `rowspan="2"`, `Fandoavana natao` et `Sonia` en `colspan="2"`,
sous-en-têtes `Daty`/`Rosia n°`/`CEFOR`/`Mpindrana`. Rien à changer ici.

### 3.b Regroupement des lignes — **écart majeur**

| | Cible | Actuel |
|---|---|---|
| Nombre de blocs "Volana" | 3 blocs de 8 lignes | 4 groupes de 6 lignes (visuel uniquement) |
| Fusion cellule "Volana" | `rowspan="8"`, une seule cellule par bloc | **Aucune fusion** : chaque ligne a sa propre cellule Volana vide (`<td>&#160;</td>`) |
| Sous-groupes "Daty" | 4 sous-groupes de 2 lignes par bloc Volana, `rowspan="2"` | **Aucune fusion** : chaque ligne a sa propre cellule Daty vide |
| Séparation visuelle actuelle | — | Un `border-bottom` plus épais (2.5px, classe `carnet-group`) toutes les 6 lignes (`carnet_row == 5`), sans lien avec une véritable fusion de cellule |

**Concrètement** : le tableau actuel est une grille plate de **7 colonnes × 24 lignes**, où
**chacune des 24 lignes possède ses propres cellules Volana et Daty** (7 `<td>` identiques par
ligne, aucun `rowspan` nulle part dans le `<tbody>`). Aucune structure de fusion n'existe
aujourd'hui — seule une bordure plus épaisse tous les 6 rangs suggère visuellement un
regroupement, mais ce n'est ni un `rowspan="8"` (Volana) ni un `rowspan="2"` (Daty), et le
découpage est en groupes de **6**, pas de **8**.

### 3.c Colonne "Rosia n°" — **incohérence à trancher, contradiction interne au prompt**

Le tableau actuel ne numérote **rien du tout** : toutes les cellules (Volana, Daty, Rosia n°,
Vola voaray, Totaly voaloa, CEFOR, Mpindrana) sont vides (`&#160;`), sans aucune distinction.

Le prompt de ce lot contient une contradiction interne sur ce point précis :
- La section « Structure cible » décrit "Rosia n°" comme une **valeur imprimée** :
  *"une valeur par ligne, numérotée en continu de 1 à 8 à l'intérieur de chaque bloc
  Volana"* — ce qui suppose un contenu réel (1, 2, 3… 8) dans chaque cellule.
- La section « Précisions supplémentaires » liste ensuite explicitement "Rosia n°" parmi
  les cellules qui **doivent rester vides** : *"les cellules Volana, Daty et Rosia n°
  doivent rester vides dans le tableau imprimé (à remplir manuellement)"* — mais la phrase
  suivante ne reprend, pour justifier ce vide, que *"la numérotation 1/2/3 (Volana) et
  1-4 (Daty)"*, sans reciter "Rosia n°" dans cette clarification.

**Ce point doit être tranché explicitement par Micka avant le Lot 1** : "Rosia n°"
doit-il être (a) réellement imprimé 1→8 par bloc (repère physique pré-imprimé, comme sur un
vrai carnet CEFOR), ou (b) laissé vide comme Volana/Daty (rempli à la main) ? Le rendu
actuel (tout vide) satisfait déjà l'option (b) mais pas l'option (a).

### 3.d Nombre de lignes par table — **écart majeur, le plus significatif de l'audit**

Le total de 24 lignes de données est correct **au niveau du document dans son ensemble** au
sens où le prompt l'entend (3 blocs × 8 lignes), mais **le rendu actuel ne correspond pas à
cette répartition** : le template actuel affiche **le même tableau de 24 lignes complet, TROIS
FOIS** :
- Une fois sur le recto (24 lignes, 4 groupes de 6).
- Deux fois sur le verso, une par bloc côte à côte (24 lignes chacune, 4 groupes de 6).

Soit **72 lignes de cellules au total** dans le PDF actuel, contre les **24 lignes réparties en
3 blocs de 8** (8 sur le recto + 8 + 8 sur le verso) attendues par la structure cible. Le Lot 1
devra donc **réduire chaque bloc à 8 lignes** (au lieu de 24), pas seulement réorganiser le
regroupement interne d'un même total de 24 par emplacement.

### 3.e Disposition de page — **déjà conforme pour la structure générale, à ajuster seulement pour le contenu par bloc**

| | Cible | Actuel |
|---|---|---|
| Page 1 | 1 bloc Volana (8 lignes) + encart infos + 1 texte d'attestation | 1 table (24 lignes) + encart infos (déjà présent, cf. section 4) + 1 texte d'attestation partagé — **structure de page déjà correcte**, seul le nombre de lignes de la table est à corriger |
| Page 2 | 2 blocs Volana (8 lignes chacun) côte à côte, **chacun avec son propre texte d'attestation + sa propre ligne "Sonia"** | 2 tables (24 lignes chacune) côte à côte, **chacune avec déjà son propre texte d'attestation + sa propre ligne "Sonia"** (`report_carnet_verso_bloc`) — **structure de page déjà correcte**, seul le nombre de lignes de chaque table est à corriger |
| Saut de page | Page 1 (recto) / Page 2 (verso), pas un saut par bloc | Déjà implémenté ainsi (`page-break-after: always` sur `.carnet-page-recto`, cf. Lot précédent) — **conforme** |

**Bonne nouvelle pour le Lot 1** : la disposition physique en pages (1 bloc à gauche du recto
+ 2 blocs côte à côte au verso, chacun avec sa propre attestation) est **déjà exactement
celle demandée** — c'est un résultat du lot précédent (corrections visuelles). Le seul
changement structurel nécessaire porte sur le **contenu interne de chaque table** (8 lignes
avec fusions Volana/Daty, au lieu de 24 lignes en groupes de 6 sans fusion).

## 4. Encart d'informations emprunteur — déjà existant, réutilisable tel quel

Le prompt demande de vérifier si un tel encart existe déjà ailleurs (ex.
`report_contrat_credit.xml`) pour éviter de le recréer. Constat :

- **`report_contrat_credit.xml` ne contient aucun encart encadré comparable** : c'est un
  document narratif (paragraphes justifiés, police Times New Roman), sans bloc à bordure
  regroupant nom/produit/montant/échéance comme celui du carnet.
- **L'encart existe déjà dans `report_carnet_remboursement.xml` lui-même**, ajouté lors d'un
  lot précédent : les classes `.carnet-col-right` / `.carnet-box` (bordure 1.5px, padding,
  titre centré en gras) forment exactement l'encart "NY MPINDRAM-BOLA" / "MOMBAMOMBA NY
  FAMPISAMBORAM-BOLA" déjà présent sur la page recto actuelle, avec les champs réels déjà
  câblés (`partner_id.name`, `microfinance_account_number`,
  `microfinance_id_number_display`, `microfinance_profession`, `phone`,
  `get_contrat_address()` — cf. commentaire du template, lignes 109-131). **Rien à
  réutiliser depuis un autre rapport : l'encart cible EST déjà celui-ci.**

## 5. Texte d'attestation malgache — pas de source canonique trouvée, contradiction textuelle à lever

Recherche dans tout le dépôt (`grep` sur les fragments distinctifs "manamarina fa nahavita",
"famerenam-bola nindramiko", "mitotaly"/"mitohaty") :

- **Aucune autre occurrence de ce texte complet** ailleurs dans le codebase (pas de fichier de
  traduction `.po`, pas d'autre template QWeb). Le seul endroit où ce texte existe est déjà
  dans `report_carnet_remboursement.xml` lui-même (écrit lors du tout premier lot de ce
  rapport, jamais reconfirmé depuis contre une source indépendante).
- `report_contrat_credit.xml` contient le mot "mitotaly" mais dans une phrase totalement
  différente (calcul du taux d'intérêt mensuel), pas la même attestation.
- **Divergence textuelle constatée entre la version déjà implémentée et celle citée dans le
  prompt de ce lot** :

  | | Déjà implémenté (template actuel) | Cité dans ce prompt |
  |---|---|---|
  | Mot après "Ka" | **mitotaly** | **mitohaty** |
  | Après "raha" | **raha tsy misy fanitsiana** | **raha toy misy fanitsiana** |

  "tsy" (négation, "ne...pas") et "toy" (comparatif, "comme") n'ont pas du tout le même sens
  en malgache — l'une des deux versions contient probablement une coquille de saisie. **À
  faire confirmer mot à mot par Micka avant le Lot 1** : aucune des deux occurrences trouvées
  ne peut être considérée comme la référence faisant autorité sans validation externe (pas de
  document source scanné/PDF de référence trouvé dans le dépôt pour trancher).

## 6. Conventions CSS déjà en place à réutiliser

Déjà appliquées de façon cohérente dans `report_carnet_remboursement.xml` (pas besoin
d'aller chercher dans `report_contrat_credit.xml`, dont les conventions typographiques —
Times New Roman, prose narrative — ne s'appliquent pas à un tableau structuré) :

- `* { box-sizing: border-box; }` en tête de style (garantit des largeurs identiques entre
  recto/verso malgré bordures/paddings — cf. Lot corrections visuelles).
- Bordures de tableau : `border: 1px solid #000` (cellules), `border-collapse: collapse`.
- Police cellules : `font-size: 10px` (légèrement plus petite que le corps de page, `11px`
  sur `.carnet-page`).
- Saut de page entre recto/verso : classe dédiée `.carnet-page-recto { page-break-after:
  always; }` — nécessaire car Odoo ne force aucun saut automatique entre deux `<div
  class="page">` frères dans le même document QWeb (uniquement entre documents séparés,
  cf. commentaire déjà présent dans le template, section `_prepare_html()`).
- `web.basic_layout` (pas `web.html_container` direct) : indispensable à l'encodage
  UTF-8 correct sous wkhtmltopdf (cf. commentaire déjà présent en bas du fichier).
- Paperformat custom 297×150mm sans champ `orientation` explicite (piège déjà documenté :
  combiner `page_width`/`page_height` avec `orientation=Landscape` fait pivoter deux fois
  le rectangle et produit une page portrait).

## 7. Confirmation : tableau actuellement statique (pas de boucle sur l'échéancier)

Confirmé : les deux `t-foreach` du `<tbody>` (`range(4)` / `range(6)`) itèrent sur des
**entiers Python générés à la volée** (`range(...)`), **pas** sur `o.installment_ids` ni sur
aucune donnée réelle du dossier. Le tableau est donc déjà **100% statique**, indépendant du
crédit imprimé — conforme à l'esprit de la cible ("grille fixe, indépendante du dossier").
Seul le **nombre de lignes par groupe** (6 au lieu de 8) et **l'absence de fusion
Volana/Daty** doivent changer ; aucun retour en arrière depuis une logique dynamique n'est
nécessaire, il n'y en a pas.

## Synthèse pour le Lot 1

1. **Remplacer le contenu du `<tbody>`** (recto ET `report_carnet_verso_bloc`, structure
   identique dans les deux) par une grille de **8 lignes** avec :
   - Une cellule Volana `rowspan="8"` vide (ou numérotée — cf. point 2 ci-dessous, ne
     concerne que Volana/Daty, jamais en doute) par bloc.
   - 4 cellules Daty `rowspan="2"` vides, une par sous-groupe de 2 lignes.
   - Colonnes Rosia n°/Vola voaray/Totaly voaloa/CEFOR/Mpindrana : une cellule par ligne
     (8 lignes), sans fusion.
2. **Trancher avec Micka** : "Rosia n°" doit-il être numéroté 1→8 dans le PDF imprimé, ou
   rester vide comme Volana/Daty ? (contradiction interne au prompt, section 3.c).
3. **Faire confirmer mot à mot par Micka** le texte d'attestation malgache : la version
   actuellement implémentée diffère de celle citée dans ce prompt sur au moins deux mots
   ("mitotaly"/"mitohaty", "tsy"/"toy" — section 5) — aucune source tierce ne permet de
   trancher seul.
4. Aucun changement nécessaire sur : l'en-tête à deux niveaux (déjà conforme), l'encart
   d'informations emprunteur (déjà présent et câblé), la disposition en 2 pages avec saut de
   page recto/verso, ni la présence d'un texte d'attestation propre à chaque bloc du verso
   (tout cela est déjà en place depuis le lot précédent).

Aucune modification de code effectuée dans ce lot.
