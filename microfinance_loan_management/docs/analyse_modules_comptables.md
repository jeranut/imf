# Analyse préalable — `base_accounting_kit` et `custom_paid_totals`

Analyse effectuée avant l'implémentation de la priorité 2 de
`microfinance_loan_management` (provisionnement selon ancienneté, reçu de
décaissement imprimable, PAR par tranches dans le dashboard, annulation
comptable propre des remboursements postés).

Note d'emplacement : ce fichier est rangé sous
`microfinance_loan_management/docs/` plutôt qu'à la racine du dépôt
(`imf_git/docs/`) car la racine appartient à `root` et n'est pas
inscriptible par l'utilisateur d'exécution ; `microfinance_loan_management/`
est le seul dossier du dépôt sur lequel j'ai les droits d'écriture.

## 1. `base_accounting_kit`

### Rôle
Module tiers Cybrosys ("Odoo 17 Full Accounting Kit for Community") qui
ajoute à Odoo Community des fonctionnalités habituellement réservées à
Odoo Enterprise : rapports financiers (bilan, résultat, grand livre,
balance âgée partenaires, journal audit, cash flow, day/bank/cash book),
gestion des immobilisations et amortissements, limite de crédit client sur
les ventes, chèques/PDC (post-dated cheques), relances (follow-up),
verrouillage des périodes comptables (assistant), budgets.

### Modèles Odoo standard étendus
`account.move`, `account.move.line`, `account.account`, `account.journal`,
`account.payment`, `account.payment.register`, `account.payment.method`,
`account.report`, `res.partner`, `res.company`, `sale.order`.

### Effets sur `account.move` / `account.move.line` pertinents pour nous

Nos deux générateurs d'écritures existants
(`microfinance.loan._prepare_disbursement_move` et
`microfinance.loan.payment._prepare_payment_move`) créent des
`account.move` simples (2 lignes, `move_type` par défaut `'entry'`,
sans `asset_category_id`, sans lien `account.payment`). Sur cette base :

- `models/account_move.py` surcharge `action_post()` pour déclencher
  `asset_create()` sur `invoice_line_ids` ayant une `asset_category_id`.
  Comme nos comptes (prêts, intérêts, pénalités, pertes) n'ont jamais de
  catégorie d'immobilisation, cet appel est un no-op pour nos écritures :
  **aucun impact fonctionnel**, juste une itération supplémentaire
  négligeable à chaque `action_post()`.
- `models/credit_limit.py` surcharge aussi `action_post()` mais ne
  bloque que si `move_type in ('out_invoice', 'out_refund', 'out_receipt')`
  — nos écritures restent en `'entry'`, donc **jamais déclenché**.
- Aucune surcharge de `write()` ni de la validation de verrouillage de
  période (voir section verrouillage ci-dessous) : le comportement
  standard d'Odoo s'applique tel quel à nos écritures.
- Les champs ajoutés sur `account.move.line` (`asset_category_id`,
  `asset_start_date`, `asset_end_date`, `asset_mrr`) restent `False`/`0`
  pour nos lignes, sans effet.

**Conclusion : aucun conflit avec `_prepare_disbursement_move` /
`_prepare_payment_move`.**

### Verrouillage de période comptable (pertinent pour le point 4)

`wizard/account_lock_date.py` (`account.lock.date`, TransientModel) est un
simple assistant qui écrit les champs standard **déjà natifs** d'Odoo
`res.company.period_lock_date` et `res.company.fiscalyear_lock_date` — il
ne redéfinit pas la logique de contrôle elle-même. `models/res_company.py`
n'ajoute qu'une validation *avant* de poser une nouvelle
`fiscalyear_lock_date` (refuse de verrouiller une période qui contient
encore des écritures en brouillon ou des lignes de relevé non
lettrées) ; il n'intercepte pas la vérification qu'Odoo fait lors de la
création/modification d'une écriture dans une période déjà verrouillée.

**Conclusion : le mécanisme de verrouillage reste 100% standard Odoo.**
`account.move` core lève déjà une `UserError` (`_check_fiscalyear_lock_date` /
`_check_lock_dates`) si on tente de créer/poster/modifier une écriture
datée dans une période verrouillée par `period_lock_date` ou
`fiscalyear_lock_date` — que ce verrouillage ait été positionné via ce
module ou directement dans Comptabilité > Configuration. Le point 4
(annulation propre des remboursements postés) doit donc simplement laisser
remonter cette erreur standard (avec un message contextualisé si
souhaité), sans logique de contournement spécifique à
`base_accounting_kit`.

