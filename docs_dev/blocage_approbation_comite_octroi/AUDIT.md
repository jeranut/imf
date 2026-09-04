# Audit (Lot 0) — Blocage de l'approbation si le Comité d'Octroi n'accepte pas

Audit en lecture seule. **Aucune modification de code, de vue ou de donnée.** Vérifié sur le
dépôt (`microfinance_loan_management/models/microfinance_loan.py`, `microfinance_loan_
application.py`, `security/ir.model.access.csv`, `tests/test_credit_committee_review.py`) et
sur la base réelle SEFOR (lecture seule).

## Section 1 — État réel du chantier Comité d'Octroi (préalable bloquant)

**Confirmé : réellement implémenté en base de code, pas seulement audité/maquetté.** Le modèle
`microfinance.credit.committee.review` existe (`microfinance_loan_application.py:1823-1879`,
classe complète avec champs, deux `@api.constrains`), les slots et champs `related` Section VIII
existent sur `microfinance.loan.application` (lignes 747-820), la vue (`<group string="VIII —
Comité d'octroi">`, groupée par `groups=`), les droits d'accès (`ir.model.access.csv`) et une
suite de tests dédiée (`tests/test_credit_committee_review.py`) sont tous présents. **Ce
chantier vient d'être commité** (commit du jour, avec le reste des lots récents) - avant cela,
il ne vivait qu'en modifications non commitées de la session précédente ; désormais réellement
intégré à l'historique git.

**Correction préalable au périmètre de la demande** : les valeurs du champ de décision ne sont
**pas** `accepte`/`refuse`/`reporte` comme supposé, mais **`accepted`/`refused`/`postponed`**
(clés techniques anglaises, libellés français `Accepté`/`Refusé`/`Reporté` - à utiliser tels
quels dans toute condition/contrainte du Lot 1).

