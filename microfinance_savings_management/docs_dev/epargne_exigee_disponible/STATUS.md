# Statut — Lot 1 : Calcul automatique Épargne exigée / Épargne disponible

**Terminé. Aucun commit — à la charge de Micka après revue du diff.**

## Ce qui a été fait

`required_savings`/`available_savings` sur `microfinance.loan.application` : convertis de
saisie libre en `related=` vers les champs déjà existants et déjà testés sur `microfinance.loan`
(`guarantee_savings_required`/`guarantee_savings_balance`, `microfinance_savings_management`) -
**aucun nouveau calcul écrit**, réutilisation pure conformément à l'audit Lot 0.

## Écart technique découvert en implémentant (important, à retenir)

**Un `related=` déclaré uniquement dans l'extension épargne (comme initialement tenté) fait
planter le chargement du module de base.** Contrairement à ce que suggérait la simple lecture du
code (`guarantee_savings_required` semblait pouvoir être relayé depuis l'extension), Odoo résout
la chaîne d'un champ `related=` (`setup_related`) **au chargement du modèle qui déclare le
champ**, pas paresseusement à la première lecture réelle - si la cible n'existe pas encore à ce
moment (le module savings n'a pas encore été traité), le chargement échoue avec un
`KeyError` explicite. Confirmé en le tentant (`git` non commité, donc sans risque) : le module de
base ne charge même plus.

**Solution, alignée sur le patron déjà utilisé par `avis_ca_epargne_exigee`/`avis_cdag_epargne_
exigee` (même chantier antérieur, `docs_dev/epargne_exigee_ca_cdag/`)** : `guarantee_savings_
required`/`guarantee_savings_balance` sont désormais **aussi déclarés comme simples champs Monetary
en saisie libre dans le module de base** (`microfinance_loan_management/models/
microfinance_loan.py`), **redéclarés en `compute=`** par `microfinance_savings_management`
(déclaration déjà existante, inchangée) - le module de base "sait" que le champ existe (nom,
type), sans rien savoir de son calcul réel. `required_savings`/`available_savings` restent eux
aussi déclarés dans le module de base (comme `ca_required_savings`/`cdag_required_savings`),
`related=` vers ces deux champs.

## Résultat des tests

**5 nouveaux tests** (`microfinance_savings_management/tests/test_epargne_exigee_disponible.py`)
: 5/5 passants - correspondance avec `guarantee_savings_required`/`guarantee_savings_balance`,
cas sans compte (0 sans erreur), cas produit sans épargne garantie configurée (0 sans erreur),
confirmation que les champs sont bien `readonly` (non modifiables manuellement).

**Suite complète des deux modules**, avant/après ce diff : 607 tests (+5), écart initial d'un
test (`TestCaisseSearchClients.test_search_by_name`) - **investigué et confirmé pré-existant,
sans rapport avec ce Lot** : reproduit à l'identique sur le même clone avec le code HEAD seul
(sans mon diff). Cause : ce test utilise `cls.env.company` (la vraie société CEFOR Isotry du
clone, pas une société de test dédiée) et cherche par sous-chaîne "Rakoto" - un client réel
nommé "rakotonirina" a été créé en production entre deux clones successifs de cette session,
faisant apparaître une collision de recherche substring qui n'existait pas dans les clones plus
anciens utilisés comme référence. Liste des 88 échecs/erreurs historiques : identique par
ailleurs (diff vide en dehors de ce cas isolé et confirmé non lié).

## Fichiers modifiés

- `microfinance_loan_management/models/microfinance_loan.py` : `guarantee_savings_required`/
  `guarantee_savings_balance` (nouveaux champs "coquille", saisie libre par défaut).
- `microfinance_loan_management/models/microfinance_loan_application.py` : `required_savings`/
  `available_savings` convertis en `related=`.
- `microfinance_savings_management/tests/test_epargne_exigee_disponible.py` (nouveau, 5 tests) +
  `tests/__init__.py` (import).

Aucune modification de vue nécessaire (confirmé à l'audit - `readonly=True` du champ suffit,
même pattern que `ca_required_savings`/`cdag_required_savings` juste au-dessus dans la même
vue). Aucun `write()` manuel sur ces deux champs trouvé ailleurs dans le dépôt (wizard, import).
