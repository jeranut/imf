# Audit — Gestion Caisse (état des lieux)

Périmètre : `microfinance_loan_management` et `microfinance_savings_management`. Audit en lecture seule, aucune modification de code. Toutes les affirmations sont sourcées par chemin relatif + ligne + nom de méthode/champ/modèle. Quand un élément recherché est absent du code, cela est indiqué explicitement plutôt que supposé.

## 1. Journaux caisse/banque configurés

### 1.1 Absence de données de démo
Aucun répertoire `demo/` n'existe dans les deux modules (vérifié par recherche récursive). Le mot-clé `'demo'` n'apparaît dans aucune des deux clés `'data'` des manifestes (`microfinance_loan_management/__manifest__.py`, `microfinance_savings_management/__manifest__.py`). Aucun `account.journal` n'est donc livré via un mécanisme de données de démonstration Odoo classique.

### 1.2 Journaux créés par post_init_hook (pas par agence explicitement, mais par société)
Les journaux ne sont pas créés par une donnée statique mais par du code exécuté à l'installation :
- `microfinance_loan_management/hooks.py:56-64` (constante `JOURNALS`) définit 7 journaux :
  - `('BQOP', 'Banque - Opérations', 'bank', '131001')`
  - `('BQEP', 'Banque - Épargne', 'bank', '131002')`
  - `('BQCR', 'Banque - Crédits', 'bank', '131003')`
  - `('CAI', 'Caisse', 'cash', '101000')`
  - `('CRE', 'Crédits', 'general', None)`
  - `('EPG', 'Épargne', 'general', None)`
  - `('OD', 'Opérations diverses', 'general', None)`
- `microfinance_loan_management/hooks.py:103-113` (`_create_journals`) crée ces 7 journaux, un jeu par `res.company`, uniquement si le journal (par code) n'existe pas déjà pour cette société.
- `microfinance_loan_management/hooks.py:116-125` (`post_init_hook`) n'exécute cette création que pour les sociétés dont `company.chart_template == 'mg_pcec'` (`hooks.py:122`). Pour toute société utilisant un autre plan comptable, aucun journal n'est créé par le module : la configuration reste alors entièrement manuelle et absente de tout fichier de données.
- `microfinance_savings_management/hooks.py:59-68` ne crée aucun journal ; le commentaire `microfinance_savings_management/hooks.py:61-63` indique explicitement que les journaux, y compris `EPG` utilisé par les défauts des champs dépôt/retrait, sont créés par `microfinance_loan_management`.

Chaque société (« agence » au sens métier, cf. section 4) dispose donc de son propre jeu de 7 journaux si et seulement si elle utilise le plan comptable `mg_pcec`. Il n'existe pas de notion d'agence distincte de `res.company` dans le code : le cloisonnement caisse/banque par agence est un cloisonnement par société Odoo, rien de plus.

### 1.3 Anomalie de typage relevée : journal `CRE` utilisé comme valeur par défaut de champs `bank/cash`
`microfinance_loan_management/models/microfinance_loan_product.py:86-93` définit :
```python
disbursement_journal_id = fields.Many2one('account.journal', ..., domain="[('type', 'in', ('bank','cash'))]", default=_journal_default('CRE'))
payment_journal_id = fields.Many2one('account.journal', ..., domain="[('type', 'in', ('bank','cash'))]", default=_journal_default('CRE'))
```
et `microfinance_loan_management/models/microfinance_loan_product.py:283-288` fait de même pour `fee_journal_id` avec le même défaut `CRE`. Or le journal de code `CRE` est créé de type `'general'` (`hooks.py:61`), pas `'bank'` ni `'cash'`. Le domaine de vue restreint la sélection utilisateur à `bank`/`cash`, mais la valeur par défaut calculée par `_journal_default('CRE')` (`microfinance_loan_product.py:19-27`) retourne ce journal général `CRE`, qui ne respecte pas ce même domaine.

### 1.4 Recensement des champs `Many2one('account.journal', ...)`
| Champ | Fichier:ligne | Domaine | Obligatoire | Défaut |
|---|---|---|---|---|
| `disbursement_journal_id` (microfinance.loan.product) | `microfinance_loan_management/models/microfinance_loan_product.py:86-89` | `[('type','in',('bank','cash'))]` | non (`required=` absent) | `_journal_default('CRE')` |
| `payment_journal_id` (microfinance.loan.product) | `microfinance_loan_management/models/microfinance_loan_product.py:90-93` | `[('type','in',('bank','cash'))]` | non | `_journal_default('CRE')` |
| `fee_journal_id` (microfinance.loan.product) | `microfinance_loan_management/models/microfinance_loan_product.py:283-288` | `[('type','in',('bank','cash'))]` | non | `_journal_default('CRE')` |
| `journal_id` (microfinance.loan.payment) | `microfinance_loan_management/models/microfinance_loan_payment.py:37` | `[('type','in',('bank','cash'))]` | oui (`required=True`) | aucun défaut déclaratif (rempli par `_onchange_loan_id`, `microfinance_loan_payment.py:62-71`) |
| `journal_id` (microfinance.loan.payment.wizard) | `microfinance_loan_management/wizard/microfinance_loan_payment_wizard.py:20` | `[('type','in',('bank','cash'))]` | oui | aucun défaut déclaratif (rempli par `@api.onchange`, `wizard.py:30-34`) |
| `journal_id` (microfinance.fond.contribution) | `microfinance_loan_management/models/microfinance_fond_contribution.py:30-33` | non renseigné dans le code lu | non (requis conditionnellement, voir `@api.constrains` `microfinance_fond_contribution.py:69-75`) | aucun |
| `deposit_journal_id` (microfinance.savings.product) | `microfinance_savings_management/models/microfinance_savings_product.py:211-214` | `[('type','in',('bank','cash'))]` | non | `_journal_default('EPG')` (même mécanisme que côté crédit) |
| `withdrawal_journal_id` (microfinance.savings.product) | `microfinance_savings_management/models/microfinance_savings_product.py:215-218` | `[('type','in',('bank','cash'))]` | non | `_journal_default('EPG')` |

