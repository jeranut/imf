# Correctifs groupés Ampaly — rapport de chantier

Date : 2026-10-12. Aucun commit, aucun déploiement, aucune donnée de production modifiée
(diagnostics en lecture seule sur MOWGLI ; essais sur copie jetable). État : **terminé** (blocs 0, A, B, C).

Avancement : Bloc 0 ✔ · Bloc A ✔ · Bloc B ✔ · Bloc C ✔ — **terminé**

> Remarque de départ : l'arbre de travail contient déjà des modifications **non commitées
> antérieures à ce chantier** (38 fichiers : verrou « une session ouverte par caissier »,
> transit chèque/virement, tuile Trésorerie, etc.). Ce rapport distingue ce qui existait déjà
> de ce qui est fait ici.

---

## BLOC 0 — Diagnostics (lecture seule)

### 0.1 Crédit AG3/000067 : les 84 000

- Le crédit (id 5105, société 9, officer 2, fonds « fond 26 » = id 3522, virement) a un
  échéancier correct : 12 échéances, Σ principal = 1 000 000. Ce n'est **pas** un défaut d'échéancier.
- Les 84 000 sont un **remboursement n° 290** (`AG3/000036`, origine `manual`, 100 % capital)
  créé le 2026-10-12 par la **retenue sur salaire** du bulletin 490 (novembre 2026, employé
  « Jeranut Mickael »), journal `RSAL`, écriture 32146 : débit 315000 / crédit 203001.
  Chemin : `hr.payslip._microfinance_apply_salary_deduction` (module `microfinance_payroll_loan`),
  donc **hors guichet** et sans mouvement de caisse (`microfinance_caisse_mouvement` vide pour ce paiement).
  L'échéance n° 1 est passée `paid`.
- « Remboursements encaissés = 0 » : `get_agent_portfolio_kpis` ne somme que les paiements
  `posted` dont `payment_date` est dans le **mois courant** (octobre). Le paiement est daté
  du **30/11/2026** (`date_to` du bulletin, futur) → hors fenêtre, donc 0.
- Dashboard comptable : « encours décaissé » = Σ `loan_amount` des crédits décaissés
  (4 000 000) ; « encours agent » = principal restant (3 916 000). Écart = 84 000 de
  capital remboursé, même cause.
- Grand livre du fonds : `_get_portfolio_funds_tab` ne journalise que les allocations (crédit)
  et les décaissements au `loan_amount` (débit) ; **le remboursement de capital est
  explicitement hors périmètre** (docstring : « MVP, capital hors périmètre »). Le solde
  « disponible » (`solde_disponible = contributions − principal restant`) lui le réintègre.
  D'où : le grand livre ne montre pas les 84 000, le disponible les montre.
  Chiffres MOWGLI actuels pour ce fonds : contributions 250 000 000, décaissé 1 000 000,
  remboursé 84 000, disponible 249 084 000 (= 250 000 000 − 916 000). (Les 9 000 000 / 9 084 000
  cités dans la demande ne correspondent pas à MOWGLI aujourd'hui, mais le mécanisme est le même : 84 000.)
- Point de règle à trancher : la retenue sur salaire est un second chemin de remboursement
  hors guichet. La règle « le guichet est le seul chemin » ne doit pas casser la paie (voir B3).

### 0.2 Session de caisse d'Analakely (session 502, 27/09, journal 2163)

- Les 25 000 **ne sont pas** les frais de dossier : le produit 1589 est `fee_type = fixed`,
  `fee_amount = 0` (le taux 5 % est ignoré en mode fixe) ; `fee_amount_due = 0` sur le crédit ;
  aucun mouvement `frais_dossier` sur la session 502. (5 % de 1 000 000 serait de toute façon 50 000.)
- Solde théorique de la session = ouverture 25 000 + net compte 101000 (0) + frais (0) +
  épargne (50 000 + 30 000 + 50 000 − 10 000 − 20 000 = 100 000) = **125 000**. Les
  décaissements 1 000 000 (virement) sont correctement exclus des espèces.
- Cause du refus : ce n'est pas l'écart comptage/théorique (qui, lui, ne bloque pas) mais le
  contrôle de cohérence de `microfinance.caisse.fiche.journee.action_close_day()`. La fiche 567
  hérite 25 000 de l'ouverture (clôture figée de la fiche 566 du 26/09), alors que le grand
  livre du compte 101000 ne contient qu'**une ligne** (balance d'ouverture de 5 000 000 datée du
  10/10). Solde réel au 27/09 = 0 ≠ 25 000 → « Écart détecté… Clôture refusée ».
  Les écritures du 26/09 ont disparu du grand livre (remise à zéro de données), mais la fiche
  clôturée du 26/09 a conservé son instantané.