### Provisionnement, ancienneté de créances, PAR / balance âgée

`report/report_aged_partner.py` fournit un rapport de balance âgée
générique (tranches 1-30/31-60/61-90/91-120/+120 jours, paramétrable),
mais **au niveau du grand livre** : il interroge `account.move.line`
filtrées par `account_type in ('asset_receivable', 'liability_payable')`,
`date_maturity`, et l'état de lettrage (`reconciled`). Nos écritures de
décaissement/remboursement sont des écritures agrégées à 2 lignes, sans
`date_maturity` par échéance et sans lettrage — même si `loan_account_id`
était configuré en `asset_receivable`, ce rapport ne pourrait pas
reconstituer l'ancienneté par échéance de crédit telle que suivie par
`microfinance.loan.installment` (due_date/state par échéance). Il s'agit
d'un outil complémentaire mais **non réutilisable tel quel** pour un PAR
par tranches au niveau de l'échéancier microfinance.

`models/account_followup.py` ne fait que paramétrer des délais de
relance (texte de courrier), sans écriture comptable ni logique
d'ancienneté financière. `models/account_asset.py` gère l'amortissement
des immobilisations, sans rapport avec le provisionnement de créances
douteuses.

**Conclusion : aucun mécanisme de provisionnement de créances ni de PAR
par échéance n'existe déjà.** Les points 1 (provisionnement selon
ancienneté des arriérés) et 3 (PAR par tranches dans le dashboard) seront
construits directement sur `microfinance.loan.installment`
(due_date/state/residual_amount), sans dupliquer ni s'appuyer sur le
rapport de balance âgée de `base_accounting_kit`.

## 2. `custom_paid_totals` (nommé "TRESORERIE")

### Rôle
Malgré son nom technique, ce module ne calcule pas des "totaux payés" sur
des factures ou des partenaires : c'est un module de **clôture de caisse
journalière** (`account.daily.balance` et son pendant Mobile Money
`account.daily.balance.mobile`), avec réconciliation automatique des
`account.payment` liés à des factures/notes de frais vers des comptes
d'attente, garde-fou de solde caisse négatif, suivi d'acomptes
(`custom.paid.advance.payment`) et un rapport d'analyse trésorerie
(`treasury.analysis.report`, vue SQL).

### Modèles Odoo standard étendus
`account.payment`, `account.payment.register`, `hr.expense.sheet`. Le
reste (`account.daily.balance*`, `custom.paid.advance.payment`,
`treasury.analysis.report`) sont des modèles propres au module.

### Risque de double calcul avec `microfinance.loan._compute_totals()` / `paid_principal`/`paid_interest`/`paid_penalty`

**Aucun.** Le mécanisme de clôture de caisse de `custom_paid_totals`
n'ingère que des enregistrements du modèle standard `account.payment`
(via `_get_cash_payments()` : `self.env['account.payment'].search([...])`)
réconciliés avec des factures/notes de frais, ou les paiements créés via
l'assistant `account.payment.register`. Or :

- `microfinance.loan.payment` (remboursement de crédit) et le
  décaissement (`action_disburse`) créent directement des `account.move`
  (`env['account.move'].create(...)` + `action_post()`), **sans jamais
  passer par le modèle `account.payment` ni par
  `account.payment.register`**.
- Il n'existe donc structurellement aucun enregistrement `account.payment`
  correspondant à un remboursement ou un décaissement microfinance que
  `custom_paid_totals` pourrait intercepter, dupliquer ou recalculer.

Les totaux de `microfinance.loan._compute_totals()` (calculés depuis
`installment_ids.paid_principal/paid_interest/paid_penalty`) et le
"Rapport journalier Encaissements/Décaissements" de `custom_paid_totals`
opèrent donc sur des données et des déclencheurs complètement disjoints :
**aucun risque d'incohérence ou de double calcul.**

### Risque non bloquant à signaler (angle mort trésorerie)

