# Workflow Programme progressif (prêts successifs par palier)

## 1. Objectif métier
Ce workflow couvre le calcul d'une **éligibilité informative** affichée sur le dossier
d'instruction (`microfinance.loan.application`) lorsque le produit visé fait partie d'un
**programme progressif** — une suite ordonnée de produits de crédit (ex. "Prêt initial" →
"Prêt successif 1" → "Prêt successif 2") où l'étape N+1 suppose normalement un prêt
clôturé sans retard significatif sur le produit de l'étape N. **Ce n'est jamais un
blocage système** : la décision d'octroi reste toujours à la commission de crédit / au
valideur. Le calcul ne fait qu'informer (statut + message) sur l'écran du dossier ; il
n'est jamais utilisé dans `_check_eligibility()` (`microfinance_loan.py`), qui reste
dédiée aux blocages durs préexistants (ancienneté, second crédit parallèle, arriérés du
co-emprunteur, garanties).

Il ne couvre PAS le rang de prêt global par client (`loan_sequence_number` /
`microfinance.loan.application.tier`, voir workflow `dossier_precredit`) : ce mécanisme
libelle un rang numérique de crédit (1er, 2e, …) indépendamment de tout produit précis,
alors que le programme progressif chaîne des *produits* précis entre eux avec un critère
de retard par étape. Les deux mécanismes coexistent sans interaction.

## 2. Utilisateurs concernés
D'après `security/ir.model.access.csv` :
- **Agent crédit** (`group_microfinance_user`), **Finance microfinance**
  (`group_microfinance_finance`), **Auditeur microfinance** (`group_microfinance_auditor`) :
  lecture seule sur `microfinance.loan.progressive.program` et `.step` (1,0,0,0).
- **Manager crédit** (`group_microfinance_manager`) : accès complet (1,1,1,1) — seul
  groupe pouvant créer/modifier un programme ou ses étapes.
- **Gestionnaire** (`group_microfinance_gestionnaire`) : hérite de
  `group_microfinance_manager` via `implied_ids` (`security/groups.xml`), donc accès
  complet également.
- Le champ `progressive_eligibility_status`/`_message` sur le dossier est visible par
  quiconque peut lire `microfinance.loan.application` (aucune restriction de groupe
  propre à ce champ) — c'est un champ `compute` non stocké, pas un modèle séparé.

## 3. Menus utilisés
`Microfinance > Configuration > Programmes progressifs`
(`menu_microfinance_root` > `menu_microfinance_config` >
`menu_microfinance_loan_progressive_program`, action
`action_microfinance_loan_progressive_program`), réservé à
`group_microfinance_manager` comme tout le sous-menu Configuration.

Le calcul d'éligibilité lui-même n'a pas de menu dédié : il s'affiche automatiquement en
bandeau sur la vue formulaire de `microfinance.loan.application`
(`menu_microfinance_loan_applications`).

## 4. Étapes principales
1. Un manager crédit configure un **programme progressif**
   (`microfinance.loan.progressive.program`) avec un nom, éventuellement un code, une
   société (vide = commun à toutes) et une description.
2. Il ajoute des **étapes** (`microfinance.loan.progressive.program.step`) en sous-liste
   éditable, dans l'ordre : `sequence_number` (1 = premier palier), `product_id` (le
   produit de crédit de cette étape — un produit ne peut appartenir qu'à une seule étape,
   tous programmes confondus), `late_tolerance_days`/`late_tolerance_amount_percent`
   (tolérance de retard pour considérer le palier "sans défaut" en sortie).
3. Sur la fiche produit (`microfinance.loan.product`), un bandeau en lecture seule
   confirme le rattachement ("Fait partie du programme progressif *X*, étape *N*") si le
   produit est utilisé dans une étape.
4. Lorsqu'un agent crée/ouvre un dossier d'instruction (`microfinance.loan.application`)
   et sélectionne `loan_product_id`, le champ `progressive_eligibility_status` (et son
   message) se recalcule automatiquement (`@api.depends('loan_product_id',
   'partner_id')`).
5. Si le produit est une étape ≥ 2 d'un programme, le système recherche — tous
   établissements confondus (cross-agency) — les crédits (`microfinance.loan`) du même
   client sur le produit de l'étape précédente, et détermine le statut le plus favorable
   parmi les prêts trouvés.
