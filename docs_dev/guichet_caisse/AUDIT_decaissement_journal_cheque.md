# Audit — Choix du journal et gestion chèque au décaissement

Audit en lecture seule. Aucune modification de code. Toutes les références de ligne sont
prises sur l'état actuel de la branche `main` (non commité inclus).

## 1. Journal de décaissement actuel

- `microfinance.loan.product.disbursement_journal_id` ([microfinance_loan_product.py:128-132](../../microfinance_loan_management/models/microfinance_loan_product.py#L128-L132)) :
  `Many2one('account.journal')`, domaine `[('type','in',('bank','cash')), ('company_id','=',company_id)]`,
  défaut = journal `CRE` (`_journal_default('CRE')`). C'est un champ de **configuration du
  produit de crédit**, pas une saisie par dossier ni par décaissement.
- Usages exacts :
  - `_prepare_disbursement_move()` ([microfinance_loan.py:2237-2266](../../microfinance_loan_management/models/microfinance_loan.py#L2237-L2266)) :
    lit `product.disbursement_journal_id`, l'utilise comme `journal_id` de l'écriture ET comme
    source du compte de contrepartie (`journal.default_account_id`) pour la ligne de sortie
    caisse/banque. Aucun paramètre : le journal est entièrement déterminé par le produit au
    moment de la préparation de l'écriture.
  - `_check_disbursement_limit()` ([microfinance_loan.py:2523-2541](../../microfinance_loan_management/models/microfinance_loan.py#L2523-L2541)) :
    ne s'applique que si `journal.type == 'cash'` (plafond espèces, pas de plafond sur un
    décaissement banque).
  - `_check_cash_journal_balance()` ([microfinance_loan.py:2543-2564](../../microfinance_loan_management/models/microfinance_loan.py#L2543-L2564)) :
    idem, ne s'applique que si `journal.type == 'cash'` ET
    `product.check_cash_balance_at_disbursement` activé.
  - Ces deux contrôles sont rejoués **uniquement à `action_activate()`**
    ([microfinance_loan.py:2566-2592](../../microfinance_loan_management/models/microfinance_loan.py#L2566-L2592)),
    jamais à `action_process_disbursement()` — confirmé, décision actée dans
    `AUDIT_decaissement.md` (découplage activation/décaissement).
- `action_process_disbursement()` ([microfinance_loan.py:2594-2625](../../microfinance_loan_management/models/microfinance_loan.py#L2594-L2625)) :
  **ne reçoit aucun paramètre**, ni journal ni montant. Elle relit uniquement l'état du prêt
  (verrou pessimiste, garde `state == 'active'`, garde `disbursement_date` vide), puis appelle
  `loan._prepare_disbursement_move()` qui va rechercher `product.disbursement_journal_id`
  en dur. Il n'existe aujourd'hui **aucun canal** pour passer un journal différent au moment
  du décaissement effectif : le journal est figé au niveau du produit, choisi une fois pour
  toutes en configuration, jamais par dossier ni par opération de caisse.
- Appel côté guichet : `microfinance_caisse_mouvement.py:137` —
  `self._run_posting_sudo(loan, session, 'action_process_disbursement')`, sans aucun argument
  de journal, confirmant qu'il n'y a pas de point d'insertion existant même côté appelant.
- Les 7+1 journaux standards (`hooks.py:76-90`) :

  | Code | Nom | Type Odoo | Compte par défaut |
  |---|---|---|---|
  | BQOP | Banque - Opérations | bank | 131001 |
  | BQEP | Banque - Épargne | bank | 131002 |
  | BQCR | Banque - Crédits | bank | 131003 |
  | CAI | Caisse | cash | 101000 |
  | CRE | Crédits | cash | (compte cash par défaut Odoo, non fixé) |
  | EPG | Épargne | cash | (idem) |
  | OD | Opérations diverses | general | (idem) |
  | TRANSIT | Transit inter-agences | general | 302000 |

  Aucun de ces journaux n'est spécifiquement dédié à un règlement par chèque : le type Odoo
  `account.journal` ne porte pas de sous-type "chèque" natif utilisé ici (pas de champ
  `journal.type == 'cheque'` — ce type n'existe pas dans Odoo standard pour un `account.journal`
  de trésorerie). CRE et EPG sont explicitement contraints à rester `'cash'` (jamais
  `'general'`) — cf. commentaire `hooks.py:67-72` — car ce sont les journaux retournés par
  défaut sur les produits crédit/épargne et le domaine des champs `disbursement_journal_id`/
  `payment_journal_id` exige `type in ('bank','cash')`.
- Conclusion §1 : le "journal chèque" n'existe pas comme catégorie de journal — un chèque est
  un **moyen de règlement** (`payment_method`), orthogonal au journal (bancaire ou caisse), pas
  un type de journal en tant que tel. Voir §3.

## 2. Mécanisme chèque existant (épargne) — réutilisable ou non

- Localisation : `microfinance.savings.transaction`
  ([microfinance_savings_transaction.py](../../microfinance_savings_management/models/microfinance_savings_transaction.py)).
  Champs :
  - `payment_method` (ligne 37-42) : sélection `cash` / `bank_transfer` / `mobile_money` /
    `cheque`, défaut `cash`. Champ générique sur toute transaction épargne (dépôt ET retrait),
    mais la logique de traitement spécifique au chèque ne s'active que pour
    `transaction_type == 'deposit'`.
  - `cheque_state` (ligne 48-56) : sélection `en_attente` / `compense` / `rejete`, `copy=False`,
    `readonly=True`, `tracking=True`. Le help le dit explicitement : "Ne concerne que les
    dépôts par chèque... un retrait par chèque n'est pas pris en charge par ce mécanisme."
  - `clearing_move_id` (ligne 57-62) : `Many2one('account.move')`, l'écriture de compensation.
  - **Aucun champ `cheque_number` ni `cheque_date` (ni équivalent) n'existe nulle part dans le
    projet** — recherche exhaustive négative sur `cheque_number`, `cheque_date`,
    `numero_cheque`, `num_cheque`, `check_number` dans tout `imf_git`. Le mécanisme épargne
    capture uniquement le **moyen de paiement** et un **statut de compensation**, jamais le
    numéro physique du chèque ni sa date d'émission. Il n'y a donc rien à réutiliser tel quel
    pour la partie "saisir numéro + date de chèque" demandée dans le besoin : cette capture de
    données serait entièrement nouvelle, même côté épargne.
- Méthodes :
  - `action_post()` (ligne 317-337) : si `transaction_type == 'deposit'` et
    `payment_method == 'cheque'`, pose `cheque_state = 'en_attente'` après comptabilisation.
  - `action_clear_cheque()` (ligne 339-371) : vérifie `cheque_state == 'en_attente'`, crée une
    écriture de compensation qui débite le compte du journal de dépôt réel
    (`product.deposit_journal_id.default_account_id`) et crédite le compte d'attente
    (`product.account_cheques_attente_id`), poste, écrit `cheque_state = 'compense'`.
  - `action_reject_cheque(reason=None)` (ligne 373-399) : vérifie `cheque_state == 'en_attente'`,
    contrôle que la contre-passation ne fait pas passer le solde sous `min_balance`, contre-passe
    intégralement l'écriture d'origine (`move._reverse_moves(..., cancel=True)`), écrit
    `cheque_state = 'rejete'` et `state = 'cancelled'`.
  - Compte comptable utilisé : `product.account_cheques_attente_id`
    ([microfinance_savings_product.py:200-210](../../microfinance_savings_management/models/microfinance_savings_product.py#L200-L210)),
    domaine `account_type in ('asset_cash','asset_current')`, défaut PCEC `511200`. Un second
    champ `account_commission_cheques_rejetes_id` (ligne 211-219) existe mais est explicitement
    marqué **"Non implémenté — sans effet actuellement"**.
- Réutilisable tel quel ? **Non, directionnellement inverse et structurellement lié au modèle
  épargne** :
  1. Le mécanisme épargne traite un chèque **reçu** par l'institution (dépôt d'un client) :
     le risque géré est que le chèque ne soit pas encaissable (provision insuffisante), d'où
     l'attente avant "compensation" et le compte d'attente comme contrepartie provisoire.
     Un décaissement de crédit par chèque est l'inverse : l'institution **émet** un chèque au
     client. Le risque de non-provision ne pèse pas sur l'institution émettrice de la même
     façon, et il n'y a pas de notion évidente de "compensation" côté émetteur — le chèque émis
     représente une sortie déjà engagée dès sa remise (voir §5 pour la question comptable
     précise, non tranchée ici).
  2. Le champ `cheque_state` et les deux actions sont codés en dur pour
     `transaction_type == 'deposit'` et lèvent une `UserError` sur tout autre type
     (`'Seul un dépôt par chèque peut être compensé/rejeté.'`) : ils ne sont pas génériques,
     ils sont écrits spécifiquement pour le sens dépôt.
  3. Le compte d'attente est un champ du **produit d'épargne**
     (`microfinance.savings.product`), pas un concept partagé ; le produit de crédit
     (`microfinance.loan.product`) n'a pas d'équivalent aujourd'hui.
  4. Le modèle porteur (`microfinance.savings.transaction`) n'a pas d'équivalent structurel
     unique côté crédit : le décaissement n'est pas une ligne de transaction dédiée mais un
     champ (`disbursement_date`) + une écriture posée directement sur `microfinance.loan`.
- Ce qui est réutilisable en revanche : le **patron** (nom de champ `payment_method` avec les
  mêmes valeurs `cash`/`cheque`/etc., principe `cheque_state` en_attente/compense/rejete si un
  besoin de compensation est confirmé côté décaissement) — mais pas le code lui-même, et le
  §5 ci-dessous doit d'abord trancher si la notion de "compensation" a même un sens ici.

## 3. `payment_method` — état transversal

- `payment_method` n'existe **que** sur `microfinance.savings.transaction`. Recherche exhaustive
  dans `microfinance_loan_management` (modèles ET vues) : **aucune occurrence** de champ
  `payment_method` sur `microfinance.loan`, `microfinance.loan.payment`, ou tout autre modèle
  crédit. La seule occurrence côté crédit est un affichage en lecture, dans le template OWL du
  guichet, de l'historique des transactions épargne
  (`microfinance_caisse_pos.xml:290` : `<td t-esc="txn.payment_method_label"/>`) — un simple
  passe-plat de la donnée épargne, pas un champ crédit.
- `microfinance.loan.payment` (remboursement) n'a pas de `payment_method` mais **a bien un
  `journal_id`** ([microfinance_loan_payment.py:37-40](../../microfinance_loan_management/models/microfinance_loan_payment.py#L37-L40)),
  `required=True`, domaine `[('type','in',('bank','cash'))]`, suggéré par
  `default_payment_amount_and_journal()` (ligne 6-23) via `loan.product_id.payment_journal_id`.
  C'est un précédent utile : le modèle de remboursement porte déjà un champ journal
  **par enregistrement**, contrairement au décaissement où le journal reste uniquement au
  niveau du produit. Mais au guichet, ce choix n'est pas exposé : `register_operation` (branche
  `remboursement_credit`, `microfinance_caisse_mouvement.py:113-117`) écrase systématiquement
  avec `session.journal_id` (le journal fixe de la session de caisse), sans lire ni proposer
  `product.payment_journal_id`. Donc même le champ `journal_id` existant sur
  `microfinance.loan.payment` n'est aujourd'hui pas piloté par un choix utilisateur au guichet.
- Conclusion §3 : rien de transversal à réutiliser directement pour `payment_method` côté
  crédit — le champ serait entièrement nouveau sur le modèle crédit concerné, quel qu'il soit.

## 4. Point d'insertion dans le flux guichet

- Signature confirmée de `register_operation`
  ([microfinance_caisse_mouvement.py:85](../../microfinance_savings_management/models/microfinance_caisse_mouvement.py#L85)) :
  `register_operation(self, session_id, type, partner_id, amount, savings_account_id=False, loan_id=False)`
  — pas de paramètre journal ni moyen de paiement.
- Branche `decaissement_credit` ([microfinance_caisse_mouvement.py:129-142](../../microfinance_savings_management/models/microfinance_caisse_mouvement.py#L129-L142)) :
  `self._run_posting_sudo(loan, session, 'action_process_disbursement')` — appel sans argument,
  confirmé exact.
- La session de caisse elle-même (`microfinance.caisse.session.journal_id`,
  [microfinance_caisse_session.py:12-15](../../microfinance_loan_management/models/microfinance_caisse_session.py#L12-L15))
  porte un journal, mais **domaine restreint à `type = 'cash'`** et **non utilisé par la
  branche `decaissement_credit`** (seule la branche `remboursement_credit` s'en sert). Le
  journal de session ne peut donc pas servir tel quel de "journal de décaissement choisi" —
  il ne couvre que le cash, jamais bancaire, et un seul journal par session (contrainte SQL
  `unique(journal_id, date)`).
- Front OWL (`microfinance_caisse_pos.js` / `.xml`) : **pas de pattern `<select>` natif** pour
  un choix parmi plusieurs options liées à une opération de caisse. Le seul `<select>` HTML
  trouvé dans tout le projet est hors guichet, dans le dashboard crédit
  (`microfinance_loan_dashboard.xml:131`, filtre agent). Le guichet utilise systématiquement un
  **pattern de liste cliquable** (`o_microfinance_pos__account_row`, classe
  `--selected` togglée via `state.selectedAccountId`, cf.
  `microfinance_caisse_pos.xml:252-302` et `microfinance_caisse_pos.js:30,234-524`) pour tout
  choix (sélection d'un compte épargne, d'un crédit à décaisser). C'est ce pattern de liste
  cliquable, pas un `<select>`, qui est le précédent réel du guichet si un choix de journal
  doit être ajouté à l'écran de décaissement.
- Aucun champ de saisie libre (texte + date) n'existe non plus dans le guichet OWL actuel : la
  saisie est limitée à un montant (`this.amount`) et des sélections de type liste. Un couple
  "numéro de chèque + date" serait une première dans ce composant.

## 5. Comptabilisation d'un décaissement par chèque

- `_prepare_disbursement_move()` ([microfinance_loan.py:2237-2266](../../microfinance_loan_management/models/microfinance_loan.py#L2237-L2266))
  utilise `journal.default_account_id` comme compte de contrepartie de la sortie
  caisse/banque (ligne 2245 : `'account_id': journal.default_account_id.id`). Ce compte est
  donc **déjà entièrement piloté par le journal** — changer de journal changerait
  automatiquement de compte de contrepartie, sans modification de code. En ce sens, la méthode
  est techniquement "prête" à recevoir un journal différent si on le lui passait.
- En revanche, il n'existe **aucune notion de compte d'attente / compte intermédiaire**
  configurable indépendamment du journal pour le décaissement — contrairement au mécanisme
  épargne (§2) où le compte de contrepartie d'un dépôt chèque (`account_cheques_attente_id`)
  est un champ dédié du produit, distinct du compte du journal réel. Pour le décaissement, si
  un chèque émis doit transiter par un compte d'attente avant d'être considéré définitivement
  sorti, ce compte n'existe pas aujourd'hui et devrait être ajouté (nouveau champ sur
  `microfinance.loan.product`, sur le modèle de `account_cheques_attente_id`) — **question
  ouverte, non tranchée ici, cf. §7**.
- Point non résolu par cet audit (car hors périmètre "état des lieux") : est-ce qu'un
  décaissement par chèque doit être traité comme une sortie immédiate et définitive de caisse
  (le journal bancaire/caisse choisi porte directement le compte, sans étape d'attente — le
  chèque remis au client vaut sortie), ou comme une sortie provisoire nécessitant un compte
  d'attente jusqu'à encaissement effectif par le client (symétrique du mécanisme épargne) ?
  Le code actuel ne permet aucune des deux automatiquement pour le décaissement : il n'y a
  qu'un seul compte possible (`journal.default_account_id`), sans variante par
  `payment_method`.
- Rappel : `_check_disbursement_limit()` et `_check_cash_journal_balance()` ne s'appliquent
  qu'aux journaux `type == 'cash'`. Si le choix du journal au décaissement inclut des journaux
  bancaires (BQOP/BQEP/BQCR) pour un règlement chèque, ces deux contrôles resteraient inactifs
  sur ce chemin — cohérent avec leur intention actuelle (plafond/solde ne concernent que les
  espèces physiques), mais à confirmer explicitement dans la conception si le chèque est piloté
  via un journal bancaire plutôt que cash.

## 6. Tests existants (patron à reproduire)

> **Résolu** — implémenté depuis cet audit : `disbursement_payment_method`
> (`microfinance_loan.py:78-86`), `disbursement_cheque_state`/`disbursement_cheque_number`/
> `disbursement_cheque_date`/`disbursement_clearing_move_id` (lignes 87-102),
> `microfinance.loan.product.account_cheques_emis_attente_id` (`microfinance_loan_product.py:351`),
> `action_clear_disbursement_cheque()` et `action_reject_disbursement_cheque()`, en miroir direct
> du patron épargne décrit ci-dessus. Le verrou `FOR UPDATE` mentionné en §7.5 est en place dans
> `action_process_disbursement()`. Le champ `disbursement_move_id` a depuis remplacé l'heuristique
> `_get_disbursement_move()` (recherche par contenu de ligne dans `move_ids`) par un lien direct,
> écrit par `action_process_disbursement()` et vidé par `action_reject_disbursement_cheque()`.

- `microfinance_savings_management/tests/test_cheque_workflow.py`
  (classe `TestSavingsChequeWorkflow`, hérite de `SavingsCommon`) — 7 tests :
  1. `test_cheque_deposit_uses_waiting_account_and_sets_en_attente` — dépôt chèque, vérifie
     `cheque_state == 'en_attente'`, contrepartie = compte d'attente, pas le compte banque.
  2. `test_cheque_deposit_requires_waiting_account_configured` — `UserError` si le compte
     d'attente n'est pas configuré sur le produit.
  3. `test_clear_cheque_transfers_to_real_account` — `action_clear_cheque()` transfère le
     montant du compte d'attente vers le compte réel, solde compte épargne inchangé (déjà
     crédité à l'origine).
  4. `test_clear_cheque_blocked_if_not_en_attente` — double appel `action_clear_cheque()`
     rejeté.
  5. `test_clear_cheque_blocked_on_non_cheque_transaction` — `action_clear_cheque()` sur une
     transaction non-chèque rejeté.
  6. `test_reject_cheque_reverses_move_and_excludes_from_balance` — `action_reject_cheque()`
     contre-passe intégralement, exclut du solde.
  7. `test_reject_cheque_blocked_if_would_go_below_min_balance` — rejet bloqué si la
     contre-passation ferait passer sous le solde minimum.
  Un 8e test (`test_cash_deposit_unaffected_by_cheque_workflow`) vérifie la non-régression du
  chemin `cash` (pas de `cheque_state`, contrepartie = compte banque normal).
- Aucun test ne couvre `payment_method` sur le crédit ni un quelconque décaissement par chèque
  — confirmé, cette fonctionnalité n'existe pas encore côté crédit, donc pas de non-régression
  directe à ce stade, seulement un patron structurel à reproduire (setUpClass configurant un
  compte technique dédié + tests positifs/négatifs par action).
- Tests de décaissement existants à connaître pour ne pas régresser lors d'une future
  implémentation : `test_disbursement_limit.py`, `test_cash_balance_check.py`,
  `test_disbursement_decouple_aggregates.py`, `test_disbursement_decouple_guards.py`,
  `test_disbursement_concurrent_guard.py`, `test_disbursement_schedule_recalc.py` — tous
  appellent `action_process_disbursement()` sans argument ; toute évolution de signature devra
  les garder compatibles ou les migrer explicitement.

## 7. Questions bloquantes pour l'implémentation

> **Résolu** — les points 1, 2 (partiellement) et 5 de cette section ont été tranchés : compte
> d'attente adopté (§7.1), `disbursement_cheque_number`/`disbursement_cheque_date` ajoutés
> uniquement côté crédit (§7.2, pas de rétroportage vers `microfinance.savings.transaction`), et
> le journal/moyen de paiement sont posés sur `microfinance.loan` avant l'appel à
> `action_process_disbursement()` plutôt que passés en paramètre (§7.5). Les points 3, 4 et 6 ne
> sont pas documentés comme tranchés ailleurs — à vérifier séparément si besoin.

1. **Comptabilisation** (cf. §5) : un décaissement par chèque doit-il transiter par un compte
   d'attente (symétrique au mécanisme épargne, avec un workflow `en_attente`/`compense`/`rejete`
   propre au décaissement), ou est-il traité comme une sortie définitive dès l'émission (le
   `journal.default_account_id` suffit, aucun état de compensation) ? Les deux mécaniques
   existent en germe dans le code actuel (compte d'attente configurable comme
   `account_cheques_attente_id` vs. compte de journal direct comme aujourd'hui pour tout
   décaissement) mais rien ne les distingue encore côté crédit.
2. **Capture des données chèque** : `cheque_number`/`cheque_date` n'existent nulle part dans le
   projet, y compris côté épargne (§2). Faut-il les ajouter aussi rétroactivement à
   `microfinance.savings.transaction` pour cohérence transversale, ou uniquement côté crédit
   dans un premier temps ?
3. **Portée du choix de journal** : le besoin dit "le caissier doit pouvoir choisir le journal"
   — s'agit-il de choisir parmi tous les journaux `bank`/`cash` du domaine actuel de
   `disbursement_journal_id` (identique au champ produit), ou d'une liste restreinte
   spécifique au guichet (ex. seulement les journaux de l'agence de la session) ?
4. **Lien avec `payment_method`** : le choix de journal et la question "est-ce un chèque"
   sont-ils deux champs indépendants (un journal peut être réglé cash ou chèque), ou le choix
   d'un journal bancaire implique-t-il automatiquement `payment_method == 'cheque'` ? Le §1
   montre qu'aucun journal n'est actuellement typé "chèque" — c'est `payment_method`, pas le
   journal, qui doit porter cette information si le patron épargne est suivi.
5. **`action_process_disbursement()` sans paramètre** : toute conception devra décider si le
   journal (et le futur `payment_method`/`cheque_number`/`cheque_date`) est stocké au préalable
   sur le prêt avant l'appel (ex. un ou plusieurs champs sur `microfinance.loan`, remplis par
   le guichet juste avant `register_operation`), ou passé en paramètre à
   `action_process_disbursement()` — ce qui casserait la compatibilité avec `action_disburse()`
   (déjà déprécié, §1 de `AUDIT_decaissement.md`) et tous les appels directs listés en §6.
6. **Session de caisse mono-journal** : la session de caisse (`journal_id`, type `cash`
   uniquement, un seul journal par session/jour) n'est pas conçue pour représenter un choix de
   journal différent à chaque opération. Un décaissement par banque ou par un journal différent
   de celui de la session pose-t-il une question de cohérence avec la fiche journalière
   (`microfinance.caisse.fiche.journee`, 1 session = 1 fiche) ? Non investigué ici (hors
   périmètre de cet audit), mais à vérifier avant conception si le journal choisi peut différer
   du journal de la session en cours.
