# AUDIT — Perte apparente du motif d'écart et du comptage à la clôture de session de caisse

Statut : diagnostic terminé, **aucun correctif appliqué**. En attente de validation avant toute
modification/commit.

## 1. `git status` / `git diff` — code non committé

`/opt/odoo17_2/custom_addons` est bien un dépôt git (contrairement à `/opt/odoo17_2` à la
racine). Le flux en 3 temps observé en production (comptage → récapitulatif → écart) existe
uniquement dans l'arbre de travail, **non committé, non poussé** :

```
Changes not staged for commit:
	modified:   microfinance_loan_management/wizard/microfinance_caisse_close_session_wizard.py
	modified:   microfinance_loan_management/wizard/microfinance_caisse_close_session_wizard_views.xml
	modified:   microfinance_loan_management/models/microfinance_caisse_session.py
	modified:   microfinance_loan_management/models/microfinance_caisse_comptage.py
	modified:   microfinance_loan_management/static/src/js/microfinance_caisse_pos.js
	modified:   microfinance_loan_management/static/src/scss/microfinance_caisse_pos.scss
	modified:   microfinance_loan_management/static/src/xml/microfinance_caisse_pos.xml
	modified:   microfinance_loan_management/views/microfinance_caisse_comptage_views.xml
	modified:   microfinance_loan_management/views/microfinance_caisse_session_views.xml
	modified:   microfinance_loan_management/security/ir.model.access.csv
	modified:   microfinance_loan_management/wizard/__init__.py
	... (+ fichiers de tests, hooks.py, migrations/, __manifest__.py — cf. Note ci-dessous)

Untracked files:
	microfinance_loan_management/wizard/microfinance_caisse_open_session_wizard.py
	microfinance_loan_management/wizard/microfinance_caisse_open_session_wizard_views.xml
	... (+ migrations/17.0.1.13.0 à .17.0/, tests/test_caisse_open_wizard.py, etc.)
```

Le diff complet des fichiers `wizard/` et `static/src/` a été inspecté intégralement (voir §2-3
ci-dessous pour les extraits pertinents).

**Note de portée** — une partie des fichiers listés comme modifiés (`hooks.py`,
`models/res_company.py`, `models/microfinance_caisse_comptage.py` lignes 129/178/186-188,
`__manifest__.py`, les migrations `17.0.1.16.0`/`17.0.1.17.0`, `tests/common.py`) provient du
chantier "Compte d'attente écart de caisse" traité juste avant cet audit dans la même session,
déjà déployé sur MOWGLI. Ce n'est PAS le code mystère à investiguer — mais il s'avère être
directement impliqué dans la cause racine trouvée ci-dessous (§3-4). Le code du **flux en 3
temps lui-même** (wizard comptage/récap/écart, JS du guichet, vues) est, lui, entièrement
antérieur à cette session : personne dans cette conversation ne l'a écrit, et il n'existe dans
aucun commit du dépôt `jeranut/imf.git`.

## 2. Localisation de l'écran "Clôturer la session" et de la popup "Écart de caisse"

Un seul wizard Odoo (`TransientModel`) éclaté en **3 classes séquentielles** dans le même
fichier, pas un composant OWL dédié — l'écran "Clôturer la session" (comptage) et la popup
"Écart de caisse" sont deux formulaires Odoo standard (`ir.actions.act_window`, `target: new`)
qui s'enchaînent via des enregistrements `TransientModel` liés par `Many2one`, pas par contexte
ni par champ caché :

| Étape UI | Modèle | Fichier |
|---|---|---|
| 1. "Clôturer la session" (numpad + tableau coupures) | `microfinance.caisse.close.session.wizard` | [wizard/microfinance_caisse_close_session_wizard.py:1-80](../../microfinance_loan_management/wizard/microfinance_caisse_close_session_wizard.py) |
| 2. Récapitulatif (intermédiaire, sans écart) | `microfinance.caisse.close.session.recap.wizard` | même fichier, ~ligne 175 |
| 3. Popup "Écart de caisse" (théorique/compté/écart/motif) | `microfinance.caisse.close.session.variance.wizard` | même fichier, ~ligne 220 |
| Vues des 3 formulaires | — | [wizard/microfinance_caisse_close_session_wizard_views.xml](../../microfinance_loan_management/wizard/microfinance_caisse_close_session_wizard_views.xml) |
| Bouton "Fermer la caisse" (en-tête guichet) | JS | [static/src/js/microfinance_caisse_pos.js:127-141](../../microfinance_loan_management/static/src/js/microfinance_caisse_pos.js) (`openCloseSessionWizard`) |

