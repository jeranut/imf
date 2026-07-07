# Microfinance Loan Management - Odoo 17 Community

Module créé from scratch pour gérer les crédits clients d'une institution de microfinance.

## Fonctionnalités V1

- Produits de crédit configurables
- Méthodes d'intérêt : flat rate et reducing balance
- Workflow : brouillon, soumis, validation manager, validation finance, approbation, actif, clôturé, défaut, radié
- Génération d'échéancier automatique, avec prise en compte du délai de grâce (`grace_period_days`) : première échéance décalée d'autant, et intérêt couru pendant un délai de grâce supérieur à une période capturé dans une échéance dédiée
- Remboursement avec allocation : pénalité → intérêt → capital
- Comptabilité : décaissement et remboursement via `account.move`
- Pénalités de retard appliquées une seule fois après délai de grâce
- Rééchelonnement de crédit actif (nouvelle durée et/ou nouvelle date de première échéance restante), historisé via `reschedule_count` et le chatter
- Règles de blocage à la demande de crédit : ancienneté client minimum, second crédit actif autorisé ou non, blocage si arriérés, blocage si le co-emprunteur a déjà un crédit actif
- Radiation / passage en perte d'un crédit actif ou en défaut, avec écriture comptable dédiée et exclusion du calcul de risque/PAR actif
- Provisionnement selon l'ancienneté des arriérés (`microfinance.provision.rule`, tranches paramétrables par société), écriture de régularisation par crédit via `action_post_provisions`, cron mensuel optionnel
- Reçu de décaissement imprimable (PDF, QWeb) depuis le crédit actif
- Portefeuille à risque (PAR) par tranche d'ancienneté (1-30/31-60/61-90/90+) dans le tableau de bord
- Annulation comptable propre d'un remboursement posté (contre-passation, restauration des échéances, réouverture du crédit si nécessaire)
- Garanties et cautions (`microfinance.loan.guarantee` : garantie matérielle ou caution personnelle), garantie obligatoire et/ou ratio minimum de couverture configurables par produit, libération automatique à la clôture du crédit
- Frais de dossier (fixes ou % du montant), encaissables via `action_charge_fee()`, décaissement bloqué tant qu'ils sont dus si le produit l'exige
- Périodicités de remboursement étendues : quinzaine, 4 semaines, bimestriel, trimestriel, 4 mois, semestriel, annuel (en plus de journalier/hebdomadaire/mensuel), avec intérêt proraté correctement pour chacune
- Visites de recouvrement
- Scoring crédit configurable (`microfinance.scoring.profile`/`microfinance.scoring.rule`) : un score unique (`internal_score`) par règles à seuil ou linéaires (points par unité), profils par produit ou génériques par société, décision (recommandé/revue manuelle/rejet) et niveau de risque associés
- Groupes de sécurité : agent crédit, manager, finance, auditeur, recouvrement
- Multi-company

## Installation

Copier le dossier `microfinance_loan_management` dans votre `addons_path`, redémarrer Odoo, mettre à jour la liste des applications puis installer le module.

### Dépendance à `base_accounting_kit`

Le module dépend désormais de `base_accounting_kit` (dépendance obligatoire dans le
manifest) : Odoo 17 Community n'a pas nativement de bilan / compte de résultat / balance,
et c'est ce module qui les fournit. Les comptes comptables de `microfinance_loan_management`
(`loan_account_id`, `interest_account_id`, `penalty_account_id`, `fee_account_id`,
`write_off_account_id`, `provision_account_id`, `provision_contra_account_id`) doivent donc
être configurés avec le `account_type` standard Odoo adapté pour apparaître correctement
classés dans ces états financiers (voir le détail et la correspondance recommandée dans
`docs/analyse_modules_comptables.md`).

## Configuration minimale

Créer un produit de crédit et renseigner :

- Journal de décaissement
- Journal de remboursement
- Compte prêts clients
- Compte produits intérêts
- Compte produits pénalités

