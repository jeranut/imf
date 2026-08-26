# Audit — Section VIII "Comité d'Octroi" (fiche d'enquête)

Audit en lecture seule (Lot 0). **Aucune modification de code, de vue, de modèle ni de sécurité
n'a été effectuée.** Toutes les valeurs ci-dessous ont été vérifiées directement sur le dépôt
(`microfinance_loan_management/models/microfinance_loan_application.py`, `microfinance_loan.py`,
`res_partner.py`, `microfinance_caisse_fiche_journee.py`, `security/groups.xml`,
`security/ir.model.access.csv`, les vues XML correspondantes). Modules EAT/MIIA non touchés,
aucun commit effectué.

---

## 1 — Usage actuel de `group_microfinance_credit_committee`

Recherche exhaustive (`grep` sur tous les `.xml`/`.py`/`.csv` du module) : **4 usages**, tous
dans `microfinance_loan_management` (aucun dans un autre module) :

```
security/groups.xml:40        <record id="group_microfinance_credit_committee" model="res.groups">
security/ir.model.access.csv:92   access_microfinance_loan_credit_committee,...,model_microfinance_loan,group_microfinance_credit_committee,1,0,0,0
security/ir.model.access.csv:95   access_microfinance_loan_account_credit_committee,...,model_microfinance_loan_account,group_microfinance_credit_committee,1,0,0,0
views/microfinance_loan_views.xml:65  <button name="action_ca_review" string="Avis CA" ... groups="...group_microfinance_credit_committee" invisible="state != 'enquete'"/>
views/microfinance_loan_views.xml:66  <button name="action_cdag_review" string="Avis CDAG" ... groups="...group_microfinance_credit_committee" invisible="state != 'avis_ca'"/>
```

Définition (`groups.xml:40-44`) :
```xml
<record id="group_microfinance_credit_committee" model="res.groups">
    <field name="name">Comité de crédit</field>
    <field name="category_id" ref="module_category_microfinance"/>
    <field name="implied_ids" eval="[(4, ref('group_microfinance_user'))]"/>
</record>
```

**Ambiguïté de sens détectée — à signaler explicitement, la demande le pressentait à juste
titre.** Ce groupe ("Comité de crédit") gouverne aujourd'hui **exclusivement** les deux boutons
de transition d'état sur `microfinance.loan` : "Avis CA" (`enquete` → `avis_ca`) et "Avis CDAG"
(`avis_ca` → `avis_cdag`). C'est un chantier distinct et déjà en place (Lot 1 "Avis CA/CDAG",
`docs_dev/workflow_avis_ca_cdag/`), lui-même déjà signalé dans son propre audit comme utilisant
**un seul groupe indifférencié pour deux instances théoriquement distinctes** (CA et CDAG) :
*"tout membre du 'Comité de crédit' peut cliquer les deux boutons l'un après l'autre - il
n'existe strictement aucune séparation technique entre 'qui peut donner l'avis CA' et 'qui peut
donner l'avis CDAG'"* (`docs_dev/workflow_avis_ca_cdag/AUDIT.md`).

