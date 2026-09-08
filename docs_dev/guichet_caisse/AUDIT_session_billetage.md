# Audit — Session de caisse et billetage

Audit **en lecture seule**. Aucune modification de code, de vue, de données ni de sécurité.
Aucun commit. Les extraits sont recopiés du code, pas reformulés.

Fichiers de référence :
- `microfinance_loan_management/models/microfinance_caisse_session.py` (85 lignes)
- `microfinance_loan_management/models/microfinance_caisse_fiche_journee.py` (250 lignes)
- `microfinance_savings_management/models/microfinance_caisse_mouvement.py`
- `microfinance_loan_management/static/src/js/microfinance_caisse_pos.js`
- `microfinance_loan_management/static/src/xml/microfinance_caisse_pos.xml`
- `microfinance_loan_management/views/microfinance_caisse_session_views.xml`
- `microfinance_loan_management/views/microfinance_caisse_fiche_journee_views.xml`
- `microfinance_loan_management/report/microfinance_caisse_fiche_journee_report.xml`
- `microfinance_loan_management/security/ir.model.access.csv`, `security/groups.xml`
- `microfinance_loan_management/tests/test_caisse_*.py` + `microfinance_savings_management/tests/test_caisse_pos.py`

---

## 1. `microfinance.caisse.session` — état actuel

### 1.1 Champs (`microfinance_caisse_session.py:12-41`)

| Champ | Type | Détail |
|---|---|---|
| `journal_id` | M2o `account.journal` | `required`, `tracking`, `domain="[('type','=','cash'),('company_id','=',company_id)]"` |
| `date` | Date | `required`, `default=fields.Date.context_today`, `tracking` |
| `company_id` | M2o `res.company` | `required`, **`readonly`**, `default=lambda self: self.env.company` |
| `cashier_id` | M2o `res.users` | `required`, `tracking`, `default=lambda self: self.env.user` |
| `currency_id` | M2o (related `company_id.currency_id`) | `readonly` |
| `state` | Selection `draft` / `open` / `closed` | `default='draft'`, `required`, `tracking` |
| `fiche_journee_id` | M2o `microfinance.caisse.fiche.journee` | **`readonly`**, `copy=False` — renseigné par `action_open_session` |
| `opening_balance` | Monetary | **`related='fiche_journee_id.opening_balance'`**, `readonly` |
| `total_debit` | Monetary | **`related='fiche_journee_id.total_debit'`**, `readonly` |
| `total_credit` | Monetary | **`related='fiche_journee_id.total_credit'`**, `readonly` |
| `closing_balance` | Monetary | **`related='fiche_journee_id.closing_balance'`**, `readonly` |
| `mouvement_ids` | O2m `microfinance.caisse.mouvement` | ajouté par `_inherit` dans `microfinance_caisse_mouvement.py:173-176` |

Commentaire du code (`:32-34`) :
> « La session ne porte aucun solde propre : elle alimente microfinance.caisse.fiche.journee
> (1 session = 1 fiche, cf. décisions actées) et se contente de relayer ses montants, plutôt
> que de dupliquer la logique de calcul déjà en place sur la fiche (_refresh_amounts). »

**Aucun montant d'ouverture / fond de caisse saisi.** `opening_balance` est un `related`
lecture seule vers la fiche ; sur la fiche il est `readonly` et écrit uniquement par
`_refresh_amounts()` (voir §2). Il n'existe **aucun champ éditable** de fond de caisse initial,
ni sur la session ni sur la fiche.

### 1.2 Contrainte SQL (`:43-46`)

```python
_sql_constraints = [
    ('journal_date_unique', 'unique(journal_id, date)',
     'Une seule session de caisse par journal et par jour.'),
]
```

