# Audit — Anomalies guichet caisse du 2026-09-21 (Ampitatafika / Ambanidia)

Audit en lecture seule. Aucune modification de code, aucun correctif appliqué. Vérifications
faites en lecture directe sur la base `MOWGLI` (sessions encore ouvertes, non clôturées, telles
que constatées le 2026-09-26) en complément de la lecture du code. Toutes les références de
ligne sont prises sur l'état actuel de la branche (non commité inclus).

## Résumé des verdicts

| Symptôme | Agence | Verdict |
|---|---|---|
| 1 — remboursement absent du solde caisse | Ampitatafika (SY, company_id=3) | **Bug transverse** — chemin de saisie hors session de caisse, ouvert à toutes les agences |
| 2 — ticket de session vidé, solde figé | Ambanidia (BD, company_id=2) | **Bug transverse** — garde manquante contre les sessions multiples ouvertes sur un même journal, exploitable dans toutes les agences |

Aucun des deux symptômes n'est spécifique à la configuration d'une agence (journal, compte,
`disbursement_journal_ids`, etc.) : les deux tiennent à des trous structurels du modèle
`microfinance.caisse.session` / `microfinance.caisse.mouvement`, présents identiquement pour
toutes les sociétés provisionnées.

---

## Symptôme 1 — Ampitatafika : remboursement non reflété dans le solde caisse

### Ce qui A été vérifié et écarté

L'hypothèse de départ (même classe de bug que les frais de dossier, cf.
`_get_session_moves()` [microfinance_caisse_session.py:88-123](../../microfinance_loan_management/models/microfinance_caisse_session.py#L88-L123)
et son commentaire `AUDIT_solde_caisse_frais_dossier`) ne se vérifie **pas** ici :