**Découverte critique, non anticipée par la demande, directement pertinente pour le Lot 1** :
**aucune décision de comité n'existe nulle part dans SEFOR** - la table `microfinance_credit_
committee_review` est **vide (0 ligne)**, et les deux seuls dossiers réels de la base
(applications liées à IS/000289 et IS/001076) **n'ont même pas de 1er emplacement de comité
créé** (`first_committee_review_id` NULL sur les deux, vérifié en base), alors que le mécanisme
cense le garantir (`_ensure_committee_review_slot()`, appelée depuis `create()`). **Cause
identifiée avec certitude** : ces deux dossiers ont été créés (16 et 25 août) **avant** que le
code du Comité d'Octroi ne soit chargé par l'instance - `_ensure_committee_review_slot()` n'est
appelée qu'à la création d'un nouveau dossier, jamais rétroactivement sur les dossiers
existants (même limite déjà rencontrée et documentée sur le Lot "Épargne exigée CA/CDAG" : un
mécanisme nouveau ne s'applique jamais rétroactivement aux enregistrements déjà en base sans
script de rattrapage explicite). **Conséquence directe pour le Lot 1** : appliqué tel quel
aujourd'hui, un blocage à l'approbation empêcherait l'approbation des deux seuls dossiers
réels existants, dans un état "aucune décision" indiscernable côté utilisateur d'un vrai refus
- à signaler explicitement à Micka (cf. tableau de cas en section 5, et note finale).

## Section 2 — Lien `microfinance.loan` ↔ `microfinance.loan.application`

**Champ confirmé** : `microfinance.loan.application_ids` = `One2many('microfinance.loan.
application', 'loan_id')` (`microfinance_loan.py:148`) ; champ inverse `microfinance.loan.
application.loan_id` = `Many2one('microfinance.loan', ...)` (`microfinance_loan_
application.py:99`). Chemin exact pour retrouver le dossier depuis le crédit : `loan.
application_ids`.

**Ambiguïté réelle, pas seulement théorique** : `application_ids` est un **One2many**, pas un
`One2one` - **rien dans le modèle n'empêche structurellement plusieurs dossiers d'instruction
pour un même crédit** (pas de contrainte SQL, pas de `@api.constrains` d'unicité sur `loan_id`,
recherche exhaustive confirmée). Le seul point de création actuel, `action_view_applications()`
(`microfinance_loan.py:1786-1806`), **évite lui-même la duplication** en ouvrant le premier
dossier existant (`self.application_ids[:1]`) plutôt que d'en recréer un - mais cette protection
ne vaut que pour CE bouton précis ; une création directe (API, import, autre point d'entrée
futur) avec `loan_id` déjà renseigné ne serait pas bloquée.

**Vérifié en base sur les 2 seuls crédits réels de SEFOR** : chacun a exactement UN dossier lié
(IS/000289 → application id 1154 ; IS/001076 → application id 1319), et une recherche
exhaustive (`GROUP BY loan_id HAVING count(*) > 1`) confirme **zéro doublon dans toute la base**
à ce jour. Le risque est donc réel dans l'absolu (rien ne l'empêche structurellement) mais **pas
encore matérialisé** - aucun cas ambigu à traiter aujourd'hui, mais le Lot 1 devra décider quoi
faire si `application_ids` contenait plus d'un enregistrement (prendre le premier ? le plus
récent ? bloquer par prudence ?) plutôt que de supposer silencieusement l'unicité.

## Section 3 — Implémentation actuelle du bouton "Approuver"

**Méthode confirmée : `action_approve()`** (`microfinance_loan.py:786-787`) :

```python
def action_approve(self):
    self.write({'state': 'approved', 'approval_date': fields.Date.context_today(self)})
```

**Aucun garde-fou existant, au-delà de la visibilité du bouton en vue.** La méthode elle-même ne
contient aucune condition, aucune vérification, aucun appel à une méthode de contrôle (contraste
net avec `action_disburse()`, qui enchaîne plusieurs `_check_*()` avant de décaisser). Le seul
filtre actuel est le `invisible="state != 'avis_cdag'"` du bouton en vue (+ `groups=
"...group_microfinance_manager"`, restriction d'accès, pas une règle métier) - donc le seul
pré-requis actuel pour approuver est que `state == 'avis_cdag'`. Rien sur le Comité d'Octroi, ni
sur aucune autre condition métier.

## Section 4 — Champs de décision du Comité d'Octroi

| Emplacement | Champ décision (accès direct) | Champ décision (via `related`, sur `loan.application`) |
|---|---|---|
| 1er comité | `microfinance.credit.committee.review.decision` (sur l'enregistrement `first_committee_review_id`) | `committee_first_decision` (`related='first_committee_review_id.decision'`, readonly=False) |
| 2ème comité | même champ `decision`, sur l'enregistrement `second_committee_review_id` | `committee_second_decision` (`related='second_committee_review_id.decision'`) |

**Un seul champ `decision` (Selection), partagé entre 1er et 2ème comité** - pas deux champs
distincts au niveau du modèle enfant ; la distinction se fait par `committee_number` (`'first'`/
`'second'`) sur l'enregistrement, pas par le nom du champ.

**Valeurs confirmées** : `decision = fields.Selection([('accepted', 'Accepté'), ('refused',
'Refusé'), ('postponed', 'Reporté')], ...)` - **les trois valeurs sont techniquement
disponibles sur le 2ème comité aussi** (même champ, même modèle), **mais `postponed` y est
rejeté par une contrainte serveur dédiée** :

```python
@api.constrains('committee_number', 'decision')
def _check_second_committee_no_postpone(self):
    for review in self:
        if review.committee_number == 'second' and review.decision == 'postponed':
            raise ValidationError(_(
                "Le 2ème comité d'octroi ne peut pas avoir la décision 'Reporté' - seul le "
                "1er comité peut reporter."
            ))
```

Confirmé : **la règle "2ème comité = Accepté/Refusé uniquement" est déjà activement garantie
côté serveur**, pas seulement une intention de vue - le Lot 1 peut s'appuyer dessus sans avoir à
revalider cette contrainte lui-même.

**Règle d'apparition du 2ème comité, confirmée** : `action_add_second_committee_review()`
(`microfinance_loan_application.py:775-791`) ne crée le 2ème emplacement **que si** `first_
committee_review_id.decision == 'refused'` (sinon `UserError` explicite), doublée d'une
contrainte serveur équivalente sur le modèle enfant, `_check_second_committee_requires_first_
refused` (ligne 1881-1890) - garantie réelle même hors bouton (import, API). Une contrainte
symétrique, `_check_first_committee_decision_consistency` (ligne 1892-1906), empêche également
de faire "disparaître" la justification d'un 2ème comité déjà créé en changeant après coup la
décision du 1er comité - cohérence globale déjà bien verrouillée, rien à ajouter pour le Lot 1
de ce côté.

## Section 5 — Tableau des cas de figure pour le Lot 1

| Cas | 1er comité | 2ème comité | Décision effective | Remarque |
|---|---|---|---|---|
| 1 | `accepted` | — | **Acceptée** | Cas nominal simple |
| 2 | `refused` | `accepted` | **Acceptée** | Cas nominal avec recours |
| 3 | `refused` | `refused` | **Non acceptée** | — |
| 4 | `refused` | non créé (`second_committee_review_id` vide) | **Non acceptée** | Le 2ème comité n'a peut-être pas encore été convoqué - à distinguer d'un vrai refus définitif dans le message d'erreur si possible |
| 5 | `refused` | créé mais `decision` vide (en attente) | **Non acceptée** | Décision en cours, pas encore rendue |
| 6 | `postponed` | (n'existe pas, règle 2ème comité = refus uniquement) | **Non acceptée** | Pas de décision finale par construction |
| 7 | vide/`False` (slot existe mais rien sélectionné) | — | **Non acceptée** | Distinct du cas 8 en base (le slot existe, juste vide) mais indiscernable pour l'utilisateur |
| 8 | **`first_committee_review_id` lui-même absent** (slot jamais créé) | — | **Non acceptée** | **Cas réel et actuel des 2 seuls dossiers de SEFOR** (section 1) - à ne pas confondre avec un refus : ici, personne n'a même eu l'occasion de statuer |

**Cas non prévu par la demande, identifié pendant l'audit** : les cas 7 et 8 (décision jamais
posée) sont traités identiquement à un refus authentique (cas 3) par la logique proposée en
section 5 de la demande ("Aucun comité renseigné du tout → non acceptée") - cohérent avec
l'intention métier (pas d'approbation sans décision positive explicite), mais le **message
d'erreur** devrait probablement distinguer ces cas ("aucune décision enregistrée" vs "le comité
a refusé ce dossier") pour ne pas laisser croire à un refus qui n'a jamais eu lieu - point à
valider avec Micka, pas tranché ici.

**Cas de l'ambiguïté multi-dossiers (section 2)** : non couvert par le tableau ci-dessus, à
traiter séparément - que faire si `loan.application_ids` contient plus d'un enregistrement au
moment de l'approbation ? Aucune occurrence réelle en base aujourd'hui, mais le Lot 1 devra
choisir un comportement explicite plutôt que de supposer silencieusement `application_ids[:1]`.

## Proposition de message d'erreur

Deux variantes possibles (à trancher avec Micka) :

**Variante simple (un seul message générique)** :
```
Impossible d'approuver le crédit {référence} : le comité d'octroi n'a pas accepté ce dossier.
Contactez le support technique si cette décision doit être révisée.
```

**Variante détaillée (distingue "jamais statué" de "refusé")**, recommandée au vu de la
découverte de la section 1 (les deux seuls dossiers réels sont aujourd'hui dans le cas "jamais
statué", pas "refusé") :
```
Impossible d'approuver le crédit {référence} : {détail}. Contactez le support technique si
cette décision doit être révisée.
```
où `{détail}` vaut par exemple *"aucune décision du comité d'octroi n'a encore été enregistrée
sur le dossier d'instruction"* (cas 7/8), *"le comité d'octroi a reporté sa décision"* (cas 6),
ou *"le comité d'octroi a refusé ce dossier"* (cas 3/4/5).

Stop après ce rapport, conformément à la consigne.