Si un produit de crédit microfinance est configuré avec un
`disbursement_journal_id` ou `payment_journal_id` de type `cash` qui est
**le même journal caisse physique** que celui suivi par
`account.daily.balance` pour la clôture journalière de la société, alors
les mouvements de caisse réels du décaissement/remboursement microfinance
**n'apparaîtront jamais** dans le rapport journalier de trésorerie de
`custom_paid_totals` (puisque ce dernier ne lit que des `account.payment`,
jamais les `account.move` bruts créés par le module crédit). Le solde de
caisse physique bougerait sans que la clôture caisse du jour ne le reflète
— un angle mort comptable, pas un bug de code.

*Recommandation (non implémentée dans cette itération car hors périmètre
des 4 points demandés) : configurer des journaux de caisse dédiés pour
les opérations de crédit microfinance, distincts des journaux suivis par
`custom_paid_totals`, ou prévoir une intégration future si les deux
modules doivent partager une même caisse physique.*

### Provisionnement / PAR

Aucun mécanisme de provisionnement de créances douteuses, ni de balance
âgée, dans `custom_paid_totals` — le module ne traite que la trésorerie
(caisse/mobile money), pas les comptes clients. Rien à réutiliser ici non
plus pour les points 1 et 3.

### Verrouillage de période comptable

Aucune référence à `lock_date` dans ce module — comportement standard
Odoo inchangé, cohérent avec la conclusion de la section
`base_accounting_kit`.

## Conclusion générale

**Aucun conflit bloquant identifié** entre `base_accounting_kit`,
`custom_paid_totals` et les 4 points de priorité 2 :

| Point | Impact des modules tiers |
|---|---|
| 1. Provisionnement selon ancienneté | Aucun mécanisme existant à dupliquer ; à construire sur `microfinance.loan.installment`. |
| 2. Reçu de décaissement imprimable | Aucune interaction ; rapport QWeb propre à `microfinance.loan`. |
| 3. PAR par tranches dans le dashboard | Le rapport de balance âgée de `base_accounting_kit` est ledger/lettrage, non réutilisable au niveau échéance ; à construire indépendamment. |
| 4. Annulation comptable propre des remboursements postés | Le verrouillage de période reste 100% standard Odoo dans les deux modules ; s'appuyer sur la `UserError` native levée par `account.move` pour toute période verrouillée. |

Point de vigilance non bloquant (documenté ci-dessus, hors périmètre de
cette itération) : partage éventuel d'un même journal caisse entre
microfinance et `custom_paid_totals`, créant un angle mort dans le rapport
de trésorerie journalier.

## 3. Option d'intégration `account.payment` — DÉCISION EN ATTENTE, NON IMPLÉMENTÉE

Statut : analysée ci-dessous à la demande explicite du produit, **aucun
code n'a été modifié pour ce point**. En attente de confirmation avant de
choisir une approche.

### Ce que ça impliquerait concrètement