Les journaux doivent avoir un compte par défaut.

Le compte de pertes sur créances irrécouvrables (`write_off_account_id`) est optionnel à la
configuration du produit, mais devient obligatoire au moment de radier un crédit de ce produit
(un journal des opérations diverses doit aussi exister pour la société).

De même, `provision_account_id` (charge de dotation) et `provision_contra_account_id`
(contrepartie bilan) sont optionnels à la configuration du produit, mais deviennent
obligatoires au moment de comptabiliser une provision pour ce produit
(`action_post_provisions`, même journal des opérations diverses que la radiation).

Les frais de dossier (`fee_type`/`fee_amount`/`fee_rate`, `fee_account_id`,
`fee_journal_id`) sont optionnels : par défaut `fee_amount`/`fee_rate` valent 0 (aucun frais).
Si activés et que `fee_charged_before_disbursement` est coché (par défaut), `fee_journal_id`
et `fee_account_id` doivent être configurés avant de pouvoir décaisser un crédit de ce
produit.

### Logique de provisionnement retenue

Les tranches d'ancienneté d'arriéré (`microfinance.provision.rule` : `min_days`/`max_days`/
`provision_rate`, par société, sans chevauchement) déterminent le taux de provision appliqué
au solde restant dû (`balance_total`) du crédit, selon le nombre de jours de retard de sa pire
échéance impayée. Le module livre des tranches indicatives par défaut pour la société
principale (0-30j : 0 %, 31-60j : 25 %, 61-90j : 50 %, 91-180j : 75 %, 181j+ : 100 %),
éditables sans redéploiement dans Microfinance > Configuration > Règles de provisionnement —
**à ajuster avec l'institution si une norme réglementaire précise s'applique** (ex. normes
BCEAO/COBAC pour la microfinance en zone UEMOA).

`action_post_provisions` comptabilise **une écriture par crédit** (plutôt qu'une écriture
consolidée pour tout le portefeuille) : plus simple à tracer et auditer individuellement dans
le chatter de chaque crédit, au prix d'un nombre d'écritures plus élevé lors d'une campagne
mensuelle sur tout le portefeuille. Chaque écriture ne comptabilise que le delta entre la
provision déjà comptabilisée (`provision_posted_amount`) et la provision recalculée
(`provision_amount`), jamais plus que le solde restant dû. Un cron mensuel optionnel
(désactivé par défaut) peut automatiser cette comptabilisation sur tout le portefeuille actif.

### Méthode de calcul d'intérêt au prorata selon la périodicité

`repayment_frequency` accepte désormais journalier, hebdomadaire, quinzaine (15 jours fixes),
4 semaines, mensuel, bimestriel, trimestriel, 4 mois, semestriel et annuel. Le taux annuel du
produit est proratisé par période selon deux méthodes, choisies pour rester cohérentes avec le
calcul en jours déjà utilisé ailleurs dans le module (délai de grâce) :

- **Périodicités qui correspondent à un nombre exact de mois calendaires** (mensuel,
  bimestriel, trimestriel, 4 mois, semestriel, annuel) : le taux annuel est proratisé par
  `nombre_de_mois / 12` (ex. trimestriel = taux annuel / 4, semestriel = taux annuel / 2,
  annuel = taux annuel complet).
- **Périodicités qui ne correspondent pas à un nombre entier de mois** (journalier,
  hebdomadaire, quinzaine, 4 semaines) : le taux annuel est proratisé au prorata du nombre de
  jours réel de la période, `nombre_de_jours / 365` — la quinzaine est un intervalle fixe de 15
  jours calendaires (pas une notion de "deux fois par mois" à dates fixes).

### Scoring crédit unifié (`internal_score`)

