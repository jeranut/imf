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
`Microfinance` (`menu_microfinance_root`) > `Tableau de bord` (`menu_microfinance_dashboard`, séquence 1).

## 4. Étapes principales
1. L'utilisateur clique sur le menu `Microfinance > Tableau de bord`.
2. L'écran se charge automatiquement et calcule, pour la seule société active du sélecteur Odoo, l'ensemble des indicateurs du portefeuille de crédit : KPI, répartition par état, tendances mensuelles, répartition de risque, portefeuille à risque (PAR) par ancienneté et crédits les plus en retard.
3. Les 5 cartes KPI s'affichent en premier, suivies de 5 graphiques (état des crédits, décaissements mensuels, remboursements vs impayés, taux de défaut avec répartition de risque, PAR par ancienneté), puis du tableau des crédits les plus en retard.
4. En cas d'échec du chargement des données, un message d'erreur générique s'affiche à la place des graphiques.

## 5. Champs importants
Indicateurs affichés à l'écran (calculés à chaque ouverture, aucun n'est saisissable) :
- **Crédits actifs** : nombre de crédits à l'état actif, pour la société active.
- **Montant décaissé** : somme des montants des crédits actifs, clôturés ou en défaut.
- **Encours total** : somme des soldes restants dus des crédits actifs et en défaut.
- **Impayés** : somme des montants en retard des crédits actifs et en défaut.
- **Taux de défaut (%)** : nombre de crédits en défaut / nombre de crédits actifs × 100.
- **Devise** : celle de la société active.

Données supplémentaires affichées via les graphiques et le tableau :
- **Répartition des crédits par état** : histogramme du nombre de crédits par état (actif, clôturé, en défaut, etc.).
- **Tendances mensuelles** : décaissements, remboursements et impayés sur les 12 derniers mois glissants.
- **Répartition de risque** : nombre de crédits actifs/en défaut par niveau de risque (faible/moyen/élevé).
- **Portefeuille à risque (PAR) par ancienneté** : tranches d'impayés par ancienneté de retard.
- **Crédits les plus en retard** : top 10 (partenaire, crédit, montant dû, jours de retard), trié par jours de retard puis montant dû décroissants.

## 6. Boutons et actions
Aucun bouton : l'écran est exclusivement dédié à la consultation. Aucune action de création, modification ou suppression n'est proposée depuis le tableau de bord.

## 7. Règles métier
- Tous les indicateurs sont recalculés à chaque ouverture de l'écran et toujours scopés à la société active unique du sélecteur Odoo, même si l'utilisateur a coché plusieurs sociétés : jamais de vue consolidée multi-société.
- La répartition de risque regroupe le niveau de risque "critique" du crédit dans la catégorie "élevé" (le dashboard ne distingue que 3 niveaux : faible/moyen/élevé).
- Les séries mensuelles couvrent une fenêtre glissante de 12 mois (mois courant inclus + 11 mois précédents).
- Le tableau "crédits les plus en retard" ne retient que les échéances en retard avec un montant restant dû strictement positif, agrégées par crédit, triées par jours de retard décroissants puis montant dû décroissant, limitées à 10 lignes.

## 8. Contrôles et blocages
- Aucune écriture n'est possible : l'écran est exclusivement dédié à la consultation, aucune action de création/modification/suppression n'y est proposée.
- Si le chargement des données échoue (erreur serveur, droits insuffisants sur les données sous-jacentes, etc.), le message "Impossible de charger les données du dashboard." s'affiche à la place des graphiques.
- Si la bibliothèque de graphiques ne se charge pas côté navigateur, les graphiques sont simplement absents, mais les cartes KPI et le tableau restent affichés.

