# Audit — Workflow Avis CA / Avis CDAG (Comité d'Octroi)

Audit en lecture seule (Lot 0). **Aucune modification de code effectuée.** Toutes les valeurs
ci-dessous ont été vérifiées directement sur le dépôt (`microfinance_loan_management/models/
microfinance_loan_application.py`, `microfinance_loan.py`, `microfinance_loan_product.py`,
`security/groups.xml`, `views/microfinance_loan_application_views.xml`) et sur la base réelle
SEFOR (lecture seule) pour la liste des agences.

## Correction préalable au périmètre de la demande

La demande situe les champs Avis CA/CDAG en **"section VIII"**. En réalité, la vue les place en
**section "VII — Avis du CA et du CDAG"** (`microfinance_loan_application_views.xml:630`).
**"VIII — Comité d'octroi"** est une section *distincte*, déjà présente juste en dessous
(ligne 662), explicitement commentée `<!-- VIII — Comité d'octroi : standby, pas de workflow de
comité multi-validateurs. Affiche seulement l'état du dossier -->` et qui n'affiche que le
badge `state` du dossier. Les deux sections cohabitent sur la même page de pagination (Page 7,
valeur technique `ca_cdag_committee`). Le reste de ce rapport utilise donc "section VII" pour les
champs Avis CA/CDAG, conformément au code, et signale "section VIII" séparément quand pertinent.

---

## Étape 1 — Localisation exacte des champs et du modèle

**Modèle confirmé : `microfinance.loan.application`**, bloc commenté "Bloc E — Avis CA / CDAG"
(`microfinance_loan_application.py:675-694`) :

| Champ (nom technique) | Libellé | Type |
|---|---|---|
| `requested_amount` | Montant demandé | `Monetary`, **related='loan_id.loan_amount'**, readonly |
| `required_savings` | Épargne exigée (demande) | `Monetary` |
| `repayment_amount` | Remboursement (demande) | `Monetary` |
| `period` | Durée demandée (échéances) | `Integer` |
| `available_savings` | Épargne disponible | `Monetary` |
| `ca_amount` | Montant avis CA | `Monetary`, tracking |
| `ca_required_savings` | Épargne exigée (CA) | `Monetary` |
| `ca_repayment_amount` | Remboursement (CA) | `Monetary` |
| `ca_period` | Durée avis CA (échéances) | `Integer` |
| `cdag_amount` | Montant avis CDAG | `Monetary`, tracking |
| `cdag_required_savings` | Épargne exigée (CDAG) | `Monetary` |
| `cdag_repayment_amount` | Remboursement (CDAG) | `Monetary` |
| `cdag_period` | Durée avis CDAG (échéances) | `Integer` |

**Aucun `@api.onchange`, `@api.depends`/compute, ni `@api.constrains` ne touche ces 13 champs**
(recherche exhaustive) : ce sont de simples champs stockés, sans aucune logique de calcul ni de
contrôle d'accès, exactement comme décrit dans la demande.

**Source du "montant demandé par le client" : `requested_amount`, déjà présent sur
`microfinance.loan.application` elle-même**, en `related='loan_id.loan_amount'` readonly - pas
un champ à calculer, il reflète simplement le crédit lié.