Point d'entrée unique : le bouton "Fermer la caisse" de l'en-tête du guichet (POS caisse OWL)
appelle `microfinance.caisse.session.action_open_close_wizard()` par RPC (`orm.call` +
`doAction()` sur le dict brut retourné), qui ouvre le temps 1. Le bouton direct sur la fiche
`microfinance.caisse.session` a été retiré (`views/microfinance_caisse_session_views.xml`).

**Transmission des données entre les 3 temps** : chaque wizard porte un `Many2one` vers le
précédent (`source_wizard_id`), jamais de contexte ni de champ caché :
- `recap.wizard.source_wizard_id` → `close.session.wizard` (temps 1)
- `variance.wizard.source_wizard_id` → `close.session.wizard` (temps 1, pas le récap)

`line_ids` (quantités saisies) est un champ **compute, related en lecture** vers
`source_wizard_id.line_ids` sur les temps 2 et 3 — aucune duplication de données, aucune
sérialisation côté client entre les étapes. Ce mécanisme est correct et ne perd rien : les
quantités du temps 1 restent en base (même enregistrement `TransientModel`) tout du long des
3 temps, y compris via `action_back()` qui rouvre le même `source_wizard_id`.

## 3. Trace du bouton "Confirmer la clôture" → couche serveur

- Handler XML : `wizard/microfinance_caisse_close_session_wizard_views.xml`, bouton
  `action_confirm_close` (`type="object"`), sur la vue du wizard `variance.wizard` (temps 3).
- Méthode Python : `MicrofinanceCaisseCloseSessionVarianceWizard.action_confirm_close()`,
  [wizard/microfinance_caisse_close_session_wizard.py:243-276](../../microfinance_loan_management/wizard/microfinance_caisse_close_session_wizard.py#L243).

Séquence exacte (lignes citées dans le fichier actuel) :

```python
243  def action_confirm_close(self):
...
255      if abs(variance) > 0.01 and not (self.variance_comment or '').strip():
256          raise UserError(...)                          # motif manquant -> pas de comptage créé, correct
259      comptage = self.env['microfinance.caisse.comptage'].create({...})   # AVEC variance_comment + line_ids
273      comptage.flush_recordset()
274      comptage._post_variance_move()                     # <-- ICI
275      session.action_close_session()
276      return {'type': 'ir.actions.act_window_close'}
```

`comptage.create()` (ligne 259) construit bien l'enregistrement avec `variance_comment` et les
`line_ids` (quantités par coupure) — **le comptage est correctement créé, avec le motif, avant
tout appel à `action_close_session()`**. Aucun problème à ce niveau : pas de `sudo()` mal
scopé, pas de `try/except` qui avale une exception, pas de `cr.commit()` prématuré.

### La cause racine : `_post_variance_move()` lève une exception qui annule TOUT, y compris le `comptage` qui vient d'être créé

`comptage._post_variance_move()` ([models/microfinance_caisse_comptage.py:114-145](../../microfinance_loan_management/models/microfinance_caisse_comptage.py#L114)) :

```python
129  waiting_account = (company.microfinance_account_ecart_caisse_excedent_id if self.variance > 0
                         else company.microfinance_account_ecart_caisse_deficit_id)
137  if not waiting_account:
138      raise UserError(_(
139          "Configurez le compte d'attente d'écart de caisse (déficit/excédent) sur l'agence "
140          "%(company)s (Paramètres > Sociétés) avant de clôturer une session avec un écart."
141      ) % {'company': company.name})
```

Toute la séquence du bouton (`comptage.create()` + `_post_variance_move()` +
`action_close_session()`) s'exécute dans **la même transaction PostgreSQL** que la requête RPC
`call_button`. Odoo encapsule chaque `call_button` dans une transaction unique : si
`_post_variance_move()` lève `UserError` (ligne 138), tout ce qui a été fait dans la même
requête est **annulé par ROLLBACK**, y compris le `comptage.create()` de la ligne 259 — malgré
le `flush_recordset()` explicite (qui force l'écriture SQL immédiate dans la transaction en
cours, mais ne la committe pas). Résultat : **ni le comptage, ni le motif, ni la ligne de
comptage n'existent nulle part après ce clic** — exactement le symptôme rapporté ("aucune trace
... ni comptage, ni mouvement, ni log", si l'on excepte le message d'erreur lui-même qui, lui,
est bien loggé côté serveur en `WARNING`, cf. §5).

Ce n'est **pas un bug de logique** au sens strict (le rollback est le comportement transactionnel
correct — on ne veut jamais committer un comptage sans sa contrepartie comptable), mais c'est un
**problème produit/UX réel** : l'utilisateur perd tout son travail de comptage (saisie des
coupures + motif) à cause d'une configuration manquante côté société, sans message assez clair
pour comprendre qu'il doit tout ressaisir après correction, ni aucun filet de rattrapage
(brouillon, sauvegarde intermédiaire).