- Conséquence aggravante : le wizard de clôture crée le comptage puis appelle
  `action_close_session()`; l'erreur de la fiche annule toute la transaction → comptage, écart
  et motif sont **perdus** (voir B2).

### 0.3 Tuile « Trésorerie » 191 641 100 Ar

Somme du « disponible » (solde comptable − sorties en transit) des journaux bancaires hors
caisse/Mvola, sur les sociétés cochées. Avec Analakely + Ambohibao seulement :

| Journal | Solde | Transit | Disponible |
|---|---|---|---|
| Banque BNI – Crédit (Analakely) | 29 000 000 | 0 | 29 000 000 |
| Banque BMOI – Épargne (Analakely) | 400 000 | 0 | 400 000 |
| Fonds BNI (avant partage) (Analakely) | 250 000 000 | 90 000 000 | 160 000 000 |
| Banque BMOI – Exploitation (Analakely) | 2 241 100 | 0 | 2 241 100 |
| **Total** | | | **191 641 100** |

Avec la société 67 Ha cochée en plus (650 000 épargne + 2 500 000 exploitation) le total
devient 194 791 100. La tuile mélange donc argent des bailleurs (fonds, 160 M), épargne des
clients et exploitation. Les 29 000 000 du compte crédit sont le symptôme du bloc C.

---

## BLOC A — Portefeuilles indépendants par société ✔

### A1. Inventaire (qui traverse les sociétés)

