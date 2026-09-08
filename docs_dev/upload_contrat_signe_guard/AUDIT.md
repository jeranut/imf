# LOT 0 — Audit : bouton "contrat signé" et guard d'activation/décaissement

Audit en lecture seule. Aucune modification de code. Base réelle interrogée : `SEFOR`
(IS/001076 = `microfinance.loan` id 2327).

## 1. Le champ "Contrat signé"

`microfinance_loan_management/models/microfinance_loan.py:260-269`

```python
signed_contract = fields.Binary(
    string='Contrat signé', attachment=True, copy=False,
    help="...",
)
signed_contract_filename = fields.Char(string='Nom du fichier contrat signé', copy=False)
```

- Type : `Binary` avec `attachment=True` → stocké comme `ir.attachment` avec
  `res_field='signed_contract'`, `res_model='microfinance.loan'`, `res_id=<id du crédit>`
  (pas de colonne dédiée dans `microfinance_loan`, donc invisible à une requête SQL directe
  sur la table — normal pour ce type de champ, pas un signe d'anomalie).
- Pas de Many2one vers `ir.attachment`, pas de champ alternatif : un seul champ candidat.

Vue (`views/microfinance_loan_views.xml:164-165`) :

```xml
<field name="signed_contract_filename" invisible="1"/>
<field name="signed_contract" widget="binary" filename="signed_contract_filename"
       invisible="state not in ('approved', 'active', 'closed', 'defaulted', 'written_off')"/>
```

- **Aucun `groups=` sur ce champ** : visible pour tout utilisateur ayant accès au formulaire,
  quel que soit son groupe.
- **Aucun `readonly=`** sur ce champ à l'état `approved` : le widget `binary` (bouton "Charger
  votre fichier") est bien actif, pas seulement affiché en lecture.
- Condition d'affichage : visible dès `approved` et dans tous les états suivants
  (`active`, `closed`, `defaulted`, `written_off`) — donc bien visible sur IS/001076
  (état actuel : `approved`). Pas de condition cachée liée à la résolution d'écran ou à un
  autre widget : une seule ligne `invisible=` porte sur `state`, rien d'autre.

**Conclusion point 1/5** : le champ et son bouton d'upload sont réellement présents et
actifs dans l'état où se trouve IS/001076. L'hypothèse (a) "bouton réellement absent" est
**infirmée** pour ce dossier précis.

## 2. Le guard d'activation

`microfinance_loan_management/models/microfinance_loan.py:1868-1890`, méthode
`action_disburse()` (appelée par le bouton `Activer / Décaisser`,
`views/microfinance_loan_views.xml:73`) :

```python
def action_disburse(self):
    for loan in self:
        if loan.state != 'approved':
            raise UserError(_('Le crédit doit être approuvé avant décaissement.'))
        if not loan.signed_contract:
            raise UserError(_(
                "Le contrat signé doit être téléversé avant l'activation du crédit."
            ))
        ...
```

Le guard teste littéralement `loan.signed_contract` — **exactement le même champ** que
celui affiché et rempli par le widget binaire de la vue.

**Conclusion point 2-3** : **pas de mismatch de champ**. Le champ vérifié par le guard est
rigoureusement le même que celui exposé par le bouton d'upload visible en vue. L'hypothèse
d'un guard qui pointerait vers un autre champ que celui réellement rempli est **infirmée**.

## 3. État réel de IS/001076 en base (SEFOR, id 2327)

```
name       | state    | write_date
IS/001076  | approved | 2026-09-04 02:25:29
```

Recherche de toute pièce jointe liée à ce dossier (`ir_attachment.res_model='microfinance.loan'
AND res_id=2327`, y compris celles seulement rattachées au chatter via
`message_attachment_rel`, au cas où une copie existerait sans lien direct au champ) :

| id   | name                                          | res_field         | create_date          |
|------|-----------------------------------------------|-------------------|----------------------|
| 5578 | Calendrier de remboursement - IS/001076.pdf   | *(vide)*          | 2026-08-25 06:09     |
| 6065 | Calendrier de remboursement - IS/001076.pdf   | *(vide)*          | 2026-08-25 12:06     |
| 8503 | Contrat de crédit - IS/001076.pdf             | *(vide)*          | 2026-09-02 19:40     |

**Aucune pièce jointe avec `res_field='signed_contract'`.** Le champ `signed_contract` est
donc **réellement vide** sur IS/001076 — ce n'est pas un problème d'affichage ou de guard qui
"ne verrait pas" un fichier pourtant présent : le fichier n'a jamais été persisté sur ce
champ.

Le fil de communication (`mail_message`) confirme : le seul message relatif à un "contrat"
sur ce dossier est **"Contrat de crédit généré."** le 2026-09-02 19:40:46, produit par le
bouton distinct `action_print_contrat_to_chatter` ("Imprimer le contrat",
`microfinance_loan.py:2175` et suivants — poste un PDF généré depuis le rapport, indépendant
du champ `signed_contract`). Il n'existe **aucun** message
**"Contrat signé téléversé."** (celui que poste `_post_signed_contract_to_chatter`,
déclenché uniquement par `write()` quand `vals.get('signed_contract')` est vrai,
`microfinance_loan.py:393-397`) — confirmation directe que le widget d'upload n'a jamais été
utilisé avec succès sur ce dossier.

**Hypothèse la plus probable** : confusion entre deux boutons distincts qui portent des noms
très proches et produisent des PDF au nom quasi identique :

- **"Imprimer le contrat"** (`action_print_contrat_to_chatter`, bouton vert
  `btn-cefor-print`, dans le header, visible à l'état `approved` pour
  `group_microfinance_user`) : génère le contrat *vierge/à signer* depuis un rapport QWeb et
  le poste dans le chatter sous le nom "Contrat de crédit - IS/001076.pdf". **N'écrit jamais
  le champ `signed_contract`.**
- **"Charger votre fichier"** (widget `binary` sur le champ `signed_contract`, dans le
  panneau SUIVI) : c'est l'action qui doit recevoir la *version signée scannée* et qui seule
  satisfait le guard de `action_disburse()`.

Sur IS/001076, seul le premier bouton a été utilisé (le 2026-09-02) — le contrat a été
*imprimé* pour signature, mais le fichier signé n'a ensuite jamais été re-téléversé via le
second bouton. Le clic sur "Activer / Décaisser" bloque donc **à juste titre** selon la
logique actuelle : le champ est bien vide.

## 4. Piste "sauvegarde différée du widget binaire" (hypothèse b)

`action_disburse` est un bouton `type="object"` standard (pas de `special="cancel"`, pas
d'attribut désactivant la sauvegarde automatique). Le comportement standard du client web
Odoo 17 (`FormController`) sauvegarde l'enregistrement modifié avant d'exécuter la méthode
serveur d'un bouton `type="object"`. Aucune surcharge de ce comportement n'a été trouvée
dans `static/src/js/microfinance_loan_form_view.js` : le contrôleur personnalisé
(`MicrofinanceLoanFormController`) ne redéfinit que `afterExecuteActionButton` (pour
rafraîchir le chatter après certains boutons d'impression) — **pas**
`beforeExecuteActionButton` ni la logique de sauvegarde elle-même.

Il n'existe donc pas, dans le code, de mécanisme qui empêcherait la persistance du fichier
téléversé avant l'appel du guard. Combiné à l'absence totale de toute trace d'upload
(aucune pièce jointe `res_field='signed_contract'`, aucun message "Contrat signé
téléversé.") sur IS/001076, cette piste (b) n'est **pas corroborée** par les faits observés
sur ce dossier : rien n'indique qu'un upload ait été tenté et perdu — tout indique qu'aucun
upload n'a eu lieu sur ce champ.

Cette piste ne peut néanmoins pas être totalement exclue en général (elle resterait
plausible sur un dossier où l'utilisateur upload puis clique immédiatement sans que le
formulaire ait le temps de confirmer la sauvegarde, ex. double-clic rapide ou coupure
réseau) — mais ce n'est pas ce qui s'est produit sur IS/001076.

## 5. Visibilité conditionnelle du bouton d'activation (constat annexe)

Le bouton **"Activer / Décaisser"** lui-même (`action_disburse`,
`views/microfinance_loan_views.xml:73`) porte
`groups="microfinance_loan_management.group_microfinance_finance"` : il n'est visible que
pour les utilisateurs de ce groupe. Ce n'est pas la cause du symptôme rapporté (l'erreur a
bien été déclenchée, donc le bouton était visible et cliquable pour l'utilisateur
concerné), mais c'est un point de vigilance distinct si un autre utilisateur (hors groupe
finance) rapporte un jour ne "voir aucun bouton d'activation" — ce serait alors une
restriction de groupe normale, pas un bug.

Le champ `signed_contract` et son widget d'upload n'ont, eux, **aucune** restriction de
groupe : ils sont visibles par tout profil ayant accès au formulaire dès l'état `approved`.

## Synthèse

| Question de l'audit                                            | Constat |
|------------------------------------------------------------------|---------|
| Mismatch entre champ affiché et champ vérifié par le guard ?     | **Non** — même champ (`signed_contract`) des deux côtés. |
| Bouton d'upload réellement absent dans l'état observé ?          | **Non** — présent, actif, aucune condition `groups`/`readonly` ne le masque à l'état `approved`. |
| Champ vide en base sur IS/001076 ?                                | **Oui**, confirmé (aucune pièce jointe `res_field='signed_contract'`, aucun message de confirmation d'upload). |
| Cause la plus probable                                            | **Confusion utilisateur** entre "Imprimer le contrat" (génère le PDF à signer, ne remplit pas `signed_contract`) et "Charger votre fichier" (upload réel, seul à satisfaire le guard). Aucune preuve d'un problème de sauvegarde différée du widget sur ce dossier. |

## Proposition pour le Lot 1 (à confirmer avant implémentation)

Puisqu'il n'y a ni bug de champ ni bug de guard, le Lot 1 devrait viser l'**ergonomie /
clarté**, pas une correction de logique :

1. Renforcer visuellement la distinction entre les deux boutons pour éviter la confusion
   observée, par exemple :
   - Reformuler le libellé "Imprimer le contrat" en quelque chose qui exclut toute ambiguïté
     avec un archivage définitif (ex. "Imprimer le contrat à signer"), et/ou
   - Ajouter un texte d'aide (`help=`) ou un placeholder visible à côté du widget
     `signed_contract` du type "Téléversez ici la version signée scannée — le simple aperçu
     imprimé ne suffit pas à activer le crédit."
2. Envisager un message d'erreur plus explicite dans `action_disburse()` qui rappelle *où*
   téléverser (ex. mentionner le nom du champ / la section "Suivi") plutôt que le message
   générique actuel, si le retour terrain confirme que l'utilisateur ne sait pas où agir une
   fois l'erreur affichée.
3. Si le risque de clic prématuré après upload (piste b) est jugé possible en usage réel
   malgré l'absence de preuve sur ce dossier, un garde-fou supplémentaire pourrait forcer un
   `save()` explicite du formulaire avant d'autoriser l'exécution de `action_disburse`
   (`beforeExecuteActionButton` dans `MicrofinanceLoanFormController`) — mais ce n'est pas
   nécessaire pour corriger le symptôme observé sur IS/001076, qui s'explique entièrement
   par l'absence d'upload.

Aucune modification de code n'a été faite dans ce lot.
