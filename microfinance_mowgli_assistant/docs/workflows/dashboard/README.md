# Workflow Dashboard

## 1. Objectif métier
Ce workflow couvre le tableau de bord agrégé du portefeuille de crédit : indicateurs clés (crédits actifs, montant décaissé, encours, impayés, taux de défaut), répartition des crédits par état, tendances mensuelles (décaissements/remboursements/impayés sur 12 mois glissants), répartition du risque et portefeuille à risque (PAR) par ancienneté, et liste des crédits les plus en retard. Il est **exclusivement en lecture** : aucune saisie, création, modification ou suppression de données n'y est possible. Ce qui N'est PAS couvert ici : la saisie des crédits, remboursements, garanties ou visites de recouvrement (voir les workflows `dossier_precredit`, `comptabilite`, `par_reporting`) — ce README documente uniquement la restitution agrégée de ces données.

## 2. Utilisateurs concernés
D'après les `groups` du menu racine `menu_microfinance_root` (`microfinance_loan_management/views/microfinance_menus.xml`), qui porte le sous-menu du dashboard :
- `group_microfinance_user` (Agent crédit)
- `group_microfinance_manager` (Manager crédit)
- `group_microfinance_finance` (Finance microfinance)
- `group_microfinance_auditor` (Auditeur microfinance)
- `group_microfinance_collection_agent` (Agent recouvrement)

Par `implied_ids` (`security/groups.xml`), voient aussi ce menu (car rattachés à `group_microfinance_user`) : `group_microfinance_cashier` (Caissier), `group_microfinance_credit_committee` (Comité de crédit), et `group_microfinance_gestionnaire` (Gestionnaire, rattaché à Manager + Finance). Le groupe `group_microfinance_comptable` (Comptable) n'a **aucun** `implied_ids` et n'apparaît pas dans les `groups` du menu racine : un utilisateur uniquement Comptable ne voit donc pas ce menu, sauf s'il détient un autre groupe Microfinance en plus.

## 3. Menus utilisés
`Microfinance` (`menu_microfinance_root`) > `Tableau de bord` (`menu_microfinance_dashboard`, séquence 1, action `action_microfinance_dashboard_client`).

## 4. Étapes principales
1. L'utilisateur clique sur le menu `Microfinance > Tableau de bord`.
2. Le composant OWL `MicrofinanceLoanDashboard` (`static/src/js/microfinance_loan_dashboard.js`), enregistré sous la clé d'action client `microfinance_loan_dashboard`, se monte et appelle en JSON-RPC la route `/microfinance/dashboard/data`.
3. Le contrôleur `MicrofinanceDashboardController.dashboard_data` (`controllers/microfinance_dashboard_controller.py`) calcule, pour la société courante (`request.env.company`) uniquement, les KPI, la répartition par état, les séries mensuelles, la répartition de risque, les tranches de PAR (`Loan.get_par_buckets`) et le top 10 des crédits en retard, puis renvoie le tout en JSON.
4. Le template QWeb (`static/src/xml/microfinance_loan_dashboard.xml`) affiche les 5 cartes KPI, puis 5 graphiques ApexCharts (état des crédits, décaissements mensuels, remboursements vs impayés, jauge du taux de défaut avec répartition de risque, PAR par ancienneté), puis le tableau des crédits les plus en retard.
5. En cas d'échec du RPC, un message d'erreur générique s'affiche à la place des graphiques.

## 5. Champs importants
Modèle `microfinance.dashboard` (`models/microfinance_dashboard.py`), tous calculés (`compute='_compute_dashboard'`, aucun champ stocké/éditable) :
- `active_loan_count` (Crédits actifs) : nombre de crédits à l'état `active` de la société courante.
- `disbursed_amount` (Montant décaissé) : somme de `loan_amount` des crédits `active`, `closed` ou `defaulted`.
- `outstanding_amount` (Encours total) : somme de `balance_total` des crédits `active`.
- `overdue_amount` (Impayés) : somme de `overdue_amount` des crédits `active`.
- `default_rate` (Taux de défaut (%)) : nombre de crédits `defaulted` / nombre total de crédits (`active`+`closed`+`defaulted`) × 100.
- `currency_id` (Devise) : devise de la société courante (par défaut).

