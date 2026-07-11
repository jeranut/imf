# Workflow PAR / Reporting

## 1. Objectif métier
Ce workflow couvre le suivi du portefeuille à risque (PAR) via l'état des échéances impayées (`microfinance.loan.installment`), les visites de recouvrement terrain (`microfinance.collection.visit`), les vues d'analyse échéances/paiements, et la balance des comptes d'épargne. Il documente en détail le champ `state` et les champs de retard de `microfinance.loan.installment`, ainsi que les champs agrégés `overdue_amount`/`balance_total` de `microfinance.loan` sous l'angle analyse/reporting.

N'est PAS couvert ici : l'allocation d'un remboursement sur les échéances (méthode `_allocate_to_installments`) et sa comptabilisation, documentées dans le workflow `comptabilite` — ce README se limite à la lecture de l'état résultant des échéances, pas à la mécanique qui le produit. Ne sont pas non plus couverts : le calcul du provisionnement comptable (`comptabilite`), le scoring crédit et le niveau de risque (`garanties_scoring`), le rééchelonnement d'un échéancier (`reechelonnement`).

## 2. Utilisateurs concernés
D'après `microfinance_loan_management/security/groups.xml` et `ir.model.access.csv` :
- **Agent recouvrement** (`group_microfinance_collection_agent`) : lecture/écriture/création sur les visites de recouvrement (`visit.collection`), pas de suppression.
- **Agent crédit** (`group_microfinance_user`) : lecture seule sur les visites et sur les échéances.
- **Manager crédit** (`group_microfinance_manager`) : accès complet aux visites et aux échéances.
- **Finance microfinance** (`group_microfinance_finance`) : lecture/écriture sur les échéances (`installment.finance`), pas d'accès dédié aux visites.
- **Auditeur microfinance** (`group_microfinance_auditor`) : lecture seule sur `microfinance.loan` en général (via `loan.auditor`) et sur les comptes/transactions d'épargne (module MSM).
- **Agent épargne / Manager épargne** (`group_savings_agent` / `group_savings_manager`, module MSM) : accès aux comptes d'épargne consultés dans la balance épargne (respectivement lecture/écriture/création, et accès complet).

## 3. Menus utilisés
Depuis `microfinance_loan_management/views/microfinance_menus.xml` et `microfinance_savings_management/views/microfinance_savings_menus.xml` :
- Microfinance > Recouvrement > Visites terrain (`menu_microfinance_visits`, parent `menu_microfinance_collection`, lui-même enfant de `menu_microfinance_root` ; action `action_microfinance_visit`).
- Microfinance > Analyse > Analyse échéances (`menu_microfinance_analysis_installments`, parent `menu_microfinance_analysis`, enfant de `menu_microfinance_root` ; action `action_microfinance_installment`, la même action que le menu Échéances du workflow `comptabilite`).
- Microfinance > Analyse > Analyse paiements (`menu_microfinance_analysis_payments`, parent `menu_microfinance_analysis` ; action `action_microfinance_payment`).
- Microfinance > Analyse > Balance épargne (`menu_microfinance_savings_balance_report`, parent `microfinance_loan_management.menu_microfinance_analysis` ; action `action_microfinance_savings_balance_report`, module MSM).

Depuis la fiche crédit elle-même (bouton statistique) : « Visites » (`action_view_visits`) ouvre la liste/calendrier des visites du crédit concerné.

## 4. Étapes principales