Réutiliser ce **même** groupe pour le "Comité d'Octroi" (Section VIII, décision d'acceptation/
refus/report - une **troisième** instance de décision dans le circuit CEFOR, distincte des avis
CA et CDAG qui la précèdent) reviendrait à faire gouverner **trois étapes conceptuellement
différentes du circuit d'octroi** (Avis CA, Avis CDAG, Décision du Comité d'Octroi) par un seul
et même groupe Odoo indifférencié. Ce n'est pas nécessairement un problème si, dans la réalité
CEFOR, le même comité humain assure ces trois rôles - mais si "CA", "CDAG" et "Comité d'Octroi"
sont des instances différentes (ce que suggère la fiche papier : Avis CA/CDAG en section VII,
décision d'octroi séparée en section VIII, potentiellement un 2ème comité si refus), le nom même
du groupe ("Comité de **crédit**", pas "Comité d'**octroi**") entretient la confusion. **Décision
déjà actée, non remise en question ici** - mais l'ambiguïté est documentée telle que demandée,
à trancher consciemment plutôt que découverte après coup.

**Droits actuels du groupe sur `microfinance.loan`/`microfinance.loan.account` : lecture
seule** (`1,0,0,0` = read=1, write=create=unlink=0). Point de vigilance pour le Lot 1 (pas un
blocage, à signaler) : un utilisateur membre de `group_microfinance_credit_committee` **sans**
être aussi dans `group_microfinance_user`/`manager`/`finance` n'a aujourd'hui aucun droit
d'écriture sur `microfinance.loan` au niveau `ir.model.access` - les boutons "Avis CA"/"Avis
CDAG" ne fonctionneraient pour un tel utilisateur QUE parce que `implied_ids` fait hériter
`group_microfinance_user` (qui, lui, a probablement les droits d'écriture nécessaires - à
vérifier séparément, hors périmètre de cet audit). Pour la Section VIII, le nouveau modèle
`microfinance.credit.committee.review` nécessitera ses propres lignes `ir.model.access.csv`
(Lot 1) - l'existence de `implied_ids` vers `group_microfinance_user` couvrira probablement le
besoin de la même façon.

---

## 2 — État du modèle `microfinance.loan.application`

**Pagination confirmée : 7 pages**, `_SURVEY_PAGES` (`microfinance_loan_application.py:1517-1521`) :
```python
_SURVEY_PAGES = [
    'partner_identification', 'guarantor_documents_activity', 'financial_visits_ca_cdag',
    'income_growth_forecast', 'financing_plan_social_grid',
    'surveyor_impression_field_visits', 'ca_cdag_committee',
]
```
**Page 7 (`ca_cdag_committee`) est la dernière** - footer de navigation déjà en place
(`action_survey_previous_page`/`action_survey_next_page`/`action_survey_goto_page`, boutons de
pagination numérotés 1-7, `microfinance_loan_application_views.xml:673` et suivantes).

**"Section VIII" existe déjà, en placeholder explicite - à fusionner, pas dupliquer, exactement
comme la demande le pressentait.** Trouvé dans le même bloc `<div invisible="survey_page !=
'ca_cdag_committee'">` que la Section VII, lignes 662-670 :
```xml
<!-- VIII — Comité d'octroi : standby, pas de workflow de comité
     multi-validateurs. Affiche seulement l'état du dossier (les
     boutons d'action sont déjà dans l'en-tête). -->
<group string="VIII — Comité d'octroi">
    <group>
        <field name="state" widget="badge"/>
    </group>
    <group/>
</group>
```
Ce placeholder n'affiche que le badge `state` (état du **dossier**, `draft`/`visite`/
`contre_visite`/`fait` - cf. audit précédent, sans rapport avec le circuit d'octroi
avis_ca/avis_cdag qui vit sur `microfinance.loan`) et ne contient aucune logique. **C'est
exactement l'emplacement où la nouvelle section doit être construite** - remplacer ce `<group>`
plutôt qu'ajouter un bloc parallèle.

**Structure de la page 7 actuelle (contexte pour le raccordement)**, dans l'ordre :
1. Bloc VAV/Contre-VAV (Section VI, visite au lieu de vente)
2. `<group string="VII — Avis du CA et du CDAG"/>` + sous-groupes Demande/Antécédent/Avis CA/
   Avis CDAG (13 champs, désormais `related` vers `microfinance.loan.avis_ca_*`/`avis_cdag_*`,
   cf. `docs_dev/workflow_avis_ca_cdag/`)
3. **`<group string="VIII — Comité d'octroi">` (placeholder ci-dessus) — à remplacer.**

---

## 3 — Patterns existants de restriction de champ par groupe

**Pas de précédent exact "champ individuel restreint par un groupe custom microfinance" dans ce
module** (recherche exhaustive de `<field ... groups="microfinance...">` sur tout le module et
sur `microfinance_savings_management`) : tous les `groups=` sur des `<field>` trouvés portent
sur `base.group_multi_company` (champ `company_id`, sans rapport). **En revanche, un précédent
existe au niveau bloc** (`<group groups="...">`, pas champ isolé) :
```xml
<!-- microfinance_res_company_views.xml:23 -->
<group string="Crédit (microfinance)" groups="microfinance_loan_management.group_microfinance_manager">
```
C'est le pattern directement transposable pour restreindre l'**affichage** de tout le bloc
Section VIII à `group_microfinance_credit_committee` (un `<group groups="...">` englobant, pas
un `groups=` répété sur chaque `<field>`).

**Côté serveur, deux précédents partiels, complémentaires, aucun ne combine exactement les deux
axes (groupe + immutabilité) mais leur synthèse couvre le besoin :**

