# Lot 1 étendu — Onglet « Frais » au Guichet Caisse — Statut

Fait suite à `docs_dev/guichet_caisse/AUDIT_frais.md`. 3 sous-lots, arrêt entre chaque, aucun
commit. Décisions actées reprises du prompt (non re-discutées).

---

## Sous-lot A — Backend : marquage et méthode d'envoi — **FAIT, en attente de validation**

### Modifié — `microfinance_loan_management/models/microfinance_loan.py`

- Nouveau champ **`fee_sent_to_cashier`** (`Boolean`, `default=False`, `copy=False`,
  `readonly=True`) — marqueur historique, jamais remis à `False`.
- Nouveau champ **`fee_charged_before_disbursement`** (`related='product_id.fee_charged_
  before_disbursement'`, `readonly=True`, non stocké) — nécessaire pour le modifier `invisible=`
  du bouton (les expressions de vue ne suivent pas `product_id.xxx`).
- Nouvelle méthode **`action_send_fee_to_cashier()`** : ne comptabilise rien, pose
  `fee_sent_to_cashier = True` + `message_post`. Gardes : `state == 'approved'`, `not
  fee_paid`, `fee_amount_due > 0`, `product.fee_charged_before_disbursement` (sinon
  `UserError` « frais nettés au décaissement »), `not fee_sent_to_cashier` (double-envoi).
- **`action_charge_fee()`** : ajout d'une garde en tête de boucle,
  `if not loan.fee_sent_to_cashier: raise UserError("Les frais doivent d'abord être envoyés
  en caisse avant encaissement.")`. **Le reste de la méthode est inchangé** (verrou
  `FOR UPDATE`, rattrapage engagement, règlement, lettrage). N'est plus appelée par le bouton
  fiche crédit ; le sera par `register_operation` (sous-lot B).
- Nouvelle méthode **`get_pending_fees(company_id)`** (`@api.model`) : domaine
  `state == 'approved'` ET `company_id` ET `fee_sent_to_cashier` ET `not fee_paid` ET
  `fee_amount_due > 0` ET `product_id.fee_charged_before_disbursement`. Payload `{id,
  partner_id, partner_name, dossier, product_name, amount (= fee_amount_due), company_name}`.
  Tri `id asc`.

### Modifié — `microfinance_loan_management/views/microfinance_loan_views.xml`

- Bouton `action_charge_fee` (`:72`) remplacé par **`action_send_fee_to_cashier`**
  (« Envoyer les frais en caisse »), `groups="group_microfinance_finance"`,
  `invisible="state != 'approved' or fee_paid or fee_amount_due <= 0 or fee_sent_to_cashier
  or not fee_charged_before_disbursement"`.
- Onglet frais : indicateur discret `<div class="text-muted fst-italic"
  invisible="not fee_sent_to_cashier or fee_paid">En attente d'encaissement en caisse</div>`,
  + `<field name="fee_sent_to_cashier" invisible="1"/>` et
  `<field name="fee_charged_before_disbursement" invisible="1"/>`. **Le badge
  `fee_payment_state` n'est pas touché** (reste `unpaid` dans cet intervalle, décision actée).

### Tests — `microfinance_loan_management/tests/test_fee.py`

- Tests appelant `action_charge_fee()` directement **adaptés** (ajout de
  `loan.action_send_fee_to_cashier()` avant, pas de suppression de la nouvelle garde) :
  `test_fee_payment_state_badge`, `test_charge_fee_generates_move_and_unblocks_disbursement`,
  `test_charge_fee_retrofits_missing_engagement`,
  `test_fee_settlement_falls_back_to_commission_when_product_unconfigured`,
  `test_charge_fee_twice_blocked`, `test_charge_fee_concurrent_guard_no_double_move`.
- Nouveaux tests : `test_send_fee_to_cashier_sets_flag`,
  `test_send_fee_to_cashier_twice_blocked`, `test_send_fee_to_cashier_rejected_for_netted_
  product`, `test_send_fee_to_cashier_rejected_when_not_approved`,
  `test_charge_fee_blocked_without_send`, `test_send_fee_to_cashier_rejected_after_paid`,
  `test_get_pending_fees_nominal_and_payload`, `test_get_pending_fees_scoped_by_company`,
  `test_get_pending_fees_excludes_netted_product`.

### Vérifications