Aucun `@api.constrains` Python sur ce modèle. Aucune `ir.rule` propre (seule la règle
multi-société générique s'applique, testée en `test_caisse_security.py:91`).

### 1.3 `action_open_session` — corps intégral (`:48-71`)

```python
def action_open_session(self):
    for session in self:
        if session.state == 'open':
            continue
        if session.state == 'closed':
            raise UserError(_('Cette session est déjà clôturée.'))
        fiche = self.env['microfinance.caisse.fiche.journee'].search([
            ('journal_id', '=', session.journal_id.id),
            ('date', '=', session.date),
        ], limit=1)
        if fiche and fiche.state == 'closed':
            raise UserError(_(
                "La fiche journalière du %(date)s pour le journal « %(journal)s » est déjà "
                "clôturée. Un manager doit la rouvrir (motif requis) avant d'ouvrir une "
                "nouvelle session sur ce journal pour ce jour."
            ) % {'date': session.date, 'journal': session.journal_id.name})
        if not fiche:
            fiche = self.env['microfinance.caisse.fiche.journee'].create({
                'journal_id': session.journal_id.id,
                'date': session.date,
                'company_id': session.company_id.id,
            })
        session.write({'fiche_journee_id': fiche.id, 'state': 'open'})
        session.message_post(body=_('Session ouverte par %s.') % session.cashier_id.name)
```

- Idempotent si `state == 'open'` ; refus si `state == 'closed'` (pas de ré-ouverture, cf.
  `test_reopening_closed_session_blocked`).
- Réutilise la fiche `(journal, date)` si elle existe et n'est pas clôturée ; sinon la crée.
- **Aucune saisie, aucun comptage, aucun contrôle de solde à l'ouverture.**

### 1.4 `action_close_session` — corps intégral (`:73-84`)

```python
def action_close_session(self):
    for session in self:
        if session.state != 'open':
            raise UserError(_('Seule une session ouverte peut être clôturée.'))
        # Ne redéclenche aucun contrôle ici : action_close_day() porte déjà la
        # séquentialité chronologique et la vérification d'écart de solde. Une erreur levée
        # ici doit remonter telle quelle à l'utilisateur, sans quoi state='closed' n'est
        # jamais écrit — la session reste 'open' tant que la fiche n'est pas réellement
        # clôturée.
        session.fiche_journee_id.action_close_day()
        session.write({'state': 'closed'})
        session.message_post(body=_('Session clôturée par %s.') % self.env.user.name)
```

- Seul contrôle propre : `state == 'open'`.
- **Toute la clôture est déléguée à `fiche.action_close_day()`** (§2.3). Si celle-ci lève,
  `state='closed'` n'est jamais écrit — la session reste `open` (couvert par
  `test_close_session_fails_on_balance_variance_and_leaves_session_open`).
- **Aucun montant saisi, aucun comptage, aucun paramètre.** La méthode ne prend rien en
  entrée.

### 1.5 Contrôle de solde existant à la fermeture — OUI, mais théorique vs comptable

La fermeture **fait déjà un contrôle d'écart**, mais **pas** un contrôle « théorique vs
comptage physique ». `fiche.action_close_day()` (`microfinance_caisse_fiche_journee.py:180-188`) :

```python
fiche._refresh_amounts()
account = fiche.journal_id.default_account_id
real_balance = fiche._get_account_balance_as_of(account, fiche.date) if account else fiche.closing_balance
if abs(real_balance - fiche.closing_balance) > 0.01:
    raise UserError(_(
        'Écart détecté : le solde de clôture calculé (%(calc).2f) ne correspond pas '
        'au solde comptable réel du journal à cette date (%(real).2f). Clôture '
        'refusée tant que cet écart persiste.'
    ) % {'calc': fiche.closing_balance, 'real': real_balance})
```

- Compare l'**instantané figé** `closing_balance` (recalculé juste avant par
  `_refresh_amounts()`) au **solde comptable réel** du compte du journal
  (`sum(debit) - sum(credit)` des `account.move.line` postées `date <= fiche.date`).
- En workflow normal les deux sont égaux (le refresh vient de les aligner) : cet écart ne se
  déclenche que sur une dérive hors workflow, ex. écriture directe sur `closing_balance`
  (cf. `test_close_day_detects_variance_against_real_balance`).