Le journal `EPG` est lui aussi créé de type `'general'` (`microfinance_loan_management/hooks.py:62`), donc le même écart de typage relevé en 1.3 s'applique à `deposit_journal_id`/`withdrawal_journal_id`.

Aucun champ Many2one `account.journal` propre au dépôt/retrait n'a été trouvé ailleurs que `deposit_journal_id`/`withdrawal_journal_id` dans `microfinance_savings_management`.

### 1.5 Domaines des champs journal : absence de filtre `company_id`
Sur les 8 champs recensés ci-dessus, aucun domaine ne contient de clause `('company_id', '=', company_id)` (à comparer aux champs `account.account` du même module, qui portent systématiquement ce filtre, ex. `microfinance_loan_product.py:98` `domain="[('account_type', 'in', (...)), ('company_id', '=', company_id)]"`). Voir section 4 pour l'analyse de cet écart.

## 2. Écritures comptables et contrepartie caisse

### 2.1 Décaissement de crédit
`microfinance_loan_management/models/microfinance_loan.py:696-725` (`_prepare_disbursement_move`) : la contrepartie caisse/banque est `journal.default_account_id` où `journal = product.disbursement_journal_id` (ligne 699, 704). Le compte est extrait du journal, pas codé en dur. Appelée par `action_disburse` (`microfinance_loan.py:811-827`).

### 2.2 Encaissement des frais de dossier
`microfinance_loan_management/models/microfinance_loan.py:727-742` (`_prepare_fee_move`) : contrepartie = `journal.default_account_id` où `journal = product.fee_journal_id` (ligne 730, 739). Appelée par `action_charge_fee` (`microfinance_loan.py:744-759`).

### 2.3 Remboursement de crédit
`microfinance_loan_management/models/microfinance_loan_payment.py:114-143` (`_prepare_payment_move`) : contrepartie = `self.journal_id.default_account_id` (ligne 122), `self.journal_id` étant saisi/sélectionné sur l'enregistrement `microfinance.loan.payment` lui-même (pas dérivé automatiquement du produit au moment de la comptabilisation, seulement pré-rempli par onchange). Appelée par `action_post` (`microfinance_loan_payment.py:145-161`).

### 2.4 Radiation de crédit (write-off)
`microfinance_loan_management/models/microfinance_loan.py:842-862` (`_prepare_writeoff_move`) : n'utilise pas de journal caisse/banque, mais un journal de type `'general'` recherché dynamiquement (`journal = self.env['account.journal'].search([('company_id','=',self.company_id.id), ('type','=','general')], limit=1)`, ligne 848-850). Aucune sortie de caisse réelle (écriture perte / sortie prêt client).

### 2.5 Provisions
`microfinance_loan_management/models/microfinance_loan.py:881-919` (`_get_misc_operations_journal`, `_prepare_provision_move`) : même mécanisme, journal `type='general'` recherché dynamiquement, aucun mouvement de caisse.

### 2.6 Dépôt/retrait/intérêt/frais épargne
`microfinance_savings_management/models/microfinance_savings_transaction.py:146-220` (`_prepare_transaction_move`) :
- Dépôt (`deposit`) : contrepartie = `product.deposit_journal_id.default_account_id` (lignes 169-172).
- Intérêt crédité (`interest_credit`) : contrepartie = compte `interet_paye` du produit (ligne 164-167), pas un journal caisse — aucun mouvement de caisse réel puisqu'il s'agit d'une capitalisation comptable interne.
- Retrait (`withdrawal`)/prélèvement automatique (`auto_debit`)/virement (`transfer`) : contrepartie = `product.withdrawal_journal_id.default_account_id` (lignes 182-186), sauf `fee_debit` qui utilise `product.account_commission_id` (lignes 178-181), pas un journal caisse.
- Le journal effectivement utilisé pour l'écriture (`journal_id` de l'`account.move`) est déterminé lignes 207-210 : `deposit_journal_id` si crédit (hors intérêt), sinon `withdrawal_journal_id or deposit_journal_id`.
- Appelée par `action_post` (`microfinance_savings_transaction.py:222-239`).

