# Analyse Technique - Microfinance Loan Management
## Module Odoo 17 Community Edition

---

## Vue d'ensemble

Le module **Microfinance Loan Management** (v17.0.1.0.0) est une solution complète pour gérer le cycle de vie des crédits dans une institution de microfinance. Il intègre :

- **Gestion de produits** : Configuration flexible des paramètres de crédit
- **Workflow d'approbation** : 6 étapes de validation avant décaissement
- **Génération automatique** d'échéanciers avec calcul d'intérêts (flat ou reducing)
- **Comptabilité intégrée** : Écritures automatiques pour décaissement et remboursement
- **Allocation intelligente** : Répartition automatique des paiements (pénalité → intérêt → capital)
- **Gestion des pénalités** : Application automatique après délai de grâce
- **Suivi du recouvrement** : Visites terrain et engagement de paiement
- **Scoring de risque** : Calcul automatique basé sur le retard et les impayés

---

## Architecture et modèles

### 1. microfinance.loan.product

**Responsabilité** : Définir les règles et paramètres de crédit

#### Champs principaux

```
name (Char)                          # Nom du produit (unique par société)
code (Char)                          # Code unique
company_id (Many2one)                # Société
min_amount / max_amount (Float)      # Limites de montant
min_term / max_term (Int)            # Limites de durée (en mois)
interest_rate (Float)                # Taux annuel (%)
interest_method (Selection)          # 'flat' ou 'reducing_balance'
repayment_frequency (Selection)      # 'daily', 'weekly', 'monthly'
grace_period_days (Int)              # Jours avant pénalité
penalty_type (Selection)             # 'fixed' ou 'percentage'
penalty_fixed_amount (Float)         # Pénalité fixe
penalty_rate (Float)                 # Taux pénalité (%)
```

#### Comptes comptables (obligatoires)

```
disbursement_journal_id              # Journal pour décaissement
payment_journal_id                   # Journal pour remboursements
loan_account_id                      # Compte prêts clients (Bilan)
interest_account_id                  # Compte produits intérêts
penalty_account_id                   # Compte produits pénalités
```

#### Méthodes clés

- `name_get()` : Affichage personnalisé (Code - Nom)
- `_check_uniq_code()` : Validation de l'unicité du code par société

### 2. microfinance.loan

**Responsabilité** : Gérer le cycle de vie d'un crédit individuel

#### Champs principaux

```
name (Char)                          # Numéro de crédit (auto-généré)
partner_id (Many2one)                # Emprunteur (client)
product_id (Many2one)                # Produit de crédit appliqué
state (Selection)                    # État du workflow
loan_amount (Float)                  # Montant emprunté
number_of_terms (Int)                # Nombre d'échéances
term_number (Int)                    # Numéro de l'échéance (obsolète)
interest_rate (Float)                # Taux appliqué
application_date (Date)              # Date de candidature
disbursement_date (Date)             # Date du décaissement
maturity_date (Datetime)             # Date d'échéance théorique
```

#### États (Workflow)

```
draft                                # Brouillon
submitted                            # Soumis
manager_validated                    # Validé manager
finance_validated                    # Validé finance
approved                             # Approuvé
active                               # Actif (décaissé)
closed                               # Clôturé (remboursé)
defaulted                            # Défaut
cancelled                            # Annulé
```

#### Totaux calculés (Read-only)

```
total_principal (Float)              # Total capital
total_interest (Float)               # Total intérêts
total_penalty (Float)                # Total pénalités
total_due (Float)                    # Total dû
total_paid_principal (Float)         # Total capital payé
total_paid_interest (Float)          # Total intérêts payés
total_paid_penalty (Float)           # Total pénalités payées
outstanding_balance (Float)          # Solde restant à payer
risk_score (Float)                   # Score de risque 0-100
```

#### Méthodes clés

