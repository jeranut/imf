# Workflow Comptabilité

## 1. Objectif métier
Ce workflow couvre le volet comptable des crédits et de l'épargne : décaissement d'un crédit approuvé (écriture `account.move`), encaissement des frais de dossier, enregistrement et comptabilisation des remboursements (allocation pénalité → intérêt → capital, puis écriture), annulation par contre-passation d'un remboursement déjà comptabilisé, radiation (write-off) d'un crédit, provisionnement comptable périodique du portefeuille, et les transactions d'épargne (dépôt, retrait, intérêt crédité, frais, prélèvement automatique, virement) avec leur comptabilisation. Il couvre les modèles `microfinance.loan` (volet comptable uniquement), `microfinance.loan.payment` et `microfinance.savings.transaction`.

N'est PAS couvert ici : le cycle de validation d'une demande de crédit avant décaissement (`draft` → `approved`, workflow `dossier_precredit`) ; le calcul et l'analyse du portefeuille à risque du point de vue reporting/recouvrement — état des échéances, visites terrain, tableaux d'analyse (workflow `par_reporting`, qui documente en détail `microfinance.loan.installment` et le champ `overdue_amount`) ; le paramétrage des comptes PCEC et journaux sur les produits (workflows `creation_produit_credit` / `creation_produit_epargne`).

## 2. Utilisateurs concernés
D'après `microfinance_loan_management/security/groups.xml` et les deux `ir.model.access.csv` :
- **Agent crédit** (`group_microfinance_user`) : lecture seule sur les remboursements et échéances ; peut ouvrir l'assistant de remboursement (accès complet sur le wizard, transitoire).
- **Manager crédit** (`group_microfinance_manager`) : accès complet aux remboursements, aux assistants d'annulation et de radiation ; seul groupe (avec Finance) autorisé à radier ou rééchelonner.
- **Finance microfinance** (`group_microfinance_finance`) : lecture/écriture/création sur les remboursements ; seul groupe (avec Manager pour la radiation) autorisé à encaisser les frais de dossier et à décaisser un crédit (boutons réservés `groups=`).
- **Comptable** (`group_microfinance_comptable`) : lecture seule sur `microfinance.loan` (`loan.comptable`) et `microfinance.loan.product` (`loan.product.comptable`).
- **Caissier** (`group_microfinance_cashier`, implique `group_microfinance_user`) : lecture/écriture/création sur les remboursements (`payment.cashier`), lecture seule sur les crédits (`loan.cashier`).
- **Comité de crédit** (`group_microfinance_credit_committee`) : lecture seule sur les crédits (`loan.credit_committee`), pas d'accès dédié aux remboursements.
- **Agent épargne** (`group_savings_agent`, module MSM) : lecture/écriture/création sur les transactions d'épargne.
- **Manager épargne** (`group_savings_manager`) : accès complet aux transactions d'épargne.
- **Auditeur microfinance** (`group_microfinance_auditor`) : lecture seule sur les crédits et sur les transactions d'épargne (`savings.transaction.auditor`).

## 3. Menus utilisés
Depuis `microfinance_loan_management/views/microfinance_menus.xml` et `microfinance_savings_management/views/microfinance_savings_menus.xml` :
- Microfinance > Crédits > Demande de crédit (`menu_microfinance_loans`, parent `menu_credits_root`, action `action_microfinance_loan`) — formulaire crédit portant les boutons de décaissement/frais/radiation.
- Microfinance > Crédits > Échéances (`menu_microfinance_installments`, parent `menu_credits_root`, action `action_microfinance_installment`).
- Microfinance > Crédits > Remboursements (`menu_microfinance_payments`, parent `menu_credits_root`, action `action_microfinance_payment`).
- Microfinance > Épargne > Transactions épargne (`menu_microfinance_savings_transactions`, parent `microfinance_loan_management.menu_epargne_root`, action `action_microfinance_savings_transaction`).

`menu_credits_root` et `menu_epargne_root` sont eux-mêmes enfants de `menu_microfinance_root` (racine "Microfinance").

## 4. Étapes principales