## 9. Statuts suivis
Le tableau de bord n'a **aucun cycle de statuts propre** : c'est un écran 100 % calculé, sans machine à états. Cette section documente donc les indicateurs suivis dans le temps plutôt qu'un cycle de statuts :
- **Répartition des crédits par état** : histogramme dynamique construit à partir de l'état de chaque crédit. Les libellés affichés sont ceux définis sur le champ statut du crédit (`microfinance.loan`), pas une liste figée dans ce module. Les statuts explicitement pris en compte dans les calculs du dashboard sont `actif`, `clôturé` et `en défaut` ; la liste complète des statuts d'un crédit est documentée dans le workflow `dossier_precredit`.
- **Taux de défaut** : suivi en continu, calculé comme crédits en défaut / crédits actifs.
- **Encours et impayés** : suivis en valeur absolue à l'instant présent, pas d'historique conservé (recalcul à chaque affichage).
- **Tendances mensuelles** (décaissements, remboursements, impayés) : seule forme de suivi "dans le temps" au sens strict, sur une fenêtre glissante de 12 mois.
- **Portefeuille à risque (PAR) par ancienneté** : calculé côté crédit (hors périmètre de ce README, voir workflow `par_reporting`).
- **Répartition de risque** : photographie instantanée des crédits actifs/en défaut par niveau de risque, pas un historique.

## 10. Rapports ou PDF
Aucun rapport dédié à ce jour.

## 11. Tableaux de bord
Ce workflow **est** le tableau de bord ; voir sections 5 et 9 pour le détail des indicateurs.

## 12. Sécurité et groupes utilisateurs
L'accès au menu `Tableau de bord` est gouverné par les groupes autorisés sur le menu racine `Microfinance` (section 2) : Agent crédit, Manager crédit, Finance microfinance, Auditeur microfinance, Agent recouvrement, ainsi que Caissier, Comité de crédit et Gestionnaire par héritage. Un utilisateur n'appartenant à aucun de ces groupes ne voit pas le menu.

Au-delà de l'accès au menu, l'affichage effectif des indicateurs dépend aussi des droits de lecture de l'utilisateur connecté sur les crédits, échéances et remboursements (`microfinance.loan`, `microfinance.loan.installment`, `microfinance.loan.payment`) : un utilisateur voyant le menu mais disposant de droits insuffisants sur ces données peut rencontrer une erreur de chargement (voir section 14).

## 13. Cas d'utilisation complets
1. **Manager crédit consulte la santé du portefeuille** : Menu `Microfinance > Tableau de bord` → lecture des 5 cartes KPI (crédits actifs, montant décaissé, encours, impayés, taux de défaut) → consultation du graphique "Crédits par état" pour visualiser la répartition.
2. **Finance microfinance suit les tendances mensuelles** : Menu `Microfinance > Tableau de bord` → graphique "Décaissements par mois" et "Remboursements vs impayés" pour repérer une dégradation sur les 12 derniers mois.
3. **Agent de recouvrement identifie les priorités** : Menu `Microfinance > Tableau de bord` → tableau "Crédits les plus en retard" (trié par jours de retard) pour cibler les visites de recouvrement à programmer.

## 14. Erreurs fréquentes
- Un utilisateur ne voyant pas le menu "Tableau de bord" : il n'appartient à aucun des groupes listés en section 2 (cas typique : utilisateur uniquement `group_microfinance_comptable`, qui n'est pas rattaché au menu racine).
- Message "Impossible de charger les données du dashboard." : échec du chargement des données, le plus souvent parce que l'utilisateur connecté n'a pas les droits de lecture nécessaires sur les crédits, échéances ou remboursements.
- Chiffres qui semblent incomplets lors d'un changement de société : normal, tous les indicateurs sont scopés à la société active unique du sélecteur Odoo, jamais cumulés multi-société.
- Graphiques absents mais KPI/tableau présents : la bibliothèque de graphiques n'est pas chargée côté navigateur, sans que cela bloque l'affichage des KPI et du tableau.

## 15. Bonnes pratiques
- Basculer explicitement de société (sélecteur Odoo) pour consulter le dashboard de chaque agence plutôt que de supposer une vue consolidée, puisque les indicateurs ne sont jamais agrégés sur plusieurs sociétés.
- Ne pas se fier au seul menu visible pour juger des droits d'un utilisateur sur les données sous-jacentes : le chargement du tableau de bord peut échouer avec un message générique si les droits de lecture sur les crédits ou les modèles liés sont insuffisants, même si l'utilisateur voit le menu.
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