- **Un montant unique, pas de ventilation par coupure. Aucun rapprochement à un comptage
  physique saisi par le caissier — cette notion n'existe nulle part.**

### 1.6 `microfinance.caisse.fiche.journee` — rôle et relation à la session

| Point | Constat |
|---|---|
| **Qui porte les soldes** | La **fiche**. `opening_balance`, `total_debit`, `total_credit`, `closing_balance` sont des `fields.Monetary(readonly=True, copy=False)` **stockés, non `compute=`** (`microfinance_caisse_fiche_journee.py:41-54`), écrits une fois par `_refresh_amounts()`. La session ne fait que les exposer en `related`. |
| **Cardinalité** | « 1 session = 1 fiche » (commentaire `session.py:33`). Mais **la fiche peut vivre sans session** : `action_quick_close_today` (`fiche_journee.py:192-214`) et les tests créent des fiches directement. Contrainte identique des deux côtés : `unique(journal_id, date)`. Donc au plus 1 fiche et 1 session par `(journal, jour)`, et la session pointe vers la fiche de son `(journal, date)`. |
| **Solde affiché en en-tête du guichet** | `state.session.closing_balance` (voir §2), c.-à-d. le `related` vers `fiche.closing_balance`. |
| **`state`** | `open` / `closed`, `default='open'` (`:24-27`). Verrou dur : `AccountMove.action_post()` est surchargé (`:230-249`) pour **refuser toute écriture** sur un `(journal, date)` dont la fiche est `closed`. |
| **`reopen_reason`** | `Char`, requis avant `action_reopen_day` (manager only). |
| **`is_stale`** | `compute='_compute_is_stale'` **non stocké** (`:55-61`, `:151-158`) : vrai si `state == 'open'` et `|solde comptable réel à la date − closing_balance figé| > 0.01`. Affiché en alerte sur le formulaire fiche (`views/...fiche_journee_views.xml:35-37`) mais **pas lu par le guichet OWL** (`microfinance_caisse_pos.js` ne charge pas ce champ). |

Autres méthodes de la fiche :
- `action_refresh()` (`:74-81`) — refus si `closed` ; sinon `_refresh_amounts()`.
- `action_close_day()` (`:160-190`) — clôture réelle, détaillée §2.3.
- `action_quick_close_today()` (`@api.model`, `:192-214`) — action serveur de liste, ne
  fonctionne que s'il existe **exactement un** journal `cash` pour `self.env.company`.
- `action_reopen_day()` (`:216-227`) — `AccessError` si pas
  `group_microfinance_manager` ; `UserError` si `reopen_reason` vide ; repasse `state='open'`,
  efface le motif, `message_post`.

---

## 2. Calcul du solde théorique de session

### 2.1 D'où vient « Solde caisse » dans l'en-tête du guichet

`static/src/xml/microfinance_caisse_pos.xml:23-26` :
```xml
<div class="o_microfinance_pos__header_balance">
    <span>Solde caisse : </span>
    <strong t-esc="formatMoney(state.session.closing_balance)"/>
</div>
```

`state.session` est peuplé par `loadSession()` (`microfinance_caisse_pos.js:70-89`) :
```js
const sessions = await this.orm.searchRead(
    "microfinance.caisse.session",
    [["state", "=", "open"], ["company_id", "=", this.company.currentCompany.id]],
    ["id", "journal_id", "cashier_id", "date", "company_id", "currency_id",
     "opening_balance", "total_debit", "total_credit", "closing_balance"],
    { order: "date desc", limit: 1 }
);
```

Donc **`closing_balance` = `related` vers `fiche_journee_id.closing_balance`** = l'instantané
figé de la fiche. **Ce n'est ni un `compute` sur la session, ni le solde courant live du
`account.journal`, ni une agrégation des `mouvement_ids`** — c'est la valeur écrite au dernier
`_refresh_amounts()` de la fiche.