- `register_operation()` (branche `remboursement_credit`,
  [microfinance_caisse_mouvement.py:120-123](../../microfinance_savings_management/models/microfinance_caisse_mouvement.py#L120-L123))
  et `register_repayment_confirmed()`
  ([microfinance_caisse_mouvement.py:288-292](../../microfinance_savings_management/models/microfinance_caisse_mouvement.py#L288-L292))
  écrivent tous les deux explicitement `'journal_id': session.journal_id.id` sur le
  `microfinance.loan.payment` créé — **avant** `action_post()`.
- `microfinance.loan.payment.action_post()` pose la ligne de trésorerie sur
  `self.journal_id.default_account_id`
  ([microfinance_loan_payment.py:170-175](../../microfinance_loan_management/models/microfinance_loan_payment.py#L170-L175)) —
  c'est-à-dire, quand le remboursement passe par le guichet, **le même compte** que celui filtré
  par `_compute_theoretical_balance()`
  ([microfinance_caisse_session.py:125-145](../../microfinance_loan_management/models/microfinance_caisse_session.py#L125-L145)).
  Le `journal_id` du formulaire (`domain="[('type','in',('bank','cash'))]"`,
  [microfinance_loan_payment.py:37-40](../../microfinance_loan_management/models/microfinance_loan_payment.py#L37-L40))
  n'a d'effet que si le champ est réellement modifié après création ; via le guichet, il ne
  l'est jamais.
- Le seul `@api.onchange('loan_id')` qui pourrait re-suggérer un `product_id.payment_journal_id`
  différent ([microfinance_loan_payment.py:81-90](../../microfinance_loan_management/models/microfinance_loan_payment.py#L81-L90))
  ne s'exécute **pas** lors d'un `create()` par RPC (`register_operation`/
  `register_repayment_confirmed` appellent `.create({...})` directement, pas de passage par
  formulaire) : aucun risque d'écrasement silencieux du `journal_id` passé.

**Conclusion partielle : quand un remboursement est saisi via le guichet OWL (les deux chemins
`register_operation` et `register_repayment_confirmed`), le compte de l'écriture correspond
toujours au compte filtré par le calcul de solde. Ce n'est pas la cause du symptôme.**

### Preuve base : aucun mouvement de remboursement pour Ampitatafika le 2026-09-21

```sql
-- Session ouverte Ampitatafika (company_id=3), le 2026-09-21
select id, company_id, journal_id, state from microfinance_caisse_session
where date='2026-09-21' and state='open';
--  428 | 3 | 1525 (Caisse, compte 6463) | open

-- Mouvements de cette session
select id, type, amount, loan_id, payment_id from microfinance_caisse_mouvement
where session_id = 428;
--  134 | depot_epargne  | 50000
--  135 | depot_epargne  | 20000
--  211 | frais_dossier  | 15000
--  212 | depot_epargne  |  5000
-- (AUCUN remboursement_credit)

-- Recherche large : aucun microfinance.loan.payment n'existe pour company_id=3, jamais.
select count(*) from microfinance_loan_payment where company_id = 3;  -- 0
```

Il n'existe **aucun enregistrement `microfinance.loan.payment`** pour Ampitatafika — ni ce
jour-là, ni à aucune date. Le remboursement décrit n'a donc pas pu passer par
`register_operation`/`register_repayment_confirmed` (qui créent systématiquement ce modèle) :
il a nécessairement été saisi par un **autre chemin**, hors guichet et hors session de caisse.

### Le chemin hors guichet identifié

Le formulaire "Crédit" (back-office, pas le guichet OWL) porte un bouton d'action directe :

```xml
<!-- microfinance_loan_views.xml:78 -->
<button name="action_open_payment_wizard" string="Enregistrer remboursement" type="object"
        class="btn-primary" invisible="state not in ('active','defaulted')"/>
```

[microfinance_loan_views.xml:71-79](../../microfinance_loan_management/views/microfinance_loan_views.xml#L71-L79)
montre que **tous les autres boutons de ce header portent un `groups="..."` restrictif**
(comité, manager, finance) — celui-ci est le seul bouton d'état sans aucune restriction de
groupe, visible par tout utilisateur ayant accès à la fiche crédit.

`action_open_payment_wizard()`
([microfinance_loan.py:3278-3283](../../microfinance_loan_management/models/microfinance_loan.py#L3278-L3283))
ouvre `microfinance.loan.payment.wizard`
([microfinance_loan_payment_wizard.py:8-51](../../microfinance_loan_management/wizard/microfinance_loan_payment_wizard.py#L8-L51)) :

- `action_create_payment()` crée directement un `microfinance.loan.payment` et appelle
  `action_post()` — **sans jamais passer par `microfinance.caisse.mouvement`**, sans
  `session_id`, sans aucune vérification qu'une session de caisse soit seulement ouverte.
- Droits d'accès : `access_microfinance_payment_wizard` est accordé au groupe
  `group_microfinance_user`
  ([ir.model.access.csv:52](../../microfinance_loan_management/security/ir.model.access.csv#L52)),
  et `group_microfinance_cashier` **implique** `group_microfinance_user`
  ([groups.xml:35-38](../../microfinance_loan_management/security/groups.xml#L35-L38)) : un
  caissier a donc bien les droits d'utiliser ce bouton.

Un remboursement saisi par ce chemin :
- crée bel et bien un `account.move` posté (« le mouvement comptable semble bien créé » —
  confirmé par le code, ce n'est pas une impression) ;
- **n'est jamais tracé** dans `microfinance.caisse.mouvement`, donc invisible pour
  `_get_session_moves()`/`_compute_theoretical_balance()`, qui ne parcourent que
  `session.mouvement_ids` — peu importe le compte comptable utilisé.

### Verdict Symptôme 1 : bug transverse

Rien dans ce chemin ne dépend de l'agence : le bouton, l'absence de `groups`, l'absence de lien
vers une session de caisse et les droits `group_microfinance_user` sont identiques pour les
5 agences provisionnées (`REGISTRE_configuration_agence.md`). Toute agence est exposée dès
qu'un utilisateur avec accès à la fiche crédit (caissier compris) utilise "Enregistrer
remboursement" sur la fiche au lieu du guichet OWL. Le fait que ce soit apparu à Ampitatafika en
premier est une coïncidence d'usage, pas une particularité de configuration de cette agence.

---

## Symptôme 2 — Ambanidia : ticket de session vidé, solde figé à 227 000 MGA

### Preuve base : deux sessions `open` simultanées sur le même journal

```sql
select id, journal_id, date, state, create_date, write_date
from microfinance_caisse_session where company_id = 2 order by date desc limit 5;

--  427 | 1509 | 2026-09-21 | open   | 2026-09-21 08:26:11 | 2026-09-21 08:26:12
--  426 | 1509 | 2026-09-19 | open   | 2026-09-19 02:47:02 | 2026-09-19 02:47:02   <- jamais close
--  425 | 1509 | 2026-09-18 | closed | ...
```

La session 426 (ouverte le 2026-09-19) n'a **jamais été clôturée**. Une seconde session (427,
2026-09-21) a ensuite été ouverte sur le **même journal** (1509 = Caisse Ambanidia) pendant que
426 était encore à l'état `open`. La contrainte SQL existante ne l'empêche pas :

```python
# microfinance_caisse_session.py:64-67
_sql_constraints = [
    ('journal_date_unique', 'unique(journal_id, date)',
     'Une seule session de caisse par journal et par jour.'),
]
```

Cette contrainte porte sur `(journal_id, date)`, pas sur `(journal_id, state='open')` : elle
empêche deux sessions pour le *même jour*, mais ne dit rien sur deux dates différentes toutes
deux à l'état `open`. `action_open_session()`
([microfinance_caisse_session.py:147-170](../../microfinance_loan_management/models/microfinance_caisse_session.py#L147-L170))
et le wizard d'ouverture
([microfinance_caisse_open_session_wizard.py:31-46](../../microfinance_loan_management/wizard/microfinance_caisse_open_session_wizard.py#L31-L46))
ne vérifient que la fiche journalière *de la date demandée* — aucun des deux ne recherche
d'autres `microfinance.caisse.session` encore ouvertes sur le même `journal_id`.

### Ce que ça explique côté guichet OWL

`loadSession()` ([microfinance_caisse_pos.js:102-121](../../microfinance_loan_management/static/src/js/microfinance_caisse_pos.js#L102-L121))
sélectionne la session affichée par :

```js
const sessions = await this.orm.searchRead(
    "microfinance.caisse.session",
    [["state", "=", "open"], ["company_id", "=", this.company.currentCompany.id]],
    [...], { order: "date desc", limit: 1 }
);
```

— appelé au montage du composant, **et de nouveau après chaque opération validée**
(`submitOperation()` → `this.loadSession()`,
[microfinance_caisse_pos.js:657-663](../../microfinance_loan_management/static/src/js/microfinance_caisse_pos.js#L657-L663)).
Tant que 426 était la seule session ouverte, ce filtre la sélectionnait sans ambiguïté. Dès que
427 existe *aussi* à l'état `open`, ce même filtre bascule silencieusement, à chaque rechargement,
sur la session **la plus récente par date (427)** — sans avertissement, sans que l'écran ne
signale un changement de session en cours d'utilisation.

`loadMouvements()` ([microfinance_caisse_pos.js:155-165](../../microfinance_loan_management/static/src/js/microfinance_caisse_pos.js#L155-L165))
filtre strictement sur `session_id = this.state.session.id` — donc sur la session que
`loadSession()` vient de sélectionner, pas nécessairement celle sur laquelle portaient les
opérations précédentes du poste.

### Preuve base : le solde affiché est celui, figé, de l'ouverture — pas un solde qui "s'incrémente"

```sql
select id, session_id, type, amount, create_date from microfinance_caisse_mouvement
where session_id in (426, 427);
--  132 | 426 | remboursement_credit | 76.92    | 2026-09-19 02:49:21
--  133 | 426 | depot_epargne        | 49923.08 | 2026-09-19 02:49:21
-- (rien pour la session 427 : 0 ligne)

select id, date, state, opening_balance, closing_balance
from microfinance_caisse_fiche_journee where journal_id = 1509 order by date desc limit 3;
--  495 | 2026-09-21 | open | 227000.00 | 227000.00   <- fiche de la session 427
--  494 | 2026-09-19 | open | 227000.00 | 227000.00   <- fiche de la session 426
--  493 | 2026-09-18 | closed | 40000.00 | 227000.00
```

`opening_balance` de la session 427 est un champ `related='fiche_journee_id.opening_balance'`
([microfinance_caisse_session.py:52](../../microfinance_loan_management/models/microfinance_caisse_session.py#L52)),
lui-même repris de la clôture du 2026-09-18 (227 000). La session 427 a **zéro mouvement** :
son `theoretical_balance` vaut donc exactement `opening_balance` = 227 000 MGA
([microfinance_caisse_session.py:125-145](../../microfinance_loan_management/models/microfinance_caisse_session.py#L125-L145),
branche `state != 'draft'` avec `net_cash = net_fees = 0`).

Autrement dit : les **227 000 MGA affichés ne sont pas le résultat d'opérations comptabilisées
le 2026-09-21** — c'est le solde d'ouverture, statique, de la session 427, qui n'a reçu aucun
mouvement depuis sa création. Le "ticket vide" n'est donc pas une désynchronisation d'affichage
entre deux vues d'une même session (agrégat correct / détail perdu) : c'est la conséquence
directe du fait que le widget s'est mis à afficher **une session différente, réellement vide**,
de celle sur laquelle le caissier pensait opérer. Aucune ligne de mouvement n'a été perdue ou
effacée en base : la session 426 conserve intactes ses 2 lignes du 2026-09-19.

### Verdict Symptôme 2 : bug transverse

Le trou est structurel et identique pour toutes les agences :

1. Rien n'empêche d'ouvrir une nouvelle session sur un journal alors qu'une session antérieure
   du même journal est encore `open` (contrainte SQL insuffisante + absence de contrôle dans
   `action_open_session()`/le wizard d'ouverture).
2. Le guichet OWL sélectionne systématiquement, à chaque rechargement, "la session ouverte la
   plus récente par date" sans jamais comparer à la session précédemment affichée ni avertir
   d'un changement.

Toute agence où une session reste ouverte au-delà d'un jour (cf. mémoire projet : sessions non
clôturées le 2026-09-21 sur *deux* agences simultanément, signe que ce n'est pas un cas isolé)
est exposée au même effacement apparent du ticket dès qu'une session suivante est ouverte sans
clôturer la précédente. Rien dans la configuration propre à Ambanidia (journal, compte,
`disbursement_journal_ids`) n'entre en jeu.

---

## Points communs et recommandation de méthode (pas de correctif proposé ici)

Les deux symptômes partagent la même signature : une opération **réellement comptabilisée**
(écriture posée) mais **invisible dans le solde/ticket de la session affichée**, parce que le
lien entre "ce qui est comptabilisé" et "ce qui est rattaché à la session en cours" repose sur
un traçage optionnel (`microfinance.caisse.mouvement`) et une sélection de session non
verrouillée (pas de session unique garantie par journal). Aucun correctif n'est appliqué par cet
audit — conformément à la demande, ce document sert de base de décision avant toute
intervention sur `action_open_payment_wizard`, le wizard d'ouverture de session, ou la garde
d'unicité des sessions ouvertes.
