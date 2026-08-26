# Statut — Lot 1 : verrouillage des champs "Calcul crédit"

Suite à `AUDIT.md` (Lot 0) et aux décisions actées par Micka (5 champs verrouillés, mécanisme
`write()` + flag de contexte, `_EDITABLE_SCHEDULE_STATES` non touché).

## Correctif appliqué

`microfinance_loan_management/models/microfinance_loan.py` :
- `_LOCKED_DOSSIER_STATES = ('avis_ca', 'avis_cdag', 'approved', 'active', 'closed', 'defaulted',
  'written_off')` - reprend exactement la liste établie à l'audit (section 2), `cancelled` exclu
  (état mort, jamais atteint par aucune méthode).
- `_LOCKED_DOSSIER_FIELDS = {'loan_amount', 'term', 'product_id', 'interest_rate',
  'installment_amount'}`.
- `_check_locked_dossier_fields(vals)` : override de `write()` (pas un `@api.constrains`, cf.
  note technique de la demande - un constrains ne peut pas distinguer une écriture système d'une
  saisie manuelle sans le même mécanisme de contexte). Lève une `ValidationError` si `vals`
  touche un champ verrouillé alors que `state in _LOCKED_DOSSIER_STATES`, sauf si le contexte
  `propagation_avis_ca_cdag` est posé.
- `_propagate_avis_to_loan()` : son `self.write(...)` interne passe désormais par
  `self.with_context(propagation_avis_ca_cdag=True)` - seul point du module qui pose ce flag.

`microfinance_loan_management/views/microfinance_loan_views.xml` : `readonly` ajouté sur
`product_id`, `loan_amount`, `term`, `installment_amount` (même liste d'états). **`interest_rate`
non touché** : ce champ n'a aujourd'hui aucun `<field>` dans la vue crédit (confirmé à l'audit,
`related` sans widget) - rien à rendre readonly côté vue ; il reste protégé par le seul filet
serveur (`write()`), qui est de toute façon le rempart réel. Décision de ne pas ajouter un widget
pour ce champ dans ce Lot (aurait élargi le périmètre au-delà du verrouillage demandé) - à
signaler si Micka souhaite l'exposer un jour.

## Message d'erreur

```
Le crédit {référence} a déjà reçu {un avis CA|un avis CDAG|un avis CA/CDAG} : {champs} ne
peuvent plus être modifiés à ce stade. Contactez le support technique si une correction est
encore nécessaire.
```

`{champs}` liste dynamiquement les libellés des champs réellement présents dans l'écriture
bloquée (pas toujours les 5) ; l'avis cité dépend de `state` (`avis_ca`/`avis_cdag` littéral,
"avis CA/CDAG" générique pour les états suivants où les deux avis sont déjà passés).

## Tests

Nouveau fichier `tests/test_locked_dossier_fields.py` (5 tests, ajouté à `tests/__init__.py`) :
- Modification manuelle de chacun des 5 champs bloquée en `avis_ca`.
- Bloquée aussi en `avis_cdag` et `approved`.
- `_propagate_avis_to_loan()` (déclenchée par une modification du bloc Avis CA) continue de
  fonctionner sans lever, en `avis_ca`.
- Non-régression : régénération d'échéancier (`action_generate_schedule()`) toujours
  fonctionnelle en `approved`.
- Les 5 champs restent librement modifiables avant tout avis (`draft`/`enquete`).

**Un test préexistant a dû être adapté** (`test_installment_schedule_persistence.py::
test_write_does_not_regenerate_once_active`) : il écrivait directement `installment_amount` sur
un crédit `active` pour vérifier la non-régénération de l'échéancier (Lot précédent) - ce même
champ étant désormais verrouillé à cet état, l'écriture est maintenant bloquée en amont par une
`ValidationError` (comportement correct et plus strict, pas une régression). Le test a été
recentré sur `repayment_frequency_id` (seul champ de `_SCHEDULE_TRIGGER_FIELDS` non verrouillé),
qui vérifie toujours exactement ce que ce test voulait couvrir à l'origine.

## Validation - zéro régression

Suite complète du module (654 tests) comparée strictement (`comm` sur les listes `FAIL`/`ERROR`
triées) avec l'état juste avant ce Lot : **listes identiques** - mêmes 6 échecs et 62 erreurs
pré-existants (environnement SEFOR non isolé, déjà documentés dans les lots précédents), aucun
de plus, aucun de moins.

## Reste à faire (hors de mes mains)

**Redémarrage du service `odoo17` requis** (`sudo systemctl restart odoo17`) pour que le
correctif Python soit pris en compte par l'instance en cours.