Le guichet ne rafraîchit ce nombre qu'en **rechargeant la session** (`loadSession()` rappelé
après chaque opération validée, `microfinance_caisse_pos.js:482` / `:485`). Il n'appelle
jamais `action_refresh()` sur la fiche : entre deux `_refresh_amounts()` (création de la fiche,
`action_refresh` manuel backend, ou `action_close_day`), le nombre affiché peut être périmé si
des écritures sont postées entre-temps (`is_stale` le signalerait côté backend, pas côté
guichet).

### 2.2 Formule `_refresh_amounts()` (`microfinance_caisse_fiche_journee.py:92-126`)

```python
account = journal.default_account_id
# opening_balance :
previous_fiche = self.search([
    ('journal_id', '=', journal.id),
    ('date', '<', fiche.date),
    ('state', '=', 'closed'),
], order='date desc', limit=1)
if previous_fiche:
    opening_balance = previous_fiche.closing_balance
else:
    opening_balance = fiche._get_account_balance_before(account, fiche.date)  # Σ(debit-credit) AML postées date <
lines = account.move.line WHERE account_id = account AND date = fiche.date AND parent_state = 'posted'
total_debit  = sum(lines.debit)
total_credit = sum(lines.credit)
closing_balance = opening_balance + total_debit - total_credit
```

- **Base = `journal_id.default_account_id`** (le compte de trésorerie du journal de caisse),
  écritures **postées uniquement**, à la **date exacte** de la fiche.
- `opening_balance` s'enchaîne sur le `closing_balance` de la **dernière fiche clôturée**
  antérieure du même journal ; à défaut, repli sur le solde comptable réel du compte avant la
  date (couvert par `test_opening_balance_falls_back_to_account_balance_before_date`,
  `test_opening_balance_chains_from_previous_closed_fiche`,
  `test_open_previous_fiche_not_used_as_opening_reference`).

### 2.3 `action_close_day()` — séquence complète (`:160-190`)

1. `continue` si `state == 'closed'`.
2. **Séquentialité** : s'il existe une fiche du **même journal**, `date <`, `state == 'open'`
   → `UserError` (« Les journées doivent être clôturées dans l'ordre chronologique »).
   L'**absence** de fiche pour la veille ne bloque pas (`test_close_day_allowed_when_no_fiche_at_all_for_previous_day`).
3. `_refresh_amounts()` (réaligne l'instantané).
4. `real_balance = _get_account_balance_as_of(account, date)` (Σ debit−credit des AML postées
   `date <= fiche.date`).
5. Si `|real_balance − closing_balance| > 0.01` → `UserError` « Écart détecté … » (voir §1.5).
6. `write({'state': 'closed'})` + `message_post`.

**Aucune de ces étapes ne prend, ne stocke, ni ne compare un comptage physique / une
ventilation par coupure.** Le seul « écart » est calculé-figé vs comptable-réel.

### 2.4 Le fond de caisse d'ouverture est-il inclus ?

Indirectement seulement : `opening_balance` = solde comptable du compte du journal (via
chaînage ou repli). Si un fond de caisse physique a été déposé, il n'apparaît que s'il a fait
l'objet d'une **écriture comptable** sur ce compte. **Il n'existe aucun champ « montant
d'ouverture » saisi** : ni sur `microfinance.caisse.session` (`opening_balance` y est un
`related` readonly), ni sur `microfinance.caisse.fiche.journee` (`readonly`, écrit seulement
par `_refresh_amounts()`). Confirmé : l'ouverture de session ne porte **aujourd'hui aucun
montant initial saisi** (`action_open_session`, §1.3, n'en demande aucun).

---

## 3. Concept de billetage existant — absence confirmée

Recherche `grep -rin "billet\|coupure\|denomination\|comptage\|cashbox\|cash_count"` sur
`microfinance_loan_management` + `microfinance_savings_management` :

| Résultat | Nature |
|---|---|
| `report/report_contrat_credit.xml:90,276` : « anti-coupure », « coupure est reportee au niveau des lignes tr » | CSS `page-break` du contrat de crédit — **sans rapport** avec le billetage de caisse. |
| *(aucun autre)* | — |

Aucun mécanisme de comptage par coupure/pièce, aucun modèle de dénominations, aucun champ de
type `account.cashbox.line` dans les deux modules, ni dans `microfinance_mowgli_assistant` ni
`microfinance_data_reset_wizard`.

Dépôts voisins de l'`addons_path` (`/opt/odoo17/eat_git`, `packimmo_git`, `cuf_git`,
`custom`) : **aucun module de billetage / caisse générique** réutilisable. **Pas de dépôt
MIIA** présent sur cette machine. `base_accounting_kit` (dépendance de
`microfinance_loan_management`) : aucun `cashbox` / `billet`.

Odoo core `point_of_sale` possède bien un contrôle d'espèces (ouverture/fermeture avec
comptage, `pos.session` + `account.bank.statement`), **mais `point_of_sale` n'est pas une
dépendance** de ces modules — `microfinance_loan_management` dépend de `['base', 'mail',
'account', 'base_vat', 'contacts', 'hr', 'calendar', 'base_accounting_kit']`. Aucun modèle
core de type `account.cashbox.line` n'est référencé dans le projet.

