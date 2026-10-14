# Balance d'ouverture — audit : zéro négatif, format des montants, garde-fou anti-doublon

Base **MOWGLI**, relevé du 2026-10-10. Lecture seule : rien n'a été modifié.

## 1. Modèles et vues
- Modèle `microfinance.opening.balance` (+ `.line`) : [microfinance_opening_balance.py](../../microfinance_loan_management/models/microfinance_opening_balance.py). Vues form / list / search : [microfinance_opening_balance_views.xml](../../microfinance_loan_management/views/microfinance_opening_balance_views.xml). La liste n'est **pas éditable** : « Nouveau » ouvre le formulaire.
- Concordance : champ `reprise_concordance_html` (Html calculé, non stocké) de [microfinance_opening_reprise_balance.py](../../microfinance_loan_management/models/microfinance_opening_reprise_balance.py) (`_compute_reprise_concordance_html`, lignes via `_reprise_concordance()`), affiché au-dessus des lignes par [microfinance_opening_reprise_views.xml](../../microfinance_loan_management/views/microfinance_opening_reprise_views.xml). Le volet épargne ajoute son groupe par `_reprise_groups()` (module épargne).

## 2. Origine du « -0.00 »
Cause confirmée : dans `_reprise_concordance()`, `amount = sign * sum(débit - crédit)` avec `sign = -1` pour le groupe épargne. Pour 213002 et 213003 (lignes du modèle chargées à 0,0) : `-1 * 0.0 = -0.0` (vérifié : `repr(-1*0.0) == '-0.0'`), puis `'{:,.2f}'.format(-0.0)` donne `-0.00`. L'écart suit : `currency.round(-0.0 - 0.0)` reste `-0.0`.
Même risque, ailleurs : `difference = currency.round(debit - credit)` (`_compute_totals`) si un arrondi ramène un résidu flottant négatif à `-0.0` ; `total_debit` / `total_credit` sont des sommes de `0.0` (pas de `-0.0`).

## 3. Format « 3,000,000.00 » contre « 5.000.000,00 Ar »
Cause confirmée : la concordance n'est **ni Float ni Monetary** : c'est un champ Html dont les cellules sont fabriquées en Python avec `'{:,.2f}'.format(...)` — format anglo-saxon codé en dur, sans symbole de devise, indépendant de la langue de l'utilisateur. Les lignes de la balance sont des `Monetary` (`currency_field`) rendus par le client web avec la langue et le symbole.
Solution proposée : conserver le tableau Html mais formater chaque montant avec `odoo.tools.misc.format_amount(env, montant, devise_de_la_société)` : même moteur que le rendu Monetary (séparateurs de la langue de l'utilisateur, symbole et position de la devise), aucun format codé en dur. Un champ `Monetary` par ligne n'est pas possible tel quel (le tableau est dynamique, un champ par compte) ; l'alternative (modèle transitoire de lignes de concordance avec `Monetary`) alourdit sans changer le rendu. À confirmer à la phase 2 : le rendu reflète la langue du contexte de lecture (calcul non stocké, donc par utilisateur).

## 4. Points d'entrée de création d'une balance
| Chemin | État actuel |
|---|---|
| Bouton **Nouveau** (liste → formulaire) | Le client web appelle `onchange` sans champ modifié ; le serveur exécute alors **`default_get`** pour les champs absents de la vue ([web/models/models.py `onchange`](../../../odoo/addons/web/models/models.py)). Le chargement de la **liste** n'appelle pas `default_get` (liste non éditable). Un `UserError` dans `default_get` empêche donc le formulaire de s'ouvrir. |
| `create()` direct : RPC, import CSV de la liste, tests | Aucune garde à la création. `create()` appelle aussi `default_get` pour les champs manquants : un blocage placé dans `default_get` seul est contournable en fournissant tous les champs, d'où le filet dans `create()`. |
| **Dupliquer** | `copy()` crée un brouillon (`state` et `date` ne sont pas copiés, `line_ids` l'est, `copy=True`). Aucune garde. |
| Code applicatif | Aucun : ni l'assistant de reprise, ni action serveur, ni cron, ni autre module ne crée de balance (recherche dans tous les `.py`, `.xml`, `.js`). |
| Seul filet existant | `_check_one_validated_per_company` : une seule balance **validée** par société ; rien pour les brouillons. |

## 5. Doublons existants (MOWGLI)
| id | Société | Date | État | Lignes | Débit / crédit |
|---|---|---|---|---|---|
| 43 | 9 AGENCE ANALAKELY | 2026-10-10 | **validée** | 58 | 11 400 000 / 11 400 000 (écriture 15300) |
| 44 | 9 AGENCE ANALAKELY | 2026-10-10 | **brouillon vide** | 0 | 0 / 0 |

Aucune autre balance. Il n'y a qu'un doublon : le brouillon 44, à supprimer (phase 2, D). Index existants : clé primaire et `company_id` seulement.

## 6. Constats qui pèsent sur les décisions
1. **Aucun chemin n'existe aujourd'hui pour refaire un test après validation.** Une balance validée refuse la suppression et la modification, et l'assistant de purge (`microfinance_data_reset_wizard`) **ne touche pas** aux balances d'ouverture (aucune référence dans son code), contrairement à ce que dit [STATUS.md](STATUS.md) (« purge de simulation »). La seule issue actuelle est du SQL manuel. Bloquer « Nouveau » quand une balance validée existe est donc cohérent, mais il faut offrir ce chemin.
2. **Tests existants à adapter** ([test_opening_balance.py](../../microfinance_loan_management/tests/test_opening_balance.py)) : `test_second_validation_for_the_same_company_is_refused` crée deux balances dans la même société ; `test_empty_or_zero_balance…` en crée deux d'affilée (lignes 104-105) ; la fixture `_balance` de mes tests de reprise en crée une par test (correct, base propre à chaque test). Deux options : tests qui créent la seconde balance avec une clé de contexte réservée aux tests, ou une société distincte par cas.
3. `default_get` est aussi appelé par `create()` : le garde de la couche 1 ne doit se déclencher que pour une demande portant `company_id` (donc le formulaire), sinon il interfère avec les créations internes déjà légitimes (un `create` qui échouerait de toute façon par la couche 2).
4. L'index unique partiel (couche 3) est sans risque une fois le brouillon 44 supprimé : (9, brouillon) devient unique ; la balance validée 43 n'est pas concernée par `WHERE state = 'draft'`. Il se crée à la mise à jour du module ; la suppression du doublon doit passer **avant**.

## 7. Question à trancher avant la phase 2 : balance validée existante
Par défaut (votre proposition) : couches 1 et 2 refusent aussi la création si une balance **validée** existe (« déjà validée »). Chemin pour refaire un test, au choix :
- **(A) Recommandé** — action « Annuler l'ouverture » réservée au comptable / gestionnaire comptable, sur une balance validée **dont aucun écrit postérieur** n'existe dans la société : extourne de l'écriture d'ouverture, retour en brouillon (lignes conservées), chatter ; on la corrige ou on la supprime ensuite. Garde : refus si des écritures comptabilisées existent après la date, ou si une reprise de portefeuille est rattachée (crédits / épargne repris).
- **(B)** Étendre l'assistant de purge pour supprimer écriture d'ouverture, balance et reprise (test uniquement), sans bouton dans la balance.
- **(C)** Rien : refus définitif, nettoyage en SQL à la demande.
Réponse attendue : A, B ou C (et, si A, qui peut l'utiliser). La phase 2 (correctifs A, B, D, couches 1 à 3) n'est pas lancée.
