# Audit — Séparation activation / décaissement effectif

Audit **en lecture seule**. Aucune modification de code, de vue, de données ni de sécurité.
Aucun commit. Les extraits ci-dessous sont recopiés du code, pas reformulés.

Fichiers de référence :
- `microfinance_loan_management/models/microfinance_loan.py`
- `microfinance_loan_management/models/microfinance_loan_installment.py`
- `microfinance_loan_management/models/microfinance_loan_payment.py`
- `microfinance_loan_management/models/microfinance_fond_credit.py`
- `microfinance_loan_management/models/microfinance_dashboard.py`
- `microfinance_loan_management/controllers/microfinance_dashboard_controller.py`
- `microfinance_savings_management/models/microfinance_caisse_mouvement.py`
- `microfinance_savings_management/models/microfinance_loan_extension.py`
- `microfinance_savings_management/models/microfinance_savings_account.py`
- `microfinance_savings_management/models/res_partner.py`
- `microfinance_loan_management/tests/common.py` + `tests/test_*.py`

---

## 1. `action_disburse` — corps actuel détaillé

**Définition : `microfinance_loan.py:1973-1995`.** Corps intégral :

```python
def action_disburse(self):
    for loan in self:
        if loan.state != 'approved':
            raise UserError(_('Le crédit doit être approuvé avant décaissement.'))
        if not loan.signed_contract:
            raise UserError(_(
                "Le contrat signé doit être téléversé avant l'activation du crédit."
            ))
        if loan.product_id.fee_charged_before_disbursement and not loan.fee_paid and loan.fee_amount_due > 0:
            raise UserError(_('Les frais de dossier doivent être encaissés avant le décaissement.'))
        loan._check_disbursement_limit()
        loan._check_cash_journal_balance()
        loan._check_fond_disponibilite()
        if not loan.installment_ids:
            loan.action_generate_schedule()
        move = self.env['account.move'].with_context(
            default_loan_id=False,
            default_loan_line_id=False,
        ).create(loan._prepare_disbursement_move())
        move.action_post()
        loan.write({'state': 'active', 'disbursement_date': fields.Date.context_today(loan)})
        loan.message_post(body=_('Crédit décaissé. Écriture : %s') % move.name)
    return True
```

### (a) Contrôles d'éligibilité (dans l'ordre)

| # | Contrôle | Code | Lève |
|---|---|---|---|
| 1 | État == `approved` | `:1975-1976` | `UserError('Le crédit doit être approuvé avant décaissement.')` |
| 2 | Contrat signé téléversé (`signed_contract`) | `:1977-1980` | `UserError("Le contrat signé doit être téléversé avant l'activation du crédit.")` |
| 3 | Frais de dossier payés si `product.fee_charged_before_disbursement` et `fee_amount_due > 0` | `:1981-1982` | `UserError('Les frais de dossier doivent être encaissés avant le décaissement.')` |
| 4 | `_check_disbursement_limit()` — plafond de décaissement espèces (`product.disbursement_limit_amount`), uniquement si `disbursement_journal_id.type == 'cash'` ; compare `net_disbursed_amount` | `:1983` → `:1930-1948` | `UserError('Décaissement refusé : le montant net remis au client … dépasse le plafond …')` |
| 5 | `_check_cash_journal_balance()` — solde du compte de caisse (`disbursement_journal_id.default_account_id.current_balance`), uniquement si `journal.type == 'cash'` **et** `product.check_cash_balance_at_disbursement` **et** pas `loan.bypass_cash_balance` ; projette `current_balance - net_disbursed_amount < 0` | `:1984` → `:1950-1971` | `UserError('Décaissement refusé : solde insuffisant sur le journal de caisse …')` |
| 6 | `_check_fond_disponibilite()` — fonds de crédit rotatif : (a) si aucun `fond_credit_id` mais `has_active_fond` → blocage ; (b) si `fond.verification_disponibilite == 'at_disbursement'` : dates de début/clôture du fonds, solde `> 0`, solde `>= loan_amount` | `:1985` → `:1880-1928` | plusieurs `UserError` (`'Un fonds de crédit rotatif actif existe …'`, `'… n'est pas encore actif …'`, `'… est clôturé …'`, `"Ce fonds ne dispose d'aucun solde disponible …"`, `'Solde insuffisant sur le fonds …'`) |

`'at_request'` et `'never'` ne déclenchent **aucun** contrôle de disponibilité (`:1904-1905` + docstring `:1880-1894`).

### (b) Génération d'échéancier de secours

`:1986-1987` :
```python
if not loan.installment_ids:
    loan.action_generate_schedule()
```
Filet uniquement : ne s'exécute que si l'échéancier est vide. En pratique il est déjà
généré à la saisie via `write()` / `_SCHEDULE_TRIGGER_FIELDS` (`:454-466`) dès que
`loan_amount` + `term` + `repayment_frequency_id` sont présents sur un crédit dans
`_EDITABLE_SCHEDULE_STATES` (`= ('draft','enquete','avis_ca','avis_cdag','approved')`, `:304`).
Voir §3 pour l'ancrage de date.

### (c) Écriture comptable

`_prepare_disbursement_move()` — `microfinance_loan.py:1644-1673`. Créée sur `account.move`
avec `default_loan_id=False, default_loan_line_id=False` dans le contexte, puis
`move.action_post()`.

