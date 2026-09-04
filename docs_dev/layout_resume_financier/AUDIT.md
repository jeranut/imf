# AUDIT — Mise en page cassée du groupe « Résumé financier » (form microfinance.loan)

Date : 2026-09-03
Périmètre : formulaire `microfinance.loan` (`view_microfinance_loan_form`) + ses
vues héritées. **Lecture seule — aucune correction à ce stade.**

Symptôme (capture Micka) : de « Nombre d'échéances en retard » jusqu'à « Déroger au
contrôle de solde de caisse », l'alignement label / valeur en 2 colonnes du
`<group>` n'est plus respecté — les valeurs se décalent d'une cellule et
apparaissent sous / à côté du mauvais label.

---

## 1. Vues héritant du formulaire `microfinance.loan`

| Vue (xmlid) | Fichier | Touche la zone « Résumé financier » ? |
|---|---|---|
| `microfinance_loan_management.view_microfinance_loan_form` | `microfinance_loan_management/views/microfinance_loan_views.xml` | **OUI — vue de base**, contient le `<group string="Résumé financier">` (L153-173) |
| `microfinance_loan_management.view_microfinance_loan_form_scoring_inherit` | `microfinance_loan_management/views/microfinance_scoring_views.xml` (L172+) | Non — ajoute un `<group string="Scoring interne">` **après** le groupe (sibling), + stat button + page « Scoring ». Aucune insertion *dans* « Résumé financier ». |
| `microfinance_savings_management.view_microfinance_loan_form_inherit_savings` | `microfinance_savings_management/views/microfinance_loan_views_inherit.xml` | **OUI** — `<field name="fee_move_id" position="after">` insère 5 `<field>` dans « Résumé financier ». |

Aucun autre module n'hérite de cette vue. Aucun `<newline/>` ni `<separator>`
dans la zone. Le `<group>` n'a pas d'attribut `col=` (défaut `col="2"`), et aucune
insertion ne le modifie.

---

## 2. Contenu réel du `<group string="Résumé financier">` après application des héritages

Ordre des enfants directs du groupe (base + héritage savings) :

| # | Élément | Origine | Type de rendu dans un `<group>` Odoo 17 |
|---|---|---|---|
| 1 | `<field name="principal_total">` | base L154 | label + valeur (paire) |
| 2 | `<field name="interest_total">` | base L155 | paire |
| 3 | `<field name="penalty_total">` | base L156 | paire |
| 4 | `<field name="paid_total">` | base L157 | paire |
| 5 | `<field name="balance_total">` | base L158 | paire |
| 6 | `<field name="overdue_amount">` | base L159 | paire |
| 7 | `<field name="overdue_installment_count">` | base L160 | paire |
| 8 | `<field name="internal_score" widget="progressbar">` | base L161 | paire |
| **9** | **`<button name="action_recompute_risk" string="Recalculer le score" type="object" class="btn-secondary btn-sm" icon="fa-refresh"/>`** | **base L164** | **⚠️ UNE seule cellule, PAS de label** |
| 10 | `<field name="provision_amount">` | base L165 | paire — **désalignée à partir d'ici** |
| 11 | `<field name="provision_posted_amount">` | base L166 | paire (désalignée) |
| 12 | `<field name="guarantee_total">` | base L167 | paire (désalignée) |
| 13 | `<field name="fee_amount_due">` | base L168 | paire (désalignée) |
| 14 | `<field name="fee_paid">` | base L169 | paire (désalignée) |
| 15 | `<field name="fee_move_id">` | base L170 | paire (désalignée) |
| 16 | `<field name="savings_target_amount">` | savings inherit L18 | paire (désalignée) |
| 17 | `<field name="savings_target_reached">` | savings inherit L19 | paire (désalignée) |
| 18 | `<field name="guarantee_savings_required">` | savings inherit L20 | paire (désalignée) |
| 19 | `<field name="guarantee_savings_balance">` | savings inherit L21 | paire (désalignée) |
| 20 | `<field name="guarantee_savings_verified">` | savings inherit L22 | paire (désalignée) |
| 21 | `<field name="net_disbursed_amount">` | base L171 | paire (désalignée) |
| 22 | `<field name="bypass_cash_balance" invisible="state != 'approved'">` | base L172 | paire (désalignée) |

