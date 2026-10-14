# Reprise de portefeuille — audit (lecture seule)

Base **MOWGLI**, relevé du 2026-10-10. **Aucun code, aucune vue, aucune donnée de MOWGLI n'a été modifié.** Seule trace
hors dépôt : une copie jetable de MOWGLI (`MOWGLI_audit_repr`) a servi à vérifier huit comportements par des créations
annulées (rollback) ; elle est supprimée. Les constats « vérifié » ci-dessous viennent de ces essais, les autres de la
lecture du code.

Modules : `microfinance_loan_management` (L), `microfinance_savings_management` (S). Prérequis : balance d'ouverture
comptable (V1) déjà déployée — voir [STATUS.md](STATUS.md) et [AUDIT_existant.md](AUDIT_existant.md).

## 0. Écarts entre l'énoncé et le code actuel (à lire d'abord)

| # | L'énoncé suppose | Le code / les données réels | Effet |
|---|---|---|---|
| E1 | Type de client « individuel / groupe » → 203001 / 203002 et 213001 / 213002 | `res.partner.microfinance_client_type` n'a que **`individual` et `company`** (`ir_model_fields_selection`, MOWGLI). Le code de comptes teste `== 'group'` ([microfinance_loan_product.py:484](../../microfinance_loan_management/models/microfinance_loan_product.py#L484)) mais la valeur n'existe pas. Aucun client groupe, 0 ligne `microfinance_client_group_member`. | **203002 et 213002 sont inatteignables**. `company` → 203001 (crédit) mais **213003** (épargne). Voir décision D1. |
| E2 | Épargne = « conteneur » IS/I/N portant un solde | Depuis la scission ([epargne_split/STATUS.md](../epargne_split/STATUS.md)) : *compte épargne* (`microfinance.savings.holder.account`, nom `CE/<n° compte crédit>`) qui regroupe des **produits souscrits** (`microfinance.savings.account`, nom `CE/AG3/000020-01`). **Le solde est porté par le produit souscrit**, le compte n'en est que la somme. | L'onglet Épargne cible un *produit souscrit*, pas le conteneur. |
| E3 | Crédit « IS/N » et conteneur « IS/I/N » au même N | Le crédit prend `AGENCE/N` d'une séquence **propre** (`microfinance.loan.agency`) ; le compte crédit et le compte épargne reprennent le **n° permanent du client** (`microfinance.partner.account`). Vérifié : client `AG3/000020`, compte épargne `CE/AG3/000020`, mais premier crédit `AG3/000021`. Les séquences ne sont **pas transactionnelles** (essais annulés : numéros consommés). | La règle n'est vraie que pour compte crédit ↔ compte épargne (déjà garantie par `_name_from_loan_account`). Crédit = même N : voir D2. |
| E4 | Gabarit : crédits de 1 000 000 et 2 000 000 | Produits actifs d'Analakely (société 9) : « PP 500 000 » max **500 000**, « PRET STAFF » max **1 000 000**. `_check_product_limits` ([L:653](../../microfinance_loan_management/models/microfinance_loan.py#L653)) contrôle `loan_amount` (= principal **initial**). Vérifié : 1 000 000 sur « PP 500 000 » → « Le montant doit respecter les limites du produit ». | Le client B (2 000 000) n'entre dans aucun produit existant de la 9. Voir D3. |
| E5 | « Référence client » comme clé d'idempotence | L'onglet Clients n'a pas de colonne référence. Il existe `res.partner.microfinance_internal_reference` ([res_partner.py:223](../../microfinance_loan_management/models/res_partner.py#L223)), **sans contrainte d'unicité** (vérifié : deux clients avec `CLI-A` acceptés). | Ajouter la colonne « Référence client » et la rendre unique **par société dans l'import**. |
| E6 | « Menu Comptabilité > Balance d'ouverture > Reprise de portefeuille » | « Balance d'ouverture » est une **entrée feuille** (action directe) sous `account.menu_finance_entries`, séq. 6 ([views:149](../../microfinance_loan_management/views/microfinance_opening_balance_views.xml#L149)). | Entrée sœur recommandée (séq. 6, juste après) plutôt que transformer la feuille en dossier. |

## 1. Chemins de création actuels

### 1.1 Client (`res.partner`, `microfinance_context`)
- Garde-fou **création directe** ([res_partner.py:508](../../microfinance_loan_management/models/res_partner.py#L508)) : sous `microfinance_context`, un client (`microfinance_partner_type='client'`) ne se crée que si le contexte porte `allow_microfinance_partner_create`. Le flag est une clé de contexte (forgeable en RPC, point ouvert déjà documenté dans [clients_portefeuille/STATUS.md](../clients_portefeuille/STATUS.md)) ; l'assistant le posera **côté serveur**, jamais depuis le client web.
- Règle **portefeuille** ([res_partner.py:79](../../microfinance_loan_management/models/res_partner.py#L79)) : avec le flag, `microfinance_officer_id` (vals ou `default_`) doit avoir un `microfinance.portfolio` **actif** dans la société du client. Agents actifs aujourd'hui : société 9 → `jeranutmickael@gmail.com` (id 2) et `ccl1@andohar.com` (363) ; 11 → `marin@ampaly.com` (8) ; **société 1 : aucun portefeuille** (donc aucun client importable dans l'agence 1 tant qu'il n'y en a pas).
- Règle **inter-agences** : `create` et `write` (CIN, type de pièce, société) appellent `_check_no_active_loan_elsewhere(cin, company_id)` ([L:481](../../microfinance_loan_management/models/res_partner.py#L481)), en `sudo()` ciblé, états `('active','defaulted')`.
- Contraintes : société obligatoire ([L:150](../../microfinance_loan_management/models/res_partner.py#L157)) ; **CIN obligatoire, 12 chiffres** pour un particulier client ([L:166](../../microfinance_loan_management/models/res_partner.py#L166), `_check_cin_format`) ; conjoint + téléphone obligatoires si « marié(e) ».
- Séquence : `microfinance_account_number` = `AGENCE/NNNNNN` (séquence `microfinance.partner.account`, par société), attribué une fois à la création.
- Hooks post-création : `_get_or_create_microfinance_loan_account()` (compte crédit, même transaction) puis, côté S, `_get_or_create_microfinance_savings_container()` ([S res_partner.py](../../microfinance_savings_management/models/res_partner.py)). **Créer le client crée donc déjà le compte crédit et le compte épargne** ; l'import n'a rien à créer de plus pour les conteneurs. Vérifié : `AG3/000020` → compte crédit `AG3/000020` et compte épargne `CE/AG3/000020`.
- Un client existant (42 aujourd'hui, tous « individual », sociétés 1, 2, 3, 4, 6, 8, 9, 11) n'a **aucun** compte crédit ni compte épargne (tables vides) ; ils se créent au premier crédit (`_get_or_create_microfinance_loan_account` dans `loan.create`) ou au premier produit d'épargne.

### 1.2 Compte épargne (conteneur) — `microfinance.savings.holder.account`
`_get_or_create_for(partner, company)` ([S holder_account.py](../../microfinance_savings_management/models/microfinance_savings_holder_account.py)) : idempotent, sudo interne, unicité `(partner, company)` et `name`. Nom = `<préfixe société, défaut CE>/<nom du compte crédit>`. Aucune création directe possible par l'utilisateur (pas de droit create).

### 1.3 Crédit — `microfinance.loan`
- États : `draft → enquete → avis_ca → avis_cdag → approved → active → closed / defaulted / written_off / cancelled`.
- Obligatoires (NOT NULL / `required`) : `partner_id`, `product_id`, `company_id`, `loan_amount`, `term`, `application_date` (défaut), `currency_id` (défaut), `name` (séquence `AGENCE/N`, `microfinance.loan.agency`).
- `create` ([L:401](../../microfinance_loan_management/models/microfinance_loan.py#L401)) : numérote, vérifie l'inter-agences, attribue le n° permanent du client, rattache le compte crédit. **Ne génère pas d'échéancier** ; `write` ([L:550](../../microfinance_loan_management/models/microfinance_loan.py#L550)) en génère si l'état est modifiable (`draft…approved`) — **jamais en `active`**. Extensions : `microfinance_payroll_loan` (`officer_id` repris du client, retenue sur salaire), S (champs épargne garantie), `fond_separation` (contrainte fonds d'exploitation).
- Contraintes qui s'appliquent à un crédit créé directement en `active` : `_check_product_limits` (montant, **durée en mois = term × périodicité**), `_check_repayment_frequency_allowed`, `_check_fee_paid_before_activation_constrains` ([L:3453](../../microfinance_loan_management/models/microfinance_loan.py#L3453)), `_check_fond_credit_id_locked_after_disbursement` ([L:3270](../../microfinance_loan_management/models/microfinance_loan.py#L3270)).
- Droits : `loan` — agent (user) lecture/écriture/création ; **finance : lecture/écriture, pas de création** ; manager : tout. `installment` — agent lecture seule ; finance sans création ; manager tout ([ir.model.access.csv:23-41](../../microfinance_loan_management/security/ir.model.access.csv#L23)). Règle d'isolement : un agent ne voit que ses crédits (`officer_id = user.id`).

### 1.4 Compte (produit) d'épargne — `microfinance.savings.account`
- `create` ([S savings_account.py:100](../../microfinance_savings_management/models/microfinance_savings_account.py#L100)) : garde « attribution depuis la fiche client » (uniquement si le contexte `savings_menu_readonly` est posé), cohérence agence client/société, résolution ou création du compte épargne, rang réservé sous verrou, nom `<compte>-NN`. Obligatoires : `partner_id`, `company_id`, `product_id` (contrainte Python).
- `state` : `draft → active` ; `action_activate()` exige `balance ≥ min_opening_amount`.
- Droits : produit souscrit — agent lecture/écriture/création ; **transaction — agent lecture/écriture, pas de création** (création directe verrouillée hors guichet, [S ir.model.access.csv:11](../../microfinance_savings_management/security/ir.model.access.csv#L11)).

## 2. Crédit repris « réellement décaissé » — champs, états, réactions

### 2.1 Combinaison minimale (vérifiée par création sur copie)
`state='active'` **et** `disbursement_date` renseignée, avec `installment_ids` fournis à la création. Résultat vérifié :

| Observation | Valeur |
|---|---|
| Création acceptée sans passer par approbation / comité / activation | oui (`create` ne contrôle rien de tout cela) |
| `account.move` créées (décaissement, frais, engagement) | **0** (`move_ids` vide, total `account_move` inchangé) |
| `disbursement_move_id`, `fee_receivable_move_id`, `fee_move_id`, `fee_sent_to_cashier` | tous vides / `False` |
| Dans `get_pending_disbursements(9)` | **non** (exige `disbursement_date = False`) |
| Dans `get_pending_or_late` | non tant qu'aucune échéance n'est échue |
| Écriture / mouvement de caisse (`microfinance.caisse.mouvement`) | aucun (34 avant, 34 après) |
| Échéancier non régénéré à la création | confirmé (3 échéances fournies = 3 conservées) |

### 2.2 Pièges relevés
1. **Frais** : tous les produits sont `fee_charged_before_disbursement=True`. Sur un crédit créé directement en `active`, `_compute_fee_amount` lit la valeur *figée* en SQL (`state ∈ _FEE_FROZEN_STATES`) — la ligne n'a pas encore de valeur → **`fee_amount_due = 0.0`** (vérifié : 0.0 alors que « PP 500 000 » porte 5 %). La contrainte `_check_fee_paid_before_activation` passe donc **par accident**. À poser explicitement : `fee_paid=True` (pas d'écriture : c'est un simple booléen) pour ne pas dépendre de cet effet de bord. Conséquence d'affichage : frais de dossier à 0 sur les crédits repris (voulu).
2. **Fonds** : `_check_fond_credit_id_locked_after_disbursement` lève une erreur si `fond_credit_id` figure dans les valeurs d'une écriture alors que `disbursement_date` est posée, **y compris à la création**. Sans objet si on ne rattache aucun fonds (option b, §4) ; sinon il faut créer sans date puis écrire la date (vérifié : créer sans date puis `write(disbursement_date)` fonctionne).
3. **Limites produit** : voir E4. `loan_amount` = principal initial ; `term` = nombre d'échéances (restantes, faute d'autre donnée) et la contrainte de durée porte sur `term × périodicité`.
4. **Pas de dossier d'instruction** (`application_ids` vide), pas de contrat signé, pas de garantie : à vérifier côté rapports (contrat, carnet) mais sans effet sur les états ; `signed_contract` n'est exigé que par `action_process_disbursement`, que le crédit repris ne traverse jamais.
5. **Agent** : `officer_id` a pour défaut `env.user` ; à fournir explicitement (agent du fichier). Les règles d'isolement masquent le crédit à tout autre agent.

### 2.3 Tous les create / write / cron qui réagiraient à un crédit repris

| Mécanisme | Réaction | Écriture comptable ? | Action |
|---|---|---|---|
| `microfinance.loan.create` / `write` | numérotation, compte crédit ; `_SCHEDULE_TRIGGER_FIELDS` ne régénère pas en `active` | non | RAS |
| Contraintes ci-dessus | voir 2.2 | non | `fee_paid=True`, montant/durée dans les limites |
| `cron_update_overdue_and_penalties` (quotidien, actif) | marque les échéances échues `overdue`, applique les pénalités (montant écrit sur l'échéance, **sans écriture**), recalcule le score, rafraîchit `max_days_overdue` | non | si la 1ʳᵉ échéance reprise est dans le passé → arriérés artificiels dès la nuit suivante (vérifié : échéance à J−10 → `overdue`, `max_days_overdue = 10`) |
| `cron_post_provisions` (mensuel) | **inactif** dans MOWGLI (`active = f`) ; actif, il passerait des écritures de provision (`action_post_provisions`) sur tout crédit décaissé en retard | **oui si activé** | rien tant qu'il reste inactif ; à signaler |
| `cron_snapshot_portfolio_par` (mensuel) | instantané PAR par agent, inclut le crédit | non | RAS |
| `cron_release_ready_disbursements` | filtre `disbursement_date = False` → ignore | non | RAS |
| `cron_process_savings_auto_debit` (S) | seulement si `savings_account_id` renseigné et échéance en retard | oui (remboursement) | **ne pas** renseigner `savings_account_id` |
| `_compute_provision` | 0 tant que non décaissé ; avec `disbursement_date`, applique le barème (tranche 0-30 j = 0 %) | non (calcul seul) | RAS |
| `base.automation`, actions serveur sur ces modèles | aucune (table `base_automation` absente ; seules les actions serveur des crons) | — | RAS |
| `mf_trace` | ne couvre ni `microfinance.loan` ni `res.partner` | — | RAS |
| Fiche de caisse, solde de session | calculés depuis `account.move` / mouvements de caisse : aucune donnée | — | RAS |

## 3. Échéancier des seules échéances restantes

Données du fichier : principal restant `R`, nombre d'échéances restantes `n`, date de la prochaine échéance `D₁`, périodicité `f` (celle du produit si imposée).

Réutiliser **sans le modifier** ce qui existe, appelé sur le crédit créé (état `active`, sans échéance) :
- pas de période : `_period_delta()` ([L:2398](../../microfinance_loan_management/models/microfinance_loan.py#L2398)) → `D_i = _roll_forward_to_collection_day(D₁ + (i−1)·delta)` ([L:2426](../../microfinance_loan_management/models/microfinance_loan.py#L2426), jour de collecte `res.company.collection_day` : mardi pour la 9, lundi pour la 1, jeudi pour la 11 ; sans effet pour la périodicité journalière) ;
- principal : `R / n` arrondi à l'unité monétaire, **dernière échéance = reliquat exact** (somme = `R` au centime, comme `_build_installment_commands`) ;
- intérêt et pénalité : **0** en V1 (§7) ;
- création directe des lignes `microfinance.loan.installment` (`sequence`, `due_date`, `principal_amount`), `paid_*` à 0 : `balance_total` = Σ `residual_amount` = `R` (vérifié : 3 × 50 000 → 150 000 ; 4 × 50 000 → 200 000).

Ne **pas** appeler `action_generate_schedule` / `_build_installment_commands` : ils recalculent tout le crédit depuis `loan_amount`, `term` et la date de décaissement (historique entier, intérêts inclus) et `action_generate_schedule` refuse l'état `active`.

Contrôles du rapport d'erreurs : `D₁` ≥ date d'ouverture (sinon arriérés artificiels, §2.3) ; `D₁` sur le jour de collecte (sinon avertissement : la date est décalée par le roll-forward) ; `n ≥ 1` ; `R > 0` et `R ≤ principal initial`.

Autres effets de bord à connaître : les tuiles « décaissé ce mois » se basent sur `disbursement_date` et `loan_amount` (le principal **initial** compte comme décaissé dans le mois de la date de décaissement) ; `principal_total` du crédit = principal **restant** (somme des échéances), pas `loan_amount`.

## 4. Fonds de crédit — consommation par un crédit repris

État réel : **MOWGLI n'a aucun fonds** (`microfinance_fond_credit` vide) et une société mère est désignée (`allocation_required` vaut donc `True` par défaut pour tout nouveau fonds).

Mécanique :
- `_check_fond_disponibilite` ([L:3289](../../microfinance_loan_management/models/microfinance_loan.py#L3289)) n'est appelé **que** par `_check_activation_eligibility` (clic « Activer ») : une création directe en `active` ne l'exécute pas, il n'y a donc rien à « contourner » techniquement.
- La consommation d'un fonds ne dépend que de `fond_credit_id` : `solde_disponible = contributions − Σ principal restant des crédits approved/active du fonds`, et `montant_utilise` de l'allocation de l'agence (idem). Sans `fond_credit_id`, le crédit est invisible des fonds.
- `total_decaisse` du fonds additionne `loan_amount` des crédits décaissés rattachés (principal initial).

| | (a) Rattachés à un fonds + ajustement | (b) Hors fonds (recommandé) |
|---|---|---|
| Principe | `fond_credit_id` renseigné ; contribution d'ouverture + (fonds partagé) partage, allocation d'agence et répartition de portefeuille couvrant le principal repris | `fond_credit_id` vide, aucun contrôle de fonds |
| Gabarit (3 000 000 d'encours) | contribution d'ouverture **3 000 000** au moins ; sinon `solde_disponible` du fonds devient négatif | aucune |
| Code à écrire | contribution passée à `posted` sans `action_post` (sinon écriture sur le journal de fonds), allocations créées dans le contexte technique du partage, portefeuilles : ≈ 250-350 lignes, 4 modèles du module fonds, ≈ 8 tests (estimation) | 0 ligne spécifique |
| Risques | doublon avec les lignes « Fonds » de la balance d'ouverture (116000 / 240000 / 240xxx) : le fonds serait alimenté deux fois si la balance porte déjà le passif ; `total_decaisse` gonflé ; contournement du mécanisme de plafond par agent | `has_active_fond` : sans effet à la création ; le jour où un fonds actif existe, les **nouveaux** crédits restent contrôlés normalement et ne voient pas l'encours repris ; les KPI « fonds utilisé » ne contiennent pas la reprise |
| Cohérence comptable | écritures évitées par contournements ciblés, à tester | aucune écriture, rien à compenser |

**Recommandation : (b).** Le but est de faire concorder le *détail* avec une balance déjà posée ; le fonds est un mécanisme de plafonnement de nouveaux décaissements, pas un registre du passé. Rattacher la reprise au fonds ferait un deuxième enregistrement du passif déjà présent dans la balance d'ouverture. L'écart est documenté (pas de ventilation par fonds de l'encours repris) ; à reprendre plus tard si le comité veut un suivi par fonds.

## 5. Épargne — solde stocké ou calculé

- `microfinance.savings.account.balance` est **calculé et stocké** : Σ transactions `state='posted'` (`deposit` et `interest_credit` en positif, les autres en négatif), [S savings_account.py:146](../../microfinance_savings_management/models/microfinance_savings_account.py#L146). Le compte épargne (`holder`) somme ses produits non clôturés.
- Poser un solde d'ouverture sans écriture ni mouvement de caisse : **créer une `microfinance.savings.transaction` directement à `state='posted'`** (type `deposit`, `date` = date d'ouverture), sans appeler `action_post`. Vérifié sur copie : `move_id` vide, solde produit 250 000, solde du compte épargne 250 000, `account.move` inchangé (0), mouvements de caisse inchangés (34).
- Ensuite `action_activate()` (état `active`, `opening_date`) ; il vérifie `balance ≥ min_opening_amount` du produit (utile : un solde repris sous le minimum devient une ligne d'erreur).
- Pièges :
  - **Droits** : l'agent n'a pas `create` sur la transaction → création en `sudo()` ciblé dans l'assistant, après contrôle de société (même patron que `_run_posting_sudo`, [microfinance_caisse_mouvement.py:77](../../microfinance_savings_management/models/microfinance_caisse_mouvement.py#L77)).
  - **Montant modifiable** : la garde de `write` ne verrouille `amount` que si `move_id` est posé ([S transaction](../../microfinance_savings_management/models/microfinance_savings_transaction.py#L101)) ; une transaction d'ouverture sans pièce reste donc modifiable. À marquer (champ `opening_balance_id`) et verrouiller.
  - **Ordre chronologique** : `_check_transaction_date_order` refuse une date antérieure à la dernière transaction (vérifié) → la transaction d'ouverture doit être la première.
  - **Crons** : la capitalisation (mensuelle/trimestrielle/annuelle, actifs, prochain passage le 2026-10-12) crédite des intérêts **avec écriture comptable** sur les produits à taux > 0 ; la détection de dormance part de `last_transaction_date` (= date d'ouverture : ne pas dater l'ouverture plus de `savings_dormancy_months` avant l'import). Produits de MOWGLI en 1/9/11 : tous à 0 % → aucun effet aujourd'hui.
  - **Produit d'épargne ↔ compte GL** : `account_epargne_{individuel|groupe|entreprise}_id` selon le type du client (E1) ; produit « EP 1 » (société 9) → 213001 pour un particulier, 213003 pour une société.

## 6. Encours / PAR du dashboard

- Portefeuille agent et PAR : `state in ('active','defaulted')` **et** `disbursement_date` renseignée **et** `officer_id` renseigné ([L:1322](../../microfinance_loan_management/models/microfinance_loan.py#L1322), [L:1434](../../microfinance_loan_management/models/microfinance_loan.py#L1434), `get_par_buckets`). Un crédit repris dans ces conditions y entre.
- **L'encours du dashboard est `Σ balance_total`, c'est-à-dire principal + intérêts + pénalités restants** (somme des `residual_amount`), pas le principal seul. Avec intérêts et pénalités à 0 (V1) il vaut le principal restant ; il s'en écartera dès qu'une pénalité s'appliquera à une échéance reprise en retard (le cron écrit la pénalité sur l'échéance) → l'encours du dashboard dépasse alors le solde du compte 203xxx. Le contrôle de concordance (§8) doit donc porter sur le **principal** (`principal_amount − paid_principal`) et non sur `balance_total`.
- Vérifié (copie, utilisateur agent id 2) : `get_agent_portfolio_kpis` → 1 client, encours 200 000, 1 dossier actif, 0 en retard ; PAR 0 % sur toutes les tranches.
- `max_days_overdue` (utilisé par le PAR) n'est rafraîchi que par le cron quotidien : un crédit repris en retard n'apparaît au PAR qu'à partir du lendemain.

## 7. Intérêts et pénalités déjà échus à 0 en V1 — comptabilité de caisse stricte

- **Aucune comptabilisation à l'échéance** : les comptes « intérêts échus » (208xxx) existent sur le produit mais **ne sont lus par aucun code** (recherche : seulement des déclarations de champs). Les intérêts sont constatés **au seul remboursement** : `_prepare_payment_move` ([microfinance_loan_payment.py](../../microfinance_loan_management/models/microfinance_loan_payment.py)) crédite 707xxx (intérêts reçus) et le compte pénalités du produit à hauteur de `allocated_interest` / `allocated_penalty`. L'application d'une pénalité n'écrit qu'un montant sur l'échéance.
- Donc laisser intérêts et pénalités restants à 0 :
  - n'a **aucun effet sur les comptes de bilan** (203xxx = principal seul ; 208xxx non alimentés) ni sur la concordance ;
  - n'empêche aucun remboursement (ventilation intérêt → principal → pénalité, avec 0 d'intérêt tout va au principal ; contrôle « surpaiement » sur `balance_total` = principal restant) ;
  - a pour seul effet un **manque à gagner de produits d'intérêts** sur la durée restante des crédits repris (sans incidence sur la concordance d'ouverture), et des tableaux de remboursement sans intérêt.
- Les comptes 208xxx, 273xxx, 293xxx, 325xxx de la balance d'ouverture restent saisis à la main dans la balance (hors périmètre de la reprise).

## 8. Contrôle de concordance — requêtes proposées

Principe : comparer le détail repris aux **lignes de la balance d'ouverture en brouillon** (pas au grand livre : la balance n'est pas encore validée). Le périmètre du détail est borné par un marqueur (voir « Marqueurs » ci-dessous) pour ne pas mélanger la reprise et des crédits postérieurs. Les listes de comptes sont **configurables** : colonne de rôle sur `microfinance.opening.template` (`credit_principal`, `savings`) plutôt que les codes en dur ; les codes ci-dessous sont les valeurs actuelles.

```sql
-- Détail crédit (par compte de principal du produit), société :company
SELECT acc.code, SUM(i.principal_amount - i.paid_principal) AS detail
FROM microfinance_loan l
JOIN microfinance_loan_installment i ON i.loan_id = l.id
JOIN microfinance_loan_product p ON p.id = l.product_id
JOIN res_partner pt ON pt.id = l.partner_id
JOIN account_account acc ON acc.id = CASE WHEN pt.microfinance_client_type = 'group'
        THEN p.account_principal_groupe_id ELSE p.account_principal_individuel_id END
WHERE l.company_id = :company AND l.state IN ('active','defaulted')
  AND l.disbursement_date IS NOT NULL AND l.opening_balance_id = :balance      -- marqueur
GROUP BY acc.code;

-- Détail épargne (par compte de produit d'épargne)
SELECT acc.code, SUM(CASE WHEN t.transaction_type IN ('deposit','interest_credit') THEN t.amount ELSE -t.amount END)
FROM microfinance_savings_transaction t
JOIN microfinance_savings_account a ON a.id = t.account_id
JOIN microfinance_savings_product p ON p.id = a.product_id
JOIN res_partner pt ON pt.id = a.partner_id
JOIN account_account acc ON acc.id = CASE pt.microfinance_client_type
        WHEN 'company' THEN p.account_epargne_entreprise_id
        WHEN 'group'   THEN p.account_epargne_groupe_id
        ELSE p.account_epargne_individuel_id END
WHERE a.company_id = :company AND t.state = 'posted' AND t.opening_balance_id = :balance   -- marqueur
GROUP BY acc.code;

-- Côté balance d'ouverture (brouillon) : crédit - débit pour l'épargne, débit - crédit pour le principal
SELECT account_code, SUM(debit) - SUM(credit)
FROM microfinance_opening_balance_line
WHERE balance_id = :balance AND account_code IN ('203001','203002')
GROUP BY account_code;
SELECT account_code, SUM(credit) - SUM(debit)
FROM microfinance_opening_balance_line
WHERE balance_id = :balance AND account_code IN ('213001','213002','213003')
GROUP BY account_code;
```
Ecart affiché par compte = ligne de la balance − détail. Validation bloquante quand écart ≠ 0 sur un compte configuré.

Points de conception :
- **Placement** : le contrôle crédit vit dans L ; la partie épargne dans S par un point d'extension (`_opening_reprise_concordance()` qui renvoie des lignes `{compte, détail, ligne balance, écart}`, étendu par S) — jamais d'import de S dans L.
- **Garde de non-régression** : le blocage de `action_validate` ne doit s'appliquer **que si une reprise existe pour la balance** (au moins un crédit ou produit d'épargne marqué) ; sinon l'ouverture comptable seule (déployée, 16 tests, dont une ligne 203001) cesserait de se valider. Voir D4.
- **Marqueurs** : deux champs nouveaux (`opening_balance_id` sur `microfinance.loan` en L, sur `microfinance.savings.transaction` en S) ; ils servent aussi de clé d'idempotence côté crédit/épargne et au verrouillage du montant (§5).

## 9. Risques

1. **Tests / fonds** : 114 échecs préexistants sur 1 033 tests ([clients_portefeuille/STATUS.md](../clients_portefeuille/STATUS.md)), surtout « Un fonds de crédit rotatif actif existe pour cette agence » (fonds réels de MOWGLI) ; `TestFondLiaison` et dérivées échouent en `setUpClass` (société mère déjà configurée, voir la note de test sur MOWGLI). **Aujourd'hui MOWGLI n'a plus de fonds**, ces échecs ont sans doute changé : non remesuré ici. Les nouveaux tests utiliseront `MicrofinanceNoFundMixin` (neutralise les fonds actifs, [tests/common.py:179](../../microfinance_loan_management/tests/common.py#L179)) devant `MicrofinanceCommon`. `MicrofinanceCommon` pose des comptes de test (`TPRET`…) : les tests de concordance créeront eux-mêmes des comptes `203001`/`213001` dans une société de test, comme `test_opening_balance.py`.
2. **Séquences non transactionnelles** : tout essai consomme des numéros (crédit, n° permanent client, compte crédit), même annulé (vérifié : 4 tentatives, numéros 17 → 22). Le **dry-run ne doit rien créer** (validation pure, pas de create + rollback) pour ne pas trouer la numérotation.
3. **Unicité du CIN — la portée est toujours ouverte et, en pratique, limitée à l'agence de la session.** `_check_cin_unique` ([res_partner.py:748](../../microfinance_loan_management/models/res_partner.py#L748)) est une contrainte Python **sans sudo** : un utilisateur dont la société active est la 11 ne voit pas les clients de la 9 (règle multi-société) et peut donc créer le même CIN. **Vérifié** : client CIN `202022222222` créé dans la 9, même CIN accepté dans la 11 (utilisateur id 8, sans crédit). Seule la garde inter-agences (crédit en cours, en `sudo`) refuse le doublon, et seulement si l'autre agence a un crédit `active/defaulted`. La recommandation (a) de [centralisation_identite_partner/AUDIT.md](../centralisation_identite_partner/AUDIT.md) (unique global, index SQL) n'a pas été appliquée. Dans l'import : contrôler les CIN **dans toutes les sociétés, en `sudo()` ciblé** (lecture des seuls CIN), et dans le fichier. Aucune modification de la contrainte dans ce chantier sans votre décision. Coût : la contrainte parcourt tous les CIN à chaque création (O(n²) sur gros fichiers, sans importance pour une démo).
4. **CIN fictifs** : 12 chiffres exigés, uniques ; l'assistant ne doit jamais en fabriquer, il les lit du fichier. Gabarit de démo : plage réservée facile à repérer (ex. `99…`).
5. **Lecture Excel** : le lecteur maison ([microfinance_opening_xlsx.py](../../microfinance_loan_management/models/microfinance_opening_xlsx.py)) lit **la première feuille seulement** (`sheet\d+.xml` trié, premier) et renvoie les dates comme **numéros de série flottants** ; openpyxl est absent. Il faut une lecture multi-feuilles (nom → fichier via `workbook.xml`), une conversion de dates (série Excel ou texte `jj/mm/aaaa`), et écrire CIN/téléphone en **cellules texte** (zéros de tête, perte de précision d'un nombre).
6. **Droits de l'assistant** : finance n'a pas `create` sur crédit/échéance/transaction ; l'agent non plus sur la transaction. Les créations passent par un `sudo()` **ciblé** après contrôle que chaque ligne appartient à la société de l'import et que l'utilisateur a le droit d'écriture sur l'assistant (groupes finance + manager crédit en écriture, auditeur en lecture, comme demandé ; **la balance d'ouverture, elle, admet aussi comptable et gestionnaire comptable** — écart assumé ou à aligner, D5).
7. **Agent absent d'un portefeuille actif** : la société 1 n'en a aucun. Le rapport d'erreurs doit le signaler par ligne.
8. **Produits** : tous sont à frais exigés avant décaissement (`fee_charged_before_disbursement`) → `fee_paid=True` imposé (§2.2) ; durée contrôlée en mois.
9. **Pas de bouton d'annulation (V1)** : les séquences et les marqueurs ne se défont pas ; le raz de la base de test suffit (l'assistant de purge existe : `microfinance_data_reset_wizard`, à vérifier qu'il supprime aussi transactions d'ouverture et crédits repris).
10. **Provisions** : si le cron mensuel (inactif) est un jour activé, il comptabilisera des provisions sur les crédits repris en retard — c'est le comportement normal, à ne pas confondre avec la reprise.

## 10. Décisions à valider avant la phase 2

- **D1 — Type « groupe »** : ajouter la valeur `group` à `microfinance_client_type` (touche vues, domaines de `client_group_member` déjà écrits pour elle, produits, tests) ou **retirer « groupe » du gabarit** (203002/213002 restent à 0 en V1, `company` → 213003). Recommandation : retirer en V1, ouvrir un chantier à part pour le type groupe.
- **D2 — Numérotation crédit** : conserver la séquence propre du crédit (N différent du compte crédit/épargne, comportement actuel de tous les crédits) ou forcer `loan.name = n° du compte crédit` pour le premier crédit repris (risque de collision future avec la séquence, pas d'unicité SQL sur `loan.name`). Recommandation : conserver la séquence ; la règle « compte crédit = compte épargne » est déjà vraie.
- **D3 — Gabarit** : produit utilisé pour 1 000 000 / 2 000 000 et ses limites. Options : (i) créer un produit « Reprise » à plafond relevé dans la société 9 ; (ii) ramener le gabarit sous les plafonds existants (500 000 / 1 000 000 « PRET STAFF », taux 0) ; (iii) neutraliser `_check_product_limits` par un contexte propre à la reprise. Recommandation : (iii), car le principal initial d'un crédit déjà accordé n'est plus à valider contre le catalogue ; le gabarit garde alors 1 000 000 / 2 000 000.
- **D4 — Concordance** : blocage seulement si une reprise existe pour la balance (recommandé), ou toujours (casse l'ouverture comptable seule).
- **D5 — Droits** : finance + manager crédit en écriture, auditeur en lecture (spécification) — sans comptable ni gestionnaire comptable, qui peuvent pourtant valider la balance.
- **D6 — Option fonds** : (b) recommandée (§4).
- **D7 — Menu** : entrée sœur « Reprise de portefeuille » sous Comptabilité (séq. 6), à côté de « Balance d'ouverture ».
- **D8 — Clé d'idempotence** : colonne « Référence client » sur les trois onglets, stockée dans `microfinance_internal_reference`, unique par société dans l'import ; relancer ignore (sans mise à jour) les clients, crédits et produits d'épargne déjà repris sous la même balance.
- **D9 — Date d'ouverture de la reprise** : date de la balance d'ouverture (date du solde d'épargne ; la date de décaissement du fichier est celle du crédit) ; première échéance ≥ cette date.

## 11. Plan de la phase 2 (rappel, après validation)

Assistant `microfinance.opening.reprise` (L, `TransientModel`) + hooks d'extension pour S ; lecture Excel multi-feuilles ; validation pure (dry-run par défaut) avec rapport ligne par ligne ; application dans une seule transaction avec `sudo()` ciblé ; marqueurs `opening_balance_id` (crédit, transaction d'épargne) ; concordance en point d'extension ; menu, droits (`ir.model.access.csv`, règle de société) ; gabarit rempli (2 clients fictifs, Analakely) ; tests (nominal, doublon, inter-agences, écart de concordance, absence d'`account.move`, absence de « Décaissements en attente », visibilité au dashboard) avec `MicrofinanceNoFundMixin` ; STATUS.md. Aucun commit.