**A. Décaissement d'un crédit approuvé**
1. Si le produit facture les frais de dossier avant décaissement (`fee_charged_before_disbursement=True`) et que des frais sont dus, cliquer « Encaisser les frais de dossier » (`action_charge_fee`) sur la fiche crédit → crée et poste une écriture d'encaissement des frais, `fee_paid=True`.
2. Cliquer « Activer / Décaisser » (`action_disburse`) → génère l'échéancier si absent, crée et poste l'écriture de décaissement, passe le crédit en `active` et renseigne `disbursement_date`.

**B. Remboursement**
1. Depuis la fiche crédit (`active`/`defaulted`), cliquer « Enregistrer remboursement » (`action_open_payment_wizard`) → ouvre l'assistant `microfinance.loan.payment.wizard`.
2. Saisir montant, date, journal, note ; « Comptabiliser maintenant » (`post_now`) est cochée par défaut ; cliquer « Valider » (`action_create_payment`) → crée le `microfinance.loan.payment` (`draft`) puis, si `post_now`, appelle immédiatement `action_post`.
3. `action_post` alloue le montant échéance par échéance (pénalité → intérêt → capital, échéances triées par date puis séquence), crée et poste l'écriture de remboursement, passe le paiement en `posted` ; si le solde du crédit atteint 0, le crédit est automatiquement clôturé (`action_close`).
4. Alternative : depuis le menu Remboursements, ouvrir un paiement `draft` existant et cliquer « Comptabiliser » (`action_post`) directement.

**C. Annulation d'un remboursement comptabilisé**
1. Depuis la fiche du remboursement (`posted`), cliquer « Annuler (contre-passation) » (`action_open_cancel_wizard`, réservé aux groupes Manager/Finance) → ouvre `microfinance.loan.payment.cancel.wizard`.
2. Saisir le motif (obligatoire) et cliquer « Confirmer l'annulation » (`action_confirm`) → appelle `action_cancel(reason)` → `_reverse_posted_payment` : contre-passe l'écriture d'origine (`move._reverse_moves`), restitue aux échéances les montants alloués, repasse le crédit en `active` s'il avait été clôturé automatiquement, passe le paiement en `cancelled`.

**D. Radiation (write-off) d'un crédit**
1. Depuis la fiche crédit (`active`/`defaulted`), cliquer « Radier » (`action_write_off`, groupes Manager/Finance) → ouvre `microfinance.loan.writeoff.wizard`.
2. Saisir la date de radiation et le motif (obligatoire), cliquer « Radier » (`action_confirm`) → appelle `action_confirm_write_off` : crée et poste une écriture de perte sur créance pour le solde restant, passe le crédit en `written_off`.

**E. Provisionnement comptable**
1. Depuis Microfinance > Crédits > Demande de crédit, en vue liste, sélectionner un ou plusieurs crédits puis utiliser le menu Actions > « Comptabiliser les provisions » (réservé aux groupes Manager/Finance) ; le provisionnement peut aussi être exécuté par une tâche planifiée périodique prévue à cet effet.
2. Pour chaque crédit dont la provision requise (`provision_amount`) diffère de la provision déjà comptabilisée (`provision_posted_amount`), crée et poste une écriture de dotation (delta positif) ou de reprise (delta négatif), puis met à jour `provision_posted_amount`.

**F. Transaction d'épargne**
1. Depuis Microfinance > Épargne > Transactions épargne, créer une transaction (dépôt, retrait, intérêt crédité, frais prélevés, prélèvement automatique, virement), état `draft`.
2. Cliquer « Comptabiliser » (`action_post`) → crée et poste l'écriture correspondant au type (comptes de contrepartie différents selon dépôt/retrait), passe la transaction en `posted`.
3. Un prélèvement automatique (`auto_debit`) peut aussi être généré par le cron `cron_process_savings_auto_debit` (module MSM) via `_process_savings_auto_debit` : il crée à la fois la transaction d'épargne et le remboursement crédit lié (`related_loan_payment_id`).
4. Une fois `posted`, imprimer le reçu via le bouton « Imprimer le reçu ».

## 5. Champs importants

**`microfinance.loan` (volet comptable)**
- `move_ids` : écritures comptables liées (décaissement, frais, remboursements, radiation, provisions).
- `fee_move_id` : écriture d'encaissement des frais de dossier.
- `fee_amount_due` / `fee_paid` : montant de frais dû (calculé selon le type fixe/taux du produit) et indicateur d'encaissement.
- `net_disbursed_amount` : montant réellement remis en caisse (= `loan_amount` sauf si les frais sont nettés du décaissement).
- `provision_amount` (calculé) / `provision_posted_amount` : provision requise recalculée vs. provision déjà comptabilisée.
- `balance_total`, `overdue_amount` : soldes utilisés par les contrôles de surpaiement et par le calcul de provision (détaillés dans `par_reporting`).