### 2.7 Distinction de traitement espèces / chèque / virement
Le champ `payment_method` existe sur `microfinance.savings.transaction` (`microfinance_savings_management/models/microfinance_savings_transaction.py:28-32`), avec les valeurs `('cash', 'Espèces'), ('bank_transfer', 'Virement'), ('mobile_money', 'Mobile money')` — pas de valeur `'cheque'`. Ce champ est renseigné sur le formulaire (`microfinance_savings_management/views/microfinance_savings_transaction_views.xml:36`) et affiché sur le reçu imprimé (`microfinance_savings_management/report/savings_receipt_report.xml:50`), mais **n'est lu nulle part dans `_prepare_transaction_move` ni dans `action_post`** (confirmé par lecture complète de `microfinance_savings_transaction.py:146-239`) : il ne conditionne ni le choix du journal, ni celui du compte de contrepartie, ni aucune autre logique. C'est un champ purement déclaratif/informatif.

Côté `microfinance_loan_management`, il n'existe aucun champ équivalent à `payment_method` sur `microfinance.loan.payment` ni sur `microfinance.loan` : le seul levier de distinction du mode d'encaissement/décaissement est le choix manuel du `journal_id`/`disbursement_journal_id` parmi les journaux `bank`/`cash` existants.

Le seul champ `Selection` avec une valeur `'cheque'` explicite trouvé dans les deux modules est `mode_paiement` sur `microfinance.fond.contribution` (`microfinance_loan_management/models/microfinance_fond_contribution.py:27`, valeurs `('cheque', 'Chèque')` et `('virement', 'Virement')` entre autres) — ce modèle concerne les contributions des bailleurs de fonds, pas les opérations de caisse client (décaissement, remboursement, dépôt, retrait). Une contrainte (`microfinance_fond_contribution.py:69-75`, `_check_mode_paiement`) impose `journal_id` requis quand `mode_paiement` vaut `'cheque'` ou `'virement'`, mais aucune logique de compte d'attente ou d'état transitoire n'y est associée (voir 2.8).

### 2.8 Compte d'attente chèques
Recherche exhaustive des mots-clés `cheque`/`chèque` dans les deux modules (résultats complets) :
- `microfinance_loan_management/tests/test_payment_cancel.py:43` : chaîne de texte libre `reason='Chèque rejeté'` passée à `action_cancel`, sans mécanique dédiée — c'est un simple motif texte d'annulation, traité comme n'importe quel autre motif.
- `microfinance_loan_management/models/microfinance_fond_contribution.py:27,33,72,74` : valeur de sélection `'cheque'` sur `mode_paiement` (fonds bailleurs, voir 2.7).
- `microfinance_savings_management/models/microfinance_savings_product.py:188-193` : champ `account_commission_cheques_rejetes_id` (`Many2one('account.account', ...)`), avec le `help` suivant tel qu'écrit dans le code : *"Non implémenté — sans effet actuellement. Aucun mode de paiement 'chèque' ni transaction 'chèque rejeté' n'existe encore sur ce modèle."* (ligne 192-193). Ce champ n'est référencé dans aucune méthode de comptabilisation (confirmé par grep : seule occurrence hors définition est l'affichage en vue, `microfinance_savings_management/views/microfinance_savings_product_views.xml:84`).
- `microfinance_savings_management/hooks.py:35-37` (`SAVINGS_DIRECT_REUSE_CODES`) associe ce champ au compte PCEC `719000`, mais ce compte n'est utilisé nulle part dans la logique de transaction.

**Aucun compte d'attente chèques ni état transitoire (compensation, transféré, rejeté, en attente) n'existe dans le code**, ni pour les opérations de crédit, ni pour les opérations d'épargne. Le seul artefact relatif au chèque est un champ de configuration explicitement documenté comme non implémenté.

## 3. Plafonds et contrôles existants

### 3.1 Plafond de retrait — uniquement côté épargne, par transaction
`microfinance_savings_management/models/microfinance_savings_product.py:64-69` : champ `withdrawal_limit_amount` (`Monetary`, défaut `0.0`), avec le commentaire : *"dépasse ce plafond, transaction par transaction (pas de cumul sur une période)"*.
Contrôle : `microfinance_savings_management/models/microfinance_savings_transaction.py:103-118` (`_check_withdrawal_limit`, `@api.constrains`) : ne s'applique qu'à `transaction_type == 'withdrawal'`, ignoré si `bypass_withdrawal_limit` est vrai (champ `microfinance_savings_transaction.py:50-55`), ignoré si `limit` vaut `0` (pas de plafond configuré). Aucun cumul sur une période — le commentaire du code (`microfinance_savings_transaction.py:105-107`) précise explicitement que ce choix est volontaire : *"non demandé, absent du manuel LPF, écarté pour ne pas introduire une règle métier non validée"*.

Il n'existe **aucun champ ni contrainte équivalente côté `microfinance_loan_management`** pour le décaissement de crédit ou le remboursement (recherche `max_*`/`limit_*`/`threshold_*`/`plafond` : le seul autre résultat, `microfinance_loan_guarantee.py:77-79,97`, concerne `max_ratio` sur `microfinance.guarantee.valuation.rule`, un plafond de ratio de valorisation de garantie, sans rapport avec un montant de retrait/décaissement en espèces).

