# Graphique "Évolution des impayés" du tableau de bord

## Définition de "nouvel impayé"

Le graphique affiche un **flux mensuel** (nombre de nouveaux impayés apparus dans le mois), pas
le stock cumulé d'échéances en retard.

Un **prêt** compte un nouvel impayé au mois de la première échéance dont le retard est constaté,
sauf si le prêt a déjà un épisode de retard **ouvert** à ce moment-là (une ou plusieurs échéances
encore non soldées, chevauchant dans le temps) — auquel cas l'échéance rejoint le même épisode
sans être recomptée. Un nouvel épisode n'est compté que si l'épisode précédent du prêt est
**bien clos** (toutes ses échéances soldées) avant la date de retard de la nouvelle échéance.

- Un prêt en retard sur plusieurs échéances consécutives qui se chevauchent (jamais totalement
  régularisé entre-temps) → **1 seul** nouvel impayé, au mois de la toute première échéance en
  retard.
- Un prêt régularisé (retour à jour complet) puis qui retombe en retard plus tard → **2**
  nouveaux impayés distincts (un par épisode).

## Implémentation

- `microfinance.loan.installment.arrears_onset_date` / `arrears_cured_date` : historique
  persistant, alimenté par `installment._sync_arrears_state()`, appelée quotidiennement par le
  cron `cron_update_overdue_and_penalties` (`models/microfinance_loan.py`). La détection de
  retard elle-même n'est pas dupliquée : `_sync_arrears_state()` s'appuie sur
  `installment._compute_state()` (déjà utilisé pour la tuile KPI "Impayés" et le préremplissage
  du wizard de remboursement), elle se contente d'observer les transitions et de les dater.
- `microfinance.loan.get_overdue_monthly_flux(company_id, month_keys)` regroupe les échéances par
  prêt et déroule l'algorithme d'épisodes décrit ci-dessus (`models/microfinance_loan.py`).
- Le contrôleur `/microfinance/dashboard/data` expose le résultat dans `monthly.new_overdue`,
  aligné sur les mêmes 12 mois que `monthly.disbursement`.

## Point de validation métier avant mise en prod

Le modèle ne conservait jusqu'ici **aucun horodatage** de passage en retard : `installment.state`
est recalculé à partir de `due_date`/`residual_amount`, sans trace historique des transitions. La
migration `migrations/17.0.1.4.0/post-migrate.py` initialise `arrears_onset_date` uniquement pour
les échéances **actuellement en retard** au moment de la mise à jour (depuis leur `due_date`).

**Conséquence** : les épisodes d'impayés déjà entièrement soldés *avant* la mise en prod de cette
fonctionnalité ne peuvent pas être reconstitués et n'apparaîtront pas dans l'historique du
graphique — les mois passés seront donc sous-estimés pour les prêts déjà remboursés à cette date.
Le graphique ne devient pleinement fiable, y compris sur les épisodes soldés, qu'à partir de la
date de mise en production. À valider avec le métier : si un historique rétroactif complet est
requis, il faudrait reconstituer les paiements dans l'ordre chronologique réel (dates de paiement
existantes) et non plus se baser sur `due_date` seul — hors périmètre de ce chantier.

## Gap connexe corrigé au passage

`installment.state` est un champ `compute(store=True)` dont les dépendances (`residual_amount`,
`total_amount`, `due_date`) ne référencent jamais "aujourd'hui" : sans écriture sur l'un de ces
champs, un enregistrement ne repassait donc pas automatiquement en `overdue` le jour où sa
`due_date` était dépassée. `_sync_arrears_state()` force ce recalcul quotidiennement (nécessaire
pour que le suivi des impayés soit fiable), ce qui corrige aussi indirectement l'application des
pénalités (`action_apply_penalty`), qui dépendait du même état potentiellement obsolète.