**`microfinance.loan.payment`**
- `loan_id`, `partner_id` (related), `payment_date`, `amount`, `journal_id` (domaine `bank`/`cash`).
- `allocated_penalty`, `allocated_interest`, `allocated_principal` : ventilation calculée par `_allocate_to_installments`.
- `move_id` : écriture de remboursement ; `reversal_move_id` : écriture de contre-passation le cas échéant.
- `installment_ids` : échéances touchées par ce paiement.
- `payment_origin` (ajouté par MSM) : Manuel / Prélèvement automatique sur épargne.

**`microfinance.savings.transaction`**
- `account_id`, `transaction_type` (Dépôt / Retrait / Intérêt crédité / Frais prélevés / Prélèvement automatique / Virement), `amount`, `date`, `payment_method`.
- `bypass_min_balance` : autorise un retrait à descendre sous le solde minimum du produit (clôture de compte, prélèvement automatique autorisé).
- `move_id` : écriture générée ; `related_loan_payment_id` : remboursement crédit lié (uniquement pour `auto_debit`).

**Assistants**
- Wizard remboursement : `loan_id`, `amount`, `payment_date`, `journal_id`, `note`, `post_now`.
- Wizard annulation : `payment_id` (lecture seule), `reason` (obligatoire).
- Wizard radiation : `loan_id` (lecture seule), `balance_total` (related, lecture seule), `write_off_date`, `reason` (obligatoire).

## 6. Boutons et actions
Sur le formulaire crédit (`microfinance_loan_views.xml`) :
- `action_charge_fee` (« Encaisser les frais de dossier ») — groupe Finance, `invisible="state != 'approved' or fee_paid or fee_amount_due <= 0"`.
- `action_disburse` (« Activer / Décaisser ») — groupe Finance, `invisible="state != 'approved'"`.
- `action_open_payment_wizard` (« Enregistrer remboursement ») — `invisible="state not in ('active','defaulted')"`.
- `action_write_off` (« Radier ») — groupes Manager/Finance, `invisible="state not in ('active','defaulted')"`.
- Boutons statistiques : `action_view_payments`, `action_view_moves`, `action_view_installments` (compteurs `payment_count`, `move_count`, `installment_count`).
- `action_post_provisions` (« Comptabiliser les provisions ») — accessible depuis le menu Actions de la vue liste des crédits, réservé aux groupes Manager/Finance ; peut aussi être exécuté par une tâche planifiée périodique.

Sur le formulaire remboursement (`microfinance_loan_payment_views.xml`) :
- `action_post` (« Comptabiliser ») — `invisible="state != 'draft'"`.
- `action_cancel` (« Annuler ») — `invisible="state != 'draft'"` (annulation directe, sans contre-passation, uniquement en brouillon).
- `action_open_cancel_wizard` (« Annuler (contre-passation) ») — groupes Manager/Finance, `invisible="state != 'posted'"`.

Sur le formulaire échéance (`microfinance_loan_installment_views.xml`) : `action_apply_penalty` (« Appliquer pénalité »), `invisible="penalty_applied"` (détaillé dans `par_reporting`).

Sur le formulaire transaction d'épargne : `action_post` (« Comptabiliser »), `invisible="state != 'draft'"` ; bouton d'impression `%(action_report_microfinance_savings_receipt)d`, `invisible="state != 'posted'"`.

Assistants : `action_create_payment` (wizard remboursement), `action_confirm` (wizards annulation et radiation, homonymes sur deux modèles différents).