| Endroit | Verdict avant correctif |
|---|---|
| `_get_agent_portfolio_scope` (source de `company_ids` pour **tous** les endpoints agent : `get_agent_portfolio_kpis`, `get_agent_monthly_kpis`, `get_agent_due_dates_panel`, `get_agent_portfolio_table`, `get_portfolio_tab` (clients, crédits, paiements, impayés, échéances, visites, fonds), `get_par_data_by_agent`, `get_par_history_by_agent`, `get_available_agents`, `get_agent_upcoming_disbursements`) | **Traversait** : le rôle Auditeur recevait `user.company_ids` (toutes ses sociétés). L'utilisateur 2 cumule tous les groupes dont Auditeur : c'est la cause des 7 366 000 (3 916 000 société 9 + 3 450 000 société 67 Ha). Manager/gestionnaire/agent : déjà `env.company`. |
| `microfinance.portfolio.montant_utilise` (liste « Portefeuilles ») | Bon filtre société, mais **comptait aussi les crédits sans fonds** (reprise) : 3 916 000 au lieu de 916 000. |
| Détail du fonds 26 (`_get_portfolio_funds_tab`, par fonds) | Seul chiffre correct (fonds + société), mais recalculé à part avec une autre portée (crédits de tout officier, pas via les portefeuilles). |
| « Tous les fonds » (`aggregate.used`) | Σ `portfolio.montant_utilise` → divergeait du détail par fonds (7 366 000 vs 916 000). |
| `_par_by_agent_raw` / PAR | Regroupe par officier sur `company_ids` : cumulait les sociétés dès que `company_ids` en contenait plusieurs (même cause : auditeur). |
| `cron_snapshot_portfolio_par` | Déjà par (société, agent) : OK. |
| `microfinance.fond.allocation.montant_utilise` | Déjà filtré fonds + société : OK (stocké). |
| Record rules `microfinance.portfolio` | Règle société sur `company_ids` (sociétés cochées) : la **liste** peut montrer plusieurs sociétés, une ligne par portefeuille, chacune avec ses propres montants (normal). Seul risque : ouvrir un portefeuille d'une autre société que l'active. |
| Scoring / plafonds | Pas d'agrégation par agent trouvée (le plafond de décaissement passe par `solde_disponible` du portefeuille, donc corrigé avec lui). |
| `get_fond_matrix(user.company_ids)` | Transversal **volontaire** (matrice de fonds, pas un chiffre d'agent) : inchangé. |

### A2. Correctifs (fichiers)

- [microfinance_loan.py](../microfinance_loan_management/models/microfinance_loan.py) :
  `_get_agent_portfolio_scope` : agent/manager/gestionnaire = société active ; **auditeur = ses agences autorisées (`user.company_ids`) pour LISTER les agents** (décision du 13/10), mais `_resolve_agent_request` borne les chiffres à UNE société (active si dans son périmètre, sinon l'agence où l'agent demandé a un portefeuille) : jamais de cumul entre agences ;
  `get_dashboard_data(portfolio_id=…)` refuse (UserError, message français) un portefeuille d'une autre société que l'active ;
  `_get_portfolio_funds_tab` lit désormais les crédits via `portfolios._get_outstanding_fund_loans()`.
- [microfinance_portfolio.py](../microfinance_loan_management/models/microfinance_portfolio.py) :
  nouvelle méthode unique `_get_outstanding_fund_loans()` (approved/active, agent + société du portefeuille,
  `fond_credit_id` renseigné) ; `montant_utilise`/`solde_disponible` l'utilisent ; `action_open_dashboard`
  refuse un portefeuille d'une autre société que l'active.
- Résultat : tuile = liste Portefeuilles = « Tous les fonds » = Σ détails par fonds.

### A3. Champs stockés périmés — requête proposée (NON appliquée)

Constat sur MOWGLI (lecture) : aucune ligne périmée aujourd'hui (allocation société 9 : 916 000 utilisé, 29 084 000 disponible ;
fonds 3522 : disponible 249 084 000). `microfinance.portfolio.montant_utilise` n'est pas stocké, donc rien à recalculer
pour la correction A. Si des écarts apparaissent sur une autre base (stockés : `microfinance.fond.allocation`
`montant_utilise`/`solde_disponible`, `microfinance.fond.credit` totaux), recalcul par l'ORM (même code que le calcul) :

```python
# odoo shell, base cible, puis env.cr.commit()
env['microfinance.fond.allocation'].sudo().search([])._compute_allocation_totals()
env['microfinance.fond.credit'].sudo().search([])._compute_fond_totals()
```

Variante SQL (allocations) :

```sql
UPDATE microfinance_fond_allocation a
   SET montant_utilise = x.utilise,
       solde_disponible = COALESCE(a.amount_allocated, 0) - x.utilise
  FROM (SELECT a2.id,
               COALESCE(SUM(CASE WHEN i.nb > 0 THEN i.principal - i.paye ELSE l.loan_amount END), 0) AS utilise
          FROM microfinance_fond_allocation a2
          LEFT JOIN microfinance_loan l ON l.fond_credit_id = a2.fond_id AND l.company_id = a2.company_id
                                        AND l.state IN ('approved', 'active')
          LEFT JOIN LATERAL (SELECT COUNT(*) nb, SUM(principal_amount) principal, SUM(paid_principal) paye
                               FROM microfinance_loan_installment WHERE loan_id = l.id) i ON TRUE
         GROUP BY a2.id) x
 WHERE x.id = a.id;
```

### A4. Tests

Fichier [test_portefeuille_independant.py](../microfinance_loan_management/tests/test_portefeuille_independant.py) (nouveau, 6 tests) :
même agent / deux sociétés ; chaque dashboard ne voit que sa société ; deux sociétés cochées → seule l'active compte (dans les deux ordres) ;
tuile = liste = journal « Tous les fonds » = Σ détails par fonds ; un crédit sans fonds n'entre pas dans le fonds utilisé ;
PAR indépendant par société ; ouverture d'un portefeuille d'une autre société refusée.
Modifié : `test_agent_portfolio_dashboard.py` (test auditeur réécrit : liste de toutes les agences autorisées, chiffres par agence sans cumul ; `setUpClass` neutralise la société mère de MOWGLI le temps de désactiver les fonds).