**Séquencement dossier ↔ crédit — confirmé : `microfinance.loan` est toujours créé EN PREMIER.**
`loan_id` (`microfinance_loan_application.py:99`) est le champ inverse du `One2many
application_ids` sur `microfinance.loan` (`microfinance_loan.py:100`). Le seul point de création
d'une `microfinance.loan.application` trouvé dans le code est
`action_view_applications()` (`microfinance_loan.py:1439-1459`), qui crée le dossier avec
`loan_id` déjà renseigné dès la création :
```python
application = self.env['microfinance.loan.application'].create({
    'partner_id': self.partner_id.id,
    'loan_product_id': self.product_id.id,
    'company_id': self.company_id.id,
    'loan_id': self.id,
})
```
Le commentaire de cette méthode confirme explicitement : *"le crédit et le dossier d'instruction
se créent désormais indépendamment (cf. réversion du point d'entrée unique)"* - cohérent avec le
commit `13a580c` de l'historique (*"Restructure les workflows crédit/dossier, réversion du point
d'entrée unique"*). **Conséquence directe : `requested_amount` (donc le crédit et son montant)
est garanti déjà disponible dès que la section VII est atteinte** - le besoin métier n°1 ("valeur
par défaut = montant demandé par le client") est donc immédiatement réalisable par un simple
`default`/onchange lisant `requested_amount`, sans dépendance non résolue.

**Point technique à noter pour la conception (pas une décision métier au sens de la liste
demandée, mais une divergence de fait à trancher au moment du chiffrage)** :
`microfinance.loan.application` a son propre `loan_product_id` (ligne 68-74, modifiable après
création : *"pré-rempli à la création du crédit, modifiable à cette étape"*) et son propre
`company_id` (ligne 65, "Société / Agence"), distincts de `loan_id.product_id` et
`loan_id.company_id`. Si `loan_product_id` est modifié sur le dossier après création, il peut
diverger du produit réel du crédit lié - à trancher quelle source (`loan_id.product_id` ou
`loan_product_id`) doit alimenter le calcul `installment_rounding_unit`/`mode` (cf. étape 3).

---

## Étape 2 — État actuel des groupes fantômes

**Confirmé : `group_application_surveyor`, `group_application_ca`, `group_application_cdag`
existent dans `security/groups.xml:52-65`**, chacun défini uniquement comme :
```xml
<record id="group_application_ca" model="res.groups">
    <field name="name">Membre CA (dossier de crédit)</field>
    <field name="category_id" ref="module_category_microfinance"/>
    <field name="implied_ids" eval="[(4, ref('group_microfinance_user'))]"/>
</record>
```
**Recherche exhaustive (tous fichiers XML/CSV/PY du module) : ces trois xmlids n'apparaissent
NULLE PART ailleurs** - ni dans `ir.model.access.csv`, ni dans un attribut `groups=""` de vue, ni
dans un `ir.rule`, ni dans du code Python. Ce sont des groupes vides de toute portée
fonctionnelle : ils existent dans le registre Odoo (assignables à un utilisateur) mais n'ouvrent
ni ne restreignent aucun accès. Confirmé "dette technique non résolue" tel que décrit dans la
demande - rien à signaler côté impact d'une refonte (aucune dépendance existante à casser).

**Scoping par agence déjà existant à réutiliser comme modèle : oui, mais PAS via un groupe par
agence.** `company_id` fait déjà office d'agence dans tout le module (champ "Société / Agence" -
1 société = 1 agence, confirmé ligne 65 et par la liste des agences en étape 5). Le cloisonnement
par agence déjà en place ailleurs (`security/microfinance_company_rules.xml`) utilise un seul
`ir.rule` par modèle avec `domain_force="[('company_id', 'in', company_ids)]"` et `groups`
**vide** (s'applique à tout utilisateur interne, y compris managers/auditeurs) - **aucun groupe
par société n'existe nulle part dans ce module ni dans les modules adjacents** (`microfinance_
savings_management`, `microfinance_mowgli_assistant` : leurs groupes respectifs sont transverses,
pas scopés par société). Les 9 groupes `group_microfinance_*` de `groups.xml` sont tous
transverses à toutes les agences.

**Point important pour la conception (étape 5)** : créer 25 `res.groups` distincts (un par
agence) serait une première dans ce module - le pattern existant pour restreindre par agence est
au contraire d'**éviter** les groupes par société, au profit d'un `ir.rule` sur `company_id`. Une
alternative à 25 groupes serait un groupe `group_application_ca` unique + une règle
`ir.rule` combinant `groups=[ref('group_application_ca')]` et
`domain_force=[('company_id','in',company_ids)]` (restreint le CA à SA société automatiquement,
sans further group par agence) - mais cette règle ne restreindrait que la *visibilité des
enregistrements*, pas l'écriture *champ par champ* (`ca_amount` vs `cdag_amount`), qui nécessite
de toute façon un contrôle applicatif (attrs de vue et/ou `@api.constrains`/`write()` override),
cf. décision métier n°5 ci-dessous.

**Gap non lié à la demande mais pertinent pour tout le chantier** : `microfinance.loan.
application` n'a **aucun `ir.rule` de cloisonnement par société**, contrairement à
`microfinance.loan`, `microfinance.loan.product`, `microfinance.loan.account`, `microfinance.
loan.installment`, `microfinance.loan.payment` (tous cloisonnés dans `microfinance_company_
rules.xml`). Un commentaire dans ce même fichier (lignes 29-33) affirme que le modèle *"n'est
pas encore câblé dans le module (absent de models/__init__.py, d'ir.model.access.csv et de toute
vue)"* - **ce commentaire est manifestement obsolète** : le modèle est bien câblé (accès CSV
lignes 146-149, vues complètes, 7 pages de formulaire). La règle de cloisonnement, elle,
manque réellement. Conséquence concrète : aujourd'hui, un utilisateur de l'agence IS peut lire
ET modifier un dossier de l'agence BD (tant qu'il a `group_microfinance_user`). Point à signaler
à Micka : une restriction "CA par agence" au niveau champ n'a de sens complet que si le dossier
lui-même est déjà cloisonné par agence au niveau enregistrement - sinon un CA d'une autre agence
peut toujours lire (et modifier tous les champs SAUF `ca_amount`) le dossier d'une agence qui
n'est pas la sienne.

---

## Étape 3 — Réutilisabilité du moteur de calcul du Lot 1

Le calcul `ceiling` (Lot 1, cf. `docs_dev/regression_nb_echeances/`) vit dans 3 méthodes
**d'instance** sur `microfinance.loan` (`microfinance_loan.py:637-661` après le correctif
Lot 1-bis) :
- `_compute_installment_target()` : cible d'échéance interest-first arrondie, lit
  `self.loan_amount`, `self.term`, `self.interest_rate`, `self.product_id.
  installment_rounding_unit`/`installment_rounding_mode`, et appelle `_period_interest_factor()`.
- `_period_interest_factor()` : lit `self.repayment_frequency_id.periods_per_year`.
- `_round_installment_target(value, unit, mode)` : fonction pure sur ses 3 arguments, aucune
  dépendance à `self` au-delà de l'appel (pourrait être `@staticmethod` telle quelle).

**Aucune des trois ne dépend de la persistance de l'enregistrement** (pas de `self.id`,
`self.state`, `self.env.cr.execute`, ni d'écriture). **Confirmé réutilisable depuis
`microfinance.loan.application` sans aucune modification du code du Lot 1**, via un
enregistrement virtuel Odoo standard (`.new()`, jamais écrit en base) :
```python
virtual = self.env['microfinance.loan'].new({
    'loan_amount': self.ca_amount,
    'term': self.ca_period,
    'interest_rate': self.loan_id.interest_rate,
    'repayment_frequency_id': self.loan_id.repayment_frequency_id.id,
    'product_id': self.loan_id.product_id.id,  # ou self.loan_product_id.id, cf. étape 1
})
target = virtual._compute_installment_target()
```
C'est un mécanisme Odoo standard (déjà utilisé ailleurs dans ce module, cf. `odoo.tests.Form` qui
repose dessus) - aucun risque de double écriture, aucun effet de bord sur la vraie table
`microfinance_loan`. **Pas de couplage bloquant, pas de refactor nécessaire pour le Lot 1 de ce
chantier.** Un refactor en fonction utilitaire indépendante (`@api.model` ou module-level) reste
possible pour la lisibilité mais n'est pas requis techniquement - à trancher comme préférence de
conception, pas comme contrainte.

**Symétrie savings→loan** : sans objet ici - `microfinance.loan.application` et
`microfinance.loan` sont bien dans le **même module** (`microfinance_loan_management`), l'import/
appel direct entre les deux est le pattern déjà utilisé partout ailleurs dans ce module (ex.
`application.loan_id` est un lien direct ORM standard intra-module). La règle "pas de dépendance
savings→loan" concerne le cloisonnement entre modules `microfinance_savings_management` et
`microfinance_loan_management` (deux modules distincts) - non applicable ici.

---

## Étape 4 — Workflow et séquencement

**`microfinance.loan.application` a son propre état (`state`), totalement indépendant du
workflow Avis CA/CDAG** :
```python
state = fields.Selection([
    ('draft', 'Brouillon'), ('visite', 'Visite'),
    ('contre_visite', 'Contre-Visite'), ('fait', 'Fait'),
], default='draft', ...)
```
avec `ALLOWED_TRANSITIONS` (`microfinance_loan_application.py:45-49`) ne portant que sur ce
cycle d'enquête à 4 états (KYC/visite terrain). **Il n'existe aucun état "en attente avis CA" /
"en attente avis CDAG" sur ce modèle** - les champs de la section VII sont actuellement
éditables sans aucun garde-fou de séquence, à n'importe quel état du dossier (`draft` à `fait`).

**Le workflow Avis CA / Avis CDAG existe bel et bien, mais ailleurs : sur `microfinance.loan`**
(pas sur `microfinance.loan.application`) :
```python
state = fields.Selection([..., ('avis_ca', 'Avis CA'), ('avis_cdag', 'Avis CDAG'), ...])
...
def action_ca_review(self):
    self.write({'state': 'avis_ca', 'manager_id': self.env.user.id})
def action_cdag_review(self):
    self.write({'state': 'avis_cdag', 'finance_user_id': self.env.user.id})
```
(`microfinance_loan.py:74-75, 587-591`). **Ces deux méthodes ne lisent ni n'écrivent
aujourd'hui aucun des champs de la section VII** (`ca_amount`, `cdag_amount`, etc.) - elles ne
font que changer l'état du crédit et assigner l'utilisateur courant comme responsable
(`manager_id`/`finance_user_id`). **Aucun lien de code n'existe actuellement entre le passage
`avis_ca`→`avis_cdag` sur `microfinance.loan` et le remplissage des champs Avis CA/CDAG sur
`microfinance.loan.application`.** C'est très probablement le point d'ancrage naturel pour le
"séquencement" recherché par la demande (répercuter au moment de `action_ca_review`/
`action_cdag_review` plutôt qu'à chaque sauvegarde du formulaire), mais c'est un choix de
conception à valider, pas un fait déjà câblé.

**Élément de contexte directement pertinent, déjà présent dans le code comme scaffold inerte** :
`microfinance.loan.product.validation_authority` (`microfinance_loan_product.py:110-121`,
Sélection `ca`/`cdag`, défaut `cdag`) est un champ de configuration **déjà écrit noir sur blanc
pour préparer exactement ce genre de décision**, avec ce commentaire explicite dans le code :
*"Point à trancher explicitement avec Micka avant d'implémenter la logique de gating
correspondante (pas deviné ici) : 'Avis CA' signifie-t-il que le dossier peut être validé
directement après avis_ca en sautant avis_cdag, ou 'Avis CDAG' signifie-t-il que le passage par
CDAG reste obligatoire (= comportement actuel) ?"* Ce champ n'a aujourd'hui **aucun effet** sur
`action_ca_review`/`action_cdag_review` (tout dossier passe systématiquement par les deux
quel que soit le produit). Cette question recoupe directement la décision métier n°1 ci-dessous
et pourrait être le bon moment de la trancher dans le même chantier plutôt que séparément -
signalé à Micka, pas tranché ici.

---

## Étape 5 — Structure des agences

**11 sociétés provisionnées aujourd'hui** (lecture SEFOR, `res_company` avec `agency_code`) :

| id | Société | Code agence |
|---|---|---|
| 1 | CEFOR Isotry | IS |
| 2 | CEFOR Ambanidia | BD |
| 3 | CEFOR Ampitatafika | SY |
| 4 | CEFOR Andranonahoatra | AND |
| 5 | CEFOR Sabotsy Namehana | SAB |
| 6 | CEFOR Mahitsy | MAH |
| 7 | CEFOR Tsaramasay | TSA |
| 8 | CEFOR Ambohitrimanjaka | AM2 |
| 9 | CEFOR Andoharanofotsy | AN2 |
| 10 | CEFOR Ambohimanarina | AM3 |
| 11 | CEFOR Andravoahangy | AN3 |

**Note** : le code "BM" cité en exemple dans la demande n'existe **pas** parmi les agences
actuelles (aucune correspondance `agency_code='BM'` en base) - à corriger si un exemple concret
est nécessaire pour la suite du chantier.

**"14 agences restantes" confirmé et daté** : trouvé dans
`microfinance_savings_management/docs_dev/savings/ecarts_lpf.md:76-78` : *"les agences restantes
(jusqu'à 25 au total) sont ajoutées manuellement au fil de l'eau par formulaire société, une
liste figée en XML n'aurait pas pu les couvrir à l'avance."* 11 + 14 = 25, cohérent avec le
"~25 agences" de la demande. **Confirmation importante pour la conception** : le provisionnement
d'une nouvelle agence est déjà, aujourd'hui, un **acte manuel au fil de l'eau** (création d'une
`res.company` via formulaire, pas de script de batch-provisioning ni de mécanisme XML figé). Ceci
milite plutôt pour l'option "groupe CA unique + `ir.rule` sur `company_id`" décrite en étape 2
(zéro création manuelle supplémentaire à chaque nouvelle agence) que pour "un groupe `res.groups`
par agence à créer/maintenir manuellement en parallèle du formulaire société" - mais ceci reste
un choix de conception à valider avec Micka (décision n°5 ci-dessous), pas tranché ici.

---

## Complément (Lot 0 bis) — États avis_ca/avis_cdag et validation_authority

Audit en lecture seule, dans la continuité du rapport ci-dessus. Sources ajoutées : `git log -L`
(blame ligne par ligne) sur `microfinance_loan.py`, `security/groups.xml`, et
`docs/audit_backlog_urgent.md`.

### Complément étape 1 — États avis_ca / avis_cdag : réels, atteignables, mais coquilles vides côté données

`avis_ca`/`avis_cdag` sont deux valeurs parmi les **10** de l'unique champ `state` de
`microfinance.loan` (pas un champ séparé) :
```python
state = fields.Selection([
    ('draft', 'Brouillon'), ('enquete', 'Enquête'),
    ('avis_ca', 'Avis CA'), ('avis_cdag', 'Avis CDAG'),
    ('approved', 'Approuvé'), ('active', 'Actif'), ('closed', 'Clôturé'),
    ('defaulted', 'Défaut'), ('written_off', 'Radié'), ('cancelled', 'Annulé'),
], default='draft', ...)
```
(`microfinance_loan.py:71-82`.)

**Atteignables : oui, via de vrais boutons du formulaire crédit**, tous visibles/actifs
aujourd'hui (`microfinance_loan_views.xml:64-67`) :
```xml
<button name="action_start_enquete" ... invisible="state != 'draft'"/>
<button name="action_ca_review" string="Avis CA" ... groups="...group_microfinance_credit_committee" invisible="state != 'enquete'"/>
<button name="action_cdag_review" string="Avis CDAG" ... groups="...group_microfinance_credit_committee" invisible="state != 'avis_ca'"/>
<button name="action_approve" string="Approuver" ... groups="...group_microfinance_manager" invisible="state != 'avis_cdag'"/>
```
**Fait notable et directement pertinent pour la décision n°3** : `action_ca_review` ET
`action_cdag_review` sont gardés par **exactement le même groupe**,
`group_microfinance_credit_committee` ("Comité de crédit", `groups.xml:40-44`, groupe unique et
transverse à toutes les agences, sans distinction CA/CDAG). Concrètement, **aujourd'hui, tout
membre du "Comité de crédit" peut cliquer les deux boutons l'un après l'autre** - il n'existe
strictement aucune séparation technique entre "qui peut donner l'avis CA" et "qui peut donner
l'avis CDAG" au niveau du crédit lui-même. C'est un fait à rapporter tel quel à la confrontation
de l'étape 3 ci-dessous, pas une réponse à la décision n°3.

Autres lectures/écritures de ces deux états, recherche exhaustive :
- `_EDITABLE_SCHEDULE_STATES` (ligne 175) et le `readonly` de `installment_amount`
  (`microfinance_loan_views.xml:104`) : `avis_ca`/`avis_cdag` y figurent comme "états où
  l'échéancier reste modifiable" - sans rapport avec la logique CA/CDAG elle-même.
- `controllers/microfinance_dashboard_controller.py:106-107` : mapping pur affichage (badge
  "En attente", couleur `warning`), aucune logique.
- **Aucun `ir.rule`, aucun rapport PDF, aucune méthode Python autre que `action_ca_review`/
  `action_cdag_review` elles-mêmes** ne référence `avis_ca`/`avis_cdag`.
- **`action_ca_review`/`action_cdag_review` ne lisent ni n'écrivent aujourd'hui aucun des 13
  champs de la section VII** - confirmé, aucune exception trouvée (déjà signalé dans le premier
  rapport, reconfirmé ici avec la recherche élargie).

**Historique git - intention documentée, trouvée explicitement (pas de spéculation nécessaire)** :

`git log -L74,75:microfinance_loan_management/models/microfinance_loan.py` remonte au commit
`13a580c` ("Restructure les workflows crédit/dossier, réversion du point d'entrée unique,
navigation crédit-épargne", 2026-08-16), qui **renomme** simplement les états/méthodes
préexistants (`submitted`/`manager_validated`/`finance_validated` → `avis_ca`/`avis_cdag`,
`action_manager_validate`/`action_finance_validate` → `action_ca_review`/`action_cdag_review`),
sans ajouter de logique nouvelle. Le message de ce commit contient une phrase **directement
déterminante pour ce chantier**, à citer intégralement :

> "Workflow `microfinance.loan.application` simplifié (4 états) : Brouillon → Visite →
> Contre-Visite → Fait, recentré sur le suivi terrain (**l'instruction analyse/comité/avis
> CA/CDAG vit désormais sur le crédit lui-même**) ; smart button 'Crédit' sur le dossier."

**C'est une décision architecturale explicite et documentée, pas un oubli** : au moment même où
les états `avis_ca`/`avis_cdag` ont pris leur nom actuel, le dossier d'instruction
(`microfinance.loan.application`) a été **délibérément simplifié pour ne PLUS porter la logique
d'avis CA/CDAG**, cette logique étant explicitement réaffectée au crédit. Le champ `state` de
`microfinance.loan.application` a perdu, dans ce même commit, toute notion d'étape
CA/CDAG (`ALLOWED_TRANSITIONS` ne porte que sur `draft/visite/contre_visite/fait`). **Point à
signaler en clair à Micka avant de lancer le Lot 1** : la demande actuelle (relier les champs
Avis CA/CDAG du dossier au workflow du crédit) va, dans son principe, à l'inverse de cette
décision d'architecture prise il y a 9 jours - ce n'est pas nécessairement un problème (les deux
peuvent coexister : les *champs* restent sur le dossier tout en étant *déclenchés* par les
transitions d'état du crédit, ce que documente déjà l'étape 4 du premier rapport), mais Micka
devrait confirmer consciemment ce changement de cap plutôt que de le découvrir après coup.

**Recherche complémentaire - un wizard CA/CDAG a existé, puis a été supprimé, sans lien avec la
logique métier recherchée ici** : `git log --diff-filter=D` révèle que
`wizard/microfinance_loan_application_ca_cdag_wizard.py` (+ ses vues) a existé, créé par
`7cfcf17` puis supprimé par un commit ultérieur (`b47aeaee`, *"Fusion des assistants du dossier
crédit dans la fiche unique..."*, pure consolidation UI : remplace huit popups de saisie par une
saisie intégrée directement dans le formulaire). Contenu intégral de ce wizard avant suppression
(`git show b47aeaee^:...`) : un simple pop-up générique - `default_get` recopie les valeurs
actuelles du dossier dans le wizard, `action_validate` les réécrit telles quelles sur le dossier.
**Aucune formule, aucun calcul, aucun défaut dérivé de `requested_amount`, aucune restriction de
groupe.** Ce wizard ne constitue donc **aucun antécédent exploitable** pour les décisions métier
- la fonctionnalité demandée n'a, à aucun moment de l'histoire du projet, été réellement conçue
ni implémentée, même partiellement.

### Complément étape 2 — `validation_authority`

**Localisation exacte** : `microfinance_loan_product.py:110-121`, sur `microfinance.loan.product`
(pas de modèle séparé, pas de many2one vers un groupe, pas de champ de seuil numérique associé -
recherche `seuil`/`threshold` sur tout le module et `microfinance_loan_product.py` en particulier :
aucun résultat en dehors des occurrences déjà citées de la doc générale PCEC, sans rapport).

```python
validation_authority = fields.Selection([
    ('ca', 'Avis CA'),
    ('cdag', 'Avis CDAG'),
], string='Instance de validation requise', required=True, default='cdag',
    help="Détermine quelle instance doit valider les dossiers de crédit créés avec ce "
         "produit. 'Avis CA' : le CA seul peut valider le prêt. 'Avis CDAG' : l'avis CDAG "
         "est nécessaire pour la validation. Champ de configuration préparant une future "
         "évolution du workflow de validation — n'a pour l'instant aucun effet sur le "
         "déroulement actuel des états avis_ca/avis_cdag de microfinance.loan, qui reste "
         "inchangé (voir le commentaire ci-dessus pour le point à trancher avant "
         "d'implémenter la logique de gating correspondante).",
)
```
Précédé, juste au-dessus (lignes 102-109), de ce commentaire complet - cité intégralement,
sans coupe :
```python
# Champ de configuration préparant une future évolution du workflow de validation — n'a
# pour l'instant AUCUN effet sur le déroulement actuel des états avis_ca/avis_cdag de
# microfinance.loan (state, cf. action_ca_review/action_cdag_review dans
# microfinance_loan.py) : tout dossier continue de passer séquentiellement par les deux,
# quel que soit le produit. Point à trancher explicitement avec Micka avant d'implémenter
# la logique de gating correspondante (pas deviné ici) : "Avis CA" signifie-t-il que le
# dossier peut être validé directement après avis_ca en sautant avis_cdag, ou "Avis CDAG"
# signifie-t-il que le passage par CDAG reste obligatoire (= comportement actuel) ?
```

**Origine confirmée : champ tout récent**, ajouté par le commit `b6b4e17` (*"Correction ceiling
de l'arrondi d'échéance (Lot 1) et de la boucle term<->installment_amount (Lot 1-bis)"*,
`git log -S"validation_authority"`) - c'est-à-dire le chantier immédiatement précédent (arrondi
d'échéance), pas un vestige ancien. Ce n'est pas un hasard de calendrier : le champ a probablement
été ajouté "en prévision" pendant que le sujet CA/CDAG était réfléchi, sans être branché.

**Usage actuel : lu nulle part** (recherche exhaustive `validation_authority` sur tout le
module) en dehors de sa propre définition et de `tests/test_loan_product_validation_authority.py`
(2 tests, qui ne vérifient que la valeur par défaut/persistée du champ - aucun test de gating,
confirmé par lecture du fichier).

**Seuil documenté ailleurs ?** Non trouvé. La seule mention indépendante et antérieure d'un
besoin de seuil est `docs/audit_backlog_urgent.md` (2026-07-07, donc **antérieur** au
renommage `avis_ca`/`avis_cdag` - utilise encore `action_manager_validate`/
`action_finance_validate`), point n°12 *"Comité de crédit / workflow configurable — PAS FAIT"* :
> "Un seul utilisateur (`self.env.user`) est enregistré par étape (`manager_id`,
> `finance_user_id`) — aucune notion de comité (plusieurs validateurs sur une même étape), aucun
> modèle de configuration des étapes, **aucun seuil (ex. montant > X ⇒ étape supplémentaire)**."

Ceci confirme, de façon indépendante et antérieure, qu'un mécanisme de seuil montant a déjà été
identifié comme manquant - mais **aucun chiffre, aucune règle CSBF/PCEC documentée nulle part
dans le dépôt** ne précise à partir de quel montant le CDAG devrait obligatoirement intervenir.
Si un tel seuil existe dans la réglementation CSBF ou la politique interne CEFOR, il n'est pas
dans ce dépôt - à demander à Micka comme donnée métier externe, pas comme fait technique.

### Étape 3 — Confrontation aux 5 décisions métier du premier audit

| # | Décision | Élément trouvé | Portée |
|---|---|---|---|
| 1 | Durée avis CA — entrée ou sortie du calcul ? | Aucun élément direct. `action_ca_review`/`action_cdag_review` ne touchent ni montant ni durée. `validation_authority` (complément étape 2) est *adjacent* (porte sur le saut CDAG, pas sur la mécanique montant/durée du CA) mais n'y répond pas. | **Aucun** |
| 2 | Timing de répercussion vers `microfinance.loan` | Le commit `13a580c` documente explicitement que la logique d'avis CA/CDAG a été déplacée sur le crédit lui-même, et que `microfinance.loan.application` a été délibérément recentré sur le seul suivi terrain. Suggère que le point d'ancrage naturel est une transition d'état du crédit (`action_ca_review`/`action_cdag_review`), pas une sauvegarde du dossier — mais ne dit pas *quand exactement* dans le circuit. | **Partiel** |
| 3 | Restriction symétrique CA/CDAG (lecture/écriture croisée) | Fait concret et nouveau : `action_ca_review` et `action_cdag_review` sont **gardés par le même groupe** (`group_microfinance_credit_committee`) aujourd'hui — aucune séparation CA/CDAG n'existe nulle part dans le code actuel, à aucun niveau. C'est un précédent (l'existant traite CA et CDAG comme un seul corps), pas une règle métier — la décision reste entièrement à trancher. | **Partiel (contexte, pas réponse)** |
| 4 | CDAG non modifié = CA reste la source pour `microfinance.loan` ? | Aucun élément trouvé, ni dans le code actuel ni dans l'historique (le wizard CA/CDAG aujourd'hui supprimé ne contenait aucune logique de priorité). | **Aucun** |
| 5 | Groupes CA par agence (nommage, périmètre) | Confirme le premier rapport : les 3 groupes fantômes (`group_application_ca`/`cdag`/`surveyor`) sont des **vestiges d'une conception abandonnée** (créés par `7cfcf17`, dont le pan "point d'entrée unique" a été intégralement **revert** par `13a580c` sur décision de Micka) — ils n'ont jamais été conçus avec un scoping par agence (le wizard associé, cf. ci-dessus, n'avait aucune notion de société/agence). Ne fournissent donc aucun point de départ technique réutilisable, au-delà de leur simple existence en tant que noms réservés. | **Aucun élément nouveau au-delà du 1er rapport** |

---

## Décision n°6 (nouvelle, issue du complément) — Conflit d'architecture : groupe unique vs groupe par agence

À ajouter à la liste des décisions métier, sans recommandation :

- **Option A — groupe unique + `ir.rule` par `company_id`** (cohérente avec l'existant) : un
  seul `group_microfinance_ca` (ou `group_application_ca` réactivé), plus une règle
  `domain_force=[('company_id', 'in', company_ids)]` scopant automatiquement chaque utilisateur
  CA à sa propre agence. **Implications concrètes** : zéro création de groupe à chaque nouvelle
  agence provisionnée (cohérent avec le provisionnement manuel au fil de l'eau déjà en place,
  étape 5 du premier rapport) ; c'est le seul pattern de cloisonnement par agence qui existe
  aujourd'hui dans tout le module (`microfinance_company_rules.xml`) et dans les modules
  adjacents ; nécessite malgré tout l'ajout du `ir.rule` manquant sur `microfinance.loan.
  application` (gap déjà signalé, étape 2 du premier rapport) pour que le cloisonnement soit
  réellement effectif au niveau enregistrement.
- **Option B — un groupe par agence** (demande initiale, ex. `group_microfinance_ca_is`,
  `group_microfinance_ca_bm`) : **Implications concrètes** : 11 groupes à créer immédiatement,
  jusqu'à 25 à terme ; aucun précédent technique dans ce module ou les modules adjacents (les 3
  groupes fantômes existants, même s'ils portent un nom proche, n'ont jamais eu de scoping par
  agence, cf. complément étape 1) ; pose la question de la création automatique du groupe à
  chaque provisionnement de nouvelle agence (aujourd'hui un acte manuel, cf. étape 5 du premier
  rapport - un mécanisme automatique serait donc lui-même une nouveauté à concevoir) ; plus
  proche du vocabulaire "groupe CA_Isotry" employé dans la demande d'origine, ce qui peut faciliter
  la compréhension terrain par les agents CEFOR non techniques.

Aucune option n'est recommandée ici - à trancher avec Micka.

---

## Décisions métier à trancher avec Micka (reproduites telles quelles, non tranchées)

1. **Durée avis CA — entrée ou sortie du calcul ?** Quand le CA modifie le montant, la durée
   (`Durée avis CA (échéances)`) reste-t-elle égale à la durée initialement demandée (le CA ne
   fait que réduire/augmenter le montant, la cible de remboursement seule est recalculée), ou
   le CA peut-il aussi fixer une nouvelle durée, auquel cas seul `Remboursement (CA)` serait
   calculé à partir des deux (montant + durée) ?

2. **Timing de répercussion vers `microfinance.loan`** — la modification du CA doit-elle être
   répercutée sur `microfinance.loan` immédiatement à la sauvegarde (avant même l'avis du
   CDAG), ou seulement une fois le circuit d'octroi complet validé ?

3. **Restriction symétrique CA/CDAG** — le CA peut-il *lire* les champs CDAG (probablement oui
   sans enjeu) ? Le CA peut-il *modifier* les champs CDAG (a priori non, à confirmer) ? Cette
   règle n'a été énoncée que dans un sens (CDAG ne peut pas modifier CA) — vérifier si
   l'inverse doit être également verrouillé.

4. **CDAG non modifié = valeur héritée du CA reste la source pour `microfinance.loan`.** Est-ce
   bien l'intention (puisque le bloc CDAG hérite déjà par défaut de la valeur CA, la valeur
   finale utilisée pour `microfinance.loan` peut simplement toujours être "la valeur actuelle
   du bloc CDAG", que celui-ci ait été explicitement modifié ou non) ? Confirmer cette
   simplification avant de coder une logique de priorité plus complexe.

5. **Création des groupes CA par agence** — nommage souhaité (ex. `group_microfinance_ca_is`,
   `group_microfinance_ca_bm`) et périmètre : uniquement les agences déjà provisionnées
   aujourd'hui, ou prévoir un mécanisme qui crée automatiquement le groupe CA correspondant
   lors du provisionnement de chaque nouvelle agence ? **Point technique découvert pendant
   l'audit à intégrer à cette décision** : aucun pattern "groupe par société" n'existe ailleurs
   dans ce module (le cloisonnement par agence existant utilise systématiquement un groupe
   unique + `ir.rule` sur `company_id`, jamais un groupe par société) - une alternative à 25
   groupes distincts existe (cf. étape 2), à arbitrer avec le nommage. Voir aussi la décision
   n°6 ci-dessous, issue du complément d'audit, qui détaille les deux options en présence.

6. **Conflit d'architecture groupe unique vs groupe par agence** (nouvelle, cf. section dédiée
   ci-dessus pour le détail complet des deux options et leurs implications) — directement liée
   à la décision n°5 : faut-il un `group_microfinance_ca` unique combiné à un `ir.rule` sur
   `company_id` (Option A, seul pattern déjà en place dans ce module), ou un groupe `res.groups`
   distinct par agence (Option B, plus proche du vocabulaire de la demande d'origine mais sans
   aucun précédent technique) ?

**Point complémentaire (contexte, pas une 7e décision formelle, directement lié aux n°1 et n°2)**
: `microfinance.loan.product.validation_authority` (ca/cdag) est un champ déjà présent, déjà
commenté dans le code comme "à trancher avec Micka" (cité intégralement dans le complément
d'audit ci-dessus), et actuellement sans aucun effet. Sa portée recoupe la décision n°1 et le
séquencement de la décision n°2 - à clarifier si ce chantier doit aussi lui donner un effet réel
(sauter l'avis CDAG quand le produit a `validation_authority='ca'`) ou si c'est explicitement
hors périmètre.

---

## Proposition de découpage en lots (soumise à validation, pas tranchée)

- **Lot 1 — Champs, calcul, persistance** : valeurs par défaut (`ca_amount`/`cdag_amount` =
  `requested_amount`), recalcul `ca_repayment_amount`/`ca_period` via
  `_compute_installment_target()` (réutilisation confirmée, étape 3), copie CA→CDAG par défaut,
  persistance. Dépend des décisions n°1 et n°4.
- **Lot 2 — Sécurité/groupes** : conception du modèle de groupe (par agence ou groupe unique +
  `ir.rule`, décision n°5), lecture seule des champs CA hors groupe CA de l'agence, interdiction
  d'écriture CDAG→CA. Inclut probablement l'ajout du `company_id` rule manquant sur
  `microfinance.loan.application` (gap découvert étape 2, prérequis pour que la restriction par
  agence ait un sens au niveau enregistrement, pas seulement au niveau champ). Dépend de la
  décision n°3 et n°5.
- **Lot 3 — Propagation vers `microfinance.loan`** : répercussion montant/durée/échéancier au
  bon moment (décision n°2), probablement accrochée à `action_ca_review`/`action_cdag_review`
  (étape 4) plutôt qu'à chaque sauvegarde de formulaire. Dépend des décisions n°2 et n°4, et de
  la clarification du champ `product_id` à utiliser pour le calcul (étape 1, `loan_id.product_id`
  vs `loan_product_id`).

Ce découpage suit l'ordre de dépendance naturel (les champs et le calcul doivent exister avant
que la sécurité ait quelque chose à protéger, et avant que la propagation ait une valeur fiable
à propager) mais reste ouvert à un découpage différent une fois les 6 décisions tranchées.

**Mise à jour post-complément** : le complément d'audit ne change pas le découpage en 3 lots
proposé - aucun lot supplémentaire de "branchement" n'est nécessaire, le point d'ancrage
(`action_ca_review`/`action_cdag_review`) existe déjà et reste dans le périmètre du Lot 3 tel
que décrit. La seule révision : le Lot 1 devrait probablement statuer sur `validation_authority`
en même temps que la décision n°1 (même zone de code, même décision de fond sur le sens du
calcul), plutôt que de le traiter comme un sujet totalement séparé - à confirmer avec Micka au
moment du chiffrage.