**Conclusion : aucun billetage existant, rien à réutiliser tel quel dans le dépôt.**

---

## 4. Multi-session / concurrence

### 4.1 Combien de sessions ouvertes simultanément

- **Seule barrière : `unique(journal_id, date)`** (SQL, sur la session ET la fiche). Aucun
  `@api.constrains`, aucune règle liant `cashier_id`.
- Conséquence : une agence ayant **N journaux de caisse** (`type='cash'`) peut avoir **N
  sessions ouvertes le même jour** (une par journal). Plusieurs caissiers, chacun sur son
  journal → plusieurs sessions concurrentes ouvertes dans la même société, **autorisé**.
- Deux caissiers sur le **même** journal le même jour : le `create` de la 2ᵉ session est
  rejeté par la contrainte SQL (`test_unique_journal_date_constraint`).
- `cashier_id` : `default=self.env.user`, `tracking`, **mais dans aucune contrainte ni
  règle** → purement informatif. Rien n'empêche un utilisateur d'ouvrir une session au nom
  d'un autre caissier, ni de détenir plusieurs sessions.

### 4.2 Clôturer une session avec des mouvements en cours / incohérents

- `action_close_session` **ne regarde pas** `mouvement_ids` : ni leur nombre, ni leur état,
  ni la cohérence des `account.move` sous-jacents. Elle délègue à `action_close_day()`.
- `action_close_day()` ne contrôle que (a) l'ordre chronologique des fiches et (b)
  `closing_balance` figé vs solde comptable réel (tolérance `0.01`). Un mouvement guichet dont
  l'écriture aurait échoué à être postée ne figurerait tout simplement pas dans la somme des
  AML ; les lignes `microfinance.caisse.mouvement` elles-mêmes ne sont jamais validées à la
  clôture.
- **Aucun verrou concurrentiel** : ni `action_close_session` ni `action_close_day` ne font de
  `SELECT ... FOR UPDATE` / `invalidate_recordset` (à comparer avec `action_charge_fee` qui,
  lui, pose un verrou pessimiste — cf. `AUDIT_frais.md §4`, `AUDIT_decaissement.md §4`). Deux
  clôtures concurrentes de la même session/fiche exécutent toutes deux
  `_refresh_amounts()` + comparaison + `write(state='closed')` ; en `READ COMMITTED` rien ne
  les sérialise. Fenêtre étroite aujourd'hui (un seul bouton backend, pas d'appel guichet).