Résultat (copie jetable `MOWGLI_chantier`) : `TestPortefeuilleIndependant` 6/6 ✔, `TestAgentPortfolioDashboard` ✔ (16).
Non concernés par le code touché mais en erreur sur cette base pour cause d'environnement (société mère « AGENCE ANALAKELY » désignée,
fonds actif) : `TestOfficerIsolation` (4), `TestDashboardMultiCompany` (1), `TestPortfolioFundsTab*` (anciens : exigent une allocation d'agence réelle).
Ces échecs existent indépendamment de ce chantier (traces : « Seule la société mère… », « Un fonds de crédit rotatif actif existe… », « reçu en banque 0 »).

Décisions restantes (A) :
- L'auditeur perd la vue multi-agences simultanée (il change d'agence dans le sélecteur). À confirmer.
- Ouvrir le dashboard d'un portefeuille d'une autre société que l'active est refusé avec un message plutôt que de basculer la société automatiquement.

---

## BLOC B — Caisse ✔

État de départ : un chantier caisse précédent (même jour, non commité, rapport
[CORRECTIFS_CAISSE.md](guichet_caisse/CORRECTIFS_CAISSE.md)) avait déjà posé la contrainte « une session ouverte par caissier », le
blocage serveur du remboursement hors guichet, le calcul épargne/frais par montant et `test_caisse_correctifs.py` (9 tests). Ce chantier l'a
vérifié puis complété.

### B1. Solde caisse

- **Le dépôt de 50 000 « Andoharanofotsy » n'est pas vérifiable sur les données** : aucune agence de ce nom dans MOWGLI. Le mouvement `depot_epargne` n° 245
  (50 000, session 502) existe mais sans `savings_transaction_id` (lien perdu : les 13 mouvements épargne de la base sont dans ce cas).
  **Pas de régression des verrous de création directe** : le caissier n'a plus `create` sur transaction/paiement (voulu), le guichet crée en
  `sudo` ciblé et écrit bien un mouvement ; aucun dépôt guichet sans mouvement n'a été trouvé.
  La cause plausible est le défaut décrit (filtre sur le seul `default_account_id`) : il était **déjà corrigé dans cet arbre** pour dépôt/retrait/frais
  (commit d1e3f49 : sommes par `mouvement.amount`, écritures exclues du filtre de compte). Si `rotas` n'a pas ce code, c'est lui le défaut.
- Reste corrigé ici : remboursement et décaissement **espèces** postés sur un autre compte que celui de la session (journal du produit ≠ journal de la
  session) n'étaient comptés nulle part. [microfinance_caisse_session.py](../microfinance_loan_management/models/microfinance_caisse_session.py) :
  pour ces deux types, si l'écriture touche le compte de la session → lue dans le grand livre (comme avant) ; sinon → `mouvement.amount`
  (décaissement : seulement si le moyen est « espèces »). Aucun double comptage possible (l'un OU l'autre, par mouvement).
  Chèque/virement : jamais des espèces. Mouvement sans pièce (données historiques) : ignoré, comportement inchangé.