- `xmllint` (vue) OK ; `ast.parse` (modèle + test) OK.
- `-u microfinance_loan_management` sur SEFOR : 93 modules chargés sans erreur, service
  redémarré et actif (le champ related `fee_charged_before_disbursement` et le nouveau
  Boolean n'ont pas cassé le chargement ; la vue formulaire crédit se recompile).
- `TestFee` (`--test-tags /microfinance_loan_management:TestFee`) : **23 tests, 0 failure,
  3 errors**. Les 3 erreurs sont **`UserError: Un fonds de crédit rotatif actif existe pour
  cette agence`** sur les seuls tests qui appellent `action_disburse()`
  (`test_charge_fee_generates_move_and_unblocks_disbursement`,
  `test_disburse_allowed_when_fee_not_required`, `test_disburse_nets_fee_in_single_move`) —
  **échec environnemental pré-existant** (SEFOR a un `microfinance.fond.credit` actif, les
  helpers de test n'assignent pas `fond_credit_id` ; identique à
  `STATUS_lot1.md` §1.1). Ce lot ne les affecte pas : la garde
  `fee_sent_to_cashier` s'exécute correctement dans ces tests avant le blocage `fond` sur le
  décaissement. Tous les tests frais/envoi/`get_pending_fees` passent.

**Aucun commit effectué.**

---

## Sous-lot B — Backend : type `frais_dossier` sur le mouvement de caisse — **FAIT, en attente de validation**

### Modifié — `microfinance_savings_management/models/microfinance_caisse_mouvement.py`

- `type` Selection : ajout de `('frais_dossier', 'Frais de dossier')`.
- Nouveau champ `fee_move_id = fields.Many2one('account.move', string='Écriture frais',
  readonly=True, copy=False)` — traçabilité vers `loan.fee_move_id` (règlement posé par
  `action_charge_fee`), sur le modèle de `payment_id` / `savings_transaction_id`.
- `register_operation()` : nouvelle branche `elif type == 'frais_dossier'` :
  - `loan = browse(loan_id)` ;
  - garde agence `loan.company_id == session.company_id` (identité caissier, non sudo) ;
  - gardes métier explicites pour message clair : `loan.fee_sent_to_cashier` requis, `not
    loan.fee_paid` (redondantes avec les gardes internes de `action_charge_fee`) ;
  - `self._run_posting_sudo(loan, session, 'action_charge_fee')` — `action_charge_fee`
    **inchangée**, garde son verrou `SELECT ... FOR UPDATE` (même curseur sous `sudo()`, le
    `sudo` ne change que l'utilisateur), son rattrapage d'engagement, son règlement
    (`product.fee_journal_id`) et son lettrage ;
  - `vals['amount'] = loan.fee_amount_due` (relu après, figé), `vals['loan_id'] = loan.id`,
    `create(vals)` **en identité caissier**, puis `mouvement.sudo().write({'fee_move_id':
    loan.fee_move_id.id})` (le caissier n'a aucun droit `account.move` ; ce champ n'est lu
    que dans les vues manager). `return mouvement` (early return, comme les autres branches
    retournent `self.create(vals)`).
- **Le journal reste `product.fee_journal_id`** (jamais `session.journal_id`) — décision
  actée, `action_charge_fee` non modifiée.

### Tests — `microfinance_savings_management/tests/test_caisse_pos.py`

Classe `TestCaissePureCashierSavingsAccess` (helpers `_setup_fee_product`,
`_approved_loan_fee_sent` ajoutés) :
- `test_pure_cashier_frais_dossier_end_to_end` — caissier **pur** (`with_user`) : produit
  frais configuré, dossier approuvé + envoyé en caisse → `register_operation('frais_dossier',
  …, loan.id)` → `mouvement.type == 'frais_dossier'`, `loan.fee_paid`,
  `mouvement.fee_move_id == loan.fee_move_id` (posté), `mouvement.amount == 30`,
  `fee_payment_state == 'paid'`.
- `test_frais_dossier_blocked_if_not_sent` — dossier approuvé mais non envoyé →
  `UserError`, `fee_paid` reste `False`.
- `test_frais_dossier_double_call_no_double_move` — 2ᵉ `register_operation('frais_dossier')`
  → `UserError` (garde `fee_paid` sous verrou), `fee_move_id` inchangé, **un seul**
  `microfinance.caisse.mouvement` de type `frais_dossier`.
- `test_frais_dossier_cross_company_blocked` — crédit d'une agence, session d'une autre →
  `UserError`, aucune comptabilisation.

### Vérifications

- `ast.parse` OK. `-u microfinance_savings_management` sur SEFOR : 93 modules chargés sans
  erreur (schéma `fee_move_id` ajouté), service redémarré et actif.
- `TestCaissePureCashierSavingsAccess` + `TestCaisseRegisterOperation` :
  **20 tests, 0 failure, 2 errors**. Les 2 erreurs sont `UserError: Un fonds de crédit
  rotatif actif…` sur `test_register_decaissement_disburses_loan` et
  `test_register_remboursement_matches_backend_allocation` — **pré-existant environnemental
  SEFOR** (identique à `STATUS_lot1.md` §1.1), non causé par ce lot. Les 4 nouveaux tests
  `frais_dossier` et tous les tests 1.1/1.1bis passent → aucune régression.
- Le test end-to-end caissier pur valide : verrou `FOR UPDATE` OK sous `sudo()`,
  `message_post` OK sous OdooBot, engagement/règlement/lettrage OK,
  `mouvement.sudo().write({'fee_move_id': …})` OK.

---

## Sous-lot C — Frontend : 4e onglet « Frais » — **FAIT, arrêt final**

### Modifié — `microfinance_loan_management/static/src/js/microfinance_caisse_pos.js`

- `static TABS` : 5e bouton d'opération
  `{ id: "frais_dossier", label: "Frais de dossier", icon: "fa-file-text-o", kind: "fee" }`.
- `state` : `pendingFees: []`.
- `loadLists()` : ajoute `get_pending_fees(companyId)` au `Promise.all` → `state.pendingFees`.
  Rafraîchi au montage et après chaque `submitOperation` (via `loadSession`), comme les 2
  autres listes.
- `ticketTotals` : ajout de `frais_dossier: 0` (totalisateur ticket).
- Getters : `filteredFees` (filtre recherche partie (a)), `currentTabPartnerIds` gère
  `centralTab === 'frais'`, `isLoanSelectionKind` (`loan` OU `fee`), `displayedLoans`
  (`fee` → `actionableLoans` filtré `fee_sent_to_cashier && !fee_paid` ; sinon liste
  complète 1.4 inchangée), `selectedFeeAmount` (frais figés du crédit sélectionné),
  `effectiveAmount` (frais figés sur onglet frais, saisie pavé ailleurs), `numpadDisabled`
  (`activeTab === 'frais_dossier'`).
- `actionableLoans` : branche `frais_dossier` → `loans.filter(l => l.fee_sent_to_cashier
  && !l.fee_paid)`.
- `canSubmit` : sur `frais_dossier`, ne requiert pas de saisie pavé — `selectedFeeAmount > 0`
  + crédit sélectionné.
- `submitOperation` : `isLoanOp` inclut `frais_dossier` (→ `loan_id` transmis) ; montant
  transmis = `effectiveAmount` (informatif ; `register_operation` reprend `fee_amount_due`).

### Modifié — `microfinance_loan_management/static/src/xml/microfinance_caisse_pos.xml`

- Colonne numpad : affichage `formatMoney(effectiveAmount)` ; clavier + Effacer
  `t-att-disabled="numpadDisabled"` + classe `--disabled` ; hint « Montant figé : frais de
  dossier du crédit sélectionné. » sur l'onglet frais.
- Hints d'opération : `isLoanSelectionKind` (au lieu de `activeTabKind === 'loan'`), message
  dédié « Aucun frais de dossier en attente d'encaissement pour ce client. ».
- Onglets liste : 4e onglet « Frais » + **badges compteur** sur Décaissements / Échéances /
  Frais (`filteredX.length`, masqué si 0 — parité demandée).
- Corps liste : `t-elif="state.centralTab === 'frais'"` → table `Client / Dossier / Produit /
  Montant / Agence` sur `filteredFees`, clic ligne → `selectClient(row.partner_id)` (ne
  change pas l'onglet d'opération).
- Panneau client : section « Crédits » → titre « Frais de dossier » sur l'onglet frais ;
  `t-foreach="displayedLoans"` ; clic/sélection via `isLoanSelectionKind` ; montant affiché
  = `fee_amount_due` sur l'onglet frais, `balance_total` sinon.
- Ticket : 5e tuile « Frais de dossier ».

### Modifié — `microfinance_savings_management/static/src/scss/…` (via SCSS du module crédit)

`microfinance_caisse_pos.scss` : `.o_microfinance_pos__list_tab_badge` (pastille compteur,
inversée sur l'onglet actif), `.o_microfinance_pos__keypad--disabled` + `button:disabled`.

### Modifié — `microfinance_savings_management/models/res_partner.py`

`get_client_accounts_summary()` : chaque crédit du dict `loans` expose désormais
`fee_sent_to_cashier`, `fee_paid`, `fee_amount_due` (structure inchangée, 3 clés ajoutées) —
nécessaire au filtre côté client de l'onglet frais.

### Vérifications

- `xmllint` / `node --check` / `pysassc` OK. `-u microfinance_loan_management,
  microfinance_savings_management` sur SEFOR : 93 modules, bundle d'assets recompilé sans
  erreur, service redémarré/actif.
- **Vérification navigateur réelle** (Playwright, instance SEFOR, session de caisse ouverte
  réelle, utilisateur temporaire créé/désactivé, `fee_sent_to_cashier` posé puis **reverté**
  sur `IS/000289`) :
  - `frais_1_liste.png` : onglet liste « Frais » actif avec badge **1** (badge **3** sur
    Décaissements) ; table alimentée par `get_pending_fees` — `RANDRIAMISEZA / IS/000289 /
    PRET RURAL / 25 000 MGA / CEFOR Isotry` ; 5e tuile ticket « Frais de dossier ».
  - `frais_2_client_panel.png` : onglet d'opération « Frais de dossier » actif, numpad
    grisé/désactivé + hint « Montant figé… », panneau client avec section « FRAIS DE
    DOSSIER » listant `IS/000289 — 25 000 MGA` (montant = `fee_amount_due`, filtre
    `fee_sent_to_cashier && !fee_paid`).
  - `frais_3b_loan_selected.png` : crédit `IS/000289` sélectionné → affichage montant
    **25 000 MGA** (figé), bouton **« Valider » activé** (`disabled` absent). Non cliqué
    (éviterait une comptabilisation réelle sur SEFOR ; le chemin serveur est prouvé par les
    tests du sous-lot B).
- `TestCaissePureCashierSavingsAccess` + `TestCaisseGetClientAccountsSummary` +
  `TestCaisseSearchClients` : **22 tests, 1 failure, 1 error** — les 2 sont
  **pré-existants environnementaux SEFOR** (`test_summary_includes_active_loan…` →
  `UserError` fonds actif ; `test_search_by_name` → collision de noms « Rako… »), documentés
  §1.1, non causés par ce lot. Les 4 tests `frais_dossier` et `test_pure_cashier_get_client_
  accounts_summary` passent → l'extension `res_partner` n'introduit aucune régression.

### Scénario de test manuel (à rejouer par Micka)

1. Fiche crédit approuvé (produit « frais exigés avant décaissement », frais > 0), en
   `group_microfinance_finance` : bouton « Envoyer les frais en caisse » → indicateur « En
   attente d'encaissement en caisse » apparaît, badge `fee_payment_state` reste rouge.
2. Guichet (caissier) : onglet liste « Frais » (badge +1) → le dossier apparaît.
3. Onglet d'opération « Frais de dossier » → clic sur la ligne → client sélectionné, section
   « Frais de dossier » avec le crédit et son montant figé, numpad désactivé.
4. Sélectionner le crédit → montant figé affiché → « Valider ».
5. Retour fiche crédit : `fee_payment_state` passe à **vert (Payé)**, écriture de règlement
   `product.fee_journal_id` postée, créance 208005 lettrée. Le dossier disparaît de l'onglet
   « Frais » du guichet.
6. Caissier **pur** (`group_microfinance_cashier` seul) : le flux aboutit (sudo ciblé
   `_run_posting_sudo`).

### Points remontés à Micka (non tranchés)

- La 5e tuile ticket « Frais de dossier » et les badges compteur des onglets liste
  Décaissements/Échéances ont été ajoutés pour cohérence (le prompt demande la parité pour
  l'onglet Frais) — signaler si non souhaité sur les 2 onglets existants.
- Sur les onglets d'opération épargne, le panneau client n'affiche plus la liste des crédits
  (non actionnables) — `displayedLoans` renvoie la liste complète pour `kind loan`, vide
  seulement pour `savings` via `actionableLoans === []`. En pratique inchangé pour
  `remboursement_credit` / `decaissement_credit` ; seul l'affichage informatif des crédits
  sur un écran de dépôt/retrait épargne disparaît. À confirmer.
- Base de test CI propre toujours à prévoir (échecs environnementaux SEFOR récurrents).

**Lot 1 étendu (Frais) terminé — sous-lots A, B, C. Aucun commit effectué.**