**Workflow actions** :
- `action_submit()` : Brouillon → Soumis
- `action_manager_validate()` : Soumis → Manager Validated
- `action_finance_validate()` : Manager Validated → Finance Validated
- `action_approve()` : Finance Validated → Approved
- `action_disburse()` : Approved → Active (crée l'écriture comptable)
- `action_close()` : Active → Closed
- `action_mark_default()` : Active → Defaulted
- `action_cancel()` : Annule le crédit

**Génération d'échéancier** :
- `action_generate_schedule()` : Crée les lignes microfinance.loan.installment

**Remboursement** :
- `_prepare_payment_move()` : Prépare l'écriture comptable de remboursement
- `action_apply_payment()` : Wizard pour enregistrer un remboursement

**Calculs** :
- `_compute_totals()` : Agrège les montants depuis les échéances
- `_compute_risk_score()` : Calcule le score de 0 à 100

#### Règles métier

1. **Validation de montant** : `loan_amount` doit être entre `product_id.min_amount` et `product_id.max_amount`
2. **Validation de durée** : `number_of_terms` doit être entre `product_id.min_term` et `product_id.max_term`
3. **Numérotation auto** : Champ `name` auto-généré via séquence "Microfinance Loan Reference"
4. **Date d'échéance** : Calculée en fonction de `application_date` + `number_of_terms` mois
5. **Changement d'état** : Validations spécifiques à chaque transition
6. **Décaissement** : Crée une écriture comptable sur le journal et les comptes du produit
7. **Clôture auto** : Passe à "closed" si `outstanding_balance` ≤ 0.01

### 3. microfinance.loan.installment

**Responsabilité** : Représenter une ligne de l'échéancier

#### Champs principaux

```
loan_id (Many2one)                   # Crédit parent
name (Char)                          # Numéro de l'échéance
due_date (Date)                      # Date d'échéance
principal (Float)                    # Capital prévu
interest (Float)                     # Intérêt prévu
penalty (Float)                      # Pénalité prévue
total_due (Float)                    # Total dû
```

#### Paiements (Tracking)

```
paid_principal (Float)               # Capital payé
paid_interest (Float)                # Intérêt payé
paid_penalty (Float)                 # Pénalité payée
residual_amount (Float)              # Montant restant = total_due - paid
state (Selection)                    # 'pending', 'partial', 'paid', 'overdue'
```

#### Méthodes clés

- `_compute_state()` : Détermine l'état selon les résidus et le délai
- `action_apply_penalty()` : Applique la pénalité (appelé par cron)
- `_allocate_payment()` : Répartit un montant de paiement

#### Règles métier

1. **Calcul du capital** : `principal = loan_amount / number_of_terms`
2. **Calcul des intérêts** :
   - **Flat rate** : `interest = (loan_amount × annual_rate) / 12`
   - **Reducing balance** : `interest = (remaining_principal × annual_rate) / 12`
3. **État par défaut** : 'pending' (pas de pénalité au départ)
4. **Application pénalité** : Si `due_date + grace_period < today()` et pas déjà appliquée
5. **État automatique** :
   - `residual_amount == 0` → 'paid'
   - `residual_amount < 0` → impossible (validation)
   - `residual_amount > 0 et due_date < today()` → 'overdue'
   - `residual_amount > 0 et paid_amount > 0` → 'partial'
   - `residual_amount > 0` → 'pending'

### 4. microfinance.loan.payment

**Responsabilité** : Enregistrer et comptabiliser un remboursement

#### Champs principaux

```
loan_id (Many2one)                   # Crédit
payment_date (Date)                  # Date du remboursement
amount (Float)                       # Montant payé
journal_id (Many2one)                # Journal comptable
state (Selection)                    # 'draft', 'posted'
```

#### Allocation (Computed)

```
allocated_penalty (Float)            # Montant alloué aux pénalités
allocated_interest (Float)           # Montant alloué aux intérêts
allocated_principal (Float)          # Montant alloué au capital
```

#### Méthodes clés

- `_allocate_to_installments()` : Répartit le paiement selon l'ordre :
  1. Pénalités les plus anciennes en retard
  2. Intérêts dus
  3. Capital dû
- `_prepare_payment_move()` : Crée l'écriture comptable
- `action_post()` : Valide le paiement et crée l'écriture

#### Règles métier

1. **Validation de montant** : `amount` ≤ `outstanding_balance` du crédit
2. **Ordre d'allocation** : Pénalité → Intérêt → Capital (priorité stricte)
3. **Comptabilité** :
   - **Débit** : Compte journal (caisse/banque)
   - **Crédit** : Compte prêts clients
   - Lignes supplémentaires pour intérêts/pénalités si applicable
4. **Clôture auto** : Si `outstanding_balance` ≤ 0.01 après remboursement, le crédit passe à "closed"

### 5. microfinance.collection.visit

**Responsabilité** : Suivi des visites terrain pour recouvrement

#### Champs principaux

```
loan_id (Many2one)                   # Crédit suivi
agent_id (Many2one)                  # Agent terrain
visit_date (Datetime)                # Date/heure de la visite
status (Selection)                   # 'planned', 'completed', 'missed', 'cancelled'
remarks (Text)                       # Observations
promise_to_pay_date (Date)           # Date promise de remboursement
promised_amount (Float)              # Montant promis
```

#### Règles métier

1. **Tracking simple** : Permet le suivi historique des contacts
2. **Pas de validation** : Les visites sont indépendantes des remboursements

### 6. microfinance.dashboard

**Responsabilité** : Métriques de portfolio

#### Champs principaux (Computed)

```
active_loan_count (Int)              # Nombre de crédits actifs
disbursed_amount (Float)             # Montant total décaissé
outstanding_amount (Float)           # Montant total en retard
overdue_amount (Float)               # Montant > 30 jours de retard
default_rate (Float)                 # % de défaut = Defaulted / Total
```

---

## Flux comptable

### 1. Décaissement (action_disburse)

Lorsqu'un crédit passe à l'état "active" :

```
Journal : product_id.disbursement_journal_id
Date : today()
Description : "Loan Disbursement #[loan_name]"

Mouvements :
  Débit:  product_id.loan_account_id       [loan_amount]
  Crédit: journal_id.default_account_id    [loan_amount]
```

### 2. Remboursement (action_post → payment)

Lorsqu'un remboursement est enregistré :

```
Journal : payment_id.journal_id
Date : payment_date
Description : "Loan Repayment #[loan_name]"

Mouvements :
  Débit:  journal_id.default_account_id    [amount]
  Crédit: product_id.loan_account_id       [allocated_principal]
  Crédit: product_id.interest_account_id   [allocated_interest]
  Crédit: product_id.penalty_account_id    [allocated_penalty]
```

---

## Calcul du score de risque

Le score de risque est calculé comme suit :

```python
score = 0
score += 15 * number_of_overdue_installments
score += 1.2 * number_of_overdue_days_max
score += 40 * (overdue_amount / loan_amount) if overdue_amount > 0
score += 5 * number_of_partial_payments

# Limiter entre 0 et 100
score = min(100, max(0, score))
```

**Exemple** :
- 2 échéances en retard : +30
- 10 jours de retard max : +12
- Montant en retard = 50% : +20
- 3 remboursements partiels : +15
- **Total** : 77 (Risque élevé)

---

## Automatisations et crons

### Cron : Appliquer les pénalités quotidiennement

```
ID : microfinance_apply_penalties
Fréquence : Quotidienne
Action : microfinance.loan.installment._apply_penalties()
```

**Logique** :
1. Trouver toutes les échéances avec `state` ≠ 'paid'
2. Pour chaque échéance : Si `due_date + grace_period < today()` et pas de pénalité
3. Appliquer le montant de pénalité selon le type (fixed ou percentage)
4. Passer l'état à 'overdue'

---

## Sécurité et accès

### Groupes de sécurité

```
microfinance_loan_management.group_manager
  - Valider par manager
  - Accès lecture/écriture sur tous les crédits

microfinance_loan_management.group_finance
  - Valider par finance
  - Accès lecture sur tous les crédits

microfinance_loan_management.group_user
  - Créer et soumettre les crédits
  - Accès lecture/écriture sur ses crédits
```

### Règles d'accès par rôle

| Action | User | Manager | Finance |
|--------|------|---------|---------|
| Créer crédit | ✓ | ✓ | ✗ |
| Soumettre | ✓ | ✓ | ✗ |
| Valider manager | ✗ | ✓ | ✓ |
| Valider finance | ✗ | ✗ | ✓ |
| Approuver | ✗ | ✓ | ✓ |
| Décaisser | ✓ | ✓ | ✗ |
| Enregistrer paiement | ✓ | ✓ | ✓ |

---

## Limitations v1.0

### 🔴 Limitations non gérées

1. **Aucune garantie** : Pas de gestion des garanties/collateral
2. **Pas de groupes solidaires** : Lending groups non implémentés
3. **Pas de frais de dossier** : Aucun frais administratif
4. **Pas d'annulation de remboursement** : Les remboursements postés ne peuvent pas être inversés
5. **Tableau de bord limité** : Version simple, non OWL
6. **Pas de prêts croisés** : Pas de co-emprunteur
7. **Pas de restructuration** : Pas de modification de calendrier post-décaissement

### 🟡 Limitations volontaires

1. **Validation stricte** : Les montants et durées doivent respecter les produits
2. **Pas de surpaiement** : Un surpaiement > solde est rejeté
3. **Pas d'intérêt différé** : Les intérêts s'appliquent à partir de la 1ère échéance
4. **Pas de période de grâce** : Grâce uniquement pour pénalités, pas pour principal/intérêt
5. **Un produit par crédit** : Impossible de mélanger les produits sur un crédit

---

## Performance et optimisations

### Points à surveiller

1. **Calcul des totaux** : Les champs computed `total_*` et `outstanding_balance` sont recalculés à chaque lecture
   - **Impact** : Léger si peu d'échéances
   - **Optimisation possible** : Dénormalisation ou cache

2. **Cron pénalités** : Parcourt toutes les échéances quotidiennement
   - **Impact** : Négligeable pour < 10k crédits
   - **Optimisation possible** : Index sur `state` et `due_date`

3. **Requêtes SQL** : Pas de recherche complexe
   - **Impact** : Minimal
   - **ORM** : Utilisation standard de Odoo

### Recommandations

- **Indice DB recommandé** sur `microfinance_loan_installment` :
  ```sql
  CREATE INDEX idx_installment_loan_state_due 
  ON microfinance_loan_installment (loan_id, state, due_date);
  ```

- **Indice recommandé** sur `microfinance_loan` :
  ```sql
  CREATE INDEX idx_loan_partner_state 
  ON microfinance_loan (partner_id, state);
  ```

---

## Dépendances

### Modules Odoo

- `base` : Base de Odoo (obligatoire)
- `account` : Pour les écritures comptables
- `sale` : Pour les clients
- `web` : Interface web

### Dépendances externes

- Aucune (pure Odoo)

---

## Évolutions futures (v2.0+)

### Fonctionnalités prévues

- [ ] Gestion des garanties et collateral
- [ ] Prêts de groupe et solidarité
- [ ] Frais de dossier configurables
- [ ] Reversal de remboursement
- [ ] Dashboard OWL moderne
- [ ] Restructuration de crédit
- [ ] Tiers tiers du paiement
- [ ] Mobile app
- [ ] Intégration SMS pour rappels
- [ ] Scoring de risque avancé

---

## Logs et débogage

### Activer les logs détaillés

```python
# Dans Odoo console
import logging
_logger = logging.getLogger(__name__)
_logger.setLevel(logging.DEBUG)
```

### Points de débogage clés

1. **Génération d'échéancier** :
   - Vérifier que `number_of_terms` > 0
   - Vérifier que `interest_method` est valide
   - Vérifier que `application_date` est correct

2. **Remboursement** :
   - Vérifier que `outstanding_balance` > 0
   - Vérifier que `amount` ≤ `outstanding_balance`
   - Vérifier que les comptes du produit existent

3. **Comptabilité** :
   - Vérifier que les journaux ont un compte par défaut
   - Vérifier que les comptes comptables existent
   - Vérifier que la société est correcte

---

## Contact et support

- **Responsable** : SysAdaptPro
- **Email** : support@sysadaptpro.com
- **Documentation** : README.md et USER_GUIDE_FR.md

---

**Version** : 1.0 Analyse  
**Date** : Juin 2026  
**Audience** : Développeurs, Administrateurs système, Intégrateurs
