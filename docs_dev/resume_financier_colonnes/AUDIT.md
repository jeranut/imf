# LOT 0 — Audit : Mise en 2 colonnes du bloc "Résumé financier"

Audit en lecture seule. Aucune modification de code, de vue ou de données.

## 1. Extrait XML natif actuel

`microfinance_loan_management/views/microfinance_loan_views.xml:210-249` :

```xml
<group string="Résumé financier">
    <field name="principal_total" readonly="1"/>
    <field name="interest_total" readonly="1"/>
    <field name="penalty_total" readonly="1"/>
    <field name="paid_total" readonly="1"/>
    <field name="balance_total" readonly="1"/>
    <field name="overdue_amount" readonly="1"/>
    <field name="overdue_installment_count" readonly="1"/>
    <label for="internal_score" string="Score"/>
    <div class="o_row">
        <field name="internal_score" widget="progressbar" readonly="1" nolabel="1"/>
        <button name="action_recompute_risk" string="Recalculer le score" type="object" class="btn-secondary btn-sm" icon="fa-refresh"/>
    </div>
    <field name="provision_amount" readonly="1"/>
    <field name="provision_posted_amount" readonly="1"/>
    <field name="guarantee_total" readonly="1"/>
    <field name="fee_amount_due" readonly="1"/>
    <field name="fee_payment_state" widget="badge" readonly="1"
           decoration-success="fee_payment_state == 'paid'"
           decoration-danger="fee_payment_state == 'unpaid'"
           decoration-muted="fee_payment_state == 'none'"
           invisible="fee_payment_state == 'none'"/>
    <field name="fee_paid" invisible="1"/>
    <field name="fee_receivable_move_id" readonly="1" invisible="not fee_receivable_move_id"/>
    <field name="fee_move_id" readonly="1"/>
    <field name="net_disbursed_amount" readonly="1"/>
    <field name="bypass_cash_balance" invisible="state != 'approved'"/>
</group>
```

C'est **un seul `<group string="Résumé financier">`, sans sous-groupe** → rendu Odoo natif en
**une colonne unique** de lignes label/valeur (chaque `<field>` occupe une ligne pleine
largeur), pas en grille 2 colonnes de champs côte à côte.

## 2. Points d'héritage qui injectent des champs dans ce groupe

Recherche exhaustive de toute vue héritant de `view_microfinance_loan_form`
(4 modules présents dans le dépôt : `microfinance_loan_management`,
`microfinance_savings_management`, `microfinance_mowgli_assistant`,
`microfinance_data_reset_wizard`) : **seuls 2 fichiers** touchent ce formulaire,
`microfinance_mowgli_assistant` et `microfinance_data_reset_wizard` n'y touchent pas du tout.

### a. `microfinance_savings_management/views/microfinance_loan_views_inherit.xml`

```xml
<field name="co_borrower_id" position="after">
    <field name="savings_requirement_type" invisible="1"/>
    <field name="savings_account_id"/>
</field>
<field name="fee_move_id" position="after">
    <field name="savings_target_amount" invisible="savings_requirement_type != 'target_during_loan'" readonly="1"/>
    <field name="savings_target_reached" invisible="savings_requirement_type != 'target_during_loan'" readonly="1"/>
    <field name="guarantee_savings_required" invisible="not guarantee_savings_required" readonly="1"/>
    <field name="guarantee_savings_balance" invisible="not guarantee_savings_required" readonly="1"/>
    <field name="guarantee_savings_verified" invisible="not guarantee_savings_required" readonly="1"/>
</field>
```

**Point important n°1** : `co_borrower_id` n'est **pas** dans "Résumé financier" — il est
dans le groupe **"Dossier"** (`microfinance_loan_views.xml:185`). Donc `savings_requirement_type`
et **`savings_account_id` (le champ "Compte épargne") ne sont pas dans le bloc "Résumé
financier" aujourd'hui** — ils sont dans "Dossier". Le prompt de ce lot ne les mentionne pas
dans la liste des champs à répartir gauche/droite ; ils resteraient donc dans "Dossier",
inchangés, ce qui est cohérent (mais à confirmer explicitement avec Micka puisque
conceptuellement "Compte épargne" est plus proche du thème "épargne" que "Dossier").