- **Journal** : `product.disbursement_journal_id` (`:1647`). Garde : `UserError` si journal,
  `journal.default_account_id` ou compte principal manquants (`:1649-1650`).
- **Date** : `fields.Date.context_today(self)` (`:1666`).
- **`ref`** : `'Décaissement crédit %s' % self.name` ; `microfinance_loan_id = self.id`
  (`:1668-1669`).
- **Lignes** :
  - Débit `principal_account` (`product._get_account('principal', partner)`) du montant
    `loan_amount` — « Crédit client %s » (`:1671`).
  - Crédit `journal.default_account_id` du montant **`net_disbursed_amount`** — « Sortie
    caisse/banque %s » (`:1652`).
  - **Si `not product.fee_charged_before_disbursement` et `fee_amount_due > 0`** (frais nettés
    du décaissement) : ligne crédit supplémentaire sur `product.account_commission_credit_id`
    du montant `fee_amount_due` — « Frais de dossier %s » (`:1658-1664`). Garde `UserError` si
    `account_commission_credit_id` non configuré (`:1659-1660`).

**Comptes touchés** : compte principal en cours du produit (débit), compte de trésorerie du
journal de décaissement (crédit), et — cas frais nettés seulement — commission sur crédit
717003 (crédit).

### (d) Champs écrits sur le prêt en plus de `state`

`:1993` :
```python
loan.write({'state': 'active', 'disbursement_date': fields.Date.context_today(loan)})
```
**Seuls `state` et `disbursement_date` sont écrits.** Aucune autre écriture directe :

- `net_disbursed_amount` est un **compute stocké** (`:260-261`, `_compute_net_disbursed_amount`
  `:630-636`), recalculé sur `loan_amount` / `fee_amount_due` /
  `product_id.fee_charged_before_disbursement` — **jamais écrit par `action_disburse`** (voir §6).
- `installment_ids` peut être écrit indirectement via le filet `action_generate_schedule()`
  `:1986-1987`, mais seulement si l'échéancier était vide.
- `approval_date` reste celui posé par `action_approve()` (`:960`).

### (e) Effets de bord

- **`message_post`** unique : `'Crédit décaissé. Écriture : %s' % move.name` (`:1994`).
- **Écriture d'engagement des frais** : NON déclenchée ici. Elle est créée à
  `action_approve()` (`:954-963`, via `_is_fee_engagement_applicable()` → `_prepare_fee_receivable_move()`)
  ou en rattrapage dans `action_charge_fee()`. `action_disburse` ne la touche pas.
- **Aucune notification, aucun cron déclenché, aucun `activity`** dans `action_disburse`.
- **Aucun `_sync_arrears_state` / `action_calculate_scoring` / provisions** déclenchés ici :
  ce sont des crons séparés (`cron_update_overdue_and_penalties` `:2456-2471`,
  `action_post_provisions` `:2142`).
- **Consommation du fonds** : purement comptable — l'écriture postée sur le compte du fonds
  fait baisser `fond.solde_disponible` (compute `_compute_fond_totals`
  `microfinance_fond_credit.py:183-212`, dépend de `loan_ids.state` et des `installment_ids`).
  Aucun champ « réservation » écrit ; c'est l'écriture + le passage à `active` qui déplacent
  le crédit de `outstanding_states` vers `disbursed_states` (voir §2).

### `disbursement_date` — points d'écriture

`grep -n "disbursement_date" microfinance_loan.py` → écrit **uniquement** à `:1993`
(`action_disburse`). Champ `fields.Date(readonly=True)` (`:61`). Aucune autre méthode, aucun
onchange, aucun `create` ne le renseigne. Utilisé en lecture par :
- `_check_fond_credit_id_locked_after_disbursement` (`@api.constrains('fond_credit_id')`,
  `:1861-1878`) : `if loan.disbursement_date: raise ValidationError(...)` — verrouille
  `fond_credit_id` **une fois `disbursement_date` renseigné**.
- Dashboard : `monthly_disbursement` (`microfinance_dashboard_controller.py:50-54`) groupe par
  `disbursement_date`.
- `contrat_date` / divers `get_*` de reporting.

**Confirmation** : `disbursement_date` n'est renseigné qu'à l'intérieur de `action_disburse`
aujourd'hui.

---

## 2. Usages de `state == 'active'` ailleurs (impact du découplage)

Recherche exhaustive `grep -rn "'active'"` sur les modèles/contrôleurs crédit + épargne +
dashboard. Contexte du découplage : un crédit peut désormais être `active` avec
`disbursement_date` **vide** et **aucune écriture de décaissement postée** (état transitoire,
entre le clic « Activer » et le passage au Guichet Caisse).

Rappel structurel utile : dans `microfinance.fond.credit` deux tuples cohabitent
(`microfinance_fond_credit.py:188-189`) :
```python
disbursed_states = ('active', 'closed', 'defaulted', 'written_off')
outstanding_states = ('approved', 'active')
```

### 2.1 — CASSE / RÉSULTAT FAUX (à traiter)