## 4. Vérification en base — reproduction confirmée dans les logs réels de MOWGLI

Deux clics sur "Confirmer la clôture" ont été identifiés dans `odoo.log`, tous deux sur
**CEFOR Ambanidia**, tous deux résultant en la même `UserError` :

```
2026-09-17 16:26:32,584 WARNING MOWGLI odoo.http: Configurez le compte d'attente d'écart de
  caisse sur l'agence CEFOR Ambanidia (Paramètres > Sociétés) avant de clôturer une session
  avec un écart.
2026-09-17 16:30:37,720 WARNING MOWGLI odoo.http: Configurez le compte d'attente d'écart de
  caisse sur l'agence CEFOR Ambanidia (Paramètres > Sociétés) avant de clôturer une session
  avec un écart.
```

Ces deux occurrences précèdent le déploiement (17:27-17:38 le même jour) du chantier "Compte
d'attente écart de caisse" qui a justement rempli automatiquement ces deux champs pour
Ambanidia. **Confirmé en base** :

- Aucune ligne `microfinance.caisse.comptage` n'existe pour aucune session de la société 2
  (Ambanidia) — le comptage n'a effectivement jamais été persisté, les deux tentatives ont
  échoué exactement comme prévu par l'analyse ci-dessus.
- La session du jour (id 7, 2026-09-17, journal 1509) et celle de la veille (id 5,
  2026-09-16) sont **toujours à l'état `open`** — la clôture n'a jamais réussi, la session
  reste bloquée ouverte tant que l'utilisateur ne refait pas la saisie (maintenant possible,
  le compte étant configuré depuis le déploiement de 17:27-17:38).

La donnée n'a donc jamais été "créée puis supprimée" : elle n'a **jamais atteint la base**, le
`ROLLBACK` étant antérieur à tout commit.

### Effet de bord mineur observé (sans lien avec la perte de données)

```
WARNING MOWGLI odoo.models: Model 'microfinance.caisse.close.session.wizard.line' cannot be
  sorted on field 'denomination_value' (not a column)
```

`_order = 'denomination_value desc'` sur `microfinance.caisse.close.session.wizard.line`
référence un champ `related`/compute, pas une colonne réelle — le tri est silencieusement
ignoré (warning à chaque lecture de la liste, jamais bloquant). Sans rapport avec la perte du
comptage, mais à corriger en même temps par hygiène.

## 5. Impact sur les sessions déjà closes

**Aucun impact constaté à ce jour** :

```sql
SELECT state, count(*) FROM microfinance_caisse_session GROUP BY state;
 state | count
-------+-------
 open  |     5
```

Il n'existe **aucune session à l'état `closed`** dans toute la base MOWGLI — la fonctionnalité
de clôture avec comptage n'a encore jamais été utilisée avec succès jusqu'ici, pour aucune
agence. Aucun écart n'a donc pu être "perdu après une clôture réussie" : les seuls échecs
identifiés (Ambanidia) ont laissé la session **ouverte**, pas clôturée à tort.

5 sessions actuellement ouvertes, à vérifier une par une avant de les refermer (certaines
peuvent être ouvertes pour une raison indépendante de ce bug) :

