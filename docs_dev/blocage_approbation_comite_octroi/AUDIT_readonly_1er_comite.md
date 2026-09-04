# Audit — Pourquoi le 1er Comité d'Octroi est en lecture seule

Audit en lecture seule (code + `ir.model.fields` + vérification empirique via `odoo-bin shell`).
**Aucune modification apportée.**

## Cause racine confirmée avec certitude (piste 3, en réalité)

**Les 8 champs (`committee_first_review_date/decision/postpone_reason/complement/comment` et
`committee_second_review_date/decision/comment`) sont réellement `readonly=True` au niveau
Python, en base, pour TOUT dossier, indépendamment de l'état, du groupe de sécurité ou du slot
comité** - vérifié à la fois par lecture de `ir_model_fields` (colonne `readonly = t` pour les 8
champs) et empiriquement via `odoo-bin shell` (`Model._fields['committee_first_decision'].
readonly` renvoie `True`, `inverse` renvoie `None`).

**Ce n'est pas le bug déjà connu (`_inverse_related`, échec silencieux) - c'est une
régression différente, introduite par le correctif qui a justement corrigé celui-là.**

Cause exacte, dans `odoo/fields.py::Field._get_attrs()` (framework, pas ce dépôt) :
```python
if attrs.get('compute'):
    ...
    attrs['readonly'] = attrs.get('readonly', not attrs.get('inverse'))
```
**Un champ `compute=` sans `readonly=` explicite ET sans `inverse=` devient automatiquement
`readonly=True`** - règle du framework, pas une intention de vue ni un `readonly=` écrit
quelque part dans le dépôt (confirmé : aucun `readonly=` n'apparaît dans la vue XML pour ces 8
champs, ni dans leur déclaration Python actuelle).

Ces 8 champs ont été convertis de `related=` vers `compute=` (Lot 1.1 du chantier "blocage
approbation comité d'octroi", `docs_dev/blocage_approbation_comite_octroi/STATUS_LOT1_1.md`)
précisément pour corriger l'échec
silencieux `_inverse_related`. Cette conversion s'est faite en 3 étapes (documentées dans ce
même STATUS) ; la version finale retenue (écriture interceptée dans `write()`, plus aucun
`inverse=` sur les champs eux-mêmes) a **omis de repasser `readonly=False` explicitement** sur
les 8 déclarations - un oubli, pas un choix délibéré. Sans `inverse=`, la règle du framework
ci-dessus impose `readonly=True` par défaut, ce qui **rend le correctif Lot 1.1 totalement
inopérant côté formulaire** : le client web n'envoie jamais la valeur d'un champ qu'il perçoit
comme readonly, donc l'interception dans `write()` (qui fonctionne correctement si on l'appelle
directement en Python, cf. les 4 tests du Lot 1.1 qui passent) n'est **jamais atteinte** depuis
l'écran.

## Réponses aux pistes demandées

**1. `_LOCKED_DOSSIER_STATES`** : sans rapport. Ce mécanisme (`microfinance_loan.py:304-335`)
vit sur `microfinance.loan` (le crédit), verrouille uniquement `{loan_amount, term, product_id,
interest_rate, installment_amount}`, et **lève une `ValidationError` à l'écriture** (mécanisme
serveur actif), il ne positionne aucun `readonly=` de champ ni de vue. Aucun champ du comité
d'octroi n'y figure. `propagation_avis_ca_cdag` est un contexte interne à ce mécanisme, sans
lien avec le comité d'octroi.

**2. Guard logic / slot NULL** : n'explique pas le symptôme observé. Un `first_committee_
review_id` NULL (cas legacy IS/000289, IS/001076) n'a **aucun effet sur le `readonly` du
champ** - `readonly` est une propriété statique du champ Python (`_get_attrs`, ci-dessus),
évaluée une fois à l'enregistrement du modèle, pas dynamiquement selon qu'un Many2one lié existe
ou non. Le dossier en capture est donc en lecture seule **que le slot existe ou non** - à vérifier
séparément lequel des deux (legacy ou nouveau) c'est, mais cela ne change rien au diagnostic.

**3. Attributs `readonly` en vue** : **aucun** `readonly=` explicite trouvé dans
`microfinance_loan_application_views.xml` sur `committee_first_decision`/`_complement`/
`_comment` (confirmé par recherche exhaustive) - la vue n'est pas en cause, la source est
uniquement Python (section précédente).

**4. Sécurité / groupe** : sans rapport avec le symptôme actuel. Le `groups=` sur le `<group
string="VIII — Comité d'octroi">` masquerait le bloc entier (invisible) pour un non-membre, pas
un readonly sur un bloc visible - l'Administrator étant presumé superutilisateur/membre de tous
les groupes, ce n'est de toute façon pas la cause ici (le `readonly` Python s'applique
identiquement à tout utilisateur, y compris un membre du comité).

**5. Serveur non redémarré** : **infirmé pour ce diagnostic**. Le service tourne actuellement
depuis 06:08 (aujourd'hui), soit après les derniers correctifs de cette session - le code en
mémoire correspond bien au code sur disque au moment de cet audit. Le `readonly=True` observé
est donc bien le comportement réel actuellement servi, pas un artefact de code obsolète en
mémoire.

## Cas legacy ou nouveau ?

Sans référence exacte du dossier de la capture, impossible de confirmer si c'est IS/000289,
IS/001076, ou un troisième dossier - **mais cela n'a aucune incidence sur ce diagnostic** : le
`readonly=True` frappe les 8 champs pour absolument tous les dossiers, legacy ou non, slot créé
ou non. Si le dossier de la capture est un des deux cas legacy, il cumule en plus le problème déjà
documenté (silencieux avant Lot 1.1, maintenant readonly après) - mais un dossier avec slot déjà
créé (dossier normal, post-Lot 1.4) serait **tout autant bloqué** par ce readonly, ce qui va
au-delà du périmètre "cas legacy" déjà cartographié.

## Conclusion

**Point non couvert par le correctif déjà en attente de commit - une régression distincte,
introduite par ce correctif lui-même, jamais testée** (les 4 tests du Lot 1.1 valident la
logique en appelant `write()` directement en Python via l'ORM - `application.write({...})` -,
jamais via un chemin qui distinguerait un champ "readonly côté client" d'un champ réellement
inscriptible : un test ORM direct ne voit jamais cette différence, contrairement à un vrai
formulaire). **Correction triviale une fois identifiée** (ajouter `readonly=False` explicite aux
8 déclarations), mais **non appliquée ici, conformément à la consigne "audit seul, ne rien
corriger"**.

## Correctif appliqué (suite à ce rapport)

`readonly=False` ajouté explicitement aux 8 déclarations (`microfinance_loan_application.py`).
Nouveau test de régression (`test_committee_fields_are_not_readonly`, `tests/
test_committee_review_lazy_slot.py`) - vérifie `Model._fields[...].readonly is False` pour les
8 champs, exactement le type d'assertion qui aurait détecté ce bug (un `write()` ORM direct,
utilisé par tous les autres tests du chantier, ne le révèle pas).

**Tests** : 24/24 sur les tests ciblés du comité (dont le nouveau). Suite complète des deux
modules : 608 tests (+1), liste des échecs/erreurs strictement identique avant/après (diff vide,
89 éléments = 88 pré-existants + 1 flakiness déjà confirmée sans rapport, cf. `docs_dev/
epargne_exigee_disponible/STATUS.md`) - zéro régression. `-u` lancé sur SEFOR sans erreur. Reste
le restart du service côté Micka pour déployer, puis à retester à l'écran pour confirmer.
