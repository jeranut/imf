# Workflow Rééchelonnement

## 1. Objectif métier
Ce workflow couvre le rééchelonnement de l'échéancier restant d'un crédit actif (`microfinance.loan`, état `active`) : rallongement/modification de la durée restante et/ou de la date de première échéance restante, avec conservation d'un historique structuré de l'ancien échéancier avant réécriture. Il ne couvre PAS la génération de l'échéancier initial (`action_generate_schedule`, voir workflow `dossier_precredit`), ni le recouvrement des impayés (visites, pénalités — voir workflow `par_reporting`), ni la radiation (`action_write_off` — voir workflow `comptabilite`).

## 2. Utilisateurs concernés
D'après `security/ir.model.access.csv` et le bouton `action_reschedule` dans `microfinance_loan_views.xml` (`groups="microfinance_loan_management.group_microfinance_manager"`) :
- **Manager crédit** (`group_microfinance_manager`) : seul groupe autorisé à déclencher le rééchelonnement (bouton + accès complet lecture/écriture/création/suppression au wizard et lecture/écriture/création à l'historique).
- **Agent crédit** (`group_microfinance_user`) : lecture seule sur l'historique de rééchelonnement (`access_microfinance_reschedule_history_user` : 1,0,0,0), pas d'accès au bouton ni au wizard.
- **Finance microfinance** (`group_microfinance_finance`) : lecture seule sur l'historique (1,0,0,0), pas d'accès au bouton ni au wizard.
- **Auditeur microfinance** (`group_microfinance_auditor`) : lecture seule sur l'historique (1,0,0,0).
- **Gestionnaire** (`group_microfinance_gestionnaire`) : hérite de `group_microfinance_manager` via `implied_ids` (`security/groups.xml`), donc a également accès au bouton et au wizard.

## 3. Menus utilisés
Aucun menu dédié : `reechelonnement` ne possède pas d'entrée dans `microfinance_menus.xml`. Le bouton **Rééchelonner** n'apparaît que dans le formulaire de `microfinance.loan` (`view_microfinance_loan_form`), pas comme action de menu.
L'accès se fait donc uniquement en ouvrant une fiche crédit existante via le menu du workflow `dossier_precredit` :
`Microfinance > Crédits > Demande de crédit` (`menu_microfinance_root` > `menu_credits_root` > `menu_microfinance_loans`, action `action_microfinance_loan`), puis en cliquant sur le bouton **Rééchelonner** visible dans l'en-tête de la fiche crédit lorsque `state = 'active'`.

## 4. Étapes principales
Séquence dérivée de `action_reschedule` (`microfinance_loan.py` ~L525) et du wizard `microfinance_loan_reschedule_wizard.py` :
1. Ouvrir une fiche crédit (`microfinance.loan`) à l'état `active`.
2. Cliquer sur le bouton **Rééchelonner** (`action_reschedule`) — vérifie qu'il reste au moins une échéance non payée (`installment_ids` avec `state != 'paid'`), sinon bloque avec une erreur.
3. Le wizard `microfinance.loan.reschedule.wizard` s'ouvre en mode `target: 'new'`, avec `loan_id` préchargé.
4. Renseigner au moins l'un des deux champs : `new_term` (nouvelle durée restante en nombre d'échéances) et/ou `new_first_due_date` (nouvelle date de première échéance restante), et éventuellement un `reason` (motif).
5. Cliquer sur **Rééchelonner** (`action_apply`) : valide les champs puis appelle `loan_id._reschedule_installments(new_term, new_first_due_date, reason)`.
6. `_reschedule_installments` crée un enregistrement `microfinance.loan.reschedule.history` (snapshot des échéances non payées avant modification), calcule le nouveau `remaining_principal` et regénère les échéances restantes selon la nouvelle durée/date, incrémente `reschedule_count`, poste un message dans le chatter (ancien et nouvel échéancier).
7. Le wizard se ferme (`ir.actions.act_window_close`) ; la fiche crédit affiche le nouvel échéancier et l'entrée dans l'onglet **Historique de rééchelonnement**.

