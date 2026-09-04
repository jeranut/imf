# Lot 0 (complément) — Diagnostic : message "aucune décision" alors qu'un refus a été saisi

Diagnostic en lecture seule (SQL `SELECT` uniquement sur SEFOR). **Aucune modification de code,
de vue, de donnée. Aucun commit.**

## Résultat en une phrase

**Ce n'est pas un bug de la garde (`_check_committee_octroi_accepted`) ni de son message : la
logique de blocage est correcte et confirmée par les tests.** Le vrai bug est **en amont** :
saisir une décision sur le 1er comité d'un dossier qui n'a pas de "slot" comité pré-créé (cas des
2 dossiers réels IS/000289 et IS/001076) **échoue silencieusement, sans aucune erreur affichée** -
rien n'est jamais écrit en base, quoi que l'écran ait pu laisser croire à Micka. La garde, elle,
lit la vraie base et rapporte donc à juste titre "aucune décision enregistrée".

**Découverte annexe, plus préoccupante que la question posée** : le code de la garde
`action_approve` / `_check_committee_octroi_accepted` **n'est commité nulle part** dans
l'historique git (recherche exhaustive, `git log --all -S`) - il n'existe que dans les
modifications non committées du dépôt, documentées au Lot 1 (`STATUS.md`, "Arrêt obligatoire ...
avant tout déploiement"). Pourtant il tourne bel et bien en production : le service `odoo17` n'a
pas été redémarré depuis le redémarrage du 28/08 10:32 (confirmé par `systemctl`/`ps`, code
process actif en continu depuis), et Odoo (workers=0) charge le code Python présent sur disque
**au démarrage du process, sans distinguer committé/non committé** - tout redémarrage antérieur au
28/08 a donc mis en production ce code non committé sans que "l'arrêt obligatoire" documenté au
Lot 1 n'ait été respecté. À traiter séparément (voir recommandation finale).

## 1. Localisation du code de la garde

```
$ grep -rn "aucune décision du comité d'octroi" microfinance_loan_management/
microfinance_loan_management/models/microfinance_loan.py:807:
```

Fichier : `microfinance_loan_management/models/microfinance_loan.py`, méthodes `action_approve()`
et `_check_committee_octroi_accepted()` (lignes 786-816, **modifications non committées** -
`git diff` confirme, `git log --all -S "aucune décision du comité d'octroi"` ne retourne aucun
commit). Aucun autre endroit du dépôt ne contient ce message.

## 2. Code exact de la garde (état actuel, non committé)

```python
def action_approve(self):
    for loan in self:
        loan._check_committee_octroi_accepted()
    self.write({'state': 'approved', 'approval_date': fields.Date.context_today(self)})

def _check_committee_octroi_accepted(self):
    self.ensure_one()
    application = self.application_ids[:1]
    if not application:
        raise UserError(_(
            "Impossible d'approuver le crédit %(loan)s : aucun dossier d'instruction "
            "n'existe pour ce crédit, le comité d'octroi n'a donc rendu aucune décision. "
            "Contactez le support technique si cette décision doit être révisée."
        ) % {'loan': self.name})
    first = application.first_committee_review_id
    if not first or not first.decision:
        detail = _("aucune décision du comité d'octroi n'a encore été enregistrée sur le dossier d'instruction")
    elif first.decision == 'accepted':
        return
    elif first.decision == 'postponed':
        detail = _("le comité d'octroi a reporté sa décision")
    else:  # 'refused'
        second = application.second_committee_review_id
        if second and second.decision == 'accepted':
            return
        detail = _("le comité d'octroi a refusé ce dossier")
    raise UserError(_(
        "Impossible d'approuver le crédit %(loan)s : %(detail)s. Contactez le support "
        "technique si cette décision doit être révisée."
    ) % {'loan': self.name, 'detail': detail})
```

**Hypothèse "condition générique `!= 'accepted'`" infirmée.** La condition distingue bien les 4
cas (absent, accepté, reporté, refusé), et la branche "refusé" existe réellement (pas une branche
morte) - elle est directement couverte par un test qui passe :
`test_blocked_when_first_refused_and_no_second` (`tests/test_committee_octroi_approval_guard.py`),
qui pose explicitement `decision='refused'` sur `first_committee_review_id` et vérifie que le
`UserError` est bien levé (le test ne vérifie pas le texte exact du message, seulement le blocage -
mais le code montre sans ambiguïté que la branche "refusé" serait atteinte et produirait le bon
texte si `first.decision == 'refused'` en base). Le problème n'est donc pas dans cette méthode.

## 3. Vérification en base (lecture seule) — pourquoi la branche "refusé" n'est jamais atteinte

```sql
SELECT l.id, l.name, l.state, a.id AS app_id,
       a.first_committee_review_id, a.second_committee_review_id
FROM microfinance_loan l
LEFT JOIN microfinance_loan_application a ON a.loan_id = l.id
WHERE l.name = 'IS/001076';
```
```
 loan_id |   name    |   state   | app_id | first_committee_review_id | second_committee_review_id
---------+-----------+-----------+--------+---------------------------+----------------------------
    2327 | IS/001076 | avis_cdag |   1319 |     (NULL)                |     (NULL)
```

```sql
SELECT count(*) FROM microfinance_credit_committee_review;
-- 0
```

**Confirmé, sans ambiguïté : aucune ligne n'existe dans `microfinance_credit_committee_review`,
pour aucun dossier de toute la base.** Le lien `loan` ↔ `application` lui-même est correct (1
seul dossier IS/001076 → application id 1319, pas de doublon, cohérent avec l'audit Lot 0) : ce
n'est donc ni un problème de relation, ni un dossier dupliqué. Le "Refusé" saisi par Micka **n'a
jamais été écrit en base**, quelle que soit l'impression donnée par l'écran après rechargement.

## 4. Origine du champ et cause racine réelle

`committee_first_decision` (le champ affiché en Section VIII du formulaire) est un champ
`related` **non stocké** :

```python
first_committee_review_id = fields.Many2one(
    'microfinance.credit.committee.review', string='1er comité d\'octroi', readonly=True, copy=False)
committee_first_decision = fields.Selection(
    related='first_committee_review_id.decision', string='Décision', readonly=False)
```
(`microfinance_loan_application.py:748-757`)

Ce n'est **pas** un problème de cache ni de `@api.depends` manquant (`related` n'a pas besoin de
`@api.depends`, il se recalcule toujours à la lecture). Le vrai mécanisme en cause est
**l'inverse par défaut d'un champ `related`**, dans le framework Odoo lui-même
(`odoo/fields.py:713-722`, `Field._inverse_related`) :

```python
def _inverse_related(self, records):
    for record in records:
        target, field = self.traverse_related(record)
        if target and bool(target.id) == bool(record.id):
            target[field.name] = record_value[record]
```

**Si `target` (ici `first_committee_review_id`) est vide, la condition `if target` échoue et
l'écriture est silencieusement ignorée — sans la moindre erreur.** Odoo ne crée jamais
automatiquement l'enregistrement intermédiaire manquant pour un `related` en écriture.

Or `first_committee_review_id` est justement NULL sur IS/001076 (et sur IS/000289) : c'est
exactement le "cas 8" déjà identifié dans l'audit Lot 0 (`AUDIT.md`, section 1) - ces deux
dossiers ont été créés **avant** le déploiement du Comité d'Octroi, et
`_ensure_committee_review_slot()` (`microfinance_loan_application.py:791-816`) n'est appelée que
depuis `create()`, "jamais depuis `read()`" (commentaire du code lui-même) - **jamais
rétroactivement**. Résultat : sur ces 2 dossiers précis, **le formulaire Section VIII accepte
n'importe quelle saisie (décision, commentaire, date...) sans jamais rien persister**, ce qui est
un bug fonctionnel autrement plus grave que le message de `action_approve` lui-même (silence total
côté utilisateur, aucune indication que la saisie est perdue).

## 5. Une seule chaîne de message, aucune branche cachée

Un seul et unique message générique paramétré par `{détail}` (4 valeurs possibles :
absent/accepté-non atteint car return/reporté/refusé), pas de message "refus définitif" distinct
prévu ailleurs dans le code qui serait court-circuité - vérifié par lecture complète de la
méthode et recherche exhaustive du texte dans le dépôt (section 1).

## Recommandation pour la portée du Lot 1

**Pas une simple correction de message.** Deux chantiers distincts, de nature différente,
apparaissent maintenant nécessaires avant un déploiement sûr :

1. **Le Lot 1 déjà écrit (`STATUS.md`) reste valide tel quel** pour la logique de blocage
   elle-même (accepté/refusé/reporté/2ème comité) - rien à corriger dans
   `_check_committee_octroi_accepted()`, ses 7 tests passent et couvrent bien les 4 branches.
2. **Nouveau point, plus urgent, hors périmètre initial de ce chantier** : corriger le fait que
   **la saisie d'une décision de comité échoue silencieusement** sur tout dossier sans slot
   pré-créé (aujourd'hui : les 2 seuls dossiers réels de SEFOR). Pistes possibles à trancher avec
   Micka, aucune tranchée ici (lecture seule) :
   - Appeler `_ensure_committee_review_slot()` de façon paresseuse (ex. dans un `write()` surchargé
     de `microfinance.loan.application`, ou via un bouton dédié) plutôt que seulement à la création,
     pour que la saisie fonctionne aussi sur les dossiers legacy ;
   - Et/ou lever une erreur explicite si l'utilisateur tente d'écrire un `committee_first_decision`
     sans slot existant, plutôt que de laisser l'échec silencieux actuel (mauvaise UX à corriger
     dans tous les cas, indépendamment de la solution retenue) ;
   - Script de rattrapage ponctuel pour créer le slot manquant sur les 2 dossiers réels
     (option déjà évoquée au `STATUS.md` du Lot 1, option B).

**Sans ce correctif, même une fois le Lot 1 (garde `action_approve`) validé et déployé
proprement, Micka ne pourra toujours pas faire accepter ou refuser IS/000289 et IS/001076 via
l'écran** - la garde bloquera indéfiniment ces 2 dossiers, non pas parce que la règle métier est
mal implémentée, mais parce que rien ne peut être saisi dessus du tout.

## Point de process à signaler séparément

Le code de la garde `action_approve` (Lot 1) tourne actuellement en production sans avoir jamais
été committé, en violation de la règle "arrêt obligatoire avant tout déploiement" suivie sur tous
les lots précédents - probablement parce qu'un redémarrage du service (le 28/08, pour une autre
raison) a chargé l'état du disque à ce moment-là, disque qui contenait déjà ces modifications non
committées. À signaler à Micka : soit committer ce Lot 1 maintenant qu'il est validé (tests
7/7, zéro régression, cf. `STATUS.md`), soit le retirer explicitement du disque si un retour en
arrière est souhaité - le laisser non committé mais actif en production est le pire des deux
mondes (aucune traçabilité, aucun filet de sécurité en cas de restart involontaire perdant le
fichier).