**(a) `@api.constrains` + `ValidationError`, axe "état" (pas "groupe")** -
`_check_fond_credit_id_locked_after_disbursement` (`microfinance_loan.py:1126-1143`) :
```python
@api.constrains('fond_credit_id')
def _check_fond_credit_id_locked_after_disbursement(self):
    for loan in self:
        if loan.disbursement_date:
            raise ValidationError(_(
                "Le fonds de crédit rotatif d'un crédit déjà décaissé ne peut plus être modifié."
            ))
```
Bloque l'écriture pour **tout le monde** une fois une condition d'état atteinte (pas un contrôle
par groupe) - même style (`@api.constrains` + `ValidationError`, déclenché sur n'importe quel
chemin d'écriture y compris import/API, contrairement à un contrôle de vue) mais pas le même axe
que ce qui est demandé ici.

**(b) `has_group()` + exception, axe "groupe" (pas "état"), mais sur une action, pas un
`write()` générique** - seul et unique usage de `has_group` dans tout le module Python
(`microfinance_caisse_fiche_journee.py:216-218`) :
```python
def action_reopen_day(self):
    if not self.env.user.has_group('microfinance_loan_management.group_microfinance_manager'):
        raise AccessError(_("Seul un manager peut rouvrir une journée de caisse clôturée."))
```
Protège une **action précise** (bouton), pas un `write()` générique sur le modèle - un `write()`
direct contournant cette action ne serait pas bloqué par ce mécanisme précis (à la différence de
ce que demande la spécification : "même hors UI, import, API, autre vue").

**Synthèse proposée pour le Lot 1** (fusion de (a) et (b), aucun code nouveau à ce stade,
proposition seulement) : un `@api.constrains` sur les champs de la Section VIII, testant
`self.env.user.has_group('...group_microfinance_credit_committee')` et levant une
`ValidationError` si l'utilisateur courant n'est pas membre ET que les valeurs ont changé -
combine le style déjà établi ((a), `ValidationError` sur n'importe quel chemin d'écriture) avec
le contrôle par groupe déjà établi ((b), `has_group`). C'est une **synthèse de deux patterns
existants**, pas un pattern totalement inédit dans sa mécanique, mais **aucun exemple actuel du
module ne combine déjà les deux** - à tester avec un soin particulier au Lot 1 (pas de précédent
direct à copier-coller).

**Précédent le plus proche pour la contrainte "champ obligatoire selon un autre champ" (répond
aussi au point 5 de l'audit, cf. plus bas)**, doublement implémenté vue + serveur - modèle direct
pour "commentaire obligatoire si refusé" :
- Vue (`microfinance_partner_views.xml:136,148`) : `required="microfinance_marital_status ==
  'married'"`
- Serveur (`res_partner.py:605-616`) :
```python
@api.constrains('microfinance_marital_status', 'microfinance_spouse_id', 'microfinance_spouse_phone')
def _check_spouse_required_if_married(self):
    if not self.env.context.get('microfinance_context'):
        return
    for partner in self:
        if partner.microfinance_marital_status == 'married' and not (
            partner.microfinance_spouse_id and partner.microfinance_spouse_phone
        ):
            raise ValidationError(_(
                'Le conjoint et son téléphone sont obligatoires pour un client marié.'
            ))
```
Le garde `if not self.env.context.get('microfinance_context'): return` existe uniquement parce
que `res.partner` est un modèle **partagé** avec EAT/MIIA (contrainte non-négociable rappelée en
tête de la demande). **Sans objet pour `microfinance.credit.committee.review`** : ce nouveau
modèle serait entièrement propre à `microfinance_loan_management` (comme `microfinance.loan.
application` elle-même), aucun risque de contamination cross-module - pas de garde de contexte
à prévoir pour cette raison précise.

---

## 4 — Patterns One2many existants comparables

**Deux styles bien distincts déjà en place dans ce module, pour deux besoins différents :**

**Style A — One2many généré par le système, jamais saisi ligne par ligne par l'utilisateur**
(`installment_ids` sur `microfinance.loan`, `scoring_line_ids` sur le scoring) : rendu en
`<tree readonly="1">`, les lignes sont créées par du code Python (`_build_installment_commands`,
moteur de scoring), jamais via "Ajouter une ligne". **Ne correspond pas au besoin Comité
d'Octroi** : les lignes de décision sont saisies par les membres du comité, pas générées.

**Style B — One2many de cardinalité fixe et faible, jamais exposé comme liste éditable :
"emplacements" (slots) via des Many2one dédiés + champs `related`, rendu en cartes.** C'est le
pattern le plus directement comparable, et **répond très concrètement à la préoccupation "Section
VI" mentionnée dans la demande**.

`field_visit_ids` (Section VI, VAD/VAV/Contre-VAD/Contre-VAV - `microfinance_loan_application.py:485`)
est bien un `One2many`, mais **jamais rendu comme tel dans le formulaire**. Le modèle expose 4
`Many2one` fixes (`vad_visit_id`, `contre_vad_visit_id`, `vav_visit_id`, `contre_vav_visit_id`),
garantis présents par `_ensure_field_visit_slots()` (appelée uniquement depuis `create()`), et
c'est à travers eux que le formulaire expose des champs `related=` (`vad_agent_id = fields.
Many2one(related='vad_visit_id.agent_id', ...)`, etc.), affichés en cartes CSS
(`.o_microfinance_score_grid`, `display: grid`) et non en `<tree>`. Le commentaire du code est
explicite sur la raison (`microfinance_loan_application.py:488-495`) :
> "Permet d'exposer les champs de chaque visite directement sur le formulaire (via les related
> ci-après) en layout 'carte' [...] plutôt qu'un tableau où le label n'existe qu'une fois dans
> l'en-tête de colonne — **la mise en page demandée par Micka n'est atteignable qu'en sortant du
> rendu `<tree>`**."

**Implication directe pour ce chantier, sans remettre en cause la décision n°4 déjà actée** : le
modèle de stockage `microfinance.credit.committee.review` en `One2many` (décidé) est
**parfaitement compatible** avec ce pattern - `field_visit_ids` EST aussi un One2many en
dessous. La question ouverte n'est donc pas "One2many ou pas" (déjà tranché), mais **comment le
formulaire l'expose** : un `<tree>` éditable classique (jamais utilisé ailleurs sur ce formulaire
pour une saisie utilisateur directe de ce type), ou le pattern "slots" déjà établi et
explicitement motivé par une préférence de mise en page de Micka sur ce même formulaire. Vu que
la fiche papier montre exactement 2 blocs fixes ("1er comité", "2ème comité conditionnel"), la
cardinalité est du même ordre que les 4 slots VAD/VAV (fixe, petite, connue à l'avance) - le
pattern "slots" semble transposable presque tel quel (2 `Many2one` : `first_committee_review_id`
et `second_committee_review_id`, plus quelques `related=`), **avec une différence structurelle
notable à traiter au Lot 1** : les 4 slots VAD/VAV sont créés **inconditionnellement** à la
création du dossier ; le 2ème comité, lui, n'a de sens que si le 1er est refusé (règle métier
déjà actée) - `_ensure_field_visit_slots()` ne peut donc pas être copiée telle quelle,
`_ensure_committee_review_slots()` devrait créer le 1er slot à la création (ou à l'entrée en
Section VIII) et le 2ème seulement à la demande (bouton conditionnel, ou onchange sur la
décision du 1er) - à concevoir au Lot 1, pas un obstacle mais pas un simple copier-coller non
plus.

Ceci répond au point 4 de la demande : la préoccupation "Section VI" **a bien des implications
directes ici**, et elles sont plutôt éclairantes qu'un écueil - elles orientent vers un pattern
déjà motivé par une préférence connue de Micka sur ce même formulaire, plutôt que vers un
`<tree>` générique qui serait le premier de ce type sur ce formulaire pour une saisie utilisateur
directe.

---

## 5 — Contrainte "commentaire obligatoire si refusé"

Déjà traité en détail au point 3 ci-dessus (le précédent le plus pertinent, conjoint/marié, est
transversal aux points 3 et 5 de la demande - même code cité, pas dupliqué ici). Résumé du
pattern à réutiliser :
- **Vue** : `required="decision == 'refuse'"` sur le champ commentaire (première ligne de
  défense, ergonomique).
- **Serveur** : `@api.constrains('decision', 'comment')` levant `ValidationError` si
  `decision == 'refuse' and not comment` (deuxième ligne de défense, bloque aussi
  import/API - style déjà établi dans le module, cf. `_check_spouse_required_if_married` et
  `_check_fond_credit_id_locked_after_disbursement`).

Pas de garde de contexte `microfinance_context` nécessaire (modèle non partagé, cf. point 3).

---

## Incohérences/ambiguïtés détectées par rapport aux "décisions déjà actées"

1. **Ambiguïté de sens du groupe réutilisé** (décision n°1) — développée en détail au point 1 :
   `group_microfinance_credit_committee` gouverne déjà deux étapes distinctes (Avis CA, Avis
   CDAG) sans les différencier ; le réutiliser pour une **troisième** étape (Décision d'Octroi)
   accentue cette indifférenciation. Décision non remise en cause, ambiguïté signalée comme
   demandé.
2. **Aucune incohérence détectée sur les décisions n°2 à n°5** : le modèle cible
   (`microfinance.loan.application`), le mécanisme de double protection (groupe vue + contrainte
   serveur), la structure One2many, et le widget radio sont tous cohérents avec les patterns
   déjà en place dans le module (détaillés points 2 à 5 ci-dessus) - aucun d'entre eux ne
   contredit un choix déjà fait ailleurs dans le projet.

---

## Proposition de nom pour le nouveau modèle

`microfinance.credit.committee.review` (nom de la demande) est cohérent avec les conventions de
nommage déjà en place dans ce module (`microfinance.loan.application.field.visit`,
`microfinance.loan.application.income.line`, etc. - `microfinance.<domaine>.<sous-objet>`).
**Alternative à considérer, pas recommandée à la place, juste signalée** :
`microfinance.loan.application.committee.review` (préfixé par le modèle parent, comme
`field.visit`/`income.line`/`document.line` le sont tous) serait plus strictement cohérent avec
la convention DE CE MODULE SPÉCIFIQUE (tous les modèles enfants de `microfinance.loan.
application` sont préfixés ainsi, aucun n'utilise `microfinance.credit.*` comme préfixe -
recherche : aucun modèle `microfinance.credit.*` n'existe actuellement dans le projet). Les deux
noms sont utilisables ; le second colle davantage au pattern immédiatement voisin sur ce même
modèle. Décision à Micka.

---

## Proposition de structure de champs pour le Lot 1 (non implémentée)

Sur le nouveau modèle (nom à confirmer ci-dessus) :

```python
application_id = fields.Many2one('microfinance.loan.application', required=True, ondelete='cascade')
committee_number = fields.Selection([('first', '1er comité'), ('second', '2ème comité')], required=True)
review_date = fields.Date(required=True, default=fields.Date.context_today)
decision = fields.Selection([
    ('accepted', 'Accepté'), ('refused', 'Refusé'), ('postponed', 'Reporté'),
    # 2ème comité : 'postponed' non proposé (pas de report au 2ème passage, décision actée n°5/paper)
], required=True, widget='radio')
postpone_reason = fields.Selection([
    ('vad', 'VAD'), ('vav', 'VAV'), ('incomplete_file', 'Dossier incomplet'),
    ('activity_analysis', 'Analyse activité'), ('prior_repayment_issue', 'Problème remboursement prêt précédent'),
])  # visible/requis seulement si decision == 'postponed', 1er comité seulement
comment = fields.Text()  # required si decision == 'refused', cf. point 5
```
Sur `microfinance.loan.application` : deux `Many2one` slots (`first_committee_review_id`,
`second_committee_review_id`, readonly, copy=False - même style que `vad_visit_id` etc.) plutôt
qu'exposer `committee_review_ids` en `<tree>` (cf. point 4). "Complément sur ..." mentionné dans
la fiche papier de la demande n'est pas assez précis pour proposer un champ ici - **question
ouverte ci-dessous**.

---

## Questions ouvertes pour Micka avant le Lot 1

1. **Nom du modèle** : `microfinance.credit.committee.review` (demande) ou
   `microfinance.loan.application.committee.review` (convention stricte du module, cf.
   ci-dessus) ?
2. **"Complément sur ..."** de la fiche papier (section non précisée dans la demande, coupée par
   "...") : quel est le champ manquant ? Impossible à proposer une structure sans ce détail.
3. **`postpone_reason`** : Selection à choix unique ou Many2many (plusieurs raisons de report
   cumulables) ? La fiche papier liste 5 raisons sans préciser si elles sont exclusives.
4. **Rendu "slots" (2 Many2one) vs `<tree>` éditable** (point 4) : le pattern Section VI motivé
   par une préférence de mise en page connue de Micka semble transposable, mais c'est un choix
   de conception à confirmer explicitement avant de l'appliquer à un nouveau contexte (comité
   d'octroi ≠ visite terrain).
5. **Ambiguïté du groupe réutilisé** (point 1) : à confirmer consciemment que
   `group_microfinance_credit_committee` doit aussi gouverner la Section VIII, malgré son usage
   déjà établi (et déjà signalé comme indifférencié) pour Avis CA/CDAG - ou si un sous-groupe/
   une distinction devient nécessaire à ce stade.
6. **Droits d'accès du groupe** (point 1, `ir.model.access.csv` actuel = lecture seule sur
   `microfinance.loan`) : à vérifier/étendre explicitement au Lot 1 pour le nouveau modèle
   (write=1 nécessaire pour que les membres du comité puissent réellement saisir une décision).