## 5. Champs importants
**Wizard `microfinance.loan.reschedule.wizard`** (`microfinance_loan_reschedule_wizard_views.xml`) :
- `loan_id` (Crédit) : crédit concerné, readonly, préchargé par le contexte.
- `currency_id` (devise) : related readonly, invisible dans la vue.
- `new_term` (Nouvelle durée restante (échéances)) : nombre d'échéances à générer pour le solde restant.
- `new_first_due_date` (Nouvelle date de 1ère échéance restante) : date de départ du nouvel échéancier.
- `reason` (Motif du rééchelonnement) : texte libre, tracé dans l'historique.

**Fiche crédit `microfinance.loan`** (champs liés au rééchelonnement, `microfinance_loan.py`) :
- `reschedule_count` (Nombre de rééchelonnements) : compteur, readonly, tracking activé.
- `reschedule_history_ids` (Historique de rééchelonnement) : One2many vers `microfinance.loan.reschedule.history`, affiché en onglet dédié readonly.

**Historique `microfinance.loan.reschedule.history`** (`microfinance_loan_reschedule_history.py`) :
- `reschedule_date` (Date de rééchelonnement), `user_id` (Utilisateur), `reason` (Motif), `old_installment_ids` (Ancien échéancier, One2many vers les lignes snapshot).