---

## 3. Anomalie identifiée — cause unique

### `<button>` nu, enfant direct du `<group>` — `microfinance_loan_views.xml:164`

```xml
<group string="Résumé financier">
    ...
    <field name="internal_score" widget="progressbar" readonly="1"/>
    <button name="action_recompute_risk" string="Recalculer le score"
            type="object" class="btn-secondary btn-sm" icon="fa-refresh"/>   <!-- ← ICI -->
    <field name="provision_amount" readonly="1"/>
    ...
</group>
```

**Mécanisme** : un `<group>` Odoo 17 (`InnerGroup`) dispose ses enfants dans une
grille CSS à colonnes répétées. Un `<field>` (sans `nolabel`) occupe **2 cellules**
(cellule label + cellule valeur). Un `<button>` posé en enfant direct occupe **1
seule cellule**, sans label associé. À partir de ce bouton, la parité
label/valeur est décalée d'une cellule : chaque `<field>` suivant voit son label
tomber dans la colonne « valeur » et sa valeur dans la colonne « label » (ou
repli sur la ligne suivante). D'où l'effet « valeur au-dessus / à côté du mauvais
label » observé de `provision_amount` jusqu'à `bypass_cash_balance`, en passant
par les 5 champs du module épargne (qui sont, eux, **structurellement corrects** —
ils héritent seulement du décalage amont).

