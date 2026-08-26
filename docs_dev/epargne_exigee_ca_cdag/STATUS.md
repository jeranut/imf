# Statut — Lot 1 : calcul + affichage conditionnel + lecture seule de "Épargne exigée" (CA/CDAG)

Suite à `AUDIT.md` (Lot 0). Décision de Micka (capture du produit PRET RURAL, `guarantee_savings_
percent = 5`) : ne pas se limiter à l'affichage/lecture-seule des champs existants (saisie
libre, toujours à 0) - les relier au vrai calcul déjà utilisé ailleurs sur le crédit
(`guarantee_savings_required`).

## Correctif appliqué

Toute la logique de calcul vit dans `microfinance_savings_management` (le module de base,
`microfinance_loan_management`, n'a aucune notion d'épargne garantie de crédit -
`guarantee_savings_percent` n'existe que dans le module épargne) :

- `microfinance_savings_management/models/microfinance_loan_extension.py` : `avis_ca_epargne_
  exigee`/`avis_cdag_epargne_exigee` redéclarés en `compute='_compute_avis_epargne_exigee',
  store=True` (au lieu de simples champs de saisie libre définis dans `microfinance_loan_
  management`). Calcul : `avis_ca_amount x product_id.guarantee_savings_percent / 100` (et
  l'équivalent CDAG) - même pourcentage que `guarantee_savings_required`, mais appliqué au
  montant de l'avis en cours plutôt qu'au `loan_amount` générique, cohérent avec le reste du
  bloc Avis CA/CDAG (`avis_ca_installment_amount` etc.).
- `microfinance_savings_management/views/microfinance_loan_views_inherit.xml` : `invisible="not
  guarantee_savings_required"` + `readonly="1"` ajoutés sur les deux champs (réutilise le champ
  `guarantee_savings_required` déjà présent sur le formulaire - un `invisible=` de vue Odoo 17
  ne peut pas traverser `product_id.guarantee_savings_percent` directement).
- `microfinance_savings_management/models/microfinance_loan_application_extension.py` : nouveau
  champ relais `guarantee_savings_required` (`related='loan_id.guarantee_savings_required'`),
  uniquement pour servir de condition d'affichage côté dossier d'instruction (`ca_required_
  savings`/`cdag_required_savings`, déjà `related`+`readonly=True` vers les champs ci-dessus,
  héritent automatiquement de la nouvelle valeur calculée sans aucun changement de leur part).
- **Nouveau fichier** `microfinance_savings_management/views/microfinance_loan_application_views_
  inherit.xml` (enregistré dans `__manifest__.py`) : même `invisible=` sur `ca_required_savings`/
  `cdag_required_savings`.
- `microfinance_loan_management/models/microfinance_loan.py` : commentaires/`help` mis à jour
  pour documenter que ces deux champs restent en saisie libre uniquement si le module épargne
  n'est pas installé.

## Tests

Nouveau fichier `microfinance_savings_management/tests/test_avis_epargne_exigee.py` (4 tests,
ajouté à `tests/__init__.py`) : calcul correct sur CA et CDAG, zéro quand le produit n'a pas
d'exigence configurée, recalcul automatique (pas une saisie libre) quand `avis_ca_amount`
change, et propagation vers `microfinance.loan.application` via les champs `related` existants.

## Validation — zéro régression

Suite complète des deux modules (811 tests bruts) comparée strictement (`comm` sur les listes
`FAIL`/`ERROR` triées, isolant précisément ce Lot via `git stash` des fichiers concernés) :
**listes strictement identiques** (90/90) entre l'état juste avant ce Lot et l'état avec le
correctif - aucune régression, aucun test cassé.

## Recalcul des dossiers déjà en base

**Point technique découvert et corrigé** : un champ déjà `store=True` qui devient `compute=...
store=True` n'est **pas** recalculé rétroactivement par Odoo lors d'une mise à jour de module
(`-u`) - contrairement à un nouveau champ stocké, qui déclenche un calcul initial automatique.
Sur confirmation explicite (écriture en base) : `avis_ca_epargne_exigee`/`avis_cdag_epargne_
exigee` forcés au recalcul sur IS/000289 et IS/001076 (0 → 25 000 Ar chacun, 500 000 x 5%),
vérifié indépendamment par SQL brut après coup.

## Reste à faire (hors de mes mains)

**Redémarrage du service `odoo17` requis** (`sudo systemctl restart odoo17`) pour que le
correctif Python soit pris en compte par l'instance en cours.