- Verrou dur **après** clôture : `AccountMove.action_post()` surchargé refuse toute écriture
  sur un `(journal, date)` clôturé (`fiche_journee.py:230-249` ;
  `test_post_move_blocked_on_closed_day`, `test_post_move_allowed_after_reopen`,
  `test_post_move_unaffected_on_other_journal`).

---

## 5. Sécurité / accès à la clôture

### 5.1 `ir.model.access.csv` (`:122-131`)

| Modèle | `group_microfinance_cashier` | `manager` | `finance` / `comptable` / `auditor` |
|---|---|---|---|
| `microfinance.caisse.fiche.journee` | R **W C** (pas unlink) | R W C **D** | R seul |
| `microfinance.caisse.session` | R **W C** (pas unlink) | R W C **D** | R seul |

### 5.2 Groupes (`security/groups.xml`)

- `group_microfinance_cashier` (`:35-39`) : `implied_ids = [group_microfinance_user]`
  uniquement — **n'implique pas** `manager`.
- `group_microfinance_manager` (`:12-16`) : `implied_ids = [group_microfinance_user]`.

### 5.3 Qui peut clôturer aujourd'hui

- **`action_close_session`** : aucune restriction de groupe dans la méthode ; le bouton
  `microfinance_caisse_session_views.xml:25` n'a **pas** de `groups=`. → tout utilisateur
  ayant le droit **write** sur `microfinance.caisse.session`, c.-à-d. **le caissier seul
  suffit** (ou le manager).
- **`action_close_day`** (fiche) : idem, bouton `...fiche_journee_views.xml:27` sans
  `groups=` → caissier suffit.
- **`action_quick_close_today`** (action serveur de liste, `...fiche_journee_views.xml:94-101`)
  : sans `groups=` → caissier peut la lancer.
- **`action_reopen_day`** : `groups="microfinance_loan_management.group_microfinance_manager"`
  sur le bouton **ET** `has_group(...manager)` vérifié dans la méthode → `AccessError` sinon
  (`test_reopen_requires_manager_group`).

**Cohérent avec la décision « pas de validation manager requise » : le caissier peut clôturer
seul aujourd'hui. Seule la réouverture est réservée au manager (motif requis).**

### 5.4 Cloisonnement multi-société

`company_id` `readonly`, `default=self.env.company`. Isolation testée
(`test_caisse_security.py:91` `test_company_isolation`) sur la fiche. `_run_posting_sudo`
(`microfinance_caisse_mouvement.py:57-82`) re-vérifie l'appartenance agence des
enregistrements comptabilisés au guichet.

---

## 6. Tests existants (base de non-régression)

### 6.1 `microfinance_loan_management/tests/`