### 3.2 Aucun plafond spécifique aux espèces
Ni `withdrawal_limit_amount` (épargne) ni aucun autre contrôle trouvé ne distingue un plafond selon que le journal utilisé est de type `cash` ou `bank` : le plafond de retrait épargne s'applique quel que soit `withdrawal_journal_id`, sans lecture du type de journal dans `_check_withdrawal_limit` (confirmé par lecture complète de `microfinance_savings_transaction.py:103-118`, aucune référence à `journal_id.type`).

### 3.3 Contrôle de solde/disponibilité de caisse
Recherche exhaustive de `bank.statement`, `cash.register`, `reconcil*` dans les deux modules : aucune occurrence fonctionnelle (seules occurrences : paramètre `reconcile` du dictionnaire `{code: (name, account_type, reconcile)}` utilisé pour la création de comptes PCEC dans `hooks.py` des deux modules — sans rapport avec un rapprochement bancaire/caisse).
Le seul contrôle de disponibilité de fonds trouvé est `_check_fond_disponibilite` (`microfinance_loan_management/models/microfinance_loan.py:773-809`), qui vérifie le solde du **fonds de crédit rotatif bailleur** (`microfinance.fond.credit`) rattaché au crédit (`fond_credit_id`), pas un solde de caisse physique/comptable du journal de décaissement. Ce contrôle ne s'exécute que si `fond.verification_disponibilite == 'at_disbursement'` (ligne 785) ; un crédit sans `fond_credit_id` n'est soumis à aucune vérification de disponibilité.
Aucun contrôle ne vérifie, avant `action_disburse` ou avant une transaction de retrait épargne, que le solde comptable du compte `journal.default_account_id` (compte caisse/banque réel) est suffisant pour couvrir la sortie.

### 3.4 Contrôle de mot de passe / validation manager
Recherche exhaustive des mots-clés `password`, `mot_de_passe`, `manager_password` dans les deux modules : **aucune occurrence**. Aucun mécanisme de mot de passe gérant, actif ou désactivé, n'existe dans le code, y compris pour les retraits liés à une épargne de garantie (`guarantee_savings_*`, `microfinance_savings_management/models/microfinance_loan_extension.py:28-138`) : ces retraits transitent par le mécanisme standard `microfinance.savings.transaction`/`action_post` (section 2.6), sans contrôle supplémentaire de mot de passe ou de double validation.
Le répertoire `docs_dev/retrait_garantie_workflow/` existe dans le dépôt mais est actuellement **vide** (aucun fichier), confirmant qu'aucun travail de conception ni d'implémentation n'a encore été engagé sur ce point.

## 4. Multi-société / isolation par agence

