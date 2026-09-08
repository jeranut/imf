# Lot 1 — Réorganisation Guichet Caisse — Statut

Découpage en 4 sous-lots, arrêt et validation entre chaque. Aucun commit (Micka relit et
commit).

---

## Sous-lot 1.1 — Sécurité — **FAIT, en attente de validation**

### Modifié

**`microfinance_savings_management/security/savings_security.xml`** : nouveau `<record>`
étendant `microfinance_loan_management.group_microfinance_cashier` pour impliquer
`group_savings_agent` :
```xml
<record id="microfinance_loan_management.group_microfinance_cashier" model="res.groups">
    <field name="implied_ids" eval="[(4, ref('group_savings_agent'))]"/>
</record>
```

Contrainte d'ordre de chargement trouvée et respectée : l'implication est ajoutée **côté
`microfinance_savings_management`** (et non dans
`microfinance_loan_management/security/groups.xml`). `microfinance_loan_management` est chargé
**avant** `microfinance_savings_management` (dépendance inverse : c'est le module épargne qui
dépend du module crédit), donc l'external id `group_savings_agent` n'est pas résolvable dans
`groups.xml`. Aucun précédent exact de « module A étend `implied_ids` d'un groupe du module
B » dans le projet ; le patron le plus proche est
`microfinance_savings_management/security/ir.model.access.csv` qui référence déjà les external
ids `microfinance_loan_management.group_*`. **Pas de dépendance circulaire de manifest** :
seule une donnée de sécurité de `microfinance_savings_management` référence l'external id du
groupe crédit. `(4, id)` **ajoute** l'implication sans retirer `group_microfinance_user` déjà
impliqué côté module crédit (`groups.xml:38`).

**`microfinance_savings_management/tests/test_caisse_pos.py`** : nouvelle classe
`TestCaissePureCashierSavingsAccess` (5 tests) — le chemin « caissier pur au guichet » n'était
couvert par aucun test avant ce lot (AUDIT §1.1).

### Vérifications

- `xmllint --noout` OK ; `py_compile` du test OK.
- `-u microfinance_savings_management` sur SEFOR : 93 modules chargés sans erreur, service
  redémarré et actif.
- Implication effective en base (SEFOR) : `group_microfinance_cashier` implique désormais
  « Agent crédit » **et** « Agent épargne » (vérifié par requête SQL sur
  `res_groups_implied_rel`).
- `TestCaissePureCashierSavingsAccess` : **5/5 OK** sur SEFOR
  (`--test-tags /microfinance_savings_management:TestCaissePureCashierSavingsAccess`).
  - `test_implied_group_is_effective` : le caissier a bien `group_savings_agent`.
  - `test_pure_cashier_can_read_savings_models` : `search`/`read` sur
    `microfinance.savings.account` et `.transaction` sans `AccessError`.
  - `test_pure_cashier_get_client_accounts_summary` : l'appel RPC existant passe pour un
    caissier pur.
  - `test_cashier_with_accounting_group_can_register_savings_deposit` : dépôt épargne complet
    au guichet OK quand le caissier porte aussi un groupe comptable standard.
  - `test_pure_cashier_register_savings_deposit_still_blocked_on_account_move` : documente le
    point ouvert ci-dessous (assertion `AccessError`).
- Non-régression `TestCaisseFicheJourneeSecurity` (`test_caisse_security.py`) : **8/8 OK** sur
  SEFOR — `group_savings_agent` n'a aucun droit sur `microfinance.caisse.fiche.journee`, les
  ACL fiche du caissier sont inchangées.

### Échecs environnementaux (pré-existants, NON causés par ce lot)

Le lancement de `--test-enable` sur **SEFOR** (base à données réelles) fait échouer plusieurs
tests pré-existants qui supposent une base vierge — indépendants d'une implication de groupe :

- `TestCashierAccess.test_cashier_can_prefill_payment_form_from_loan` et plusieurs tests de
  `test_caisse_pos.py` (`test_register_decaissement_disburses_loan`,
  `test_register_remboursement_matches_backend_allocation`, `test_direct_disbursement_
  unaffected`, `test_direct_loan_payment_unaffected`,
  `test_summary_includes_active_loan_with_next_due_installment`) :
  `UserError: Un fonds de crédit rotatif actif existe pour cette agence` — SEFOR a un
  `microfinance.fond.credit` actif ; les helpers de test (`_activate_loan` / `_create_loan` +
  décaissement) n'assignent pas `fond_credit_id`.
- `TestCaisseSearchClients.test_search_by_name` : `AssertionError` — SEFOR contient de vrais
  partenaires « Rakoto… » qui s'ajoutent au résultat attendu par la fixture.
- Base `imf_test_dev` : `-u microfinance_loan_management` y échoue sur une erreur d'héritage
  de vue pré-existante (`microfinance.loan.tree.scoring.inherit` / champ `risk_score`
  introuvable) — base dans un état incohérent, non utilisable telle quelle pour la CI.