**A. Suivi du portefeuille à risque**
1. Le champ `state` de chaque échéance (`pending`/`partial`/`paid`/`overdue`) est recalculé automatiquement (`_compute_state`, champ `compute` stocké) dès que son montant résiduel ou sa date d'échéance change.
2. Le cron `cron_update_overdue_and_penalties` (défini dans `microfinance_loan.py`) applique quotidiennement les pénalités de retard (`action_apply_penalty`) sur toutes les échéances `pending`/`partial`/`overdue`, puis recalcule le scoring de tous les crédits `active`.
3. Un gestionnaire consulte Microfinance > Analyse > Analyse échéances et utilise le filtre « En retard » (`state = overdue`) pour visualiser les impayés, ou regroupe par État/Crédit.
4. Sur la fiche crédit, les champs calculés `overdue_amount` (montant en retard) et `overdue_installment_count` (nombre d'échéances en retard) résument la situation ; `balance_total` donne le solde global restant dû.
5. Si la situation se dégrade, un utilisateur peut cliquer « Marquer en défaut » (`action_mark_default`) sur la fiche crédit pour passer le crédit en `defaulted`.

**B. Visite de recouvrement**
1. Depuis la fiche crédit (bouton stat « Visites ») ou depuis Microfinance > Recouvrement > Visites terrain, créer une nouvelle visite.
2. Renseigner le crédit, l'agent terrain (utilisateur courant par défaut), la date de visite, le statut (`Planifiée` par défaut).
3. Après la visite, mettre à jour manuellement le statut (`Réalisée`/`Manquée`/`Annulée`), consigner les remarques, et le cas échéant la promesse de paiement (date + montant).
4. Planifier la prochaine visite (`next_visit_date`), consultable aussi en vue calendrier (couleur par agent).

**C. Balance épargne**
1. Ouvrir Microfinance > Analyse > Balance épargne : liste des comptes d'épargne (`microfinance.savings.account`) filtrée par défaut sur les comptes actifs et regroupée par produit (`search_default_active`, `search_default_group_product`).
2. Le solde (`balance`) est totalisé (`sum="Total"`) par la vue liste.

## 5. Champs importants

**`microfinance.loan.installment`**
- `sequence`, `due_date` : ordre et date d'échéance.
- `principal_amount`, `interest_amount`, `penalty_amount` : montants dus par composante.
- `total_amount` (calculé) : somme des trois montants dus.
- `paid_principal`, `paid_interest`, `paid_penalty` : montants déjà encaissés par composante (alimentés par le workflow `comptabilite`).
- `residual_amount` (calculé) : `total_amount` diminué du total payé, plancher à 0.
- `state` (calculé, stocké) : `pending`/`partial`/`paid`/`overdue`.
- `penalty_applied` : indicateur empêchant une double application de pénalité.

**`microfinance.loan` (champs PAR)**
- `overdue_amount` (calculé, stocké) : somme des `residual_amount` des échéances à l'état `overdue`.
- `overdue_installment_count` (calculé, stocké) : nombre de ces échéances.
- `balance_total` (calculé, stocké) : somme des `residual_amount` de toutes les échéances (ou `loan_amount` si aucune échéance n'existe encore).
- (Détail complet de l'allocation qui alimente ces montants : voir workflow `comptabilite`.)

**`microfinance.collection.visit`**
- `loan_id`, `partner_id` (related), `agent_id` (utilisateur courant par défaut).
- `visit_date`, `next_visit_date`.
- `status` : Planifiée / Réalisée / Manquée / Annulée.
- `remarks` : compte-rendu texte libre.
- `promise_to_pay_date`, `promised_amount` : promesse de paiement recueillie lors de la visite.

**`microfinance.savings.account` (balance épargne)**
- `name`, `partner_id`, `product_id`, `balance` (totalisé), `maturity_date`, `state`.

## 6. Boutons et actions
- `action_apply_penalty` (« Appliquer pénalité », formulaire échéance) — `invisible="penalty_applied"`. Applique la pénalité du produit (montant fixe ou taux sur le résiduel) si la date d'échéance + délai de grâce du produit est dépassée, et marque `penalty_applied=True` pour empêcher toute réapplication.
- `action_mark_default` (« Marquer en défaut », formulaire crédit) — `invisible="state != 'active'"`, aucune restriction de groupe : accessible à tout utilisateur ayant accès en écriture à la fiche crédit.
- `action_view_visits` (bouton statistique, formulaire crédit) : ouvre la liste/formulaire/calendrier des visites du crédit (`view_mode='tree,form,calendar'`).

## 7. Règles métier
- `_compute_amounts` : `total_amount = principal_amount + interest_amount + penalty_amount` ; `residual_amount = max(total_amount - (paid_principal + paid_interest + paid_penalty), 0.0)`.
- `_compute_state` : `paid` si `total_amount` non nul et `residual_amount <= 0.01` ; sinon `partial` si `residual_amount < total_amount` ; sinon `overdue` si `due_date` est dépassée ; sinon `pending`.
- `action_apply_penalty` : ne s'applique qu'aux échéances non déjà `penalty_applied`, à l'état `pending`/`partial`/`overdue`, et seulement si `due_date + grace_period_days` (délai de grâce du produit) est strictement dans le passé. Montant ajouté = `penalty_amount` fixe du produit, ou `residual_amount * penalty_rate / 100` selon `penalty_type`.
- `_get_max_overdue_days` (sur `microfinance.loan`) : nombre maximal de jours de retard parmi les échéances `overdue` du crédit, utilisé à la fois pour la PAR et pour le calcul de provision (`comptabilite`).
- `get_par_buckets` (méthode de classe, alimente le tableau de bord) : répartit l'encours des crédits `active`/`defaulted` d'une société en 4 tranches d'ancienneté de retard (1-30, 31-60, 61-90, 90+ jours), en % de l'encours total du portefeuille ; un crédit sans retard (`max_days <= 0`) n'est classé dans aucune tranche.
- `cron_update_overdue_and_penalties` recalcule aussi le scoring (`action_calculate_scoring(silent=True)`) de tous les crédits `active` après l'application des pénalités du jour.

## 8. Contrôles et blocages
Ce workflow ne présente pas de message de blocage qui lui soit propre. Le bouton « Marquer en défaut » n'est visible que si le crédit est à l'état Actif. Les messages d'erreur qu'un utilisateur peut rencontrer au sujet des échéances (surpaiement, crédit non actif pour un remboursement, etc.) sont levés au moment de l'enregistrement d'un remboursement et sont documentés dans le workflow `comptabilite`, section 8.

## 9. Statuts
**`microfinance.loan.installment.state`** : `pending` (À payer) / `partial` (Partiel) / `paid` (Payé) / `overdue` (En retard). Ce champ est recalculé automatiquement (voir section 7) mais reste modifiable manuellement sur la fiche échéance. Aucune transition n'est pilotée par un bouton dédié : l'état découle du recalcul de `residual_amount` et de la comparaison de `due_date` à la date du jour. La seule action de formulaire associée, `action_apply_penalty`, ne change pas `state` mais ajoute une pénalité et bascule `penalty_applied`.

**`microfinance.collection.visit.status`** : `planned` (Planifiée, valeur par défaut) / `done` (Réalisée) / `missed` (Manquée) / `cancelled` (Annulée). La mise à jour du statut se fait manuellement sur le formulaire de la visite, au fil du suivi de recouvrement (aucun bouton dédié n'est proposé pour ce changement).

## 10. Rapports ou PDF
Aucun rapport ou document imprimable n'est disponible pour ce workflow (les reçus de décaissement et de transaction d'épargne sont documentés dans le workflow `comptabilite`).

## 11. Tableaux de bord
Dans `microfinance.dashboard` / contrôleur `/microfinance/dashboard/data` (`microfinance_dashboard_controller.py`) :
- KPI « Impayés » (`overdue_amount`, somme de `overdue_amount` des crédits `active`/`defaulted`) et KPI « Taux de défaut (%) » (`default_rate`).
- Graphique en barres « PAR » par tranche d'ancienneté (`par_buckets`, alimenté par `get_par_buckets` : tranches 1-30/31-60/61-90/90+ jours, valeurs en % de l'encours).
- Graphique ligne mensuel « Impayés » (`monthly.overdue`, 12 derniers mois, basé sur les échéances `overdue` par mois d'échéance).
- Graphique radial « Taux de défaut » (`default_rate`).
- Tableau « Top échéances en retard » (`top_overdue_loans`, jusqu'à 10 lignes) : emprunteur, référence crédit, montant dû, nombre de jours de retard, trié par retard puis montant décroissants.

## 12. Sécurité et groupes utilisateurs

**`microfinance.loan.installment`** (`microfinance_loan_management/security/ir.model.access.csv`)

| Groupe | Lecture | Écriture | Création | Suppression |
|---|---|---|---|---|
| Agent crédit (`group_microfinance_user`) | Oui | Non | Non | Non |
| Finance microfinance (`group_microfinance_finance`) | Oui | Oui | Non | Non |
| Manager crédit (`group_microfinance_manager`) | Oui | Oui | Oui | Oui |

**`microfinance.collection.visit`**

| Groupe | Lecture | Écriture | Création | Suppression |
|---|---|---|---|---|
| Agent recouvrement (`group_microfinance_collection_agent`) | Oui | Oui | Oui | Non |
| Agent crédit (`group_microfinance_user`) | Oui | Non | Non | Non |
| Manager crédit (`group_microfinance_manager`) | Oui | Oui | Oui | Oui |

**`microfinance.savings.account`** (`microfinance_savings_management/security/ir.model.access.csv`, utilisée pour la balance épargne)

| Groupe | Lecture | Écriture | Création | Suppression |
|---|---|---|---|---|
| Agent épargne (`group_savings_agent`) | Oui | Oui | Oui | Non |
| Manager épargne (`group_savings_manager`) | Oui | Oui | Oui | Oui |
| Manager crédit (`microfinance_loan_management.group_microfinance_manager`) | Oui | Non | Non | Non |
| Finance microfinance (`microfinance_loan_management.group_microfinance_finance`) | Oui | Non | Non | Non |
| Auditeur microfinance (`microfinance_loan_management.group_microfinance_auditor`) | Oui | Non | Non | Non |

## 13. Cas d'utilisation complets
1. **Détection et relance d'un impayé.** Un gestionnaire ouvre Microfinance > Analyse > Analyse échéances, applique le filtre « En retard », identifie une échéance `overdue` d'un client. Il ouvre le crédit correspondant, consulte `overdue_amount`/`overdue_installment_count`, puis clique sur le bouton stat « Visites » pour planifier une visite de recouvrement.
2. **Visite de recouvrement avec promesse de paiement.** Un agent de recouvrement crée une visite depuis Microfinance > Recouvrement > Visites terrain (crédit, statut `Planifiée`). Après s'être rendu chez le client, il repasse le statut à `Réalisée`, saisit une promesse de paiement (date + montant) et des remarques.
3. **Passage en défaut d'un crédit très en retard.** Un manager consulte un crédit `Actif` dont `overdue_installment_count` est élevé depuis plusieurs mois, clique « Marquer en défaut » sur la fiche crédit : le crédit passe en `En défaut`, ce qui l'inclut dans le calcul de provision et le rend éligible à la radiation (workflow `comptabilite`).
4. **Consultation de la balance épargne.** Un manager épargne ouvre Microfinance > Analyse > Balance épargne pour visualiser, regroupés par produit, les soldes de tous les comptes actifs et leur total.

## 14. Erreurs fréquentes
Ce workflow ne génère pas de messages de blocage qui lui soient propres (voir section 8). Les seuls messages d'erreur qu'un utilisateur peut rencontrer en lien avec les échéances (surpaiement, crédit non actif pour un remboursement) proviennent de l'enregistrement d'un remboursement et sont documentés dans le workflow `comptabilite`, section 8.

## 15. Bonnes pratiques
- S'assurer que le cron `cron_update_overdue_and_penalties` est actif afin que les pénalités de retard et l'état des échéances restent à jour quotidiennement, condition nécessaire à la fiabilité des indicateurs PAR du tableau de bord.
- Programmer systématiquement une `next_visit_date` à l'issue de chaque visite de recouvrement, pour permettre le suivi via la vue calendrier.
- Ne marquer un crédit « En défaut » qu'après une évaluation réelle du dossier (visites de recouvrement effectuées, promesses de paiement non tenues).
- Consulter Microfinance > Analyse > Analyse échéances régulièrement plutôt que de se fier uniquement au tableau de bord, pour identifier précisément les échéances individuelles en cause derrière un indicateur agrégé.

## 16. Questions/Réponses MOWGLI potentielles
1. Comment voir la liste des échéances en retard dans MOWGLI ?
2. Quel est le montant total impayé sur un crédit donné ?
3. Comment enregistrer une visite de recouvrement chez un client ?
4. Comment consigner une promesse de paiement lors d'une visite terrain ?
5. Comment marquer un crédit en défaut ?
6. Qu'est-ce que le PAR (portefeuille à risque) et comment est-il calculé dans MOWGLI ?
7. Comment consulter la balance des comptes d'épargne par produit ?
8. Pourquoi une échéance passe-t-elle automatiquement en « En retard » ?
9. Qui peut créer ou modifier une visite de recouvrement ?
10. Comment une pénalité de retard est-elle appliquée à une échéance impayée ?