| Emplacement | Code | Impact d'un `active` non décaissé | Verdict |
|---|---|---|---|
| **`microfinance_fond_credit.py:196-204`** `_compute_fond_totals` — `total_decaisse` / `total_rembourse` | `disbursed_loans = loans.filtered(lambda l: l.state in disbursed_states)` puis `sum(disbursed_loans.mapped('loan_amount'))` | Le crédit `active`-non-décaissé est compté dans `total_decaisse` alors qu'**aucune écriture de sortie n'a été postée sur le fonds**. `total_decaisse` surévalué ; `total_rembourse` inchangé (0 payé). `solde_disponible` **non impacté** : il passe par `outstanding_states = ('approved','active')` qui incluait déjà `approved` — un `approved` et un `active` non décaissé y pèsent pareil. | **Faux** sur `total_decaisse` (indicateur d'affichage), **OK** sur `solde_disponible` (le contrôle de fonds reste correct). |
| **`microfinance_fond_credit.py:282-288`** `get_multi_company_usage_chart` (décaissements par agence) | `('state', 'in', disbursed_states)` → `disbursed_by_company[...] += loan.loan_amount` | Idem : graphique dashboard « Décaissements » surévalué tant que le crédit `active` n'est pas passé en caisse. | **Faux** (affichage dashboard). |
| **`microfinance_fond_credit.py:329-337`** `get_single_company_chart` … en fait `get_fond_matrix` (`:329`) — matrice fonds × agences | `('state', 'in', disbursed_states)` → `amount_by_fund_company[...] += loan.loan_amount` | Idem : cellule « montant décaissé » surévaluée. | **Faux** (affichage dashboard). |
| **`microfinance_dashboard.py:19-27`** `_compute_dashboard` (modèle `microfinance.dashboard`) | `active = search([... ('state','=','active')])` ; `all_loans = search([... state in ('active','closed','defaulted')])` ; `disbursed_amount = sum(all_loans.mapped('loan_amount'))` ; `outstanding_amount = sum(active.mapped('balance_total'))` | `disbursed_amount` inclut le `loan_amount` d'un crédit non décaissé. `outstanding_amount` = `balance_total` : si l'échéancier existe déjà (généré à l'approbation, voir §3), il vaut la somme des `residual_amount` — le crédit non décaissé gonfle l'encours. `active_loan_count` inclut le crédit non décaissé. | **Faux** (KPI dashboard : montant décaissé + encours + nb actifs). |
| **`microfinance_dashboard_controller.py:27-40`** `dashboard_data` | `active_domain`, `disbursed_domain = state in ('active','closed','defaulted')`, `portfolio_domain = state in ('active','defaulted')` ; `disbursed_amount = sum(disbursed_loans.mapped('loan_amount'))` ; `outstanding_amount = sum(portfolio_loans.mapped('balance_total'))` ; `overdue_amount = sum(portfolio_loans.mapped('overdue_amount'))` ; `default_rate` basé sur `active_loan_count` | Mêmes surévaluations : montant décaissé, encours, impayés (si l'échéancier pré-généré a des `due_date` déjà passées, voir §3), et `default_rate` (dénominateur `active_loan_count` gonflé). | **Faux** (KPI + graphiques dashboard agent). |
| **`microfinance_loan.py:700-724`** `get_par_buckets` (PAR dashboard) | `portfolio_loans = search([... state in ('active','defaulted')])` ; `_get_max_overdue_days()` sur chaque | Un crédit `active` non décaissé, si son échéancier pré-généré est ancré sur `approval_date` et a des `due_date` passées, apparaît dans les tranches PAR avec un arriéré **fictif** (aucun décaissement n'a eu lieu). | **Faux** (PAR gonflé) — conditionné à l'existence d'un échéancier avec `due_date` passées. |
| **`microfinance_loan.py:726-740`** `_compute_provision` | `if loan.state not in ('active','defaulted'): provision_amount = 0` puis calcul sur `_get_max_overdue_days()` et `balance_total` | Un crédit `active` non décaissé provisionne (potentiellement au taux d'un retard fictif). | **Faux** (provisions comptables anticipées). |
| **`microfinance_loan_installment.py:95-127`** `get_pending_or_late` (onglet « Échéances du jour » du **guichet**) | `('loan_id.state', 'in', ('active','defaulted'))` + `('due_date','<=',today)` + `('state','!=','paid')` | La docstring `:103-106` dit explicitement que ce filtre sert à **exclure** les échéances d'un crédit non décaissé dont l'échéancier a été généré en aperçu — **mais il ne teste que `('active','defaulted')`**. Aujourd'hui protégé parce qu'un crédit non décaissé est `approved`. **Après découplage, un `active` non décaissé passe le filtre** : ses échéances pré-générées (ancrées `approval_date`, souvent déjà échues) remontent dans le guichet comme à encaisser / en retard. | **Casse la garde documentée** — régression directe du Lot 1.2. |
| **`microfinance_loan.py:2456-2471`** `cron_update_overdue_and_penalties` (cron quotidien) | `Installment.search(['|', ('state','in',('pending','partial','overdue')), '&' (arrears_onset_date set, cured empty)])` — **aucun filtre `loan_id.state`** ; puis `_sync_arrears_state()` + `action_apply_penalty()` + `action_calculate_scoring` sur `state='active'` | `_sync_arrears_state()` (`microfinance_loan_installment.py:65-80`) : marque `overdue`, pose `arrears_onset_date` sur les échéances échues d'un crédit `active` non décaissé. `action_apply_penalty()` (`:129-138`) : applique une pénalité si `due_date + grace_period_days < today` — **génère des pénalités et des arriérés avant que les fonds soient remis**. `action_calculate_scoring(state='active')` re-score le client sur cet arriéré fictif. NB : ce cron ne filtre déjà pas `loan_id.state` aujourd'hui, donc un `approved` avec échéancier + `due_date` passées est **déjà** exposé — le découplage élargit la fenêtre (crédits qui restent plus longtemps non décaissés) et déplace le problème sous l'état `active` que d'autres filtres considèrent comme « décaissé ». | **Faux / effet réel** (pénalités + arriérés + score dégradé sans décaissement). Pré-existant partiellement, aggravé par le découplage. |
| **`res_partner.py:142-153`** `get_client_accounts_summary` (panneau client du guichet) | `loans = filtered(lambda l: ... l.state in ('approved','active','defaulted'))` | Inclut **déjà** `approved` (volontaire : « approuvé en attente de décaissement, actif ou en défaut »). Un `active` non décaissé reste listé — comportement inchangé de fait, mais le libellé/état affiché (`loan.state`) dira « Actif » au lieu de « Approuvé ». `next_due_date` pointera sur une échéance pré-générée. | **À vérifier** : fonctionnellement OK (le dossier doit rester visible au guichet pour être décaissé), mais l'UI devra distinguer « actif non décaissé » de « actif décaissé » (cf. §8). |

### 2.2 — CORRECT / PAS D'IMPACT

| Emplacement | Code | Pourquoi ça reste correct |
|---|---|---|
| `microfinance_loan_payment.py:133-136` `_allocate_to_installments` | `if self.loan_id.state not in ('active','defaulted'): raise UserError` | Un remboursement sur un crédit `active` non décaissé serait accepté par cette garde, mais : (a) le guichet ne proposera au remboursement que les crédits réellement décaissés (à cadrer §8) ; (b) `balance_total` / surpaiement restent cohérents avec l'échéancier. Pas une casse, mais **à surveiller** : rien n'empêche techniquement un remboursement avant décaissement. |
| `microfinance_loan_payment.py:263-266` (annulation de remboursement) | `reopened = loan.state == 'closed'; if reopened: loan.state = 'active'` | Sans rapport avec le décaissement (ré-ouverture d'un crédit soldé). Aucun impact. |
| `microfinance_loan.py:1537-1540` `action_reschedule` | `if self.state != 'active': raise UserError` | Un rééchelonnement sur un `active` non décaissé serait théoriquement permis, mais c'est une action manuelle finance, hors flux guichet. **À vérifier** (faut-il exiger `disbursement_date`). |
| `microfinance_loan.py:2022-2025` `action_write_off`, `:2059` (writeoff wizard) | `if self.state not in ('active','defaulted')` | Radier un crédit non décaissé n'a pas de sens métier mais ne casse rien techniquement. **À vérifier** (bas risque). |
| `microfinance_loan.py:2118-2142` provisions / `action_post_provisions` | `filtered(lambda l: l.state in ('active','defaulted'))` | Même effet que `_compute_provision` §2.1 — déjà listé. |
| `microfinance_loan.py:2333` `('state','in',('active','closed','defaulted','written_off'))` (`get_carnet_remboursement` / reporting échéancier) | domaine reporting | Un crédit `active` non décaissé apparaîtrait dans un carnet de remboursement avec des échéances non financées. **À vérifier** (affichage report). |
| `microfinance_loan.py:2470` `action_calculate_scoring` sur `state='active'` | cron scoring | Déjà couvert par `cron_update_overdue_and_penalties` §2.1. |
| `microfinance_loan.py:885-905` `_check_eligibility` — `other_active_loans` / co-emprunteur | `search([... ('state','=','active')])` | Un `active` non décaissé compterait comme « crédit actif » pour bloquer un 2ᵉ crédit du même client plus tôt qu'aujourd'hui. Arguablement **correct** (engagement réel pris) ; changement de timing seulement. **À vérifier** avec Micka. |
| `microfinance_savings_management/models/microfinance_loan_extension.py:113-117` `_compute_guarantee_savings_balance` | `('state','=','active')` sur les **comptes épargne**, pas les crédits | Aucun rapport avec `microfinance.loan.state`. **OK**. |
| `microfinance_loan_extension.py:145-151` `_check_progressive_savings_eligibility` | `('state','in',('active','closed','defaulted','written_off'))` sur un **crédit précédent** | Un `active` non décaissé comme « crédit précédent » : léger anticipé, sans effet de blocage réel (le test ne bloque que si `savings_target_reached` est faux). **OK / négligeable**. |
| `microfinance_savings_management/models/microfinance_savings_account.py:256-261` clôture compte épargne obligatoire | `account.microfinance_loan_id.state == 'active'` | Empêche de clôturer une épargne obligatoire tant que le crédit lié est `active`. Un `active` non décaissé bloquerait la clôture un peu plus tôt — **comportement souhaitable** (l'épargne de garantie doit rester en place). **OK**. |
| `microfinance_savings_management/models/res_partner.py:148-152` (déjà en 2.1) | — | listé en 2.1. |
| `microfinance_savings_management/controllers/microfinance_savings_dashboard_controller.py:18` | `('state','=','active')` sur `microfinance.savings.account` | Compte épargne, pas crédit. **OK**. |
| `microfinance_savings_management/models/microfinance_loan_application_extension.py:20` | `lambda a: a.state == 'active'` sur `microfinance.loan.application` | État d'un dossier d'instruction, pas du crédit. **OK**. |
| `microfinance_loan_management/models/microfinance_dashboard_controller.py:103` `state_badge['active'] = ('success','En cours')` | libellé badge | Un `active` non décaissé s'afficherait « En cours » (vert) au lieu de « En attente ». **Cosmétique**, à cadrer §8. |

### 2.3 — Synthèse §2

Le découplage **fait basculer une population de crédits « non décaissés » de l'état `approved`
vers l'état `active`**, or `active` est traité comme « décaissé » par : les agrégats de fonds
bailleurs (`total_decaisse`, graphiques), les KPI dashboard (montant décaissé, encours,
impayés, taux de défaut), le PAR, les provisions, et — le plus grave — le cron quotidien
d'arriérés/pénalités et l'onglet « Échéances du jour » du guichet, qui produiraient des
**arriérés, pénalités et lignes à encaisser fictifs** sur des crédits dont l'argent n'est pas
sorti.

Le point d'ancrage commun d'un correctif serait un **prédicat « réellement décaissé »**
(`disbursement_date` renseigné, ou une écriture de décaissement postée) à substituer à
`state in ('active', …)` partout où le sens visé est « décaissé », mais la liste exacte des
sites à corriger et le choix du prédicat sont une **décision d'implémentation** (§8).

---

## 3. Génération de l'échéancier — dépendance à `disbursement_date`

**`_build_installment_commands()` — `microfinance_loan.py:1358-1384` :**
```python
def _build_installment_commands(self, rounding_mode='last_installment', raise_on_negative_reliquat=False):
    ...
    self.ensure_one()
    if not self.repayment_frequency_id or not self.loan_amount or not self.term:
        return []
    remaining = self.loan_amount
    start = self.approval_date or self.application_date or fields.Date.context_today(self)
    ...
```

**L'échéancier est ancré sur `approval_date` (repli `application_date`, repli `date du jour à
la génération`) — jamais sur `disbursement_date`.** Confirmé dans le code, pas seulement par
l'exemple IS/003362.

Points d'entrée qui persistent l'échéancier, tous via `_build_installment_commands` +
`start = approval_date or …` :
- `write()` / `_SCHEDULE_TRIGGER_FIELDS` (`:454-466`) — génération automatique à la saisie dès
  que `loan_amount` + `term` + `repayment_frequency_id` sont présents et
  `state in _EDITABLE_SCHEDULE_STATES`.
- `action_generate_schedule()` (`:1482-1497`) et son bouton `action_generate_schedule_button()`
  (`:1499-1535`) — garde `state in _EDITABLE_SCHEDULE_STATES` (`= …,'approved'`, `:304`).
- `_propagate_avis_to_loan()` (`:469-484`).
- Le filet `if not loan.installment_ids: loan.action_generate_schedule()` dans `action_disburse`
  (`:1986-1987`).

`action_generate_schedule` **interdit** la génération après activation :
`if loan.state not in loan._EDITABLE_SCHEDULE_STATES: raise UserError('Échéancier autorisé
avant activation seulement.')` (`:1484-1485`). `_EDITABLE_SCHEDULE_STATES` ne contient pas
`active`.

**Conséquence du découplage :**
- **Aucun impact sur la génération elle-même** : elle ne dépend pas de `disbursement_date`, la
  génération manuelle en état `approved` (cas IS/003362) continue de fonctionner à
  l'identique.
- **Effet de bord** : l'échéancier étant ancré sur `approval_date`, un crédit qui reste en
  `active` non décaissé plusieurs jours/semaines aura des `due_date` calculées à partir de
  l'approbation — donc potentiellement **déjà échues** au moment du décaissement réel. C'est
  la source des arriérés/pénalités/PAR fictifs du §2 (le cron et le guichet regardent
  `due_date <= today` + `state != 'paid'`, sans savoir si les fonds sont sortis).
- Après activation, `action_generate_schedule` n'est plus appelable (`_EDITABLE_SCHEDULE_STATES`)
  → **impossible de re-caler l'échéancier sur la date de décaissement réel** avec le mécanisme
  actuel. Si Micka veut que les échéances partent de la date de décaissement effective, c'est
  un chantier distinct (rien ne le fait aujourd'hui, même sans découplage).

---

## 4. Verrou concurrentiel

**`action_disburse` n'a AUCUN verrou `FOR UPDATE` ni équivalent.**
`grep -n "FOR UPDATE\|_for_update\|SELECT .* FROM microfinance_loan" microfinance_loan.py` →
la seule occurrence est dans `action_charge_fee` (`:1727`, cf.
`docs_dev/guichet_caisse/AUDIT_frais.md §4`), pas dans `action_disburse`.

Protection actuelle contre le double-décaissement : **uniquement la garde d'état**
`if loan.state != 'approved': raise UserError` (`:1975-1976`). Deux transactions concurrentes
qui lisent `state == 'approved'` avant que l'une commite peuvent **toutes deux** passer la
garde, créer et poster une écriture de décaissement, puis écrire `state='active'` — Odoo/PG en
`READ COMMITTED` ne sérialise pas ces lectures. Résultat possible : **deux `account.move` de
décaissement** pour le même crédit, double sortie de caisse, double consommation du fonds.

**Risque pré-existant**, indépendant de ce chantier. Aujourd'hui la fenêtre est étroite (un
seul chemin : le bouton fiche crédit, réservé `group_microfinance_finance`). Le chantier
Guichet Caisse **ajoute un second chemin concurrent** (`register_operation` type
`decaissement_credit`, `microfinance_caisse_mouvement.py:129-138`, exécuté en `sudo` par un
caissier) → la probabilité d'un double-clic / double-appel concurrent augmente. À traiter en
même temps que le découplage : reproduire le pattern `SELECT id FROM microfinance_loan WHERE
id = %s FOR UPDATE` + `invalidate_recordset(['state','disbursement_date'])` + relecture de la
garde, comme `action_charge_fee`. **Choix du lieu (dans `action_disburse` ? dans
`register_operation` ?) = décision d'implémentation, §8.**

**Testé** : aucun test ne couvre la concurrence sur `action_disburse` (recherche
`concurrent` / `FOR UPDATE` dans `tests/` → seulement `test_fee.py`).

---

## 5. Autres appelants de `action_disburse`

`grep -rn action_disburse` hors tests :

| Appelant | Fichier | Nature |
|---|---|---|
| Bouton fiche crédit « Activer / Décaisser » | `microfinance_loan_management/views/microfinance_loan_views.xml:73` — `<button name="action_disburse" … class="btn-primary" groups="microfinance_loan_management.group_microfinance_finance" invisible="state != 'approved'"/>` | UI, `type="object"` |
| Guichet Caisse, type `decaissement_credit` | `microfinance_savings_management/models/microfinance_caisse_mouvement.py:133` — `self._run_posting_sudo(loan, session, 'action_disburse')` | via `register_operation`, en `sudo` |

**Aucun cron, aucun wizard, aucune route HTTP/API** n'appelle `action_disburse`
(`microfinance_fond_credit.py:61` n'est qu'un commentaire ; les 30+ occurrences restantes sont
dans `tests/`).

Les deux appelants réels **présument tous deux `state == 'approved'`** :
- le bouton via `invisible="state != 'approved'"` ;
- le guichet via `get_pending_disbursements` (`microfinance_loan.py:1997-2020`) qui fait
  `search([('state','=','approved'), ('company_id','=',company_id)])`, consommé par
  `microfinance_caisse_pos.js:121`.

Si `action_disburse` est scindé (le bouton ne fait plus que `state → active`), **les deux
appelants et `get_pending_disbursements` doivent être revus** : le bouton devient
« Activer » ; le guichet doit cibler les crédits `active` **non encore décaissés** (nouveau
prédicat, cf. §2.3 et §8) au lieu de `state == 'approved'` ; la méthode postante
(nouvelle ou renommée) est appelée depuis `register_operation` uniquement.

---

## 6. `net_disbursed_amount` — disponibilité avant décaissement

**Champ : `microfinance_loan.py:260-261`** :
```python
net_disbursed_amount = fields.Monetary(
    compute='_compute_net_disbursed_amount', store=True, string='Montant net remis au client',
```
**Compute stocké** — `_compute_net_disbursed_amount` (`:630-636`),
`@api.depends('loan_amount', 'fee_amount_due', 'product_id.fee_charged_before_disbursement')` :
```python
def _compute_net_disbursed_amount(self):
    for loan in self:
        if loan.product_id and not loan.product_id.fee_charged_before_disbursement:
            loan.net_disbursed_amount = loan.loan_amount - loan.fee_amount_due
        else:
            loan.net_disbursed_amount = loan.loan_amount
```

- **Disponible dès la création du crédit** (dès que `loan_amount` et `product_id` sont
  renseignés) — **pas** calculé après coup, **pas** dépendant de `disbursement_date` ni de
  `state`.
- `fee_amount_due` est figé dès l'approbation (`_FEE_FROZEN_STATES`, `microfinance_loan.py:386`
  + `_compute_fee_amount` `:585-604`), donc `net_disbursed_amount` est **stable** entre
  approbation et décaissement.
- Déjà consommé avant tout décaissement effectif par : `_check_disbursement_limit` (`:1944`),
  `_check_cash_journal_balance` (`:1966`), `_prepare_disbursement_move` (`:1652`),
  `get_pending_disbursements` (`:2017`, champ `amount` de la liste guichet),
  `register_operation` (`microfinance_caisse_mouvement.py:137`).

**Conclusion** : `net_disbursed_amount` est pleinement disponible **avant** le décaissement
effectif ; l'affichage dans l'onglet « Décaissements en attente » du guichet (sous-lot 1.2)
sur des crédits `active` non décaissés ne pose aucun problème de disponibilité de donnée.

---

## 7. Tests existants (base de non-régression)

### 7.1 Helper commun

`microfinance_loan_management/tests/common.py:119-133` — `_activate_loan()` termine par
`loan.action_disburse()` et **retourne un crédit `active` avec écriture de décaissement postée
et `disbursement_date` renseigné**. Utilisé par la quasi-totalité des suites crédit. Si
`action_disburse` est scindé, ce helper produira soit un `active` non décaissé (si on garde
`action_disburse` = `state → active`), soit devra appeler en plus la nouvelle méthode
postante — **point de non-régression central**.
`common.py:103-117` `_create_loan()` pose un `signed_contract` factice (prérequis garde #2).

### 7.2 Tests appelant `action_disburse`

| Fichier / test | Ce qui est couvert / asserté |
|---|---|
| `test_disbursement_limit.py` : `test_disbursement_limit_blocked` (`:23`), `_allowed_at_limit` (`:29`), `_zero_means_no_limit` (`:35`), `_not_applied_when_journal_is_bank` (`:41`) | Garde `_check_disbursement_limit` ; asserts `assertRaises(UserError)` / `loan.state == 'active'` |
| `test_cash_balance_check.py` : `_disabled_by_default_allows` (`:39`), `_enabled_blocks_when_insufficient` (`:47`), `_enabled_allows_when_sufficient` (`:53`), `_enabled_bypass_allows` (`:60`), `_enabled_not_applied_when_bank` (`:67`) | Garde `_check_cash_journal_balance` ; asserts `UserError` / `state == 'active'` |
| `test_fond_bailleur.py` : `test_at_request_has_no_observable_effect_at_disbursement` (`:115`), `_never_allows_disbursement_even_when_fond_empty` (`:126`), `_disbursement_blocked_after_date_cloture` (`:132`), `_empty_fond_blocks_disbursement_with_dedicated_message` (`:142`), `_insufficient_balance_blocks_disbursement_with_amounts` (`:150`), `_sufficient_balance_allows_disbursement_and_consumes_it` (`:158`), `_disbursement_without_fond_blocked_when_active_fond_exists` (`:196`), `_still_allowed_when_no_active_fond` (`:203`), `_clearing_fond_after_disbursement_blocked` (`:222`), `_reassigning_fond_after_disbursement_blocked` (`:227`), `_clearing_fond_after_disbursement_does_not_restore_solde` (`:233`), `_fond_still_editable_before_disbursement` (`:242`), multi-agence (`:329`) | Garde `_check_fond_disponibilite` ; consommation `solde_disponible` ; verrou `fond_credit_id` post-`disbursement_date` (`_check_fond_credit_id_locked_after_disbursement`) |
| `test_fond_bailleur_dashboard.py` : `:92`, `:196` | Agrégats fonds sur dashboard après décaissement |
| `test_fee.py` : `test_disburse_blocked_when_fee_unpaid_and_required` (`:67`), `_allowed_when_fee_not_required` (`:73`), `test_charge_fee_generates_move_and_unblocks_disbursement` (`:80`), `_fee_engagement_skipped_when_fee_netted` (`:113`), `test_disburse_nets_fee_in_single_move` (`:199`, asserte `loan.move_ids` = écriture nette), `test_net_disbursed_amount_equals_loan_amount_when_fee_charged_separately` (`:194`) | Garde #3 (frais avant décaissement) ; contenu de `_prepare_disbursement_move` (nettage des frais) ; `net_disbursed_amount` |
| `test_repayment_accounting.py` : `:124` (`loan_b.action_disburse()`) | Écriture de décaissement comme préalable aux écritures de remboursement |
| `test_reschedule.py` : `setUp` `:19` (`loan.action_disburse()`) puis `test_reschedule_*` | Rééchelonnement sur crédit `active` (échéancier issu du flux normal) |
| `test_disbursement_limit.py` / `test_cash_balance_check.py` `setUpClass` | Créent produit + journaux `cash` |
| `test_guichet_backend_lists.py:14` | Mentionne que sans `fond_credit_id`, `action_disburse` lève |
| `microfinance_savings_management/tests/test_caisse_pos.py` : `test_direct_disbursement_unaffected` (`:207`, `loan.action_disburse()` direct), `:264` (garde fonds), section frais `:432`, `_open_session` `:363` | Chemin guichet `decaissement_credit` via `register_operation` + `_run_posting_sudo` ; asserts sur `microfinance.caisse.mouvement` (montant = `net_disbursed_amount`), sur l'absence de droits `account.move` du caissier, sur la garde session ouverte / cohérence agence |

### 7.3 Ce qui n'est PAS couvert

- Aucun test de **concurrence** sur `action_disburse` (§4).
- Aucun test isolant « le bouton ne fait que passer `active` » vs « l'écriture est postée » —
  aujourd'hui c'est monolithique.
- Aucun test vérifiant qu'un crédit `active` **sans** `disbursement_date` est **exclu** des
  agrégats fonds / dashboard / PAR / cron pénalités / onglet « Échéances du jour » (le cas
  n'existe pas encore).
- `get_pending_disbursements` est testé (via `test_guichet_backend_lists.py` /
  `test_caisse_pos.py`) sur `state == 'approved'` uniquement.

---

## 8. Questions bloquantes pour l'implémentation

1. **Rôle exact du bouton après le découplage.** Le bouton `action_disburse`
   (`microfinance_loan_views.xml:73`, `invisible="state != 'approved'"`) : devient-il
   `action_activate` qui exécute **les 6 contrôles actuels** (§1a) puis `state → active` sans
   aucune écriture ? Est-il renommé, ou une nouvelle méthode est-elle créée à côté ? Le
   libellé « Activer / Décaisser » devient quoi ?

2. **Prédicat « réellement décaissé ».** Sur quoi se base-t-on pour distinguer un `active`
   décaissé d'un `active` transitoire : `disbursement_date` renseigné (déjà écrit nulle part
   ailleurs, §1e/§2), présence d'une écriture `account.move` avec `microfinance_loan_id` et
   `ref` de décaissement, un nouveau booléen `is_disbursed`, ou un nouvel état
   (`active` scindé en `active_pending_cash` / `active`) ? Ce choix conditionne **tous** les
   correctifs du §2.

3. **Liste des sites du §2.1 à corriger et méthode.** Faut-il un helper central
   (`_is_disbursed()` / champ calculé stocké) réutilisé dans : `_compute_fond_totals`,
   `get_multi_company_usage_chart`, `get_fond_matrix`, `microfinance_dashboard._compute_dashboard`,
   `dashboard_data`, `get_par_buckets`, `_compute_provision` / `action_post_provisions`,
   `get_pending_or_late`, `cron_update_overdue_and_penalties` ? Ou corrige-t-on au cas par cas ?
   Périmètre exact à arbitrer avec Micka (certains indicateurs dashboard sont peut-être
   tolérables transitoirement).

4. **`get_pending_or_late` (onglet « Échéances du jour » du guichet).** Sa docstring
   (`microfinance_loan_installment.py:103-106`) dit que le filtre `loan_id.state in
   ('active','defaulted')` **doit** exclure les crédits non décaissés — il ne le fera plus.
   On ajoute `('loan_id.disbursement_date', '!=', False)` (ou équivalent selon Q2) ?

5. **`cron_update_overdue_and_penalties` (arriérés / pénalités quotidiens).** Il ne filtre
   **déjà pas** `loan_id.state` aujourd'hui — un `approved` avec échéancier + `due_date`
   passées est **déjà** exposé aux pénalités/arriérés (bug pré-existant ou comportement
   voulu ?). Le découplage l'aggrave. Faut-il ajouter un filtre « crédit décaissé » à ce cron
   dans le même lot, ou est-ce un chantier séparé ?

6. **Ancrage de l'échéancier.** Aujourd'hui `approval_date` (§3), et `action_generate_schedule`
   est interdit après `active`. Le découplage crée une fenêtre où l'échéancier a des `due_date`
   déjà échues avant la remise des fonds. Est-ce acceptable (le décaissement suit vite
   l'activation), ou faut-il re-caler l'échéancier sur la date de décaissement effective au
   passage en caisse (chantier distinct, rien ne le fait actuellement) ?

7. **Verrou concurrentiel (§4).** `action_disburse` n'a pas de `FOR UPDATE`. On l'ajoute dans
   le même lot (recommandé, vu le 2ᵉ chemin guichet) ? Où : dans la méthode postante
   elle-même, ou dans `register_operation` (module épargne, sur la table `microfinance_loan`,
   comme le fait déjà `action_charge_fee`) ? Compatibilité `env.cr.execute("… FOR UPDATE")`
   sous `_run_posting_sudo` (sudo) à confirmer — même question ouverte que pour les frais
   (`AUDIT_frais.md §5`).

8. **`get_pending_disbursements` (`microfinance_loan.py:1997-2020`).** Passe de
   `('state','=','approved')` à quoi exactement : `('state','=','active'), (<prédicat non
   décaissé>)` ? L'ordre (`approval_date asc`) devient-il `disbursement… asc` ou reste-t-il
   sur `approval_date` ? Champ `amount` = `net_disbursed_amount` (inchangé, §6).

9. **Contrôles au clic « Activer » vs au passage en caisse.** Décision actée : « tous les
   contrôles actuels conservés au clic » — y compris `_check_cash_journal_balance` et
   `_check_fond_disponibilite`, alors que l'argent ne sort pas encore. Ces mêmes contrôles
   sont-ils **re-joués** au décaissement effectif en caisse (le solde de caisse / du fonds
   ayant pu changer entre-temps), ou fait-on confiance au contrôle d'activation ? Si re-joués,
   `_check_fond_disponibilite` (`microfinance_loan.py:1915-1919`) fait un calcul
   `solde_disponible + _get_principal_outstanding()` qui suppose que le crédit est déjà compté
   dans l'encours du fonds — valable pour `approved` **et** `active` (les deux sont dans
   `outstanding_states`), donc a priori inchangé, mais à confirmer.

10. **Remboursement / rééchelonnement / radiation sur un `active` non décaissé.**
    `_allocate_to_installments` (`:135`), `action_reschedule` (`:1539`), `action_write_off`
    (`:2024`) acceptent `state == 'active'` sans vérifier `disbursement_date`. Faut-il ajouter
    la garde « décaissé » à ces trois méthodes, ou considère-t-on que l'UI (guichet + fiche)
    ne les proposera jamais sur un crédit non décaissé ?

11. **Helper de test `_activate_loan` (`common.py:119-133`) et suites existantes.** Il faut
    décider si `_activate_loan` continue de produire un crédit **décaissé** (en appelant la
    nouvelle méthode postante après `action_activate`) pour ne pas casser les ~10 fichiers de
    tests qui en dépendent, ou si un helper distinct `_disburse_loan` est ajouté. Idem pour
    `test_caisse_pos.py` (chemin `decaissement_credit`).

12. **Affichage / badge.** `state_badge['active']` = « En cours » (vert) dans le dashboard
    (`microfinance_dashboard_controller.py:103`), le panneau client du guichet
    (`res_partner.py:159-164`) renvoie `loan.state`. Un `active` non décaissé doit-il être
    visuellement distingué (« Activé, en attente de décaissement ») sur la fiche, le
    dashboard « Derniers prêts » et le guichet ?

---

*Audit réalisé le 2026-09-07. Lecture seule — aucune modification de code, de vue, de données
ou de sécurité, aucun commit.*