**Origine** : ce bouton a été ajouté récemment (lot « 5 évolutions du formulaire »,
point 1 — déplacement de « Recalculer le score » depuis le `<header>`), commentaire
`<!-- Bouton déplacé du <header> vers ici... -->` L162-163. **Non commité** (présent
uniquement dans l'arbre de travail).

### Ce qui N'EST PAS en cause (vérifié)

- **Héritage savings** (`microfinance_loan_views_inherit.xml:17-22`) : les 5
  `<field>` insérés après `fee_move_id` sont des paires label/valeur bien formées,
  avec `invisible=` **dynamique** (pas `invisible="1"` statique) → ils occupent
  toujours leurs 2 cellules. `<group>`/`</group>` équilibrés, xpath `position="after"`
  correctement ciblé sur un `<field>` *à l'intérieur* du groupe. RAS.
- **Héritage savings, groupe « Dossier »** : `<field name="savings_requirement_type"
  invisible="1"/>` (statique) inséré après `co_borrower_id` — en Odoo 17 un champ
  `invisible="1"` statique est filtré de la grille (aucune cellule consommée),
  donc sans effet sur l'alignement. Cohérent avec l'absence de problème signalé
  dans « Dossier ».
- **Héritage scoring** (`microfinance_scoring_views.xml:182`) : `//field[@name=
  'internal_score']/parent::group` `position="after"` → nouveau `<group>` **frère**
  après « Résumé financier », pas d'insertion dedans. RAS.
- Aucun `col=` modifié, aucun `<newline/>`/`<separator>`, aucun autre `<button>`
  dans le groupe, aucun `<group>` orphelin ou fermeture manquante.

---

## 4. Correctifs possibles pour le Lot 1 (à trancher par Micka — non appliqués)

Tous strictement structurels, dans **la vue de base** (`microfinance_loan_views.xml`),
le bouton étant dans la vue de base : aucun autre module à toucher.

| Option | Changement | Rendu | Remarque |
|---|---|---|---|
| **A (minimal)** | Ajouter `colspan="2"` au `<button>` L164 | Bouton sur sa propre ligne pleine largeur, juste sous « Score » | 1 attribut. Rétablit la parité. |
| **B** | Remplacer L161+L164 par : `<label for="internal_score" string="Score"/>` + `<div class="o_row"><field name="internal_score" widget="progressbar" readonly="1" nolabel="1"/><button name="action_recompute_risk" .../></div>` | Bouton **à droite de la valeur** du score, sur la même ligne | Correspond le mieux à la demande initiale « à côté de la valeur du score ». Le `<div>` = 1 cellule valeur appariée au `<label>` → parité conservée. |
| **C** | Sortir le `<button>` du groupe (dans un `<div>` après `</group>`, ou le remettre dans le `<header>`) | Bouton hors de la grille financière | Revient partiellement sur le lot précédent. |

Recommandation : **B** (respecte l'intention « à côté du score ») ou **A** (plus sûr,
1 ligne de diff).

---

## Livrable

Cause unique confirmée : `<button name="action_recompute_risk">` nu dans
`<group string="Résumé financier">` à `microfinance_loan_management/views/
microfinance_loan_views.xml:164`. Les insertions multi-modules de la zone sont
saines. Correction = 1 fichier (vue de base), au choix option A ou B.

---

## LOT 1 — Correction appliquée (2026-09-03)

Micka a choisi **l'option B** (bouton à droite de la valeur du score). Blocage
technique rencontré → repli sur **A**, avec une robustification qui garde B
possible plus tard.

### Pourquoi B n'est pas applicable en un seul `-u`

L'option B enveloppe `internal_score` dans un `<div class="o_row">` → il n'est
plus enfant direct du `<group>`. Or la vue héritée
`microfinance_scoring_views.xml` (même module, chargée **après**
`microfinance_loan_views.xml` dans le manifest — L41 puis L46) contient :

```xml
<xpath expr="//field[@name='internal_score']/parent::group" position="after">
```

Pendant un `-u microfinance_loan_management` : la vue de base est mise à jour et
re-validée **d'abord**, contre la version encore en base de la vue héritée
scoring (ancien `parent::group`). Avec `internal_score` sous un `<div>`,
`parent::group` ne résout plus → `ParseError: Element ... cannot be located` →
tout le chargement de la base échoue (constaté 2×, log `upd.log`/`upd2.log`).
`microfinance_scoring_views.xml` n'est jamais atteint, sa correction non plus.

### Ce qui a été fait

| Fichier | Changement |
|---|---|
| `microfinance_loan_management/views/microfinance_loan_views.xml` | `internal_score` reste enfant direct du `<group>` ; le `<button name="action_recompute_risk">` reçoit **`colspan="2"`** → il occupe une ligne pleine largeur juste sous « Score », la parité label/valeur de la grille est rétablie (option A). |
| `microfinance_loan_management/views/microfinance_scoring_views.xml` | xpath `//field[@name='internal_score']/parent::group` → **`//field[@name='internal_score']/ancestor::group[1]`** (robustesse : survit à un futur wrap dans un `<div>`). Résultat inchangé (groupe « Scoring interne » toujours inséré après « Résumé financier »). |

Vérifié : `-u` propre (aucune ParseError), `get_view`/`get_views` OK, bouton avec
`colspan="2"`, `internal_score` toujours enfant direct du groupe, groupe
« Scoring interne » toujours présent.

### Si Micka veut vraiment B (bouton sur la même ligne que la valeur)

Déploiement en **2 temps** :
1. commit A + xpath `ancestor::group[1]` (fait ici), `-u`, restart.
2. ensuite seulement : commit qui remplace dans la vue de base
   `<field name="internal_score" .../>` + `<button colspan="2"/>` par
   `<label for="internal_score" string="Score"/>` + `<div class="o_row"><field name="internal_score" ... nolabel="1"/><button .../></div>`, `-u`, restart.
   L'étape 1 ayant déjà robustifié l'xpath scoring, l'étape 2 passe sans casse.

### STOP — relire le diff avant commit