| Fichier / classe | Tests | Couverture |
|---|---|---|
| `test_caisse_session.py` — `TestCaisseSession` | `test_unique_journal_date_constraint`, `test_open_session_creates_fiche_and_links`, `test_open_session_reuses_existing_open_fiche`, `test_open_session_blocked_if_fiche_already_closed`, `test_close_session_closes_linked_fiche`, `test_close_session_requires_open_state`, `test_close_session_fails_on_balance_variance_and_leaves_session_open`, `test_reopening_closed_session_blocked` | Contrainte unique ; `action_open_session` (création/réutilisation/blocage fiche close) ; `action_close_session` délègue à `action_close_day` ; propagation de l'échec (`state` reste `open`) ; pas de ré-ouverture. |
| `test_caisse_cloture.py` — `TestCaisseCloture` | `test_close_day_succeeds_with_no_previous_fiche`, `test_close_day_blocked_if_previous_day_still_open`, `test_close_day_allowed_once_previous_day_closed`, `test_close_day_allowed_when_no_fiche_at_all_for_previous_day`, `test_close_day_detects_variance_against_real_balance`, `test_reopen_requires_manager_group`, `test_reopen_requires_reason`, `test_reopen_succeeds_with_reason_and_clears_it`, `test_post_move_blocked_on_closed_day`, `test_post_move_allowed_after_reopen`, `test_post_move_unaffected_on_other_journal` | Séquentialité chronologique ; détection d'écart calculé vs comptable-réel ; réouverture manager+motif ; verrou dur `AccountMove.action_post` post-clôture (scopé au journal). Helpers `_post_move`, `_make_manager`. |
| `test_caisse_fiche_journee.py` — `TestCaisseFicheJournee` | `test_opening_balance_falls_back_to_account_balance_before_date`, `test_totals_and_closing_balance`, `test_opening_balance_chains_from_previous_closed_fiche`, `test_open_previous_fiche_not_used_as_opening_reference`, `test_unique_constraint_journal_date`, `test_no_moves_gives_zero_totals_and_same_opening_closing`, `test_snapshot_frozen_until_explicit_refresh`, `test_refresh_blocked_once_closed` | Formule `_refresh_amounts` ; chaînage du solde d'ouverture ; instantané figé (pas de `compute` réactif) ; `action_refresh` interdit après clôture. |
| `test_caisse_fiche_journee_report.py` — `TestCaisseFicheJourneeReport` | `test_report_renders_with_movements`, `test_report_renders_with_no_movements` | Rendu QWeb de la fiche imprimable (Lot 5). |
| `test_caisse_security.py` — `TestCaisseFicheJourneeSecurity` | `test_cashier_can_create_read_write_not_unlink`, `test_manager_full_crud`, `test_finance_read_only`, `test_comptable_read_only`, `test_auditor_read_only`, `test_collection_agent_no_access`, `test_plain_user_no_access`, `test_company_isolation` | ACL + isolation multi-société **de `microfinance.caisse.fiche.journee` uniquement**. |

### 6.2 `microfinance_savings_management/tests/test_caisse_pos.py`

- `_open_session(journal)` (`:92-96`, `:280-284`) : `create` + `action_open_session()`.
  Aucun helper de **clôture** de session.
- Scénarios `register_operation` bout-en-bout (dépôt/retrait épargne, remboursement,
  décaissement, frais) y compris en « caissier pur » (`_pure_cashier`) ; garde « session
  ouverte » (`test_register_blocked_without_open_session`, `:163`).
- `test_pure_cashier_decaissement_credit` (`:369-389`) illustre le découplage :
  `loan.action_activate()` avant `register_operation(... 'decaissement_credit' ...)`.

### 6.3 Ce qui n'est PAS couvert

- **Aucun test de sécurité sur `microfinance.caisse.session`** (seule la fiche est testée en
  `test_caisse_security.py`).
- Aucun test de **concurrence** sur `action_close_session` / `action_close_day` (pas de
  verrou à tester).
- **Aucun comptage physique / billetage / ventilation par coupure** — la fonctionnalité
  n'existe pas.
- Aucun test de `action_close_session` avec un montant saisi (la méthode n'accepte aucun
  paramètre).
- `action_quick_close_today` : pas de test dédié (chemin action serveur de liste).

---

## 7. Questions bloquantes pour l'implémentation

1. **Modèle porteur du comptage.** `action_close_session` (session) délègue tout à
   `action_close_day` (fiche). Le comptage de coupures + le commentaire obligatoire
   vivent-ils sur `microfinance.caisse.session`, sur `microfinance.caisse.fiche.journee`, ou
   sur un modèle de lignes dédié (`...denomination.line`) rattaché à l'un des deux ? La fiche
   peut être clôturée **sans session** (`action_quick_close_today`, backend direct) — le
   comptage doit-il alors être exigé aussi, ou uniquement sur le chemin session/guichet ?

2. **Deux notions d'« écart » sur la même clôture.** `action_close_day` lève **déjà** un
   `UserError` bloquant si `closing_balance` figé ≠ solde comptable réel (tolérance `0.01`,
   `fiche_journee.py:183-188`). Le nouvel écart « comptage physique vs solde théorique » doit,
   lui, **ne pas bloquer** (clôture possible avec commentaire obligatoire). Comment les deux
   cohabitent : le contrôle existant reste-t-il bloquant ? Le comptage se compare-t-il à
   `closing_balance` (instantané figé) ou au solde comptable réel live
   (`_get_account_balance_as_of`) — normalement égaux après `_refresh_amounts`, mais le
   nombre affiché au guichet peut être périmé (`is_stale` non lu côté OWL) ?