**Lignes d'historique `microfinance.loan.reschedule.history.line`** :
- `sequence`, `due_date` (Date d'échéance), `principal_amount`, `interest_amount`, `penalty_amount`, `paid_principal`, `paid_interest`, `paid_penalty`, `residual_amount` — copie figée (readonly) de l'état de chaque échéance non payée au moment du rééchelonnement.

## 6. Boutons et actions
- `action_reschedule` (bouton **Rééchelonner**, formulaire `microfinance.loan`) : `type="object"`, `groups="microfinance_loan_management.group_microfinance_manager"`, `invisible="state != 'active'"`. Ouvre le wizard.
- `action_apply` (bouton **Rééchelonner**, formulaire du wizard) : `type="object"`, classe `btn-primary`. Applique le rééchelonnement et ferme le wizard.
- Bouton **Annuler** (`special="cancel"`, classe `btn-secondary`) : ferme le wizard sans effectuer d'action.

## 7. Règles métier
Dérivées de `_reschedule_installments` (`microfinance_loan.py` L540-630) :
- Seules les échéances avec `state != 'paid'` sont éligibles au rééchelonnement (`unpaid`), triées par `due_date` puis `sequence`.
- Un snapshot complet des échéances non payées est créé dans `microfinance.loan.reschedule.history`/`.history.line` avant toute modification.
- `remaining_principal` = somme de `principal_amount - paid_principal` sur les échéances non payées.
- Seules les échéances en arriéré ou partiellement payées (`state in ('overdue', 'partial')`) reportent leur intérêt/pénalité déjà courus (`carried_interest`, `carried_penalty`) sur une ligne dédiée à la date d'échéance d'origine (`original_first_due_date`) ; les échéances futures simplement en attente (`pending`) ont leur intérêt recalculé à neuf.
- `term` = `new_term` si renseigné, sinon nombre d'échéances non payées existantes (`len(unpaid)`).
- `start` = `new_first_due_date` si renseigné, sinon date de première échéance d'origine (`original_first_due_date`).
- Les échéances partiellement payées (`paid_principal`, `paid_interest` ou `paid_penalty` non nuls) sont conservées mais verrouillées à ce qui a été réellement perçu (`principal_amount`/`interest_amount`/`penalty_amount` réécrits aux montants payés) ; la part non payée bascule dans le nouvel échéancier. Les échéances non touchées sont supprimées (`unlink`).
- Le nouveau capital par échéance = `remaining_principal / term`, réparti linéairement sur `term` échéances à partir de `start`, en respectant la même périodicité que celle du crédit (`_period_delta()`, `_period_interest_factor()`).
- L'intérêt de chaque nouvelle échéance suit la méthode du produit (`interest_method`) : `flat` (sur le capital restant total) ou dégressif (sur le solde restant courant).
- `reschedule_count` est incrémenté de 1 à chaque application réussie.
- Un message est posté dans le chatter du crédit (`message_post`) résumant l'ancien et le nouvel échéancier.

## 8. Contrôles et blocages
- **Wizard, `action_apply`** : si ni `new_term` ni `new_first_due_date` ne sont renseignés → `UserError` : *« Renseignez une nouvelle durée et/ou une nouvelle date de première échéance. »*
- **Wizard, `action_apply`** : si `new_term` renseigné et `<= 0` → `UserError` : *« La nouvelle durée doit être un nombre d'échéances positif. »*
- **`action_reschedule`** : si le crédit n'est pas à l'état `active` → `UserError` : *« Le rééchelonnement n'est possible que pour un crédit actif. »*
- **`action_reschedule`** : s'il n'y a aucune échéance restante (`state != 'paid'`) → `UserError` : *« Aucune échéance restante à rééchelonner. »*
- **`_reschedule_installments`** : même contrôle redondant côté modèle (défense en profondeur) — si `unpaid` est vide → `UserError` : *« Aucune échéance restante à rééchelonner. »*
- Le bouton **Rééchelonner** est invisible (donc inaccessible depuis l'UI) pour tout utilisateur hors `group_microfinance_manager` et pour tout crédit dont l'état n'est pas `active`.

## 9. Statuts
Ce workflow n'a pas de champ `state` propre : ni `microfinance.loan.reschedule.wizard` (`TransientModel` sans état), ni `microfinance.loan.reschedule.history` (simple journal, pas de cycle de vie). Le seul état conditionnant l'accès au workflow est celui du crédit parent, `microfinance.loan.state` (voir workflow `dossier_precredit` section 9) : le bouton **Rééchelonner** n'est visible que lorsque `state = 'active'`.

## 10. Rapports ou PDF
Aucun rapport dédié à ce jour. Aucune définition de `ir.actions.report` liée à `microfinance.loan.reschedule.history` ou au wizard n'a été trouvée dans le code.

## 11. Tableaux de bord
Aucun indicateur dédié au rééchelonnement trouvé dans `microfinance_dashboard.py`. Le compteur `reschedule_count` et l'onglet `reschedule_history_ids` ne sont visibles que sur la fiche crédit individuelle, pas agrégés dans un tableau de bord.

## 12. Sécurité et groupes utilisateurs
D'après `security/ir.model.access.csv` :

| Modèle | Groupe | Lecture | Écriture | Création | Suppression |
|---|---|---|---|---|---|
| `microfinance.loan.reschedule.wizard` | Manager crédit | 1 | 1 | 1 | 1 |
| `microfinance.loan.reschedule.history` | Agent crédit | 1 | 0 | 0 | 0 |
| `microfinance.loan.reschedule.history` | Manager crédit | 1 | 1 | 1 | 0 |
| `microfinance.loan.reschedule.history` | Finance microfinance | 1 | 0 | 0 | 0 |
| `microfinance.loan.reschedule.history` | Auditeur microfinance | 1 | 0 | 0 | 0 |
| `microfinance.loan.reschedule.history.line` | Agent crédit | 1 | 0 | 0 | 0 |
| `microfinance.loan.reschedule.history.line` | Manager crédit | 1 | 1 | 1 | 0 |
| `microfinance.loan.reschedule.history.line` | Finance microfinance | 1 | 0 | 0 | 0 |
| `microfinance.loan.reschedule.history.line` | Auditeur microfinance | 1 | 0 | 0 | 0 |

À noter : aucun groupe n'a de droit de suppression (`perm_unlink=0`) sur l'historique ou ses lignes — l'historique n'est jamais supprimable depuis l'UI standard, y compris par le manager.
De plus, `security/microfinance_company_rules.xml` définit `microfinance_loan_reschedule_history_company_rule` (cloisonnement `company_id in company_ids`, sans groupe ciblé donc appliqué à tous) et `microfinance_loan_reschedule_history_line_company_rule` (cloisonnement via `history_id.company_id`, la ligne n'ayant pas de `company_id` propre).

## 13. Cas d'utilisation complets
1. **Rééchelonnement simple pour allonger la durée** : le manager ouvre `Microfinance > Crédits > Demande de crédit`, sélectionne un crédit actif en difficulté de remboursement, clique sur **Rééchelonner**, saisit `new_term = 12` (au lieu des 6 échéances restantes) sans changer la date, ajoute un motif « Difficulté saisonnière de trésorerie », clique sur **Rééchelonner**. Le système archive l'ancien échéancier dans l'onglet **Historique de rééchelonnement**, génère 12 nouvelles échéances à partir de la date d'échéance restante d'origine, et incrémente `reschedule_count` à 1.
2. **Rééchelonnement avec report de date de départ** : le manager constate que le client n'a pas pu payer depuis 2 mois ; il ouvre le crédit, clique sur **Rééchelonner**, laisse `new_term` vide (conserve le même nombre d'échéances restantes) mais fixe `new_first_due_date` à une date 60 jours plus tard. Les intérêts et pénalités déjà courus sur les échéances en retard sont reportés sur une ligne dédiée à la date d'échéance d'origine ; les échéances futures sont régénérées à partir de la nouvelle date.
3. **Tentative bloquée par un utilisateur non autorisé** : un agent crédit (`group_microfinance_user`) ouvre une fiche crédit active ; le bouton **Rééchelonner** n'apparaît pas dans l'en-tête (masqué par le `groups=` du bouton). L'agent peut uniquement consulter l'onglet **Historique de rééchelonnement** en lecture seule si des rééchelonnements antérieurs existent.

## 14. Erreurs fréquentes
- *« Renseignez une nouvelle durée et/ou une nouvelle date de première échéance. »* — aucun des deux champs du wizard n'a été rempli.
- *« La nouvelle durée doit être un nombre d'échéances positif. »* — `new_term` saisi à 0 ou négatif.
- *« Le rééchelonnement n'est possible que pour un crédit actif. »* — tentative sur un crédit `draft`, `approved`, `closed`, `defaulted`, `written_off` ou `cancelled`.
- *« Aucune échéance restante à rééchelonner. »* — toutes les échéances du crédit sont déjà à l'état `paid` (crédit soldé).
- Bouton **Rééchelonner** invisible : soit l'utilisateur n'a pas le groupe `group_microfinance_manager` (ou `group_microfinance_gestionnaire`), soit le crédit n'est pas à l'état `active`.

## 15. Bonnes pratiques
- Toujours renseigner un `reason` explicite : c'est le seul champ texte libre conservé dans l'historique et dans le message du chatter pour justifier a posteriori (audit, comité) pourquoi un échéancier a été modifié.
- Vérifier `overdue_installment_count` et `balance_total` sur la fiche crédit avant de rééchelonner, pour choisir une `new_term` cohérente avec la capacité de remboursement réelle du client.
- Ne modifier que l'un des deux champs (`new_term` ou `new_first_due_date`) si l'objectif est ciblé (allonger la durée OU décaler le départ), afin de limiter l'impact sur le calcul des intérêts recalculés.
- Garder à l'esprit qu'un rééchelonnement supprime définitivement (`unlink`) les échéances non touchées non partiellement payées : l'historique (`reschedule_history_ids`) est la seule trace de l'échéancier précédent, à consulter avant toute nouvelle opération sur un crédit déjà rééchelonné plusieurs fois (`reschedule_count`).

## 16. Questions/Réponses MOWGLI potentielles
1. Comment rééchelonner un crédit en retard de paiement ?
2. Où se trouve le bouton pour rééchelonner un crédit dans Odoo ?
3. Pourquoi je ne vois pas le bouton Rééchelonner sur la fiche crédit ?
4. Le rééchelonnement d'un crédit clôturé est-il possible ?
5. Que devient l'ancien échéancier après un rééchelonnement ?
6. Comment consulter l'historique des rééchelonnements d'un client ?
7. Qui a le droit de rééchelonner un crédit chez MOWGLI ?
8. Les intérêts déjà courus sont-ils perdus lors d'un rééchelonnement ?
9. Combien de fois un même crédit peut-il être rééchelonné ?
10. Faut-il indiquer un motif pour rééchelonner un crédit ?