| id | Société | Date | Journal |
|---|---|---|---|
| 7 | CEFOR Ambanidia | 2026-09-17 | 1509 (cause confirmée : ce bug) |
| 5 | CEFOR Ambanidia | 2026-09-16 | 1509 (cause confirmée : ce bug) |
| 1 | CEFOR Isotry | 2026-09-15 | 25 (cause non vérifiée) |
| 2 | CEFOR Mahitsy | 2026-09-15 | 1493 (cause non vérifiée) |
| 3 | CEFOR Sabotsy Namehana | 2026-09-15 | 1477 (cause non vérifiée) |

## 6. Options de correctif (aucune appliquée)

### Option A — Garde préalable côté `action_confirm_close`, avant toute création
Vérifier la présence du compte d'attente adéquat (`deficit_id`/`excedent_id` selon le signe de
l'écart) **avant** `comptage.create()`, avec le même message d'erreur. Le motif et les quantités
restent dans le formulaire du wizard temps 3 (pas encore soumis), donc rien n'est perdu — la
popup reste ouverte, l'utilisateur peut corriger le motif ou (s'il est manager) aller configurer
le compte dans un autre onglet puis revenir cliquer à nouveau sans ressaisir le comptage (le
`TransientModel` du temps 1/3 garde ses valeurs tant que le formulaire n'a pas été fermé).
- **Implication** : correctif minimal (quelques lignes), ne change aucun flux ni modèle. Le
  filet reste imparfait si l'utilisateur ferme la popup avant de corriger (le `TransientModel`
  expire avec le temps/le nettoyage des transients, comme aujourd'hui).

### Option B — Supprimer le blocage dur : comptabiliser l'écart même sans compte configuré, avec un warning
`_post_variance_move()` ne lève plus si le compte est manquant : il logge un warning et
positionne `variance_state` à un état dédié (ex. `sans_compte_configure`) sans poster
d'écriture comptable, à régulariser plus tard par un manager quand le compte existera.
- **Implication** : plus de risque de perte de comptage/motif, mais introduit un état
  transitoire "écart constaté mais non comptabilisé" à gérer partout où `variance_state` est
  actuellement une valeur fermée (`none`/`en_attente`/`reconcilie`) — vue, `action_reconcile_variance`,
  éventuels rapports. Modification de modèle (nouvelle valeur de sélection) + tests à adapter.

### Option C — Revenir à un wizard unique (comme dans le code committé du dépôt)
Fusionner les 3 temps en un seul écran (comptage + écart + motif ensemble), comme le code déjà
committé sur `jeranut/imf.git`. Éliminerait la complexité de l'enchaînement à 3 `TransientModel`,
mais ne résout PAS en soi la cause racine (le `UserError` de `_post_variance_move()` romprait
la transaction de la même façon dans un wizard unique) — à combiner avec l'option A ou B.
- **Implication** : régression fonctionnelle du flux à 3 temps (théorique/écart caché jusqu'au
  bon moment, retour en arrière possible) déjà en place et manifestement voulu (commentaires
  détaillés dans le code, `AUDIT_session_zigzag`/`AUDIT_session_close_3temps` référencés mais
  non trouvés sur le disque — probablement écrits puis jamais committés/sauvegardés ailleurs).
  Ne pas choisir cette option sans confirmer d'abord si ce choix de design (3 temps) doit être
  conservé.

**Recommandation** : Option A seule suffit à éliminer la perte de données observée, sans toucher
au flux à 3 temps ni à la logique comptable. Option B peut être envisagée en complément si l'on
veut aussi permettre une clôture "provisoire" en attendant la configuration du compte — à
discuter séparément.

## Résumé exécutable en une phrase

`_post_variance_move()` (models/microfinance_caisse_comptage.py:137-141) lève `UserError`
quand le compte d'attente écart de caisse n'est pas configuré pour la société ; comme cet appel
a lieu **après** `comptage.create()` dans la même transaction (action_confirm_close(), wizard
temps 3, ligne 274), l'exception fait annuler par ROLLBACK tout ce qui vient d'être créé,
donnant l'impression que le comptage et le motif ont "disparu" — alors qu'ils n'ont en réalité
jamais été committés. Reproduit et confirmé dans les logs réels (CEFOR Ambanidia, 17/09 16:26
et 16:30), avant le déploiement du chantier qui a résolu la cause immédiate (compte manquant)
pour cette société précise — le risque de perte identique reste ouvert pour toute société dont
ces comptes ne seraient pas configurés à l'avenir, tant que l'option A (ou B) n'est pas
appliquée.