**Point important n°2 — ordre final réel après fusion des héritages** : l'injection se fait
`position="after"` sur `fee_move_id`, qui précède `net_disbursed_amount` dans le groupe
natif. L'**ordre affiché réellement à l'écran** (après application de l'héritage) est donc :

```
... fee_receivable_move_id, fee_move_id,
    savings_target_amount, savings_target_reached,
    guarantee_savings_required, guarantee_savings_balance, guarantee_savings_verified,
    net_disbursed_amount, bypass_cash_balance
```

Les champs épargne/garanties sont **intercalés entre `fee_move_id` et `net_disbursed_amount`**,
pas ajoutés à la fin du bloc. Une lecture séparée des deux fichiers XML donnerait l'impression
que les champs épargne suivent tout le bloc natif ; ce n'est pas le cas.

### b. `microfinance_loan_management/views/microfinance_scoring_views.xml` — conflit structurel à anticiper

```xml
<!-- ancestor::group[1] (et non parent::group) : internal_score peut être
     imbriqué dans un <div class="o_row"> à l'intérieur du groupe "Résumé
     financier" (bouton "Recalculer le score" sur la même ligne) - parent::group
     ne le localiserait alors plus. -->
<xpath expr="//field[@name='internal_score']/ancestor::group[1]" position="after">
    <group string="Scoring interne">
        <field name="scoring_profile_id"/>
        <field name="risk_level" widget="badge" readonly="1" .../>
        <field name="scoring_decision" widget="badge" readonly="1" .../>
    </group>
</xpath>
```

**C'est le point le plus important de cet audit.** Cet xpath cible
`ancestor::group[1]` du champ `internal_score` — c'est-à-dire, **avec la structure XML
actuelle (un seul `<group string="Résumé financier">`), le groupe "Résumé financier"
lui-même**. Le groupe "Scoring interne" est donc aujourd'hui inséré comme **frère, juste
après tout le bloc "Résumé financier"** (empilé en dessous, pleine largeur).

**Si le Lot 1 restructure "Résumé financier" en `<group><group string="Gauche">...</group><group string="Droite">...</group></group>`**
(le pattern 2-colonnes, §3 ci-dessous) et que `internal_score` reste dans la colonne
"Gauche" (ce qui est demandé — le Score fait partie de la liste "gauche" du prompt), alors
`ancestor::group[1]` de `internal_score` **ne désignera plus le groupe englobant, mais le
sous-groupe "Gauche" lui-même**. Conséquence : "Scoring interne" serait inséré comme
**3ᵉ enfant du groupe englobant, entre la colonne "Gauche" et la colonne "Droite"** — un
groupe `<group>` sans `col=` explicite empile ses enfants 2 par ligne par défaut, donc ce 3ᵉ
enfant retomberait seul sur une nouvelle ligne, et la colonne "Droite" (épargne/garanties)
serait poussée en dessous au lieu de rester à côté de "Gauche". **Le rendu visuel serait
cassé** : au lieu de 2 colonnes propres, on obtiendrait Gauche + Scoring interne sur une
ligne, puis Droite toute seule sur la ligne suivante (ou un chevauchement selon le moteur de
grille exact d'Odoo 17 — dans tous les cas, pas le résultat 2-colonnes voulu).

**Ce conflit doit être traité dans le même Lot 1**, pas laissé de côté : il faudra soit
donner un `name` explicite au `<group>` englobant (ex.
`<group name="resume_financier_wrapper">`) et changer l'xpath de
`microfinance_scoring_views.xml` pour cibler
`//group[@name='resume_financier_wrapper']` en position `after` (ancrage stable, indépendant
de la position d'`internal_score`), soit repenser où "Scoring interne" doit apparaître dans
la nouvelle disposition (ex. explicitement comme 3ᵉ bloc sous les 2 colonnes, avec un
`<group>` englobant dédié à `col="1"` pour éviter le repli à 2 par ligne). **Décision à
prendre par Micka avant le Lot 1** : "Scoring interne" doit-il rester sous les 2 colonnes
(pleine largeur), ou rejoindre l'une des 2 colonnes (probablement "Gauche", à côté du champ
Score) ?

## 3. Pattern 2-colonnes déjà utilisé dans le module — à répliquer à l'identique

`microfinance_loan_views.xml:158-209`, juste au-dessus de "Résumé financier" — exactement le
même écran :

```xml
<group>
    <group string="Dossier">
        <field name="partner_id"/>
        ... (10 champs)
    </group>
    <group string="Suivi">
        <field name="application_date"/>
        ... (8 champs)
    </group>
</group>
```

Un `<group>` englobant **sans `string`** contenant deux `<group string="...">` enfants =
rendu natif Odoo 17 en 2 colonnes côte à côte, chaque sous-groupe gardant son propre
empilement vertical de lignes label/valeur. **C'est exactement ce pattern qu'il faut
reproduire pour "Résumé financier"** :

```xml
<group>
    <group string="Résumé financier — Crédit"><!-- gauche --> ... </group>
    <group string="Résumé financier — Épargne / Garanties"><!-- droite --> ... </group>
</group>
```

(noms de `string` à valider avec Micka — proposés ici pour illustrer la structure, pas une
recommandation arrêtée).

## 4. Liste exhaustive des champs, origine et attrs actuels

| # | Champ | Origine | Attrs actuels | Colonne demandée |
|---|-------|---------|---------------|-------------------|
| 1 | `principal_total` | natif | `readonly="1"` | Gauche |
| 2 | `interest_total` | natif | `readonly="1"` | Gauche |
| 3 | `penalty_total` | natif | `readonly="1"` | Gauche |
| 4 | `paid_total` | natif | `readonly="1"` | Gauche |
| 5 | `balance_total` | natif | `readonly="1"` | Gauche |
| 6 | `overdue_amount` | natif | `readonly="1"` | Gauche |
| 7 | `overdue_installment_count` | natif | `readonly="1"` | Gauche |
| 8 | `internal_score` (+ label + bouton `action_recompute_risk`) | natif | `widget="progressbar"`, `readonly="1"`, `nolabel="1"`, dans `<div class="o_row">` | Gauche |
| 9 | `provision_amount` | natif | `readonly="1"` | Gauche |
| 10 | `provision_posted_amount` | natif | `readonly="1"` | Gauche |
| 11 | `fee_amount_due` | natif | `readonly="1"` | Gauche |
| 12 | `fee_payment_state` | natif | `widget="badge"`, `readonly="1"`, décorations, `invisible="fee_payment_state == 'none'"` | Gauche |
| 13 | `fee_paid` | natif | `invisible="1"` (technique, condition du bouton header) | Gauche (peu importe, invisible) |
| 14 | `fee_receivable_move_id` | natif | `readonly="1"`, `invisible="not fee_receivable_move_id"` | Gauche |
| 15 | `fee_move_id` | natif | `readonly="1"` | Gauche |
| 16 | `net_disbursed_amount` | natif | `readonly="1"` | Gauche |
| 17 | `bypass_cash_balance` | natif | `invisible="state != 'approved'"` | **Non listé dans le prompt — à confirmer (probablement Gauche par défaut, sans rapport avec l'épargne)** |
| 18 | `guarantee_total` | natif | `readonly="1"` | Droite |
| 19 | `savings_target_amount` | `microfinance_savings_management` | `invisible="savings_requirement_type != 'target_during_loan'"`, `readonly="1"` | Droite |
| 20 | `savings_target_reached` | `microfinance_savings_management` | idem | Droite |
| 21 | `savings_target_booked_amount` *(nouveau, Lot 1 du chantier précédent, pas encore codé)* | `microfinance_savings_management` | idem (proposé) | Droite |
| 22 | `savings_target_deadline` *(nouveau, pas encore codé)* | `microfinance_savings_management` | proposé sans `invisible` conditionné à confirmer | Droite |
| 23 | `guarantee_savings_required` | `microfinance_savings_management` | `invisible="not guarantee_savings_required"`, `readonly="1"` | Droite |
| 24 | `guarantee_savings_balance` | `microfinance_savings_management` | idem | Droite |
| 25 | `guarantee_savings_verified` | `microfinance_savings_management` | idem | Droite |

**Champs #21 et #22 ne sont pas encore dans le code** (chantier
`docs_dev/epargne_cible_progressive/`, Lot 0 validé mais Lot 1 pas encore généré au moment de
cet audit) — la restructuration en 2 colonnes de ce lot-ci devra soit attendre leur
implémentation, soit être conçue pour les accueillir facilement une fois codés (recommandé :
faire ce lot-ci en connaissant déjà leur nom technique proposé, pour ne pas avoir à retoucher
la vue deux fois).

**Champ non classé (#17, `bypass_cash_balance`)** : absent des deux listes gauche/droite du
prompt. Point à trancher avec Micka avant le Lot 1 — actuellement, faute d'indication
contraire, la recommandation par défaut est de le laisser à Gauche (c'est un contournement du
contrôle de caisse au décaissement, thème "crédit", sans rapport avec l'épargne).

## 5. Stratégie de `xpath` recommandée

**Un seul `xpath` de restructuration suffit côté `microfinance_loan_management`** : remplacer
tout le contenu du `<group string="Résumé financier">` natif par la nouvelle structure à 2
sous-groupes (édition directe du fichier natif, pas un héritage — c'est le module propriétaire
du bloc). Donner un `name` stable au `<group>` englobant à cette occasion (ex.
`name="resume_financier_wrapper"`), pour que d'autres modules puissent s'y ancrer sans dépendre
de la position d'un champ interne (leçon du conflit §2.b).

**Côté `microfinance_savings_management`** : les deux xpaths existants
(`co_borrower_id position="after"` et `fee_move_id position="after"`) **continueront de
fonctionner sans modification** tant que `fee_move_id` reste un enfant direct du sous-groupe
"Gauche" (puisque les champs épargne visés vont dans "Droite", il faudra en réalité **changer
leur point d'ancrage** : les rattacher à un champ qui sera désormais dans le sous-groupe
"Droite", ex. `<field name="guarantee_total" position="after">`, plutôt que `fee_move_id` qui
restera à Gauche). **Ne pas oublier ce changement** — sans lui, les champs épargne
resteraient injectés dans la colonne Gauche (juste après `fee_move_id`), à l'opposé de ce qui
est demandé.

**Côté `microfinance_scoring_views.xml`** : xpath à corriger dans ce même Lot 1, comme
détaillé au §2.b — remplacer `//field[@name='internal_score']/ancestor::group[1]` par un
ancrage stable sur le nouveau `name="resume_financier_wrapper"` (ou toute autre solution que
Micka choisira pour le placement de "Scoring interne").

**Aucun conflit entre les 2 modules qui injectent** (`savings_management` et
`scoring_views.xml`, natif) : ils ciblent des points d'ancrage différents et n'interagissent
pas entre eux directement — seul le natif change de forme, donc seuls les 2 fichiers héritant
doivent être ajustés en conséquence, chacun pour sa propre raison (déplacement de colonne pour
l'un, ancrage structurel cassé pour l'autre).

## Synthèse pour le Lot 1

1. Restructurer le `<group string="Résumé financier">` natif en
   `<group name="resume_financier_wrapper"><group string="...">Gauche</group><group string="...">Droite</group></group>`.
2. Répartir les 17 champs natifs selon le tableau §4 (statuer sur `bypass_cash_balance`).
3. Mettre à jour les 2 xpaths de `microfinance_savings_management/views/microfinance_loan_views_inherit.xml`
   pour ancrer les 5 (bientôt 7, une fois `savings_target_booked_amount`/`savings_target_deadline`
   codés) champs épargne/garanties sur un champ de la colonne Droite plutôt que sur `fee_move_id`.
4. Corriger l'xpath de `microfinance_scoring_views.xml` pour ne plus dépendre de
   `ancestor::group[1]` d'`internal_score` — ancrer sur `resume_financier_wrapper` (ou décision
   Micka sur le placement de "Scoring interne").
5. Vérifier visuellement le rendu (aucun champ dupliqué/orphelin, alignement correct sur les 2
   colonnes, `co_borrower_id`/`savings_account_id` restant dans "Dossier" comme aujourd'hui,
   sauf décision contraire de Micka).

Aucune modification de code effectuée dans ce lot. Le Lot 1 sera généré après validation de ce
rapport par Micka (en particulier : placement de `bypass_cash_balance`, placement de "Scoring
interne", et confirmation que `savings_account_id` reste dans "Dossier").