Faire passer `_prepare_disbursement_move` (`microfinance_loan.py`) et
`_prepare_payment_move` (`microfinance_loan_payment.py`) par
`account.payment` (ou l'assistant `account.payment.register`) au lieu de
créer un `account.move` brut à 2 lignes signifierait :

- **Fichiers touchés directement** : `models/microfinance_loan.py`
  (`_prepare_disbursement_move`, `action_disburse`),
  `models/microfinance_loan_payment.py` (`_prepare_payment_move`,
  `action_post`, potentiellement `_allocate_to_installments`),
  `wizard/microfinance_loan_writeoff_wizard.py` /
  `_prepare_writeoff_move` (même mécanisme de création de move brut).
- **Changement de mécanique comptable** : `account.payment` ne débite/crédite
  pas directement le compte qu'on lui indique — il s'appuie sur un compte
  "outstanding" (attente encaissement/décaissement) configuré sur le
  journal, pensé pour être ensuite **lettré** avec une facture/note de
  frais. Notre modèle actuel débite/crédite **directement**
  `loan_account_id` (le compte prêts clients) au décaissement et au
  remboursement — c'est ce lien direct qui permet à `balance_total` et au
  calcul de risque de rester cohérents avec le grand livre sans lettrage.
  `account.payment` n'a pas de notion native de "crédit à échéancier" à
  lettrer ; il faudrait soit détourner le mécanisme facture/lettrage
  (créer une pseudo-facture par crédit ou par échéance), soit
  personnaliser lourdement `_prepare_payment_moves()` — dans les deux cas
  on complexifie significativement pour un bénéfice (visibilité dans un
  rapport de caisse tiers) qui reste secondaire par rapport au rôle du
  module.
- **Risque de régression sur la priorité 1** :
  - `action_disburse()` et `action_write_off()` référencent `move.name`
    dans les messages du chatter ; le nommage/séquence changerait (celui
    du paiement, pas celui d'une écriture manuelle).
  - Le rééchelonnement (`_reschedule_installments`) et le calcul des
    totaux (`_compute_totals`) ne créent pas d'écriture eux-mêmes mais
    dépendent de l'hypothèse que `loan_account_id` est mouvementé
    directement par décaissement/remboursement — casser cette hypothèse
    imposerait de revoir la cohérence comptable de tout le module, pas
    seulement le point de génération de l'écriture.
  - Le write-off (déjà livré en priorité 1) génère aussi une écriture
    brute (`_prepare_writeoff_move`) suivant exactement le même schéma ;
    il faudrait le retraiter en cohérence si on change le mécanisme pour
    le décaissement/remboursement.
- **Tests existants impactés** :
  - `tests/common.py::_activate_loan` (utilisé par `test_reschedule.py`,
    `test_eligibility.py`, `test_write_off.py`) déclenche
    `action_disburse()` — tout changement de mécanique y transiterait,
    même si ces tests n'inspectent pas le détail du move.
  - `tests/test_write_off.py` (`test_write_off_active_loan_generates_move_and_changes_state`)
    vérifie explicitement `debit_lines.account_id == writeoff_account` et
    `credit_lines.account_id == self.loan_account` sur les lignes du
    move — direct et fragile à toute évolution du mode de génération de
    l'écriture de décaissement dont dépend le solde restant testé.
  - Un futur test sur le reçu de décaissement imprimable (point 2 de
    cette itération) devrait alors lire les données depuis un
    `account.payment` plutôt qu'un `account.move` brut, ajoutant du
    couplage entre le rapport QWeb et un mécanisme de paiement plus
    générique/complexe.

### Alternative moins invasive (recommandée si une intégration est souhaitée)

Ne pas toucher au mécanisme de génération des écritures de
`microfinance_loan_management`. Deux pistes, de la plus simple à la plus
outillée :

1. **Procédurale, sans aucun code** : `custom_paid_totals` propose déjà un
   canal de saisie manuelle pour les mouvements de caisse que son
   ingestion automatique ne capte pas (`UpdateTotalsWizard` /
   `action_update_totals_wizard()`, ligne "RECETTE" libre). Si un même
   journal caisse physique est partagé, l'agent de caisse peut y
   consigner manuellement les décaissements/remboursements microfinance
   du jour. Zéro risque de régression, zéro changement de code, mais
   dépend d'une discipline opérationnelle.
2. **Code, mais côté `custom_paid_totals` uniquement** : nos écritures
   portent déjà `microfinance_loan_id` / `microfinance_payment_id`
   (champs ajoutés sur `account.move` dès la priorité 1). Une évolution
   ciblée et additive de `custom_paid_totals`
   (`AccountDailyBalanceLine._upsert_invoice_payment` /
   `AccountDailyBalance._get_cash_payments()`) pourrait reconnaître ces
   deux champs et intégrer directement les `account.move` du journal
   caisse concerné, sans passer par `account.payment` ni par la
   réconciliation facture. Cela n'impose aucun changement à
   `microfinance_loan_management` ni à ses tests, mais c'est un
   changement dans un **autre module** et sort donc du périmètre de
   cette tâche — à traiter comme un chantier séparé, avec son propre
   arbitrage.

### Recommandation

Piste 2 (évolution ciblée dans `custom_paid_totals`, hors périmètre
actuel) si une intégration comptable réelle est souhaitée à terme ; piste
1 (procédure manuelle) en attendant, sans aucun changement de code. Ne pas
faire migrer `microfinance_loan_management` vers `account.payment` : le
coût de refonte et le risque de régression sur la priorité 1 dépassent le
bénéfice (visibilité dans un rapport de trésorerie tiers) au vu de
l'architecture actuelle du module.

**Aucune implémentation n'a été faite pour ce point — en attente de
confirmation avant de choisir une approche.**