Données additionnelles renvoyées uniquement par le contrôleur JSON (pas de champs sur le modèle `microfinance.dashboard`, calculées à la volée) : `loans_by_state` (labels/valeurs issus de `Loan.read_group` sur `state`), `monthly.disbursement/repayment/overdue` (12 mois glissants), `risk_distribution` (low/medium/high, dérivé du champ `risk_level` du crédit), `par_buckets` (via `Loan.get_par_buckets(company_id)`), `top_overdue_loans` (partenaire, crédit, montant dû, jours de retard — top 10 trié par retard puis montant).

## 6. Boutons et actions
Aucun bouton. La vue formulaire `view_microfinance_dashboard_form` est déclarée `create="false" edit="false" delete="false"` et sans `<header>`/statusbar ; le client action OWL ne comporte aucun bouton de type `object`, uniquement de l'affichage passif.

## 7. Règles métier
- Les 5 champs de `microfinance.dashboard` sont recalculés à chaque lecture (`@api.depends_context('company')`), donc toujours scopés à la société active dans le sélecteur Odoo (`self.env.company`), jamais agrégés multi-société.
- Le contrôleur applique la même règle : `company = request.env.company`, une seule société à la fois, même si l'utilisateur a plusieurs sociétés cochées.
- `default_rate` (modèle) est calculé sur `active`+`closed`+`defaulted` ; le `default_rate` du contrôleur JSON (KPI affiché à l'écran) est calculé différemment : `defaulted / active_loan_count` (uniquement sur les crédits actifs comme dénominateur). Ce sont deux formules distinctes bien que le libellé "Taux de défaut" soit identique.
- `risk_distribution` regroupe le niveau `critical` du crédit dans le bucket `high` (le dashboard ne distingue que 3 niveaux : low/medium/high), à partir du champ `risk_level` du crédit.
- Les séries mensuelles couvrent une fenêtre glissante de 12 mois (mois courant inclus + 11 mois précédents), construite via `relativedelta`.
- Le tableau "crédits les plus en retard" ne retient que les échéances (`microfinance.loan.installment`) à l'état `overdue` avec un `residual_amount > 0`, agrégées par crédit, triées par jours de retard décroissants puis montant dû décroissant, limitées à 10 lignes.

## 8. Contrôles et blocages
- Aucune écriture n'est possible : le formulaire est verrouillé en lecture seule (`create="false" edit="false" delete="false"`).
- Si l'appel RPC `/microfinance/dashboard/data` échoue (erreur serveur, droits insuffisants sur un sous-modèle interrogé, etc.), le composant affiche `state.error = true` et le message "Impossible de charger les données du dashboard." à la place des graphiques ; l'erreur est journalisée en console (`console.error`).
- Si `ApexCharts` n'est pas chargé côté navigateur, les graphiques sont silencieusement ignorés (`console.warn`) mais les cartes KPI et le tableau restent affichés.

## 9. Statuts suivis
`microfinance.dashboard` n'a **aucun champ `state`** : c'est un modèle 100 % calculé, sans machine à états propre. Cette section documente donc les indicateurs suivis dans le temps plutôt qu'un cycle de statuts :
- **Répartition des crédits par état** (`loans_by_state`) : histogramme dynamique construit par `Loan.read_group(..., ['state'], ['state'])` sur le modèle `microfinance.loan`. Les labels affichés sont les libellés de la sélection `state` de `microfinance.loan` (résolus dynamiquement via `dict(Loan._fields['state'].selection)`), pas une liste figée dans ce module. Les seules valeurs de `state` explicitement utilisées dans le code du contrôleur/modèle dashboard sont `active`, `closed` et `defaulted` (dans les domaines de recherche) ; la liste complète des statuts d'un crédit est documentée dans le workflow `dossier_precredit`.
- **Taux de défaut** (`default_rate`) : suivi en continu (crédits `defaulted` / total ou / actifs selon la formule, voir section 7).
- **Encours et impayés** (`outstanding_amount`, `overdue_amount`) : suivis en valeur absolue à l'instant présent, pas d'historisation stockée par ce module (recalcul à chaque affichage).
- **Tendances mensuelles** (`monthly.disbursement`, `monthly.repayment`, `monthly.overdue`) : seule forme de suivi "dans le temps" au sens strict, sur une fenêtre glissante de 12 mois.
- **Portefeuille à risque (PAR) par ancienneté** (`par_buckets`) : calculé par la méthode `get_par_buckets` du modèle `microfinance.loan` (hors périmètre de ce README, voir workflow `par_reporting`).
- **Répartition de risque** (`risk_distribution`) : photographie instantanée des crédits actifs/en défaut par niveau de risque (`low`/`medium`/`high`), pas un historique.

## 10. Rapports ou PDF
Aucun rapport dédié à ce jour.

## 11. Tableaux de bord
Ce workflow **est** le tableau de bord ; voir sections 5 et 9 pour le détail des indicateurs.

## 12. Sécurité et groupes utilisateurs
D'après `microfinance_loan_management/security/ir.model.access.csv`, seule une ligne existe pour le modèle `microfinance.dashboard` :

| Groupe | Lecture | Écriture | Création | Suppression |
|---|---|---|---|---|
| Agent crédit (`group_microfinance_user`) | Oui | Non | Non | Non |

Cette ligne (`access_microfinance_dashboard_user`) sécurise le modèle `microfinance.dashboard` et l'action classique `action_microfinance_dashboard` (formulaire en lecture seule), mais **cette action n'est référencée par aucun menu** (le menu `menu_microfinance_dashboard` pointe vers `action_microfinance_dashboard_client`, le composant OWL). L'affichage réellement utilisé par les utilisateurs est donc protégé uniquement par : (a) les `groups` du menu racine `menu_microfinance_root` (section 2), et (b) la route du contrôleur (`auth='user'`, donc accessible à tout utilisateur interne connecté) combinée aux droits ACL de chaque utilisateur sur les modèles sous-jacents interrogés (`microfinance.loan`, `microfinance.loan.installment`, `microfinance.loan.payment`).

## 13. Cas d'utilisation complets
1. **Manager crédit consulte la santé du portefeuille** : Menu `Microfinance > Tableau de bord` → lecture des 5 cartes KPI (crédits actifs, montant décaissé, encours, impayés, taux de défaut) → consultation du graphique "Crédits par état" pour visualiser la répartition.
2. **Finance microfinance suit les tendances mensuelles** : Menu `Microfinance > Tableau de bord` → graphique "Décaissements par mois" et "Remboursements vs impayés" pour repérer une dégradation sur les 12 derniers mois.
3. **Agent de recouvrement identifie les priorités** : Menu `Microfinance > Tableau de bord` → tableau "Crédits les plus en retard" (trié par jours de retard) pour cibler les visites de recouvrement à programmer.

## 14. Erreurs fréquentes
- Un utilisateur ne voyant pas le menu "Tableau de bord" : il n'appartient à aucun des groupes listés en section 2 (cas typique : utilisateur uniquement `group_microfinance_comptable`, qui n'est pas rattaché au menu racine).
- Message "Impossible de charger les données du dashboard." : échec de l'appel RPC, le plus souvent un droit ACL insuffisant sur `microfinance.loan`/`microfinance.loan.installment`/`microfinance.loan.payment` pour l'utilisateur connecté (le contrôleur interroge ces modèles avec les droits de l'utilisateur, pas en `sudo()`).
- Chiffres qui semblent incomplets lors d'un changement de société : normal, tous les indicateurs sont scopés à la société active unique (`env.company`), pas cumulés multi-société.
- Graphiques absents mais KPI/tableau présents : `ApexCharts` non chargé côté navigateur (avertissement en console navigateur, pas d'erreur bloquante).

## 15. Bonnes pratiques
- Basculer explicitement de société (sélecteur Odoo) pour consulter le dashboard de chaque agence plutôt que de supposer une vue consolidée, puisque les indicateurs ne sont jamais agrégés sur plusieurs sociétés.
- Ne pas se fier au seul menu visible pour juger des droits d'un utilisateur sur les données sous-jacentes : le contrôleur peut échouer silencieusement (message générique) si l'ACL sur `microfinance.loan` ou les modèles liés est insuffisante malgré l'accès au menu.
- Vérifier périodiquement le tableau "Crédits les plus en retard" (top 10) en complément du reporting PAR détaillé (workflow `par_reporting`), ce tableau étant volontairement limité à 10 lignes.

## 16. Questions/Réponses MOWGLI potentielles
- Quel est le montant total décaissé ce mois-ci ?
- Combien de crédits sont actuellement actifs dans mon agence ?
- Quel est le taux de défaut du portefeuille en ce moment ?
- Quels sont les crédits les plus en retard aujourd'hui ?
- Quelle est la répartition des crédits par état (actif, clôturé, en défaut) ?
- Quel est le montant total des impayés sur les crédits actifs ?
- Comment évoluent les remboursements par rapport aux impayés sur les 12 derniers mois ?
- Combien de crédits sont classés en risque élevé actuellement ?
- Pourquoi je ne vois pas le menu Tableau de bord dans mon compte ?
- Le tableau de bord montre-t-il les chiffres de toutes les agences en même temps ?
