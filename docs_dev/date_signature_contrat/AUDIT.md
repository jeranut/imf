# LOT 0 — Audit : Date de signature du contrat

Audit en lecture seule. Aucune modification de code, de vue ou de données. Objectif :
préparer le Lot 1 (nouveau champ `contract_signature_date`, wizard de confirmation à
l'upload du contrat signé, verrouillage définitif fichier + date).

## 1. Champ "Contrat signé" actuel

`microfinance_loan_management/models/microfinance_loan.py:260-269`

```python
signed_contract = fields.Binary(
    string='Contrat signé', attachment=True, copy=False,
    help="Contrat de crédit signé par l'emprunteur. Se téléverse une fois le crédit "
         "approuvé et constitue un prérequis à l'activation : action_disburse() refuse "
         "le décaissement tant que ce champ est vide. À l'enregistrement, le fichier est "
         "aussi posté dans le fil de communication du dossier. Sa pièce jointe ne peut "
         "plus être supprimée depuis le chatter (cf. ir.attachment.unlink) - un "
         "remplacement par une nouvelle version reste possible en re-téléversant.",
)
signed_contract_filename = fields.Char(string='Nom du fichier contrat signé', copy=False)
```

- **Modèle** : `microfinance.loan`.
- **Type** : `fields.Binary(attachment=True)` — pas de Many2one vers `ir.attachment`, pas de
  champ générique. Le fichier est stocké comme un `ir.attachment` avec `res_model=
  'microfinance.loan'`, `res_field='signed_contract'`, `res_id=<id du crédit>` (mécanisme
  standard Odoo pour un champ `Binary(attachment=True)` — pas de colonne dédiée dans la
  table `microfinance_loan`, donc invisible à une requête SQL directe sur cette table, il
  faut interroger `ir_attachment`).
- **Fichier Python** : `models/microfinance_loan.py`.
- **Fichier vue XML** : `views/microfinance_loan_views.xml` (le champ apparaît à **deux
  endroits distincts** dans le même formulaire — voir point 2).
- **Aucun champ "date de signature" n'existe aujourd'hui** sur `microfinance.loan` : le
  futur `contract_signature_date` est entièrement à créer, aucun champ proche à réutiliser.

## 2. Widget de la vue — deux occurrences

Le champ `signed_contract` apparaît **deux fois** dans `view_microfinance_loan_form`, avec
deux widgets différents, ajoutés lors d'un lot précédent (`docs_dev/
upload_contrat_signe_guard/AUDIT.md`) pour résoudre une confusion utilisateur entre
"Imprimer le contrat" (génère le PDF à signer, n'écrit jamais ce champ) et l'upload réel.

**A. Dans le `<header>`** (bouton vert, à côté de "Imprimer le contrat" /
"Activer / Décaisser") — `views/microfinance_loan_views.xml:133-136` :

```xml
<field name="signed_contract_filename" invisible="1"/>
<field name="signed_contract" widget="signed_contract_upload" filename="signed_contract_filename"
       class="o_upload_contrat_signe_header"
       invisible="state not in ('approved', 'active', 'closed', 'defaulted', 'written_off')"/>
```

`widget="signed_contract_upload"` est un widget OWL custom (`static/src/js/
signed_contract_upload_field.js` + `static/src/xml/signed_contract_upload_field.xml`) : un
simple habillage visuel du `BinaryField` standard d'Odoo (texte du bouton et classe CSS
changés — "Charger le contrat signé" au lieu de "Charger votre fichier", couleur verte
`btn-cefor-print`), **aucune différence de comportement** avec le widget natif. C'est ce
bouton qui correspond au « bouton "Charger votre fichier" » du screenshot mentionné dans le
prompt, et c'est lui qui devra être remplacé par le bouton ouvrant le wizard.

**B. Dans le panneau SUIVI** (widget natif, pour consultation/téléchargement) —
`views/microfinance_loan_views.xml:209-210` :

```xml
<field name="signed_contract_filename" invisible="1"/>
<field name="signed_contract" widget="binary" filename="signed_contract_filename" invisible="state not in ('approved', 'active', 'closed', 'defaulted', 'written_off')"/>
```

Cette seconde occurrence utilise le widget `binary` **natif** Odoo (pas le widget custom du
header) — elle aussi permet un upload/remplacement direct, avec exactement la même absence
de protection que celle décrite au point 4. **Point d'attention pour le Lot 1** : remplacer
seulement le bouton du header par le wizard ne suffira pas à garantir le verrouillage si
cette seconde occurrence (panneau SUIVI) continue d'exposer un widget d'upload actif — il
faudra soit la retirer, soit la rendre `readonly` inconditionnellement (elle ne doit plus
servir qu'à la consultation/téléchargement une fois le Lot 1 en place).

Aucun label avec point d'interrogation `?` (`help=`) séparé n'est présent dans l'arch : le
`?` visible dans le screenshot vient du tooltip standard Odoo généré automatiquement à
partir du `help=` du champ (visible au survol du label), rien de spécifique à ajouter dans
la vue pour ça.

## 3. Restrictions existantes sur le champ

- **Aucun `groups=`** sur le champ `signed_contract` lui-même, dans aucune des deux
  occurrences — tout utilisateur ayant accès en écriture au formulaire (cf. point 7) peut
  téléverser/remplacer, quel que soit son groupe métier.
- **Aucun `@api.constrains`** ne porte sur `signed_contract` (recherche `@api.constrains`
  dans tout `microfinance_loan.py` : 3 occurrences, aucune ne touche ce champ — lignes 485,
  496, 1756, toutes sur d'autres champs).
- **Aucun override de `write()`** ne restreint spécifiquement ce champ. Le seul override de
  `write()` présent sur le modèle (`_check_locked_dossier_fields()`, point 8 ci-dessous) ne
  couvre que `{'loan_amount', 'term', 'product_id', 'interest_rate', 'installment_amount'}`
  — `signed_contract` n'y figure pas.
- **Readonly conditionnel** : uniquement via `invisible=` selon `state` (le champ est
  simplement absent de la vue hors des états `approved/active/closed/defaulted/
  written_off` — pas de `readonly=` combiné avec un état particulier à l'intérieur de cette
  plage : tant que le champ est visible, il est toujours modifiable).

## 4. Suppression/modification actuelle — confirmation de l'absence de protection

`models/ir_attachment.py` (override de `ir.attachment.unlink()`) :

```python
def unlink(self):
    if not self.env.context.get('bypass_signed_contract_protection'):
        protected = self.filtered(
            lambda att: att.res_model == 'microfinance.loan' and att.res_field == 'signed_contract'
        )
        if protected:
            raise UserError(_(
                "Le contrat signé ne peut pas être supprimé. Pour le corriger, "
                "téléversez une nouvelle version à sa place."
            ))
    return super().unlink()
```

**Confirmé : aucune protection contre la modification.** Cette protection bloque
uniquement la **suppression pure** (bouton "x" du widget binaire, qui écrit
`{'signed_contract': False}` et déclenche un `unlink()` sur la pièce jointe existante) —
le commentaire du code le dit explicitement : *"Un remplacement du fichier passe par
`write({'datas': ...})` sur la pièce jointe existante (pas par unlink), il reste donc
possible."* En clair, aujourd'hui : **un utilisateur peut re-téléverser un nouveau fichier
à la place de l'ancien à tout moment**, tant que le champ est visible dans l'état courant du
dossier (approved/active/closed/defaulted/written_off) — aucun mécanisme n'empêche
d'écraser un contrat déjà signé par un autre fichier. Aucune date de signature n'existe pour
tracer *quand* le fichier actuellement en place a été déposé.

## 5. États du workflow où l'upload est actuellement possible

`state not in ('approved', 'active', 'closed', 'defaulted', 'written_off')` détermine
l'invisibilité — donc le champ (et son upload) est actionnable dans **tous** ces états :
`approved`, `active`, `closed`, `defaulted`, `written_off`. Ce n'est **pas limité à
"Approuvé"** comme le supposait le prompt — c'est délibéré (commentaire du code : *"Reste
visible ensuite pour consultation"*), mais cela signifie concrètement qu'un contrat peut
être **remplacé même sur un dossier clôturé, en défaut ou radié**, ce qui est probablement
l'un des scénarios que le verrouillage définitif du Lot 1 doit précisément empêcher.

## 6. Wizards `TransientModel` existants — pattern de référence trouvé

4 wizards dans `microfinance_loan_management/wizard/` :
`microfinance_loan_payment_wizard`, `microfinance_loan_reschedule_wizard`,
`microfinance_loan_writeoff_wizard`, `microfinance_loan_payment_cancel_wizard`.

**Meilleur candidat de référence : `microfinance_loan_writeoff_wizard`** — structure quasi
identique à ce qui est demandé (Many2one vers le crédit, **date pré-remplie et éditable via
`fields.Date.context_today`**, motif requis, un seul bouton de confirmation qui valide puis
appelle une méthode du modèle) :

```python
# wizard/microfinance_loan_writeoff_wizard.py
class MicrofinanceLoanWriteoffWizard(models.TransientModel):
    _name = 'microfinance.loan.writeoff.wizard'
    _description = 'Assistant radiation crédit'

    loan_id = fields.Many2one('microfinance.loan', string='Crédit', required=True)
    currency_id = fields.Many2one(related='loan_id.currency_id', readonly=True)
    balance_total = fields.Monetary(related='loan_id.balance_total', readonly=True)
    write_off_date = fields.Date(string='Date de radiation', default=fields.Date.context_today, required=True)
    reason = fields.Text(string='Motif', required=True)

    def action_confirm(self):
        self.ensure_one()
        if not self.reason or not self.reason.strip():
            raise UserError(_('Le motif de radiation est obligatoire.'))
        move = self.loan_id.action_confirm_write_off(self.reason, self.write_off_date)
        return {'type': 'ir.actions.act_window', 'res_model': 'account.move', 'res_id': move.id, 'view_mode': 'form'}
```

```xml
<!-- wizard/microfinance_loan_writeoff_wizard_views.xml -->
<form string="Radiation">
    <group>
        <field name="loan_id" readonly="1"/>
        <field name="currency_id" invisible="1"/>
        <field name="balance_total" readonly="1"/>
        <field name="write_off_date"/>
        <field name="reason"/>
    </group>
    <footer>
        <button name="action_confirm" string="Radier" type="object" class="btn-primary"/>
        <button string="Annuler" class="btn-secondary" special="cancel"/>
    </footer>
</form>
```

`microfinance_loan_payment_cancel_wizard` suit exactement le même squelette (motif requis +
`action_confirm` appelant une méthode du modèle + `<footer>` Confirmer/Annuler). C'est la
convention constante du projet pour toute action nécessitant une confirmation explicite —
**à répliquer telle quelle** pour le wizard "contrat signé" : `loan_id` (Many2one, readonly),
un champ binaire pour l'upload, `contract_signature_date` (Date, `default=fields.Date.
context_today`, éditable), et un `action_confirm()` qui écrit les deux valeurs sur le crédit
puis retourne (par ex.) `{'type': 'ir.actions.act_window_close'}` comme le fait
`payment_cancel_wizard`.

## 7. Groupes de sécurité — accès en écriture

`security/ir.model.access.csv` (droits sur le modèle `microfinance.loan`, colonnes
read/write/create/unlink) :

| Groupe | Nom affiché | write |
|---|---|---|
| `group_microfinance_user` | Agent crédit | ✅ |
| `group_microfinance_manager` | Manager crédit | ✅ (+ unlink) |
| `group_microfinance_finance` | Finance microfinance | ✅ |
| `group_microfinance_auditor` | Auditeur microfinance | ❌ (lecture seule) |
| `group_microfinance_comptable` | Comptable | ❌ (lecture seule) |
| `group_microfinance_cashier` | Caissier | ❌ (lecture seule) |
| `group_microfinance_credit_committee` | Comité de crédit | ❌ (lecture seule) |

Trois groupes (**Agent crédit, Manager crédit, Finance microfinance**) ont donc
aujourd'hui, via le seul droit `write` générique sur le modèle, la possibilité de
téléverser/remplacer le contrat signé — aucune restriction de groupe supplémentaire
spécifique à ce champ ou à ce bouton (contrairement par exemple à "Activer / Décaisser",
qui porte `groups="microfinance_loan_management.group_microfinance_finance"`, ou à
"Imprimer le contrat", qui porte `groups="...group_microfinance_user"`).

## 8. Pattern de champ verrouillé après confirmation — à répliquer

`models/microfinance_loan.py:334-390`, mécanisme `_LOCKED_DOSSIER_FIELDS` /
`_check_locked_dossier_fields()` (déjà utilisé pour geler `loan_amount`, `term`,
`product_id`, `interest_rate`, `installment_amount` dès qu'un avis CA/CDAG est rendu) :

```python
_LOCKED_DOSSIER_STATES = ('avis_ca', 'avis_cdag', 'approved', 'active', 'closed', 'defaulted', 'written_off')
_LOCKED_DOSSIER_FIELDS = {'loan_amount', 'term', 'product_id', 'interest_rate', 'installment_amount'}

def _check_locked_dossier_fields(self, vals):
    locked_now = self._LOCKED_DOSSIER_FIELDS & set(vals)
    if not locked_now or self.env.context.get('propagation_avis_ca_cdag'):
        return
    for loan in self:
        if loan.state not in loan._LOCKED_DOSSIER_STATES:
            continue
        raise ValidationError(...)

def write(self, vals):
    self._check_locked_dossier_fields(vals)
    result = super().write(vals)
    ...
```

C'est le pattern à suivre pour l'override de `write()` du Lot 1 — **avec une nuance
importante à traiter différemment** : `_LOCKED_DOSSIER_FIELDS` verrouille en fonction de
l'**état courant** du dossier (`loan.state in _LOCKED_DOSSIER_STATES`), alors que le besoin
exprimé pour `signed_contract`/`contract_signature_date` est un verrouillage **définitif dès
que la valeur a été renseignée une première fois**, indépendamment de l'état — donc la
condition à tester dans le futur override ne sera pas `loan.state in (...)` mais quelque
chose comme `loan.signed_contract` (valeur AVANT écriture) déjà non vide. Attention au piège
classique de ce genre de garde-fou : il faudra prévoir un contexte d'échappement analogue à
`propagation_avis_ca_cdag` pour l'écriture légitime effectuée *par le wizard lui-même* (sinon
le wizard ne pourra jamais écrire la première fois), et bien vérifier que le contrôle se
fait sur la valeur *avant* écriture (comme le fait déjà `_check_locked_dossier_fields`, qui
s'exécute avant `super().write()`).

Existe aussi `ir_attachment.py::unlink()` (point 4) comme pattern complémentaire pour la
protection anti-suppression côté pièce jointe elle-même — à conserver tel quel, il continuera
de protéger le fichier une fois le nouveau flux en place.

## 9. Anomalies / points bloquants identifiés pour le Lot 1

1. **Double occurrence du champ dans la vue** (header + panneau SUIVI, point 2) : le Lot 1
   devra traiter les deux, pas seulement le bouton du header, sous peine de laisser une
   porte de contournement du wizard/verrouillage via le widget natif du panneau SUIVI.
2. **Champ visible/modifiable dans des états "terminaux"** (`closed`, `defaulted`,
   `written_off`, point 5) : le verrouillage définitif doit couvrir ces états aussi, pas
   seulement `approved`/`active`.
3. **Aucune régression à prévoir côté guard d'activation** : `action_disburse()`
   (`microfinance_loan.py:1872`) teste `if not loan.signed_contract` — le Lot 1 doit
   continuer à remplir ce même champ (via le wizard) pour ne pas casser ce garde-fou déjà en
   place.
4. **`_post_signed_contract_to_chatter()`** (`microfinance_loan.py:2216`, déclenché depuis
   `write()` quand `vals.get('signed_contract')`) poste une copie du fichier dans le chatter
   à chaque écriture du champ — méthode à conserver/réutiliser depuis le wizard plutôt qu'à
   dupliquer, si le Lot 1 souhaite garder cette même traçabilité chatter.
5. **Pas de champ "date de signature" existant à réutiliser** : `contract_signature_date`
   est entièrement nouveau, aucun champ Date proche en sémantique sur `microfinance.loan`
   (les dates existantes du groupe "Suivi" — `application_date`, `approval_date`,
   `disbursement_date` — correspondent à d'autres étapes du workflow, pas à la signature).

## Synthèse pour le Lot 1

- Wizard de référence à copier : **`microfinance.loan.writeoff.wizard`**
  (`wizard/microfinance_loan_writeoff_wizard.py` + `_views.xml`).
- Nouveau champ à créer : `contract_signature_date` (Date), aucun override de `write()` à
  adapter en dehors du nouveau à créer pour son verrouillage.
- Verrouillage à construire sur le modèle **valeur déjà renseignée** (pas sur `state`),
  contrairement au pattern `_LOCKED_DOSSIER_FIELDS` existant qui est basé sur `state` —
  adapter, pas copier tel quel.
- Deux emplacements de vue à faire évoluer (header + panneau SUIVI), pas un seul.
- Protection anti-suppression déjà en place côté `ir.attachment` (point 4) : à conserver,
  aucune modification nécessaire de ce côté.

Aucune modification de code effectuée dans ce lot.