### 4.1 `company_id` sur les journaux
`account.journal` porte nativement un champ `company_id` (modèle standard Odoo `account`, non surchargé dans les deux modules — confirmé par l'absence de toute classe `_inherit = 'account.journal'` dans le code des deux modules, recherche exhaustive). Les journaux créés par `_create_journals` (`microfinance_loan_management/hooks.py:103-113`) reçoivent explicitement `'company_id': company.id` (ligne 108).

### 4.2 Absence de filtre `company_id` dans les domaines de champs `account.journal`
Comme relevé en 1.5, aucun des 8 champs `Many2one('account.journal', ...)` recensés (`disbursement_journal_id`, `payment_journal_id`, `fee_journal_id`, `journal_id` sur paiement/wizard, `journal_id` sur `microfinance.fond.contribution`, `deposit_journal_id`, `withdrawal_journal_id`) ne restreint son domaine par `company_id`. L'isolation par agence pour la sélection d'un journal repose donc uniquement sur la mécanique standard Odoo de filtrage des `Many2one` par `allowed_company_ids`/société courante côté client web, et non sur une clause de domaine explicite dans le code de ces deux modules.

### 4.3 Absence d'`ir.rule` dédiée à `account.journal`
Aucune règle `ir.rule` visant `model_id` = `account.journal` (ou `model_account_journal`) n'a été trouvée dans `microfinance_loan_management/security/*.xml` ni `microfinance_savings_management/security/*.xml` (recherche exhaustive, confirmée par grep sur les deux dossiers `security/`). Le cloisonnement de `account.journal` par société repose donc exclusivement sur les mécanismes standards du module Odoo `account` (hors périmètre de ce dépôt, non vérifiés ici).

### 4.4 `ir.rule` de cloisonnement par société sur les modèles métier (hors journal)
`microfinance_loan_management/security/microfinance_company_rules.xml` : règles avec `domain_force = [('company_id', 'in', company_ids)]` et `groups eval="[]"` (s'appliquent à tous les groupes, y compris managers et auditeurs) sur :
- `microfinance.loan.product` (ligne 9-14)
- `microfinance.loan` (ligne 16-21)
- `microfinance.loan.installment` (ligne 29-34)
- `microfinance.loan.payment` (ligne 36-41)
- `microfinance.loan.guarantee` (ligne 43-48)
- `microfinance.guarantee.valuation.rule` (ligne 50-55)
- `microfinance.loan.reschedule.history` (ligne 57-62)
- `microfinance.loan.reschedule.history.line` (ligne 65-70, via `history_id.company_id`)
- `microfinance.collection.visit` (ligne 72-77)

`microfinance_savings_management/security/microfinance_company_rules.xml` : même pattern sur `microfinance.savings.product` (ligne 9-14), `microfinance.savings.account` (ligne 16-21), `microfinance.savings.transaction` (ligne 23-28).

Ces règles cloisonnent les enregistrements métier (crédit, paiement, transaction, compte épargne) par société, mais ne cloisonnent pas directement le choix du journal comptable utilisé par ces enregistrements (voir 4.2/4.3).

### 4.5 Pattern de caisse partagée entre agences — recherche du pattern `scope` (single_company/multi_company)
Ce pattern existe pour les fonds bailleurs :
- `microfinance.fond.credit.scope` (`microfinance_loan_management/models/microfinance_fond_credit.py:24-31`) : `Selection([('single_company', 'Agence unique'), ('multi_company', 'Multi-agences (partagé)')])`.
- `ir.rule` associée : `microfinance_loan_management/security/microfinance_fond_bailleur_rules.xml:16-21` (`microfinance_fond_credit_company_rule`) et lignes 26-31 (`microfinance_fond_contribution_company_rule`), toutes deux avec `domain_force = ['|', ('company_id', 'in', company_ids), ('company_id', '=', False)]`, explicitement commentées comme un partage intentionnel entre agences (`microfinance_fond_bailleur_rules.xml:7-15`).

**Ce pattern n'existe pas pour `account.journal` ni pour aucun modèle lié à la caisse.** Aucun champ `scope` et aucune règle `ir.rule` de la forme `['|', ('company_id', 'in', company_ids), ('company_id', '=', False)]` n'ont été trouvés visant `account.journal`, `microfinance.loan.payment` ou `microfinance.savings.transaction` (recherche confirmée par lecture complète de `microfinance_company_rules.xml` des deux modules, section 4.4 ci-dessus : `groups eval="[]"` avec domaine strict `[('company_id', 'in', company_ids)]`, jamais de clause `OR company_id = False`). Il n'existe donc aucun mécanisme de caisse partagée entre agences dans le code actuel.

## 5. Rapports existants

### 5.1 Reçus imprimables (par opération, pas des rapports agrégés)
- `microfinance_loan_management/report/microfinance_loan_disbursement_receipt.xml` : reçu de décaissement de crédit (`action_report_microfinance_loan_disbursement_receipt`, modèle `microfinance.loan`), affiche notamment `o.product_id.disbursement_journal_id.name` (ligne 68) comme « Mode de décaissement ». Reçu unitaire par crédit, non filtrable, non agrégé.
- `microfinance_savings_management/report/savings_receipt_report.xml` : reçu de transaction épargne, affiche `o.payment_method` (ligne 50). Reçu unitaire par transaction.

### 5.2 Vues liste/pivot existantes sur les mouvements
- `microfinance_loan_management/views/microfinance_loan_payment_views.xml:8` (tree) : colonnes incluant `journal_id`, pas de vue de recherche dédiée définie dans ce fichier (aucun `<record ... model="ir.ui.view">` de type `search` pour `microfinance.loan.payment` trouvé dans ce fichier ni ailleurs dans le module).
- `microfinance_loan_management/views/microfinance_loan_payment_views.xml:27` (action `action_microfinance_payment`) : `view_mode = "tree,form,graph,pivot"`, permettant un regroupement pivot par n'importe quel champ y compris `journal_id`/`company_id` via l'interface Odoo standard, mais aucun filtre ou regroupement par journal/agence/période n'est prédéfini dans une vue de recherche du module.
- `microfinance_savings_management/views/microfinance_savings_transaction_views.xml:52-64` (vue `search`) : filtres définis uniquement sur `state == 'posted'` (`posted`, ligne 58), regroupement par `transaction_type` (ligne 60) et par `account_id` (ligne 61). **Aucun regroupement/filtre par `journal_id`, société ou période n'est prédéfini.** `view_mode = "tree,form"` (ligne 66, action `action_microfinance_savings_transaction`), sans vue graph/pivot.

### 5.3 Rapports listés dans les menus
- `microfinance_loan_management/views/microfinance_menus.xml:21` → `action_microfinance_fond_usage_report` (« Utilisation des fonds »), défini dans `microfinance_loan_management/views/microfinance_fond_credit_views.xml:133-142` : `res_model = microfinance.fond.credit`, `view_mode = "tree,pivot"`, vue consolidée par fonds bailleur (contributions, décaissements, remboursements, solde disponible), filtrable par bailleur/société/période selon le `help` du champ (ligne 139-140). Porte sur les fonds bailleurs, pas sur les journaux de caisse.
- `microfinance_savings_management/views/microfinance_savings_menus.xml:13-17` → `action_microfinance_savings_balance_report` (« Balance épargne »), défini dans `microfinance_savings_management/views/microfinance_savings_account_views.xml:100-106` : `res_model = microfinance.savings.account`, `view_mode = "tree"`, liste des comptes et de leur solde (pas des transactions/mouvements), regroupée par produit par défaut (`search_default_group_product`, ligne 104).

### 5.4 Tableau de bord (dashboard)
`microfinance_loan_management/models/microfinance_dashboard.py:1-28` (modèle `microfinance.dashboard`) : champs `active_loan_count`, `disbursed_amount`, `outstanding_amount`, `overdue_amount`, `default_rate`, calculés par société (`_compute_dashboard`, `api.depends_context('company')`). Aucun champ relatif à un journal ou à une caisse.

`microfinance_loan_management/controllers/microfinance_dashboard_controller.py:12-187` (route `/microfinance/dashboard/data`) : agrège des séries mensuelles `monthly_disbursement` (ligne 50-54, basé sur `loan.disbursement_date`/`loan.loan_amount`) et `monthly_repayment` (ligne 56-60, basé sur `payment.payment_date`/`payment.amount`), toutes deux **par mois de portefeuille, pas par journal ni par type d'opération caisse/banque**. Ces séries agrègent tous les décaissements/remboursements de la société, indépendamment du `journal_id` utilisé. Depuis le commit `a58034a` (« Ajoute la tuile fonds bailleurs et un panneau d'onglets au dashboard »), le dashboard inclut également `fond_kpi`, `fond_multi_chart`, `fond_single_chart` (lignes 87-90, 168-169, 172-173), relatifs aux fonds bailleurs, pas à la caisse.

`microfinance_savings_management/controllers/microfinance_savings_dashboard_controller.py:10-21` : ajoute `savings_outstanding_total` et `active_savings_account_count` (solde total et nombre de comptes actifs), pas de mouvement caisse.

**Aucun équivalent d'un « Rapport Flux de Caisse » LPF (mouvements de caisse agrégés par journal/agence/période, entrées vs sorties) n'a été trouvé sous quelque forme que ce soit** : ni dans le dashboard, ni dans les rapports imprimables, ni dans une vue pivot/graph dédiée à `journal_id`.

## 6. Sécurité

### 6.1 Les 9 groupes de `microfinance_loan_management/security/groups.xml`
1. `group_microfinance_user` (« Agent crédit ») — ligne 8-11.
2. `group_microfinance_manager` (« Manager crédit ») — ligne 12-16, implique `group_microfinance_user`.
3. `group_microfinance_finance` (« Finance microfinance ») — ligne 17-21, implique `group_microfinance_user`.
4. `group_microfinance_collection_agent` (« Agent recouvrement ») — ligne 22-26, implique `group_microfinance_user`.
5. `group_microfinance_auditor` (« Auditeur microfinance ») — ligne 27-30.
6. `group_microfinance_comptable` (« Comptable ») — ligne 31-34.
7. `group_microfinance_cashier` (« Caissier ») — ligne 35-39, implique `group_microfinance_user`.
8. `group_microfinance_credit_committee` (« Comité de crédit ») — ligne 40-44, implique `group_microfinance_user`.
9. `group_microfinance_gestionnaire` (« Gestionnaire ») — ligne 45-49, implique `group_microfinance_manager` et `group_microfinance_finance`.

### 6.2 Accès en écriture aux modèles déclenchant un mouvement de caisse
D'après `microfinance_loan_management/security/ir.model.access.csv` :
- `microfinance.loan.payment` (remboursement) : écriture/création pour `group_microfinance_finance` (`access_microfinance_payment_finance`, `1,1,1,0`), `group_microfinance_manager` (`access_microfinance_payment_manager`, `1,1,1,1`), et `group_microfinance_cashier` (`access_microfinance_payment_cashier`, ligne 77, `1,1,1,0`). `group_microfinance_user` a uniquement lecture (`access_microfinance_payment_user`, `1,0,0,0`).
- `microfinance.loan` (décaissement via `action_disburse`, qui écrit l'état du crédit) : écriture pour `group_microfinance_user` (`access_microfinance_loan_user`, `1,1,1,0`), `group_microfinance_manager` (`1,1,1,1`), `group_microfinance_finance` (`access_microfinance_loan_finance`, `1,1,0,0`). `group_microfinance_cashier` a uniquement lecture (`access_microfinance_loan_cashier`, ligne 78, `1,0,0,0`). `group_microfinance_comptable` a uniquement lecture (`access_microfinance_loan_comptable`, `1,0,0,0`).
- `microfinance.loan.product` (configuration des journaux `disbursement_journal_id`/`payment_journal_id`/`fee_journal_id`) : écriture réservée à `group_microfinance_manager` (`access_microfinance_loan_product_manager`, `1,1,1,1`) ; `group_microfinance_user`, `group_microfinance_comptable` en lecture seule ; `group_microfinance_cashier`, `group_microfinance_finance`, `group_microfinance_auditor` n'ont aucune ligne d'accès à ce modèle dans le fichier (donc aucun accès du tout, y compris en lecture).

D'après `microfinance_savings_management/security/ir.model.access.csv` :
- `microfinance.savings.transaction` (dépôt/retrait) : écriture/création pour `group_savings_agent` (`access_microfinance_savings_transaction_agent`, `1,1,1,0`) et `group_savings_manager` (`1,1,1,1`). `microfinance_loan_management.group_microfinance_manager` et `.group_microfinance_auditor` ont uniquement lecture.
- `microfinance.savings.account` : écriture/création pour `group_savings_agent` (`1,1,1,0`) et `group_savings_manager` (`1,1,1,1`).
- Aucune ligne n'accorde d'accès à `group_microfinance_cashier` (module crédit) sur les modèles d'épargne : la caisse épargne et la caisse crédit ont des populations d'accès disjointes (`group_savings_agent`/`group_savings_manager` vs `group_microfinance_cashier`).

### 6.3 Boutons de vue conditionnés par `groups=`
- `microfinance_loan_management/views/microfinance_loan_views.xml:70` : `action_disburse` (décaissement) conditionné par `groups="microfinance_loan_management.group_microfinance_finance"` — **`group_microfinance_cashier` n'a pas accès à ce bouton**, cohérent avec son absence d'accès en écriture sur `microfinance.loan.product` et son accès lecture seule sur `microfinance.loan` (6.2).
- `microfinance_loan_management/views/microfinance_loan_views.xml:69` : `action_charge_fee` conditionné par `groups="microfinance_loan_management.group_microfinance_finance"`.
- `microfinance_loan_management/views/microfinance_loan_payment_views.xml:17` : le bouton `action_post` (comptabilisation du remboursement) **n'est pas conditionné par un attribut `groups=`** — sa disponibilité dépend uniquement de la visibilité du formulaire et des droits d'écriture définis en 6.2 (donc accessible à `group_microfinance_cashier`, `group_microfinance_finance`, `group_microfinance_manager`, mais pas à `group_microfinance_user` en écriture bien qu'il puisse voir le bouton). Seul `action_open_cancel_wizard` (annulation par contre-passation) est conditionné, par `groups="microfinance_loan_management.group_microfinance_manager,microfinance_loan_management.group_microfinance_finance"` (même ligne).
- Aucun bouton `groups=` n'a été trouvé dans `microfinance_savings_management/views/microfinance_savings_transaction_views.xml` ni `microfinance_savings_management/views/microfinance_savings_account_views.xml` conditionnant `action_post` ou les actions de transaction : leur disponibilité dépend uniquement des droits d'accès `ir.model.access.csv` (6.2).

### 6.4 `group_microfinance_cashier` : réellement exploité, pas un groupe fantôme
Recherche exhaustive de `group_microfinance_cashier` dans les deux modules : 3 occurrences, toutes fonctionnelles —
- `microfinance_loan_management/security/groups.xml:35` (définition).
- `microfinance_loan_management/security/ir.model.access.csv:77` (`access_microfinance_payment_cashier`, écriture/création sur `microfinance.loan.payment`).
- `microfinance_loan_management/security/ir.model.access.csv:78` (`access_microfinance_loan_cashier`, lecture seule sur `microfinance.loan`).

Ce groupe est donc réellement utilisé (contrairement aux 3 groupes fantômes déjà connus sur le projet, non re-décrits ici car sans lien avec la caisse). Aucune `ir.rule` ni condition `groups=` de vue supplémentaire ne le référence par ailleurs (recherche confirmée, aucune autre occurrence dans les deux modules).

### 6.5 Modèle métier absent de `models/__init__.py`
`microfinance_loan_management/models/__init__.py` (21 imports) et `microfinance_savings_management/models/__init__.py` (8 imports) ont été vérifiés intégralement : tous les fichiers `.py` présents dans `models/` des deux modules y sont importés. **Aucun modèle lié à la caisse n'est concerné par cet anti-pattern.** Le seul cas d'omission volontaire déjà documenté dans le code concerne `microfinance.loan.application` (commentaire `microfinance_loan_management/security/microfinance_company_rules.xml:23-27`), sans rapport avec la caisse.

## 7. Écarts et manques identifiés

- Aucune donnée de démonstration ou de configuration livrée ne définit de journaux caisse/banque par agence : leur existence dépend entièrement de l'exécution de `post_init_hook` et de la condition `company.chart_template == 'mg_pcec'` (`microfinance_loan_management/hooks.py:122`). Pour toute société sur un autre plan comptable, aucun journal caisse/banque n'existe après installation.
- Le journal par défaut `CRE` (et `EPG` côté épargne) utilisé comme valeur `default=` de champs dont le domaine de vue est restreint à `('type','in',('bank','cash'))` est lui-même de type `'general'`, en écart avec ce domaine (`microfinance_loan_management/hooks.py:61-62` vs `microfinance_loan_product.py:86-93,283-288` et `microfinance_savings_product.py:211-218`).
- Aucun compte d'attente chèques ni état transitoire (compensation, transféré, rejeté, en attente) n'existe dans le code, pour aucune opération (crédit ou épargne).
- Le champ `payment_method` (épargne) ne comporte pas de valeur `'cheque'` et n'est lu par aucune logique de comptabilisation ou de sélection de journal : il n'a aucun effet observable sur le traitement de la transaction.
- Le champ `account_commission_cheques_rejetes_id` (épargne) est explicitement documenté dans le code comme non implémenté et sans effet.
- Aucun champ ni contrainte de plafond de retrait/décaissement en espèces n'existe côté crédit (décaissement, remboursement). Le seul plafond de retrait trouvé (`withdrawal_limit_amount`) est propre à l'épargne, s'applique par transaction sans cumul sur une période, et ne distingue pas le type de journal (cash vs bank).
- Aucun contrôle de solde comptable du compte caisse/banque réel (`journal.default_account_id`) n'est effectué avant un décaissement ou un retrait ; le seul contrôle de disponibilité existant (`_check_fond_disponibilite`, `microfinance_loan.py:773-809`) porte sur le solde du fonds de crédit rotatif bailleur, pas sur un solde de caisse physique.
- Aucun mécanisme de rapprochement bancaire/caisse (`account.bank.statement`, `cash.register`, réconciliation) n'est présent dans le code des deux modules.
- Aucun contrôle de mot de passe ou de validation manager, actif ou désactivé, n'existe dans le code, y compris pour les retraits sur épargne de garantie. Le répertoire `docs_dev/retrait_garantie_workflow/` existe mais est vide.
- Aucun des 8 champs `Many2one('account.journal', ...)` recensés ne filtre son domaine par `company_id`.
- Aucune `ir.rule` ne vise `account.journal` dans les deux modules ; le cloisonnement par société de ce modèle repose entièrement sur le module `account` standard, hors périmètre de ce dépôt.
- Le pattern de partage optionnel `scope` (`single_company`/`multi_company`) existant pour `microfinance.fond.credit`/`microfinance.fond.contribution` n'a pas d'équivalent pour `account.journal` ou tout autre modèle lié à la caisse : aucun mécanisme de caisse partagée entre agences n'existe.
- Aucun rapport, vue liste/pivot ou état imprimable agrégeant les mouvements de caisse (dépôts, retraits, décaissements, remboursements) filtrable par journal, agence et période n'a été trouvé. La vue de recherche `microfinance.savings.transaction` ne propose ni filtre ni regroupement par journal, société ou période. Aucune vue de recherche dédiée n'existe pour `microfinance.loan.payment`.
- Aucun équivalent d'un « Rapport Flux de Caisse » LPF n'existe, y compris dans le dashboard (contrôlé après le commit `a58034a`) : les séries mensuelles du dashboard agrègent décaissements/remboursements par portefeuille de crédits, pas par journal caisse/banque.
- Le bouton `action_post` du remboursement (`microfinance_loan_payment_views.xml:17`) n'est conditionné par aucun `groups=` de vue ; seule la couche `ir.model.access.csv` régule qui peut effectivement l'exécuter.
- `group_microfinance_cashier` n'a aucun accès (ni lecture ni écriture) à `microfinance.loan.product`, donc ne peut pas consulter la configuration des journaux de décaissement/remboursement/frais depuis ce groupe.

## 8. Questions ouvertes pour la phase de conception

- Le modèle `res.company` doit-il continuer à représenter directement une agence, ou une distinction société/agence plus fine est-elle nécessaire ?
- Pour les sociétés n'utilisant pas le plan comptable `mg_pcec`, comment la création des journaux caisse/banque doit-elle être prise en charge ?
- Le journal `CRE`/`EPG` de type `'general'` doit-il rester la valeur par défaut de champs dont le domaine de vue exige `bank`/`cash`, ou cet écart de typage doit-il être traité ?
- Le champ `payment_method` (épargne) doit-il continuer d'exister sans effet sur la logique de comptabilisation, ou son rôle doit-il être clarifié ?
- Un compte d'attente chèques et un état transitoire pour les opérations par chèque sont-ils requis pour l'un ou l'autre module (crédit, épargne), et si oui pour quelles opérations précisément ?
- Un plafond de retrait/décaissement en espèces est-il requis côté crédit (décaissement, remboursement), à l'image de `withdrawal_limit_amount` côté épargne ?
- Le plafond de retrait épargne actuel (par transaction, sans cumul sur une période) correspond-il au comportement attendu, ou un cumul sur une période est-il souhaité ?
- Un contrôle de disponibilité du solde comptable réel du journal de décaissement/retrait (par opposition au solde du fonds bailleur) est-il requis avant de comptabiliser une sortie de caisse ?
- Un mécanisme de rapprochement caisse/banque est-il attendu dans le périmètre de la consolidation à venir ?
- Le contrôle de mot de passe gérant pour les retraits sur fonds de garantie, présent dans LPF, doit-il être réintroduit, et sous quelle forme (champ dédié, groupe de sécurité, autre) ?
- Le cloisonnement par agence des journaux caisse/banque doit-il être renforcé par un domaine explicite `company_id` et/ou une `ir.rule` dédiée à `account.journal`, ou le comportement standard Odoo actuel est-il jugé suffisant ?
- Un mécanisme de caisse partagée entre agences (à l'image du pattern `scope` des fonds bailleurs) est-il souhaité pour un ou plusieurs journaux caisse/banque ?
- Un rapport « Flux de Caisse » consolidé (par journal, agence, période) est-il à construire comme nouvel état, ou comme extension du dashboard existant ?
- `group_microfinance_cashier` doit-il obtenir un accès en lecture à `microfinance.loan.product` (pour consulter la configuration des journaux), ou cet accès doit-il rester réservé aux managers ?
- Le bouton `action_post` du remboursement doit-il être explicitement conditionné par un groupe de sécurité (caissier/finance/manager), à l'image de `action_disburse` ?