3. **Référence du « solde théorique » comparé au comptage.** `closing_balance` =
   `opening_balance + total_debit - total_credit`, calculé sur le **compte du journal**, toutes
   écritures postées de la date confondues (pas seulement les mouvements guichet). Le comptage
   se rapproche-t-il de ce solde comptable complet, ou seulement du cumul des
   `mouvement_ids` de la session ? Les deux diffèrent si des écritures hors guichet touchent
   le compte du journal le même jour.

4. **Fond de caisse d'ouverture.** Aujourd'hui **aucun montant d'ouverture n'est saisi**
   (`opening_balance` = dérivé du comptable). Décision actée : pas de comptage à l'ouverture.
   Le comptage de clôture est alors comparé à un théorique dont la base d'ouverture n'a
   jamais été vérifiée physiquement — est-ce accepté, ou faut-il au moins un montant
   d'ouverture saisi comme point de départ ?

5. **Stockage et traçabilité du commentaire obligatoire.** Champ `Text`/`Char` +
   `message_post` (comme `reopen_reason`) ? Sur quel modèle ? Visible où (formulaire manager,
   rapport imprimable `microfinance_caisse_fiche_journee_report.xml`) ? Obligatoire
   **uniquement si écart**, ou toujours ?

6. **Liste des dénominations (MGA).** Aucun modèle de valeurs de coupures/pièces n'existe. À
   définir : table de configuration (`ir.model` dédié, données `data/`) ou liste figée dans le
   code ? Par société (devise) ?

7. **Granularité du comptage.** Un comptage par **session** = par **journal de caisse**.
   Confirmer : un comptage par `(journal, jour)`, indépendant s'il y a plusieurs caissiers /
   journaux dans l'agence (§4.1) ?

8. **Verrou concurrentiel.** `action_close_session` / `action_close_day` n'ont **aucun**
   `SELECT ... FOR UPDATE` (contrairement à `action_charge_fee`). Si la clôture avec comptage
   devient accessible depuis le guichet OWL (aujourd'hui le JS n'appelle jamais
   `action_close_session`), faut-il ajouter un verrou ? Où (méthode session ou méthode
   fiche) ?

9. **Emplacement de l'écran de comptage.** La clôture se fait aujourd'hui **uniquement** via
   les boutons des formulaires backend (`session` et `fiche`). Le comptage se saisit-il dans
   le guichet OWL (`microfinance_caisse_pos`), qui devrait alors gagner un chemin d'appel
   `action_close_session`, ou reste-t-il dans le formulaire backend `session` ?

10. **Sécurité `microfinance.caisse.session`.** Le modèle n'a **ni `@api.constrains`, ni test
    de sécurité, ni `groups=` sur le bouton de clôture** : le caissier clôture seul (conforme
    à la décision). Confirmer que la clôture avec comptage reste caissier-seul (aucun visa
    manager), et décider s'il faut ajouter des tests de sécurité sur ce modèle à cette
    occasion.

11. **Réouverture après comptage.** `action_reopen_day` (manager + motif) remet la fiche en
    `open`. Que devient le comptage déjà enregistré si la journée est rouverte puis
    re-clôturée : nouveau comptage exigé, historisation des comptages successifs, écrasement ?

12. **Rapport imprimable.** `microfinance_caisse_fiche_journee_report.xml` affiche
    aujourd'hui solde d'ouverture / mouvements / totaux / solde de clôture + zone de
    signatures. Le détail du billetage (par coupure) et le commentaire d'écart doivent-ils y
    figurer ?

---

*Audit réalisé le 2026-09-07. Lecture seule — aucune modification de code, de vue, de données
ou de sécurité, aucun commit.*