6. Le résultat s'affiche en bandeau coloré sur le dossier, avec la mention "Information
   indicative — la décision d'octroi reste à l'appréciation du valideur." Aucun bouton du
   workflow du dossier n'est conditionné par ce statut.

## 5. Champs importants
**`microfinance.loan.progressive.program`** (`microfinance_loan_progressive_program.py`) :
- `name` (Nom, requis, traduisible), `code` (Code, libre), `company_id` (Société, vide =
  toutes), `active`, `description`, `step_ids` (Étapes, One2many), `step_count`
  (Nombre d'étapes, computed).

**`microfinance.loan.progressive.program.step`** :
- `program_id` (Programme, requis, `ondelete='cascade'`), `sequence_number` (Rang, requis,
  défaut 1), `product_id` (Produit, requis, `unique(product_id)`),
  `late_tolerance_days` (Tolérance de retard en jours, défaut 0),
  `late_tolerance_amount_percent` (Tolérance de retard en % du montant, défaut 0.0),
  `notes` (texte libre).

**Extension `microfinance.loan.product`** :
- `progressive_step_ids` (One2many inverse sur `product_id`, au plus 1 enregistrement du
  fait de la contrainte unique), `progressive_program_id`/`progressive_step_sequence`/
  `is_progressive_step` (computed, `store=True`, dépendent de `progressive_step_ids`).

**Extension `microfinance.loan.application`** :
- `loan_product_id` (Produit de prêt, Many2one requis vers `microfinance.loan.product`,
  domaine `company_id`) — condition préalable ajoutée pour que ce chantier ait un sens
  (absent du modèle jusqu'ici, voir section 14).
- `progressive_eligibility_status` (Selection, computed, non stocké) : `not_applicable`,
  `no_prior_loan`, `prior_active`, `eligible`, `warning`, `defaulted`.
- `progressive_eligibility_message` (Char, computed, non stocké) : message en français
  interpolé avec le nom du produit précédent, la date de clôture si connue, les jours de
  retard constatés et la tolérance configurée.
- `closed_date` (nouveau champ sur `microfinance.loan`, posé automatiquement par
  `action_close()`) : nécessaire pour dater le message d'éligibilité d'un prêt clôturé.

## 6. Boutons et actions
- Aucun bouton dédié sur le dossier : le bandeau d'éligibilité est purement informatif,
  recalculé automatiquement.
- `action_open_guarantor_wizard`-like : sans objet ici (pas de wizard pour ce chantier).
- Boutons standards du programme progressif : boutons de formulaire génériques Odoo
  (Nouveau/Sauvegarder) sur `microfinance.loan.progressive.program`, pas d'action
  métier spécifique.
- **Câblage connexe découvert et corrigé pendant ce chantier** : `action_create_loan()`
  (dossier) référençait un wizard inexistant
  (`microfinance.loan.application.create.loan.wizard`) — bouton mort avant ce chantier.
  Un wizard minimal (produit pré-rempli depuis `loan_product_id`, montant, durée) a été
  construit pour que le bouton **Créer le crédit** fonctionne réellement (voir section 14).

## 7. Règles métier
Dérivées de `_compute_progressive_eligibility`/`_evaluate_progressive_eligibility`/
`_evaluate_progressive_loan` (`microfinance_loan_application.py`) :
- Si `loan_product_id` n'est pas `is_progressive_step`, ou est en `sequence_number == 1`
  de son programme : `not_applicable`, message vide (rien à vérifier).
- Sinon, l'étape précédente du même programme est identifiée
  (`sequence_number - 1`), et les crédits du même `partner_id` sur le produit de cette
  étape précédente sont recherchés **sans filtre de société** (`sudo()`), car le
  parcours client est cross-agency par nature — même exception documentée que la
  matrice fonds bailleurs (`microfinance_fond_credit.py`).
- Aucun prêt trouvé → `no_prior_loan`.
- Par prêt trouvé, statut individuel :
  - `defaulted` si `state in ('defaulted', 'written_off')`.
  - `prior_active` si `state != 'closed'` (tout autre état non terminal).
  - Sinon (prêt `closed`) : retard historique reconstitué à partir des échéances ayant eu
    un `arrears_onset_date` (jamais depuis les métriques de scoring courantes
    `overdue_amount`/`_get_max_overdue_days()`, qui valent 0 sur un prêt déjà soldé) :
    jours de retard max = `max(arrears_cured_date - arrears_onset_date)`, montant en
    retard = somme des `total_amount` des échéances concernées, en % de `loan_amount`.
    `eligible` si les deux critères (jours ET montant) respectent la tolérance de
    l'étape précédente, sinon `warning`.
- **S'il existe plusieurs prêts** sur le produit précédent, le statut global retient le
  **plus favorable** au client, classement `defaulted < prior_active < warning <
  eligible` (un seul prêt `eligible` suffit à rendre le statut global `eligible`, même
  si un autre prêt est `defaulted`) — point de décision confirmé explicitement avec
  Micka.
- `_check_eligibility()` (`microfinance.loan`) n'est jamais modifié ni appelé par ce
  calcul.

## 8. Contrôles et blocages
**Aucun contrôle bloquant.** C'est le principe fondateur de ce chantier : le champ
`progressive_eligibility_status` est purement indicatif, jamais utilisé dans une
`@api.constrains`, jamais dans `_check_eligibility()`, et n'apparaît dans aucune
condition `invisible`/`readonly` des boutons de workflow du dossier
(Soumettre/Valider/Approuver/Créer le crédit). Seule contrainte serveur réelle :
`unique(product_id)` sur `microfinance.loan.progressive.program.step` (un produit ne
peut être rattaché qu'à une seule étape).

## 9. Statuts
`progressive_eligibility_status` (Selection, computed, non stocké sur
`microfinance.loan.application`) :
| Valeur | Sens |
|---|---|
| `not_applicable` | Produit indépendant, ou étape 1 d'un programme (pas de prêt précédent à vérifier) |
| `no_prior_loan` | Étape ≥ 2, aucun prêt trouvé sur le produit de l'étape précédente |
| `prior_active` | Un prêt existe sur le produit précédent mais n'est pas clôturé |
| `eligible` | Prêt précédent clôturé, dans la tolérance de retard configurée |
| `warning` | Prêt précédent clôturé mais hors tolérance de retard |
| `defaulted` | Prêt précédent radié ou en défaut |

Ce champ ne conditionne aucune transition du cycle de vie du dossier
(`ALLOWED_TRANSITIONS`) : les deux cycles de vie (dossier, éligibilité progressive) sont
indépendants.

## 10. Rapports ou PDF
Aucun rapport dédié. Le résultat s'affiche uniquement en bandeau sur le formulaire du
dossier.

## 11. Tableaux de bord
Aucun indicateur agrégé dans `microfinance_dashboard.py` — le statut n'est visible qu'au
niveau du dossier individuel.

## 12. Sécurité et groupes utilisateurs
D'après `security/ir.model.access.csv` :

| Modèle | Groupe | Lecture | Écriture | Création | Suppression |
|---|---|---|---|---|---|
| `microfinance.loan.progressive.program` | Agent crédit | 1 | 0 | 0 | 0 |
| `microfinance.loan.progressive.program` | Manager crédit | 1 | 1 | 1 | 1 |
| `microfinance.loan.progressive.program` | Finance microfinance | 1 | 0 | 0 | 0 |
| `microfinance.loan.progressive.program` | Auditeur microfinance | 1 | 0 | 0 | 0 |
| `microfinance.loan.progressive.program.step` | Agent crédit | 1 | 0 | 0 | 0 |
| `microfinance.loan.progressive.program.step` | Manager crédit | 1 | 1 | 1 | 1 |
| `microfinance.loan.progressive.program.step` | Finance microfinance | 1 | 0 | 0 | 0 |
| `microfinance.loan.progressive.program.step` | Auditeur microfinance | 1 | 0 | 0 | 0 |

`group_microfinance_gestionnaire` hérite de `group_microfinance_manager` via
`implied_ids` (`security/groups.xml`) : pas de ligne dédiée nécessaire pour lui donner
l'accès complet, cohérent avec la convention déjà utilisée pour les autres modèles de
configuration du module (produits, périodicités, professions…).

## 13. Cas d'utilisation complets
1. **Programme simple, client éligible** : un manager crée un programme "Cycle urbain"
   avec l'étape 1 = "Prêt initial", l'étape 2 = "Prêt successif 1" (tolérance 7 jours /
   5%). Un client clôture un "Prêt initial" sans retard. Un agent crée un dossier sur
   "Prêt successif 1" pour ce client : bandeau vert "Prêt précédent (Prêt initial)
   clôturé le [date] sans retard significatif. Information indicative…".
2. **Client sans historique** : un agent soumet un dossier "Prêt successif 1" pour un
   client qui n'a jamais pris de "Prêt initial" chez CEFOR. Bandeau orange "Aucun prêt
   antérieur trouvé sur le produit prérequis (Prêt initial) — vérifier l'historique du
   client avant octroi." Le manager peut malgré tout valider le dossier : rien n'est
   bloqué.
3. **Retard hors tolérance** : le prêt précédent est clôturé mais avec 15 jours de retard
   maximum constatés (tolérance configurée : 7 jours). Bandeau orange "Prêt précédent
   (Prêt initial) clôturé le [date] avec 15 jour(s) de retard maximum constatés
   (tolérance configurée : 7 jours)."
4. **Client en défaut** : le prêt précédent a été radié. Bandeau rouge "Prêt précédent
   (Prêt initial) radié ou en défaut — vérifier avant octroi."
5. **Cross-agency** : un client a pris son "Prêt initial" à l'agence CEFOR Ampitatafika,
   puis demande "Prêt successif 1" à l'agence CEFOR Isotry. Le bandeau se calcule
   normalement malgré la différence de société (recherche `sudo()` sans filtre société).

## 14. Erreurs fréquentes
- *Le bandeau reste invisible* : le produit sélectionné n'est rattaché à aucune étape de
  programme (`is_progressive_step = False`), ou il est en étape 1 (rien à vérifier) —
  comportement normal, pas une erreur.
- *"Ce produit est déjà rattaché à une étape d'un programme progressif"* : tentative de
  rattacher un même produit à une deuxième étape (contrainte SQL `unique(product_id)`
  sur `microfinance.loan.progressive.program.step`), conformément au point de décision
  Lot 0 (un produit ↔ une seule étape d'un seul programme).
- *Le dossier ne peut plus être créé sans produit* : `loan_product_id` est désormais
  requis sur `microfinance.loan.application` — champ absent avant ce chantier, ajouté
  car indispensable au calcul (voir section 1).
- *"Le passage à 'Transformé en crédit' se fait uniquement via le bouton 'Créer le
  crédit'"* : `action_create_loan()` référençait un wizard inexistant avant ce chantier
  (bug préexistant, sans rapport direct avec l'éligibilité progressive elle-même, mais
  corrigé ici car nécessaire pour que `loan_product_id` puisse réellement se reporter
  sur le crédit créé).

## 15. Bonnes pratiques
- Configurer les programmes progressifs **avant** de rattacher des dossiers aux produits
  concernés : un produit déjà utilisé sur des dossiers existants peut être rattaché à
  une étape à tout moment (le calcul est recalculé à la volée, non stocké), mais autant
  éviter la confusion d'un dossier créé avant que le programme n'existe.
  Sur ce chantier, il n'y a aucune obligation de séquencer, uniquement un confort
  d'usage.
- Ne jamais interpréter un bandeau `warning`/`no_prior_loan`/`prior_active` comme un
  blocage : c'est une information à vérifier, pas une règle à appliquer aveuglément —
  le message le rappelle explicitement.
- Garder les tolérances (`late_tolerance_days`/`late_tolerance_amount_percent`) cohérentes
  avec la politique de crédit réelle de l'institution ; ce ne sont pas des constantes
  universelles (comme documenté dans le code de
  `microfinance_loan_product_extension.py` pour un mécanisme voisin côté épargne).
- Après un rééchelonnement ou un changement de statut d'un prêt précédent, le bandeau se
  recalcule automatiquement à la prochaine ouverture du dossier concerné (champ
  `compute` non stocké, pas de cache à rafraîchir manuellement).

## 16. Questions/Réponses MOWGLI potentielles
1. Comment configurer un programme progressif de prêts successifs ?
2. Pourquoi le dossier affiche-t-il "Aucun prêt antérieur trouvé" alors que le client a
   déjà emprunté ?
3. Le bandeau d'éligibilité bloque-t-il la soumission du dossier ?
4. Un produit peut-il appartenir à plusieurs programmes progressifs ?
5. Comment le système calcule-t-il le retard d'un prêt déjà clôturé ?
6. Le calcul d'éligibilité fonctionne-t-il si le client a emprunté dans une autre agence ?
7. Que se passe-t-il si plusieurs prêts existent sur le produit précédent ?
8. Qui peut créer ou modifier un programme progressif ?
9. Où trouver les programmes progressifs configurés dans Odoo ?
10. Quelle est la différence entre le rang de prêt (1er/2e crédit) et un programme
    progressif ?