## 7. Règles métier
- `@api.constrains('amount')` sur `microfinance.loan.payment` et sur `microfinance.savings.transaction` : le montant doit être strictement positif.
- `_allocate_to_installments` : ventilation stricte pénalité → intérêt → capital, échéance par échéance dans l'ordre chronologique (`due_date`, `sequence`), en ne dépassant jamais le résiduel dû de chaque poste.
- Surpaiement interdit : un remboursement ne peut pas dépasser `loan_id.balance_total` (+0.01 de tolérance).
- `_compute_net_disbursed_amount` : si le produit ne facture pas les frais avant décaissement, `net_disbursed_amount = loan_amount - fee_amount_due` (les frais sont nettés directement dans l'écriture de décaissement, sur le compte `account_commission_credit_id`) ; sinon `net_disbursed_amount = loan_amount` (frais encaissés séparément via `action_charge_fee`). Le capital dû (`loan_amount`) reste toujours plein.
- `_compute_provision` : le taux de provision applicable est recherché dans `microfinance.provision.rule` selon le nombre de jours de retard maximal du crédit (`_get_max_overdue_days`) et la société ; `provision_amount = min(balance_total * taux / 100, balance_total)`. Nul si le crédit n'est pas `active`/`defaulted`.
- `_reverse_posted_payment` restitue les montants alloués aux échéances les plus récemment touchées en premier (ordre inverse de l'allocation initiale) et vérifie que la date de l'écriture d'origine n'est pas dans une période verrouillée (`move._check_fiscalyear_lock_date()`) avant toute contre-passation.
- Comptabilisation des transactions d'épargne : compte de contrepartie différent selon le type — journal de dépôt/retrait du produit pour dépôt/retrait/virement, compte `account_interet_paye` pour l'intérêt crédité, compte `account_commission_id` pour les frais prélevés.
- `action_post` (remboursement) et `action_post` (transaction) sont idempotents côté état : ils ignorent silencieusement (`continue`) tout enregistrement déjà différent de `draft`.

## 8. Contrôles et blocages
- « Le crédit doit être approuvé avant décaissement. » (`action_disburse`, `state != 'approved'`).
- « Les frais de dossier doivent être encaissés avant le décaissement. » (produit à frais préalables, `fee_paid=False`, `fee_amount_due>0`).
- « Les frais de dossier ne peuvent être encaissés que sur un crédit approuvé. » / « Les frais de dossier ont déjà été encaissés. » / « Aucun frais de dossier à encaisser pour ce crédit. » (`action_charge_fee`).
- « Configurez le journal de décaissement, son compte par défaut et le compte principal en cours du produit. » / « Configurez le journal d'encaissement des frais... » / « Configurez le compte commission sur crédit du produit pour netter les frais... » (comptes PCEC manquants).
- « Le crédit doit être actif ou en défaut pour enregistrer un remboursement. » (`_allocate_to_installments`).
- « Surpaiement interdit. Solde restant : %.2f » (montant du remboursement > solde restant).
- « Le montant du remboursement doit être positif. » / « Le montant de la transaction doit être positif. »
- « Le journal de paiement doit avoir un compte par défaut. » (`_prepare_payment_move`).
- « Configurez le compte pénalités crédits du produit pour comptabiliser ce remboursement. » (si une pénalité est allouée mais le compte n'est pas configuré).
- « Le motif d'annulation est obligatoire. » / « Le motif de radiation est obligatoire. » (wizards).
- « La radiation n'est possible que pour un crédit actif ou en défaut. » / « Aucun solde restant à radier. Utilisez la clôture normale. » (`action_write_off` / `action_confirm_write_off`).
- « Configurez le compte de crédits passés en perte pour ce produit avant de radier ce crédit. » / « Aucun journal des opérations diverses n'est configuré pour cette société. »
- « Configurez les comptes de provision (coût et contrepartie) pour le produit... » (`action_post_provisions`).
- « Retrait refusé : le solde après retrait (%.2f) descendrait sous le solde minimum du produit (%.2f). » (`_check_minimum_balance`, sauf `bypass_min_balance`).
- « Les retraits ne sont autorisés que sur un compte épargne actif. » / « Dépôt impossible sur un compte clôturé ou dormant. » (`action_post` transaction, selon `account_id.state`).
- « Configurez le compte épargne sur le produit... » / « Configurez le compte intérêt payé... » / « Configurez le compte commission sur épargne... » / « Configurez le journal de dépôt/retrait et son compte par défaut... » (comptes PCEC épargne manquants).
- « Impossible de clôturer : solde restant à payer. » (`action_close`, appelé automatiquement en fin de remboursement si le solde n'est pas nul).

## 9. Statuts
**`microfinance.loan.payment.state`** : `draft` (Brouillon) → `posted` (Comptabilisé) via `action_post` → `cancelled` (Annulé) via `action_cancel` (directement si encore `draft`) ou via `action_open_cancel_wizard`/`action_confirm` (contre-passation, uniquement si `posted`).

**`microfinance.savings.transaction.state`** : `draft` (Brouillon) → `posted` (Comptabilisé) via `action_post`.

**`microfinance.loan.state`** (rappel, machine à états complète documentée dans `dossier_precredit`) : les actions de ce workflow ne pilotent que les transitions `approved` → `active` (`action_disburse`), `active`/`defaulted` → `written_off` (`action_confirm_write_off`), et `active`/`defaulted` → `closed` (`action_close`, appelé automatiquement quand `balance_total` atteint 0 après un remboursement).

## 10. Rapports ou PDF
- « Reçu de décaissement » (`action_report_microfinance_loan_disbursement_receipt`, modèle `microfinance.loan`) : numéro de crédit, emprunteur, produit, montant accordé, frais prélevés et montant net remis (si différents), date de décaissement, méthode/taux d'intérêt, nombre d'échéances, journal de décaissement, zones de signature agent/emprunteur.
- « Reçu de transaction épargne » (`action_report_microfinance_savings_receipt`, modèle `microfinance.savings.transaction`) : compte, titulaire, produit, type de transaction, montant, date, moyen de paiement, solde après transaction, zones de signature agent/titulaire.

## 11. Tableaux de bord
Dans `microfinance.dashboard` / contrôleur `/microfinance/dashboard/data` :
- KPI « Montant décaissé » (`disbursed_amount`, somme de `loan_amount` des crédits `active`/`closed`/`defaulted`).
- Graphique barres mensuel des décaissements (`monthly.disbursement`, 12 derniers mois, basé sur `disbursement_date`).
- Graphique ligne « Remboursements » vs « Impayés » (`monthly.repayment` basé sur les paiements `posted`, `monthly.overdue` basé sur les échéances `overdue` — ce second indicateur est détaillé dans `par_reporting`).

## 12. Sécurité et groupes utilisateurs

**`microfinance.loan.payment`** (`microfinance_loan_management/security/ir.model.access.csv`)

| Groupe | Lecture | Écriture | Création | Suppression |
|---|---|---|---|---|
| Agent crédit (`group_microfinance_user`) | Oui | Non | Non | Non |
| Finance microfinance (`group_microfinance_finance`) | Oui | Oui | Oui | Non |
| Manager crédit (`group_microfinance_manager`) | Oui | Oui | Oui | Oui |
| Caissier (`group_microfinance_cashier`) | Oui | Oui | Oui | Non |

**`microfinance.loan`** (lignes pertinentes pour ce workflow)

| Groupe | Lecture | Écriture | Création | Suppression |
|---|---|---|---|---|
| Comptable (`group_microfinance_comptable`) | Oui | Non | Non | Non |
| Caissier (`group_microfinance_cashier`) | Oui | Non | Non | Non |

**`microfinance.loan.product`** (ligne Comptable)

| Groupe | Lecture | Écriture | Création | Suppression |
|---|---|---|---|---|
| Comptable (`group_microfinance_comptable`) | Oui | Non | Non | Non |

**Assistants**

| Modèle | Groupe | Lecture | Écriture | Création | Suppression |
|---|---|---|---|---|---|
| `microfinance.loan.payment.wizard` | Agent crédit (`group_microfinance_user`) | Oui | Oui | Oui | Oui |
| `microfinance.loan.writeoff.wizard` | Manager crédit / Finance | Oui | Oui | Oui | Oui |
| `microfinance.loan.payment.cancel.wizard` | Manager crédit / Finance | Oui | Oui | Oui | Oui |

**`microfinance.savings.transaction`** (`microfinance_savings_management/security/ir.model.access.csv`)

| Groupe | Lecture | Écriture | Création | Suppression |
|---|---|---|---|---|
| Agent épargne (`group_savings_agent`) | Oui | Oui | Oui | Non |
| Manager épargne (`group_savings_manager`) | Oui | Oui | Oui | Oui |
| Manager crédit (`microfinance_loan_management.group_microfinance_manager`) | Oui | Non | Non | Non |
| Auditeur microfinance (`microfinance_loan_management.group_microfinance_auditor`) | Oui | Non | Non | Non |

## 13. Cas d'utilisation complets
1. **Décaissement avec frais préalables.** Un utilisateur Finance ouvre Microfinance > Crédits > Demande de crédit sur un dossier `approved` avec frais dus. Il clique « Encaisser les frais de dossier » (écriture de frais postée, `fee_paid=True`), puis « Activer / Décaisser » (l'échéancier est généré si besoin, l'écriture de décaissement est postée, le crédit passe en `Actif`).
2. **Remboursement et clôture automatique.** Un agent ouvre le crédit `Actif`, clique « Enregistrer remboursement », saisit le montant correspondant au solde restant, laisse « Comptabiliser maintenant » coché et valide : le paiement est créé, alloué (pénalité/intérêt/capital), comptabilisé, et le crédit passe automatiquement en `Clôturé` car le solde atteint 0.
3. **Annulation d'un remboursement erroné.** Un Manager ouvre le remboursement `Comptabilisé` concerné depuis Microfinance > Crédits > Remboursements, clique « Annuler (contre-passation) », saisit le motif, confirme : l'écriture d'origine est contre-passée, les montants sont restitués aux échéances, le paiement passe en `Annulé` (et le crédit repasse en `Actif` s'il avait été clôturé automatiquement par ce paiement).
4. **Radiation d'un crédit en défaut.** Un Manager ouvre un crédit `En défaut`, clique « Radier », saisit la date et le motif dans l'assistant, confirme : une écriture de perte sur créance est postée pour le solde restant et le crédit passe en `Radié`.
5. **Dépôt d'épargne.** Un agent épargne crée une transaction de type « Dépôt » sur le compte du client, saisit le montant et le moyen de paiement, clique « Comptabiliser » : l'écriture est postée, la transaction passe en `Comptabilisé`, le reçu peut être imprimé.

## 14. Erreurs fréquentes
Voir la liste complète en section 8. Les plus courantes en usage quotidien : « Surpaiement interdit. Solde restant : %.2f » (montant de remboursement saisi trop élevé), « Le crédit doit être actif ou en défaut pour enregistrer un remboursement. » (tentative de paiement sur un crédit non décaissé ou déjà clôturé/radié), « Le motif d'annulation est obligatoire. » / « Le motif de radiation est obligatoire. » (champ texte vide dans les assistants), et les messages « Configurez le compte/journal... » lorsque le produit de crédit ou d'épargne n'a pas tous ses comptes PCEC renseignés.

## 15. Bonnes pratiques
- Vérifier la configuration comptable complète du produit (journaux de décaissement/paiement/dépôt/retrait, comptes principal/intérêts/pénalités/provision/perte) avant la première utilisation en production, pour éviter les blocages `UserError` au moment du décaissement ou du remboursement.
- Toujours passer par l'assistant d'annulation (`action_open_cancel_wizard`) pour un remboursement `posted`, plutôt que de tenter une suppression manuelle : c'est le seul chemin qui contre-passe l'écriture et restitue correctement les montants aux échéances.
- Réserver la radiation et l'encaissement des frais/décaissement aux groupes Manager/Finance conformément aux restrictions `groups=` posées sur les boutons, plutôt que de contourner via l'accès technique au modèle.
- Exécuter le provisionnement (`action_post_provisions`) régulièrement (ou vérifier que le cron `cron_post_provisions` est actif) afin que `provision_posted_amount` reste synchronisé avec le risque réel du portefeuille.

## 16. Questions/Réponses MOWGLI potentielles
1. Comment décaisser un crédit approuvé dans MOWGLI ?
2. Pourquoi le bouton Décaisser n'apparaît-il pas sur ce dossier ?
3. Comment enregistrer un remboursement et voir la ventilation entre capital, intérêt et pénalité ?
4. Comment annuler un remboursement déjà comptabilisé sans casser la comptabilité ?
5. Quelles sont les étapes pour radier un crédit irrécouvrable ?
6. Pourquoi le système me dit « Surpaiement interdit » sur ce remboursement ?
7. Comment se déclenche le provisionnement comptable des crédits ?
8. Comment enregistrer un dépôt ou un retrait sur un compte épargne et imprimer le reçu ?
9. Qui peut encaisser les frais de dossier ou décaisser un crédit ?
10. Pourquoi un crédit se clôture-t-il automatiquement après un remboursement ?