- Solde du guichet = total du ticket : la ligne « Solde caisse » (= `theoretical_balance`, le champ de l'en-tête) est ajoutée au bas du ticket
  ([microfinance_caisse_pos.xml](../microfinance_loan_management/static/src/xml/microfinance_caisse_pos.xml)).
  Limite : la ligne « Décaissements » du ticket additionne aussi les chèques/virements (qui ne baissent pas le solde).

### B2. Écart perdu à la clôture

- `rotas` : **toujours inaccessible** (aucun hôte résolu depuis cette machine) ; le `git status`/`git diff` demandé n'a donc pas pu être fait.
- Dans l'arbre de MOWGLI, le flux en trois temps est **déjà versionné** : `wizard/` et `static/src/` identiques à HEAD (`git diff HEAD` vide), code
  commité en bc3358e. Aucun code importé de `rotas`, wizard versionné utilisé tel quel.
- Trace de « Confirmer la clôture » (`variance.wizard.action_confirm_close`) : motif obligatoire si écart → `comptage.create()` (lignes, théorique, écart,
  motif) → `flush` → `_post_variance_move()` → `session.action_close_session()` → suppression du brouillon. Le comptage est donc **déjà persisté
  avant** `action_close_session()`.
- Pourquoi on le « perd » quand même : si `_post_variance_move()` ou `action_close_session()` lève, **toute la transaction du bouton est annulée**, comptage
  compris. C'est voulu (pas de comptage sans écriture ni clôture) ; le brouillon `microfinance.caisse.comptage.brouillon` conserve quantités et motif pour la reprise.
  Cas réel de 0.2 : la clôture lève *systématiquement* (voir 0.2). Je n'ai **pas** changé cette atomicité : persister un comptage d'une clôture refusée
  créerait des comptages orphelins et, avec l'écriture d'écart, des doubles écritures à chaque nouvel essai. À décider (voir ci-dessous).

### B3. Remboursement hors guichet / sessions

- Déjà en place et vérifié : plus de bouton « Enregistrer remboursement » sur la fiche crédit (test sur la vue) ; `loan.action_open_payment_wizard()` et
  `payment.wizard.action_create_payment()` lèvent une erreur ; le caissier n'a que la lecture sur `microfinance.loan.payment`.
- Deux sessions ouvertes pour un même utilisateur : refusé à l'ouverture ET à la création/écriture directe (`_check_one_open_session_per_cashier`), par
  caissier (un autre caissier peut ouvrir la sienne), recherche en `sudo` ciblé pour voir une session d'une autre agence.
- Exception connue, non touchée : la **retenue sur salaire** crée des remboursements hors guichet (`payslip_id`, 0.1) par le module `microfinance_payroll_loan`.

### B4. Tests

[test_caisse_correctifs.py](../microfinance_savings_management/tests/test_caisse_correctifs.py), 12 tests (3 ajoutés ici), 12/12 ✔ sur copie jetable :
écart + motif + lignes persistés après clôture ; solde avec dépôt, frais et retrait (comptes distincts) ; comptes coïncidents sans double comptage ;
égalité solde = ouverture + ticket ; remboursement compté une seule fois (compte coïncident) *(nouveau)* ; décaissement espèces d'un journal distinct compté
par montant *(nouveau)* ; décaissement par virement jamais compté en espèces *(nouveau)* ; remboursement hors guichet refusé côté serveur ; bouton absent ;
deuxième session du même caissier refusée (ouverture et création directe) ; autre caissier accepté.
Les 4 tests existants de `TestCaisseSessionTheoreticalBalance` (frais/décaissement) échouent sur cette base pour une cause d'environnement
(« Seule la société mère… » à la neutralisation des fonds), avant comme après ce chantier.

Décisions restantes (B) :
- Persister le comptage d'une clôture refusée (au prix de comptages/écritures à rejouer) ou garder l'atomicité actuelle + brouillon ?
- Clôture refusée par la cohérence de la fiche (cas 0.2) : recaler l'ouverture sur le grand livre quand l'instantané de la veille est incohérent, ou l'exiger corrigé par un manager ?
- Retenue sur salaire : confirmer qu'elle reste une exception à la règle « le guichet est le seul chemin ».
- Ticket : marquer ou séparer les décaissements non espèces.
- MOWGLI contient des sessions ouvertes en double (caissier 2 : 4, caissier 8 : 3) que la contrainte empêche de rouvrir/transférer : à clôturer par les intéressés.

---

## BLOC C — Décaissement chèque / virement en transit ✔

### C1. Cause (lecture de l'écriture)

Écriture 31801 (`BNCR/2026/00003`, crédit AG3/000067, virement) : débit 203001 principal 1 000 000 / **crédit 131201 « Banque BNI – Crédit »**. Le compte d'attente
était pourtant configuré (produit 1589 : `account_cheques_emis_attente_id` = 8542). Cause : **chemin virement absent dans le code déployé**. Dans HEAD,
`_prepare_disbursement_move` n'utilisait le compte d'attente que pour `disbursement_payment_method == 'cheque'` ; un virement tombait dans le `else` (compte du journal =
banque). De plus l'écriture date de 13:15 et le module n'a été mis à jour sur MOWGLI qu'à 15:09 (colonne `account_virements_emis_attente_id` créée depuis).
Ce n'est donc pas de la configuration : il manquait le code, et il existe maintenant dans l'arbre (voir C2). L'écriture 31801 reste telle quelle (pas de migration, demandé).

### C2/C3. État du code (déjà présent dans l'arbre, non commité, vérifié ici)

- `microfinance.loan.product` : `account_virements_emis_attente_id` (repli sur le compte chèques) + `_get_disbursement_waiting_account()`.
- `_prepare_disbursement_move` : chèque ET virement créditent le compte d'attente ; espèces inchangé (la caisse baisse tout de suite).
- Dénouement : pointage de la ligne de relevé sur l'écriture d'attente → l'écriture de la ligne (attente → banque) devient `disbursement_clearing_move_id`, état `compense`
  (`_mf_mark_disbursement_cleared`) ; annulation du pointage → `en_attente`. L'écriture d'attente est proposée comme candidat au rapprochement, limitée au journal du relevé.
- Rejet : `action_reject_disbursement_cheque` étendu au virement (contre-passation) ; `action_clear_disbursement_cheque` étendu au virement.
- Trésorerie : « Sorties en transit » = lignes non lettrées des comptes d'attente de décaissement postées dans le journal de la banque ; Disponible = solde − transit ;
  tuile Vue d'ensemble avec « En transit » et « Écarts non expliqués : N » (`_mf_unexplained_gap`) ; tableau de bord bancaire avec transit et écart non expliqué.
- Fichiers : `models/microfinance_loan.py`, `microfinance_loan_product.py`, `microfinance_bank_settings.py`, `microfinance_bank_statement_entry.py`, `microfinance_bank_statement.py`,
  `microfinance_bank_dashboard.py`, `mf_operating_treasury.py`, `microfinance_treasury_tab.py`, `microfinance_treasury_tile.py`, vues produit et relevé.
- **Fait dans ce chantier pour C** : uniquement les tests (ci-dessous). Aucun code C supplémentaire n'était nécessaire.

### C4. Tests

`TestDisbursementWaitingAccount` (13, fichier non commité préexistant) : espèces inchangé ; chèque et virement créditent l'attente et pas la banque ; repli du virement sur le compte chèques ;
transit visible et solde banque = relevé ; écart non expliqué limité à ce que le transit ne couvre pas ; tuile avec « En transit » et compteur ; pointage dénoue (chèque et virement) ;
annulation du pointage ; candidats limités au journal du relevé ; rejet contre-passe (chèque et virement) ; action de compensation disponible pour le virement. 13/13 ✔.
Modifiés ici : `TestDisbursementChequeWorkflow` — 3 tests périmés avant ce chantier (compensation via assistant de lettrage ; contre-passation listée dans `move_ids`) alignés sur le
comportement réel ; et le mixin `MicrofinanceNoFundMixin` neutralise maintenant la société mère de la base réelle (les classes qui l'utilisent ne pouvaient plus démarrer sur MOWGLI).
Résultat : 44/44 ✔ (WaitingAccount, ChequeWorkflow, TreasuryTab, DashboardTiles).

---

## DÉCISIONS DU 13/10 (utilisateur)
- L'auditeur voit toujours les agences où il est autorisé (`company_ids`) ; chiffres jamais cumulés entre agences. Implémenté et testé (22/22).
- La retenue sur salaire reste une exception à « le guichet est le seul chemin » : aucun code ne la bloque ; 0.1 et B3 en tiennent compte.

## CLÔTURE

### Fichiers modifiés par ce chantier
- `microfinance_loan_management/models/microfinance_loan.py` — périmètre agent = société active ; journal « Tous les fonds » ; garde portefeuille d'une autre société
- `microfinance_loan_management/models/microfinance_portfolio.py` — `_get_outstanding_fund_loans`, `montant_utilise` ; garde d'ouverture
- `microfinance_loan_management/models/microfinance_caisse_session.py` — espèces sans équivalent sur le compte de la session
- `microfinance_loan_management/static/src/xml/microfinance_caisse_pos.xml` — ligne « Solde caisse » au bas du ticket
- `microfinance_loan_management/tests/common.py` (mixin), `test_agent_portfolio_dashboard.py`, `test_disbursement_cheque_workflow.py`, `test_portefeuille_independant.py` (nouveau), `tests/__init__.py`
- `microfinance_savings_management/tests/test_caisse_correctifs.py` (3 tests ajoutés)
- `docs_dev/CORRECTIFS_GROUPES.md` (ce rapport)
- Vérifiés sans modification (travail non commité antérieur) : bloc C complet, contrainte « une session ouverte par caissier », blocage du remboursement hors guichet.
- Rien n'a été commité, déployé ni écrit sur MOWGLI (les diagnostics lecture seule ont tourné en transaction annulée ; les tests sur la copie jetable `MOWGLI_chantier`, supprimée).

### Résultats des tests (copie jetable, 20 classes touchées + caisse, 171 tests)
- 163 ✔, 8 en erreur, **toutes d'environnement MOWGLI, sans lien avec le code touché** : 4 × « Seule la société mère (AGENCE ANALAKELY)… » et 3 × « Un fonds de crédit rotatif actif existe… »
  (`TestCaisseSessionTheoreticalBalance` ×4, `TestCaisseRegisterOperation` ×3, `TestDashboardMultiCompany` ×1), 1 × journal de caisse ≠ journal configuré de l'agence (`TestCaisseRegisterOperation`).
  Ces classes ne passent pas par le mixin et ne neutralisent pas la société mère. Les anciennes classes `TestPortfolioFundsTab*` exigent une allocation d'agence réelle et ne sont pas lancées ici.
- Nouveaux : `TestPortefeuilleIndependant` 6/6, `TestCaisseCorrectifs` 12/12, `TestDisbursementWaitingAccount` 13/13.

### Décisions restantes
- A : ouvrir le dashboard d'un portefeuille d'une autre société est refusé avec message (pas de bascule automatique de société).
- B : persister le comptage d'une clôture refusée (comptages/écritures à rejouer) ou garder l'atomicité + brouillon ?
- B : clôture refusée par la cohérence de la fiche (session 502, 25 000) : recaler l'ouverture sur le grand livre ou faire corriger par un manager ?
- B : ticket — séparer ou marquer les décaissements non espèces.
- 0.1 : un remboursement par retenue sur salaire est daté de la fin de période du bulletin (30/11 pour un bulletin de novembre créé le 12/10) : le dater du jour de comptabilisation ?
- 0.1 : le journal du fonds ne montre pas les remboursements de capital (« MVP ») alors que le disponible les intègre : ajouter la ligne « Remboursement » ?
- 0.3 : la tuile Trésorerie additionne fonds bailleurs (160 M), épargne et exploitation : à scinder ?
- Déploiement : le code C et A/B est dans l'arbre mais MOWGLI n'a été mis à jour qu'à 15:09 ; ordre voulu : redémarrer le service puis `-u`, sauvegarde avant.
- `rotas` toujours inaccessible : comparer son code (flux de clôture, solde caisse) à cet arbre quand l'accès sera donné.

### Données de test à purger avant la démo (MOWGLI)
- Crédit AG3/000067 (id 5105, société 9) et ses pièces : remboursement 290 (`AG3/000036`), écritures 31801 (décaissement par virement crédité à la banque) et 32146 (retenue sur salaire), mouvement de caisse 449, bulletin 490.
- Mouvements de caisse historiques sans lien (245 à 250, 307) et session Analakely 502 (ouverte, bloquée) avec fiches 566 (clôturée, instantané 25 000) et 567.
- Sessions ouvertes en double : caissier 2 (427, 428, 502…), caissier 8 (918, 1217…).
- Les 3 crédits de reprise de la société 67 Ha (3 450 000 sans fonds) et le portefeuille 272 (agent 2, société 1).
- Fonds « fond 26 » (id 3522) : contributions 250 000 000, allocations 3225/3226/3227, partages associés.
- Ligne du compte 101000 : balance d'ouverture 5 000 000 du 10/10 (Analakely) qui désynchronise les fiches du 26 et 27/09.
- Base `MOWGLI_scratch` (copie jetable du chantier précédent, encore présente).