➡️ Une **base de test propre dédiée** est nécessaire pour rejouer l'ensemble des suites caisse
sans bruit. À voir avec Micka (recréer un `imf_test_dev` sain, ou cibler une autre base).

### POINT OUVERT à trancher par Micka (hors décisions actées du Lot 1)

Ajouter `group_savings_agent` débloque bien la **lecture** des modèles épargne (les 3 tests
concernés passent), **mais ne suffit pas** pour qu'un caissier *strictement*
`group_microfinance_cashier` puisse exécuter `register_operation` de bout en bout :
`register_operation` (dépôt/retrait épargne, remboursement, décaissement) poste une écriture
comptable, or **aucun** groupe métier microfinance ni `group_savings_agent` n'accorde
`create`/`write` sur `account.move`. Résultat observé pour un caissier pur :
`AccessError: Vous n'êtes pas autorisé à créer des enregistrements 'Journal Entry'
(account.move)` (test `..._still_blocked_on_account_move`).

Cette dépendance existait **déjà** pour `remboursement_credit` / `decaissement_credit` avant ce
lot (jamais testée en `with_user`, cf. AUDIT §5.5, parenthèse « et des droits `account.move` »).

Trois options, à arbitrer séparément (ne pas trancher dans ce lot) :
1. faire aussi impliquer un groupe comptable standard (`account.group_account_user`) par
   `group_microfinance_cashier` ;
2. passer la comptabilisation des transactions/paiements/décaissements en `sudo()` avec
   contrôles d'agence explicites ;
3. acter que le profil « caissier » porte toujours un groupe comptable en production (config
   hors modules microfinance) — dans ce cas, aucune modif de code, juste une consigne de
   paramétrage.

### Reste à faire

- Sous-lot 1.3 — Frontend layout (XML + SCSS).
- Sous-lot 1.4 — Frontend logique (JS).

**Aucun commit effectué.**

---

## Sous-lot 1.1bis — Débloquer `account.move` pour le caissier pur (sudo ciblé)