Il n'existe plus qu'**un seul score de crédit**, `internal_score` (0-100, plus haut = plus
sûr), calculé par `action_calculate_scoring()` à partir des règles configurables de
`microfinance.scoring.profile`/`microfinance.scoring.rule` (Microfinance > Configuration >
Scoring crédit). L'ancien `risk_score` codé en dur (heuristique fixe non paramétrable) a été
retiré ; ses pondérations ont été migrées telles quelles en règles par défaut du profil
« Profil de scoring standard » (société principale) :

- Score de base : +100 points
- -15 points par échéance en retard sur ce crédit
- -1.2 point par jour du plus long retard sur ce crédit
- -0.4 point par % du montant du crédit en retard
- -5 points par échéance payée partiellement sur ce crédit

Les règles à mode de calcul **linéaire** (`computation = 'linear'`) multiplient les points par
la valeur de la métrique (condition seuil/opérateur ignorée) ; c'est ce mode qui reproduit
les anciennes pondérations proportionnelles. Les règles à mode **seuil** (comportement
d'origine) appliquent des points fixes si la métrique respecte l'opérateur/la valeur.
Modifier le poids d'une règle recalcule immédiatement le score des crédits concernés au
prochain `action_calculate_scoring()` (bouton "Recalculer le score", soumission, ou cron
quotidien `cron_update_overdue_and_penalties`).

Le tableau de bord (répartition par risque) et les vues crédit (liste/kanban/formulaire)
n'affichent plus que ce score unique, accompagné de `risk_level` (faible/moyen/élevé/critique)
et `scoring_decision` (recommandé/revue manuelle/rejet) dérivés du même calcul.

### Non-intégration avec `custom_paid_totals`

`custom_paid_totals` (clôture de caisse journalière du projet EAT, point de vente) est hors
scope de ce module : sans rapport fonctionnel avec le crédit microfinance, et son mécanisme
d'ingestion ne capte que des `account.payment` réconciliés à des factures/notes de frais — nos
décaissements/remboursements créent des `account.move` directement, donc invisibles de ce
module de toute façon. Voir `docs/analyse_modules_comptables.md` pour le détail (y compris un
angle mort de trésorerie si un même journal caisse était partagé, non traité ici) et une
anomalie de disque constatée sur ce module, sans lien avec ce module-ci.

## Workflow conseillé

1. Créer le produit de crédit
2. Créer le dossier crédit
3. Soumettre
4. Valider manager
5. Valider finance
6. Approuver
7. Générer échéancier
8. Activer / Décaisser
9. Enregistrer les remboursements

## Points à tester en priorité

- Installation sur base Odoo 17 Community propre
- Création produit avec comptes comptables valides
- Génération échéancier flat et reducing, avec et sans délai de grâce
- Décaissement comptable
- Remboursement partiel
- Allocation automatique pénalité / intérêt / capital
- Application cron des pénalités
- Clôture automatique quand le solde est zéro
- Rééchelonnement d'un crédit actif (durée et/ou date de première échéance restante)
- Règles de blocage à la soumission (ancienneté, second crédit, arriérés, co-emprunteur)
- Radiation d'un crédit actif avec solde restant
- Comptabilisation des provisions selon l'ancienneté des arriérés, delta par rapport à la provision déjà comptabilisée
- Impression du reçu de décaissement
- PAR par tranche d'ancienneté dans le tableau de bord
- Annulation d'un remboursement posté (partiel, ayant clôturé le crédit, bloqué par période verrouillée)
- Garantie/ratio de garantie obligatoire bloquant la soumission, libération à la clôture
- Frais de dossier fixes et pourcentage, blocage du décaissement si non encaissés
- Génération d'échéancier pour chaque nouvelle périodicité (quinzaine, 4 semaines, bimestriel, trimestriel, 4 mois, semestriel, annuel), en particulier le prorata d'intérêt trimestriel et semestriel
- Modification d'une règle de scoring (seuil ou linéaire) : le score recalculé d'un crédit existant change en conséquence

## Limites V1

- Pas encore de gestion des groupes solidaires
- Dashboard simple, améliorable en OWL ou client action