Option retenue par Micka : **option 2** (sudo ciblé + contrôles d'agence explicites, pas
d'ajout de groupe comptable).

### Phase 1 — Reconnaissance (lecture seule) — **FAITE, en attente de validation du plan**

#### 1. Points de création / post exacts de l'`account.move`

Les trois chemins font le **même geste** : `account.move.create(...)` direct (avec
`with_context(default_loan_id=False, default_loan_line_id=False)`) puis `move.action_post()`
(le `action_post` **natif** d'`account.move`, surchargé — voir plus bas). Aucun `sudo()`
existant, même partiel.

| Chemin | Création `account.move` | Post | Prépa des lignes |
|---|---|---|---|
| `microfinance.savings.transaction.action_post()` | `microfinance_savings_transaction.py:311-313` | `:314` `move.action_post()` | `_prepare_transaction_move()` `:219-300` |
| `microfinance.loan.payment.action_post()` | `microfinance_loan_payment.py:193-196` | `:197` `move.action_post()` | `_prepare_payment_move()` `:157-186` |
| `microfinance.loan.action_disburse()` | `microfinance_loan.py:1925-1928` | `:1929` `move.action_post()` | `_prepare_disbursement_move()` |

**`account.move.action_post()` est surchargé** dans
`microfinance_loan_management/models/microfinance_caisse_fiche_journee.py:230-249` (classe
`AccountMove(_inherit='account.move')`) : refuse de comptabiliser dans une journée de caisse
clôturée, puis `super().action_post()`. Un `sudo()` englobant traverserait aussi cette
surcharge — sans effet de bord (le contrôle « journée clôturée » reste actif ; et le guichet
exige déjà `session.state == 'open'`, incompatible avec une fiche clôturée).

**L'`account.move` n'est pas le seul point ACL-bloquant** pour un caissier
(`group_microfinance_cashier` + `group_savings_agent`, sans droits comptables) :

- `remboursement_credit` : `_allocate_to_installments()`
  (`microfinance_loan_payment.py:133-155`) écrit `inst.paid_interest/paid_principal/paid_penalty`
  → **write sur `microfinance.loan.installment`**, or le caissier n'a que la **lecture**
  (`ir.model.access.csv:35`, `group_microfinance_user` = `1,0,0,0` ; aucune ligne cashier).
- `decaissement_credit` : `action_disburse()` appelle `action_generate_schedule()` si pas
  d'échéancier (`microfinance_loan.py:1923-1924`) → **create sur
  `microfinance.loan.installment`** (idem, non accordé).
- `depot/retrait_epargne` : `_prepare_transaction_move()` → `product._get_account(...)` lit
  `account.account` (non accordé au caissier).

➡️ Le `sudo()` doit donc englober **l'appel complet de la sous-opération**
(`_create_transaction` / `payment.action_post` / `loan.action_disburse`), pas seulement la
ligne `account.move.create`. `group_savings_agent` (Lot 1.1) ne suffit d'ailleurs pas pour
remboursement/décaissement pour la même raison (écritures/créations d'échéances).

#### 2. Autres appelants (⚠️ méthodes partagées — ne PAS sudo-er en place)

**`microfinance.loan.payment.action_post()`** :
- `microfinance_loan_management/wizard/microfinance_loan_payment_wizard.py:52` — assistant
  « Enregistrer un remboursement » (`post_now`), ACL wizard = `group_microfinance_user`
  (`ir.model.access.csv:45`).
- `microfinance_loan_management/views/microfinance_loan_payment_views.xml:17` — bouton
  « Comptabiliser » du formulaire remboursement, **aucun `groups=`**.
- `microfinance_savings_management/models/microfinance_loan_extension.py:219` —
  `_process_savings_auto_debit()`, appelé par le cron `cron_process_savings_auto_debit`
  (`:230-...`).
- `microfinance_savings_management/models/microfinance_caisse_mouvement.py:86` — **guichet**.

**`microfinance.savings.transaction.action_post()`** (directement ou via
`_create_transaction()` qui poste toujours, `microfinance_savings_account.py:199`) :
- Bouton « Comptabiliser » du formulaire transaction épargne,
  `microfinance_savings_management/views/microfinance_savings_transaction_views.xml:26`,
  **aucun `groups=`**.
- `_create_transaction()` appelé par : `action_close()` (`microfinance_savings_account.py:263`),
  cron `cron_capitalize_interest` (`:331`), `_process_savings_auto_debit()`
  (`microfinance_loan_extension.py:208`), et le **guichet** (`microfinance_caisse_mouvement.py:75`).

**`microfinance.loan.action_disburse()`** :
- `microfinance_loan_management/views/microfinance_loan_views.xml:73` — bouton
  « Activer / Décaisser », `groups="microfinance_loan_management.group_microfinance_finance"`.
- `microfinance_savings_management/models/microfinance_caisse_mouvement.py:98` — **guichet**.

➡️ **Conclusion** : les trois méthodes sont partagées avec des boutons de formulaire /
assistants utilisés par des profils finance / manager / agent épargne, plus des crons. Un
`sudo()` posé **dans** ces méthodes changerait le comportement pour **tous** les appelants
(ceux-là ont déjà les droits comptables — le sudo serait au mieux inutile, au pire masquerait
une régression d'ACL ailleurs). Le bypass doit être **strictement circonscrit à
`register_operation`**.

#### 3. Garde d'agence existante dans `register_operation` (`microfinance_caisse_mouvement.py`)

Confirmé, `company_id` vérifié **avant** chaque appel de sous-opération, en identité caissier
réelle (non sudo) :

| Type | Garde | Appel gardé |
|---|---|---|
| `depot_epargne` / `retrait_epargne` | `:71-73` `account = browse(savings_account_id)` ; `if account.company_id != session.company_id: raise UserError` | `:75` `_create_transaction` |
| `remboursement_credit` | `:78-80` `loan = browse(loan_id)` ; `if loan.company_id != session.company_id: raise UserError` | `:81-86` `create` + `action_post` |
| `decaissement_credit` | `:95-97` idem | `:98` `action_disburse` |

En amont : `:60-62` `session.exists()` + `session.state == 'open'`. Le `browse(...)` +
comparaison tourne en **identité caissier** : un caissier ne peut pas référencer un
compte/prêt qu'il ne peut pas lire (borne `ir.rule` `company_id in company_ids`). ⚠️ à
préserver : **la garde doit rester non-sudo** ; sudo-er le `browse` permettrait de pointer un
enregistrement d'une autre agence.

Note : `register_operation` ne vérifie pas `session.company_id == self.env.company` — il fait
confiance au `session_id` fourni ; l'`ir.rule` sur `microfinance.caisse.session` empêche de
charger la session d'une autre agence, et le caissier est mono-agence (décision actée).

#### 4. Plan proposé (à valider avant Phase 2)

Invariants communs aux deux options :
- Aucune modification de `action_post` (les deux modèles), `action_disburse`,
  `_create_transaction` : elles restent partagées et non-sudo.
- La garde `company_id` existante (`:71-73`, `:78-80`, `:95-97`) **reste en identité caissier**,
  inchangée.
- Le `self.create(vals)` final (`:106`, ligne de ticket `microfinance.caisse.mouvement`) **reste
  non-sudo** : le caissier a le droit `create` (`ir.model.access` savings `:18`) et reste
  `create_uid` / `cashier_id` de la trace.
- Aucun élargissement d'`ir.model.access` sur `account.move` / `microfinance.loan.installment`
  pour quelque groupe que ce soit.

**Option A — helper privé unique dans `microfinance_caisse_mouvement.py`.**
Nouvelle méthode privée, ex.
`_run_posting_sudo(self, record, session, method_name, **kwargs)` :
1. `record.ensure_one()` ;
2. **re-vérifie** `record.company_id == session.company_id` (défense en profondeur,
   co-localisée avec le sudo — pas seulement la garde d'amont), sinon `UserError` ;
3. `return getattr(record.sudo(), method_name)(**kwargs)`.
`register_operation` l'appelle pour les 3 branches :
- épargne : `self._run_posting_sudo(account, session, '_create_transaction', transaction_type, amount, payment_method='cash')` (adapter la signature : `_create_transaction` prend des positionnels) ;
- remboursement : `payment = ...create(...)` (inchangé, non-sudo) puis
  `self._run_posting_sudo(payment, session, 'action_post')` — note : `payment.company_id`
  est `related` stocké de `loan_id.company_id`, donc la re-vérification porte bien sur
  l'agence du crédit ;
- décaissement : `self._run_posting_sudo(loan, session, 'action_disburse')`.
Avantage : un seul point de bypass, nommé, trivial à tester (le test « pas de fuite » cible
cette méthode). Inconvénient : `create_uid` de l'`account.move` (et de la transaction épargne)
= OdooBot, chatter (`message_post` dans `action_post`) authorisé par OdooBot au lieu du
caissier — dégradation mineure de la piste d'audit ; la ligne de ticket
`microfinance.caisse.mouvement` garde `cashier_id` + `session_id`.

**Option B — `.sudo()` inline aux 3 points d'appel de `register_operation`**, sans helper :
`account.sudo()._create_transaction(...)`, `payment.sudo().action_post()`,
`loan.sudo().action_disburse()`, précédés (juste avant, dans le même bloc) d'un `assert`
explicite `record.company_id == session.company_id` → `UserError`. Même effet, moins de
structure ; la propriété « le sudo ne sert qu'ici » est vraie mais plus diffuse (3 sites au
lieu d'1).

**Recommandation** : Option A (helper unique). Compromis identiques côté audit-trail
(`create_uid` OdooBot) ; meilleure testabilité de la non-fuite.

**Points à confirmer par Micka avant Phase 2** :
- (a) Accepte-t-on `create_uid = OdooBot` sur l'`account.move` / la transaction épargne créés
  au guichet (option A comme B) ? Sinon il faut un post-traitement (repositionner `create_uid`
  n'est pas possible proprement ; on pourrait forcer l'auteur du `message_post`, mais c'est
  dans la méthode partagée — hors de portée sans la modifier).
- (b) OK pour que le helper porte **aussi** le déblocage des écritures/créations
  `microfinance.loan.installment` (inhérent au sudo de `action_post` / `action_disburse`) —
  c'est nécessaire, pas optionnel, mais ça élargit de fait le bypass au-delà du seul
  `account.move`.

**Aucun code écrit. En attente de validation du plan (Option A vs B, points a/b).**

### Phase 2 — Implémentation (Option A validée par Micka) — **FAITE, en attente de relecture**

Points (a) et (b) considérés comme acceptés implicitement : ce sont des conséquences
inhérentes à l'option 2 (sudo) / option A, indissociables du choix fait.

#### Modifié — `microfinance_savings_management/models/microfinance_caisse_mouvement.py`

- Nouvelle méthode privée **`_run_posting_sudo(self, record, session, method_name, *args, **kwargs)`**
  (avant `register_operation`) : `record.ensure_one()` → **re-vérifie**
  `record.company_id == session.company_id` (défense en profondeur, `UserError` sinon, en
  identité réelle sur `record` non sudo) → `getattr(record.sudo(), method_name)(*args, **kwargs)`.
- `register_operation` : les 3 étapes comptabilisantes passent par ce helper —
  - `depot/retrait_epargne` : `self._run_posting_sudo(account, session, '_create_transaction', transaction_type, amount, payment_method='cash')` (au lieu de `account._create_transaction(...)`) ;
  - `remboursement_credit` : `payment = ...create(...)` inchangé (le caissier a le droit
    `create`), puis `self._run_posting_sudo(payment, session, 'action_post')` ;
  - `decaissement_credit` : `self._run_posting_sudo(loan, session, 'action_disburse')`.
- **Inchangés** : les gardes `company_id` d'amont (`:71-73`, `:78-80`, `:95-97`), le
  `session.state == 'open'`, le `self.create(vals)` final (caissier reste `create_uid` /
  `cashier_id` de la ligne de ticket). **Aucune modification** de `action_post` (les 2
  modèles), `action_disburse`, `_create_transaction`, ni d'`ir.model.access`.

Le sudo est donc strictement circonscrit à `register_operation` : tous les autres appelants
des méthodes cibles (boutons de formulaire finance/épargne, assistant remboursement, crons)
les exécutent toujours sans sudo, avec leurs droits propres.

#### Tests — `microfinance_savings_management/tests/test_caisse_pos.py`

Classe `TestCaissePureCashierSavingsAccess` étendue. `test_pure_cashier_register_savings_
deposit_still_blocked_on_account_move` (Lot 1.1, prémisse devenue caduque) **supprimé** et
remplacé. **10/10 OK sur SEFOR** (`--test-tags
/microfinance_savings_management:TestCaissePureCashierSavingsAccess`) :

- **Les 4 flux servis par un caissier PUR** (`group_microfinance_cashier` +
  `group_savings_agent` impliqué, aucun groupe comptable), via `register_operation` en
  `with_user(caissier)` :
  `test_pure_cashier_depot_epargne`, `test_pure_cashier_retrait_epargne`,
  `test_pure_cashier_remboursement_credit`, `test_pure_cashier_decaissement_credit`.
- **Pas de fuite du bypass** : `test_sudo_does_not_leak_arbitrary_account_move` — un caissier
  pur reste incapable de `self.env['account.move'].create(...)` en direct (`AccessError`).
- **Cloisonnement d'agence maintenu malgré le sudo** :
  `test_cross_company_operation_still_blocked_with_sudo` — compte d'une agence + session
  d'une autre → `UserError`, aucune transaction créée.
- Non-régression profil « caissier + groupe comptable » : `test_cashier_with_accounting_
  group_still_ok`.
- Rappel Lot 1.1 : `test_implied_group_is_effective`, `test_pure_cashier_can_read_savings_
  models`, `test_pure_cashier_get_client_accounts_summary`.
- Helper de test `_neutralize_funds()` (désactive les `microfinance.fond.credit` actifs le
  temps du test, rollback `TransactionCase`) pour rendre les flux crédit jouables sur SEFOR
  malgré le fonds bailleur réel.

#### Non-régression

- `TestCaisseRegisterOperation` + `TestCaissePosNoRegression` sur SEFOR : **aucune nouvelle
  défaillance** introduite par ce lot. Les 4 erreurs observées (`test_register_decaissement_
  disburses_loan`, `test_register_remboursement_matches_backend_allocation`,
  `test_direct_disbursement_unaffected`, `test_direct_loan_payment_unaffected`) sont
  **exactement** les mêmes qu'avant ce lot : `UserError: Un fonds de crédit rotatif actif
  existe pour cette agence` (fixture de test incompatible avec les données réelles SEFOR, cf.
  section 1.1). Les tests épargne / blocage / cross-company de ces classes passent.
- `-u microfinance_savings_management` sur SEFOR : 93 modules chargés sans erreur, service
  redémarré et actif.
- `ast.parse` OK sur les deux fichiers modifiés (`py_compile` impossible : `__pycache__` en
  lecture seule pour l'utilisateur courant).

#### Compromis assumés (inhérents à l'option A, à valider en relecture)

- `create_uid` de l'`account.move` (et de la `microfinance.savings.transaction` pour les
  dépôts/retraits) = **OdooBot**, et les `message_post` internes à `action_post` /
  `action_disburse` sont authored par OdooBot. La ligne de ticket
  `microfinance.caisse.mouvement` garde `cashier_id` (défaut `self.env.user`) + `session_id`
  comme trace de l'auteur réel.
- Le sudo débloque **aussi** les écritures/créations `microfinance.loan.installment`
  (`_allocate_to_installments` pour le remboursement, `action_generate_schedule` pour le
  décaissement) — nécessaire, pas seulement `account.move`. C'est le point (b) signalé en
  Phase 1.

**Aucun commit effectué.**

---

## Sous-lot 1.2 — Backend : méthodes de liste — **FAIT, en attente de validation**

### Ajouté (aucune méthode existante modifiée)

**`microfinance_loan_management/models/microfinance_loan.py`** — nouvelle méthode `@api.model`
`get_pending_disbursements(company_id)`, placée juste après `action_disburse()` :
```python
loans = self.search([('state', '=', 'approved'), ('company_id', '=', company_id)],
                    order='approval_date asc, id asc')
# -> [{id, partner_id, partner_name, dossier, product_name,
#      amount (= net_disbursed_amount), approval_date, company_name}]
```
- `state == 'approved'` strict (décision actée) ; `avis_ca` / `avis_cdag` exclus.
- Montant = `net_disbursed_amount` (champ stocké `compute='_compute_net_disbursed_amount'`,
  `microfinance_loan.py:246` — confirmé : champ, pas méthode).
- Filtre `company_id` explicite (défense en profondeur, cf. AUDIT §5).
- Tri `approval_date asc, id asc`.

**`microfinance_loan_management/models/microfinance_loan_installment.py`** — nouvelle méthode
`@api.model` `get_pending_or_late(company_id)`, placée juste après `get_due_today()` (qui reste
**inchangée**) :
```python
installments = self.search([
    ('company_id', '=', company_id),
    ('due_date', '<=', today),
    ('state', '!=', 'paid'),
    ('loan_id.state', 'in', ('active', 'defaulted')),
], order='due_date asc, loan_id asc')
# -> [{id, partner_id, partner_name, dossier, due_date,
#      amount (= residual_amount), state, is_late (due_date < today), company_name}]
```
- Périmètre acté : `due_date <= aujourd'hui AND state != 'paid' AND loan_id.state in
  ('active','defaulted')`.
- `state != 'paid'` inclut les échéances `partial` en retard (voulu).
- `('loan_id.state', 'in', ('active','defaulted'))` **obligatoire** — exclut les échéances
  d'un crédit non décaissé dont un échéancier a été généré en aperçu (AUDIT §3.3 / anomalie
  A1). Présent, non omis.
- `get_due_today` **non touchée** (périmètre plus restrictif, `due_date == aujourd'hui`,
  toujours consommée par le dashboard).

### Tests — `microfinance_loan_management/tests/test_guichet_backend_lists.py` (nouveau)

Ajouté à `tests/__init__.py`. **11/11 OK sur SEFOR** (`--test-tags
/microfinance_loan_management:TestGetPendingDisbursements,
/microfinance_loan_management:TestGetPendingOrLate`).

`TestGetPendingDisbursements` (assertions par appartenance — la base peut déjà contenir des
crédits `approved` réels) :
- `test_nominal_returns_approved_loan_with_expected_payload` — payload complet vérifié
  (montant = `net_disbursed_amount`, `approval_date`, etc.).
- `test_excludes_avis_ca_and_avis_cdag`.
- `test_excludes_active_loan`.
- `test_scoped_by_company_no_leak` — société neuve → `[]`.
- `test_ordered_by_approval_date`.

`TestGetPendingOrLate` :
- `test_due_today_included_future_excluded`.
- `test_late_installment_included_and_flagged` — `is_late=True`, `state='overdue'`,
  `amount == residual_amount`.
- `test_partial_and_late_installment_included` — échéance partiellement soldée + échue
  (`state='partial'`) bien présente.
- `test_paid_installment_excluded`.
- `test_excludes_installments_of_non_active_loan` — échéancier passé sur un crédit `approved`
  → exclu (garde `loan_id.state`).
- `test_scoped_by_company_no_leak`.

Helper `_neutralize_funds()` (désactive les `microfinance.fond.credit` actifs, rollback
`TransactionCase`) pour rendre `_activate_loan` jouable sur SEFOR malgré le fonds bailleur
réel.

### Non-régression

- `-u microfinance_loan_management` sur SEFOR : 93 modules chargés sans erreur, service
  redémarré et actif.
- Aucune méthode existante modifiée (deux nouvelles méthodes `@api.model` uniquement) —
  `get_due_today`, `get_client_accounts_summary`, `search_caisse_clients`,
  `register_operation` intactes.
- `ast.parse` OK sur les 3 fichiers touchés.

**Aucun commit effectué.**

---

## Sous-lot 1.3 — Frontend : réorganisation du layout (XML + SCSS) — **FAIT, en attente de validation visuelle**

### Modifié

**`microfinance_loan_management/static/src/xml/microfinance_caisse_pos.xml`** — bloc
`o_microfinance_pos__body` réécrit (structure uniquement) :
- **Colonne gauche `--numpad`** (~300px, style POS) : reprend tel quel l'aperçu ventilation +
  affichage montant + clavier + « Effacer » + « Valider » de l'ancienne colonne opération.
  Déplacement DOM pur, aucun handler numpad modifié (AUDIT §6.4 : aucun couplage focus/ordre
  DOM).
- **Colonne centre `--center`** (nouvelle structure interne) :
  1. barre de recherche (input existant, `onSearchInput` / `searchQuery` / `searchResults`
     inchangés) ;
  2. les 4 boutons d'opération existants (`tabs` / `setActiveTab`), inchangés ;
  3. hints d'opération (repris, le hint épargne dit maintenant « ci-dessous ») ;
  4. **bloc liste à 3 onglets** : « Décaissements en attente » (défaut) / « Échéances du
     jour » / « Épargne en attente ». Tables `Client / Dossier / Produit|Échéance / Montant /
     [État] / Agence`, ligne en rouge clair si `is_late`. Onglet Épargne = message
     placeholder « Cette liste sera disponible prochainement. ». Section « Autres clients »
     sous la liste ;
  5. **panneau « client sélectionné »** : quand `state.client` est renseigné, remplace le
     bloc liste — blocs comptes épargne / crédits repris tels quels de l'ancienne colonne
     gauche (mêmes handlers `activeTabKind` / `selectAccount` / `selectedAccountId`), plus un
     bouton « ← Retour à la liste » (= `clearClient`).
- **Colonne droite `--ticket`** : strictement inchangée.

**`microfinance_loan_management/static/src/scss/microfinance_caisse_pos.scss`** :
- `__body` : `grid-template-columns: 280px 1fr 320px` → `300px 1fr 280px` ;
  `grid-template-areas: "client operation ticket"` → `"numpad center ticket"`.
- `__col--client` / `--operation` → `--numpad` / `--center`.
- Nouvelles règles : `__list`, `__list_tabs` / `__list_tab(--active)`, `__list_body`,
  `__list_scroll` (scroll interne), `__list_table` (thead sticky), `__list_row(--late)`,
  `__num` (montants alignés à droite), `__other_clients`, `__back_to_list`.
- Media queries **inchangées dans leur logique de repli**, seuls les noms d'aires et les
  largeurs sont adaptés : `@1024px` → `260px 1fr` / `"numpad center" / "ticket ticket"` ;
  `@768px` → `1fr` / `"numpad" "center" "ticket"` (empilement vertical identique à l'existant).

**`microfinance_loan_management/static/src/js/microfinance_caisse_pos.js`** — **strict
minimum** pour que le layout se rende sans erreur (le câblage des données est le sous-lot
1.4, cf. « Fichiers » du prompt qui ne liste que xml+scss ; ~12 lignes inertes signalées
comme telles) :
- `state` : `centralTab: "decaissements"`, `pendingDisbursements: []`,
  `pendingInstallments: []`, `otherClients: []`, `listLoading: false`.
- méthode `setCentralTab(tabId)` : pose `state.centralTab` uniquement (ne touche ni au client
  ni au montant, contrairement à `setActiveTab`).

### Vérifications

- `xmllint --noout` OK sur le template ; `node --check` OK sur le JS ; `pysassc` compile le
  SCSS sans erreur (10 316 octets de CSS).
- `-u microfinance_loan_management` sur SEFOR : 93 modules chargés sans erreur, service
  redémarré et actif (le bundle d'assets se recompile côté serveur sans erreur).
- **Captures d'écran AVANT / APRÈS** (maquettes statiques rendues avec le CSS réellement
  compilé depuis le SCSS du module, données factices — conformes à « layout uniquement,
  aucune donnée réelle »), à 3 largeurs :
  - desktop 1280px : `guichet_AVANT__desktop.png`, `guichet_APRES_liste__desktop.png`,
    `guichet_APRES_client__desktop.png` ;
  - tablette 900px : `guichet_APRES_liste__tablette.png` (+ AVANT) ;
  - mobile 600px : `guichet_APRES_liste__mobile.png` (+ AVANT).
- Le repli mobile (chaque colonne à ~1/3 de hauteur d'écran avec scroll interne, clavier
  tronqué) est **identique** entre AVANT et APRÈS — comportement pré-existant lié à
  `.o_action_manager { height:100% }` (cf. commentaire en tête du SCSS), hors périmètre de ce
  lot.

### Limite assumée

Le layout se rend, mais les onglets liste ne réagissent pas au clic et les tables sont vides
(`state.pendingDisbursements` etc. non alimentés) : c'est le sous-lot 1.4 (chargement RPC via
`get_pending_disbursements` / `get_pending_or_late`, double comportement de la recherche,
« Autres clients », rafraîchissement après validation).

**Aucun commit effectué.**

---

## Sous-lot 1.4 — Frontend : logique (JS) — **FAIT, arrêt final**

### Modifié — `microfinance_loan_management/static/src/js/microfinance_caisse_pos.js`

- **`loadLists()`** (nouveau) : `Promise.all` sur
  `microfinance.loan.get_pending_disbursements(companyId)` et
  `microfinance.loan.installment.get_pending_or_late(companyId)`, stocke dans
  `state.pendingDisbursements` / `state.pendingInstallments`. `companyId =
  state.session.company_id[0]` (jamais la société active de l'UI). Appelé depuis
  `loadSession()` juste après `loadMouvements()` → couvre le montage **et** le
  rafraîchissement après chaque `submitOperation` réussi (qui rappelle déjà `loadSession`).
- **Recherche, double comportement** :
  - `onSearchInput` : pose `state.searchQuery` puis débounce 300 ms vers `refreshOtherClients`.
  - Partie (a), filtre local : getters **`filteredDisbursements`** / **`filteredInstallments`**
    = liste brute filtrée par `_matchesQuery(row)` (`partner_name` OU `dossier`, insensible à
    la casse). Aucun appel serveur. Le template itère désormais ces getters.
  - Partie (b), « Autres clients » : `refreshOtherClients()` — si `searchQuery.trim().length
    < 2` → `otherClients = []` ; sinon `search_caisse_clients(query, companyId)` (RPC
    existant, inchangé), puis exclusion des `partner_id` déjà présents dans la liste filtrée
    de l'onglet actif (getter `currentTabPartnerIds`).
- **`setCentralTab(tabId)`** : pose `state.centralTab` ; ne recharge pas les listes (déjà en
  mémoire) ; ré-appelle `refreshOtherClients()` si une recherche ≥ 2 car la base de
  dédoublonnage change. Ne touche ni au client sélectionné ni au montant (≠ `setActiveTab`).
- **`selectClient`** : nettoie désormais `otherClients` (au lieu de `searchResults`) + vide
  `searchQuery`. Reste inchangé par ailleurs (ne touche pas `activeTab` → décision actée :
  clic sur une ligne = sélection client seule).
- `state` : suppression de `searchResults` (dropdown flottant retiré) ; `searching` conservé
  (indicateur de chargement « Autres clients »).

### Modifié — `microfinance_caisse_pos.xml` (ajustements liés à la logique 1.4)

- Suppression du dropdown flottant `o_microfinance_pos__search_results` (remplacé
  fonctionnellement par « Autres clients », dédoublonné et inline).
- Les 3 tables : `t-foreach` / `t-if` sur `state.pendingDisbursements|pendingInstallments` →
  `filteredDisbursements` / `filteredInstallments` (filtre partie (a)).

### Vérifications

- `xmllint` / `node --check` / `pysassc` : OK. `-u microfinance_loan_management` sur SEFOR :
  93 modules, bundle d'assets recompilé sans erreur, service redémarré et actif.
- **Vérification navigateur réelle** (Playwright sur l'instance SEFOR en marche, session de
  caisse ouverte réelle « CEFOR Isotry », utilisateur temporaire désactivé après coup) :
  - `live_1_liste_decaissements.png` : onglet « Décaissements en attente » alimenté par
    `get_pending_disbursements` — 3 crédits `approved` réels (IS/003363, IS/003362, IS/000289),
    colonnes Client / Dossier / Produit / Montant (`net_disbursed_amount`) / Agence
    (`company_name`).
  - `live_2_liste_echeances.png` : `setCentralTab('echeances')` OK — table « Aucune échéance
    du jour ni en retard » (SEFOR n'a aucun crédit `active`/`defaulted` avec échéance due ou
    en retard ; les impayés de IS/000289, `avis_cdag`, sont bien exclus par le filtre
    `loan_id.state` — anomalie A1 neutralisée).
  - `live_3_epargne_placeholder.png` : onglet « Épargne en attente » → « Cette liste sera
    disponible prochainement. » (aucun RPC).
  - `live_4_recherche.png` : requête « ra » — partie (a) : la liste reste filtrée sur les
    lignes correspondantes ; partie (b) : « Autres clients » liste des clients réels de
    l'agence (RAFALISON Jeranut, RANDRIAMBELOMASINA, …) **sans répéter** ceux déjà dans la
    liste filtrée. Dédoublonnage sur `partner_id` confirmé.
- **Aucun framework de test JS** dans le projet (que des tests Python) — vérification par
  scénario navigateur réel ci-dessus.

### Scénario de test manuel recommandé (à rejouer par Micka)

1. Ouvrir le Guichet avec une session de caisse ouverte : la liste « Décaissements en
   attente » se charge seule (onglet actif par défaut).
2. Cliquer une ligne → le client est sélectionné (panneau comptes/crédits), l'onglet
   d'opération **ne change pas**, le montant reste vide. « ← Retour à la liste » ramène à la
   liste.
3. Onglet « Décaissement crédit » + sélectionner le crédit du client + `Valider` → le crédit
   décaissé **disparaît** de « Décaissements en attente » au rafraîchissement.
4. Depuis « Échéances du jour », cliquer une échéance en retard (ligne rouge clair) →
   sélectionne le client ; onglet « Remboursement crédit » + montant au pavé + `Valider`.
5. Taper 2+ caractères dans la recherche : la liste de l'onglet se filtre en direct ET
   « Autres clients » apparaît avec les clients non listés. Cliquer un « Autre client » le
   sélectionne (utile pour un dépôt épargne d'un client hors des 3 listes).
6. Cas caissier pur (`group_microfinance_cashier` seul) : les 4 opérations aboutissent
   (sudo ciblé du sous-lot 1.1bis).

### Points remontés à Micka (non tranchés dans ce lot)

- La règle SCSS `.o_microfinance_pos__search_results` est devenue morte (dropdown retiré) —
  laissée en place, à nettoyer dans une passe ultérieure si souhaité.
- Repli mobile (colonnes à ~1/3 de hauteur d'écran) : pré-existant, non modifié (sous-lot
  1.3).
- Une base de test CI propre reste à mettre en place pour rejouer l'ensemble des suites
  caisse sans les échecs environnementaux SEFOR (cf. section 1.1).

**Lot 1 terminé (1.1 → 1.4). Aucun commit effectué — relecture et commit par Micka.**
