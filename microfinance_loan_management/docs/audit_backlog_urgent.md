# Audit du backlog — 13 points prioritaires

Audit du code réel de `microfinance_loan_management` uniquement (models, views,
controllers, tests). Le README n'a pas été utilisé comme source — il peut être en
décalage avec l'implémentation réelle.

## Tableau récapitulatif

| # | Fonctionnalité | Statut | Fichiers / champs concernés | Reste à faire |
|---|---|---|---|---|
| 1 | PAR 30/60/90/180 | PARTIELLEMENT FAIT | `models/microfinance_loan.py::get_par_buckets` | Renommer/redécouper les tranches (actuellement 1-30/31-60/61-90/90+, pas de tranche 180 distincte) — petit ajustement |
| 2 | Module Épargne complet | HORS PÉRIMÈTRE | — (rien trouvé) | Nouveau module séparé, pas une extension |
| 3 | Groupes solidaires | PAS FAIT | — (rien trouvé) | Nouveau modèle dans ce module (crédit de groupe) — ampleur moyenne |
| 4 | Scoring configurable avec pondérations | FAIT | `models/microfinance_scoring.py` (`computation` linéaire/seuil ajouté), `models/microfinance_loan.py::action_calculate_scoring/_get_scoring_metrics`, `data/scoring_rules_data.xml` (profil + règles par défaut), `views/microfinance_loan_views.xml`, `views/microfinance_scoring_views.xml`, `controllers/microfinance_dashboard_controller.py`, `tests/test_scoring.py` | `risk_score` retiré ; un seul champ `internal_score` (0-100, plus haut = plus sûr) alimenté par le moteur de règles configurable, ancien formule migrée en règles par défaut (score de base + 4 malus linéaires) |
| 5 | Garanties + ratio de valorisation | PARTIELLEMENT FAIT | `models/microfinance_loan_guarantee.py`, `min_guarantee_ratio` sur `microfinance_loan_product.py` | Le ratio (114%, 120%...) est déjà configurable et sans plafond ; il manque des types de garantie détaillés (terrain/véhicule/maison/meuble/salaire) et une valorisation différenciée par type — petit ajustement |
| 6 | Notifications SMS/WhatsApp/e-mail | PAS FAIT | — (rien trouvé) | Nouveau sous-système (mail.template + cron pour l'e-mail, reste dans ce module ; SMS/WhatsApp nécessite une passerelle/API tierce, potentiellement hors périmètre) |
| 7 | Audit trail complet | PARTIELLEMENT FAIT | `mail.thread`/`tracking=True` sur loan/product/payment/visit/scoring.profile | Pas de `mail.thread` sur installment/guarantee/provision.rule ; tous les champs ne sont pas trackés ; pas de log exhaustif de toutes les actions — petit ajustement pour combler, mais un audit trail "complet" au sens strict dépasse `mail.thread` |
| 8 | Décaissement automatique planifié | PAS FAIT | `models/microfinance_loan.py::action_disburse` (manuel, immédiat) | Ajouter une date planifiée + cron — ampleur petite à moyenne, reste dans ce module |
| 9 | Jours ouvrables / jours fériés | PAS FAIT | `models/microfinance_loan.py::_period_delta`, `action_generate_schedule` (dates calendaires brutes) | Intégrer `resource.calendar` — ampleur moyenne, reste dans ce module |
| 10 | Prélèvement auto arriérés sur épargne | HORS PÉRIMÈTRE | — | Dépend du point 2 (épargne), non applicable sans ce module séparé |
| 11 | Rééchelonnement avec ancien échéancier conservé | PARTIELLEMENT FAIT | `models/microfinance_loan.py::_reschedule_installments` (`unlink()` + résumé texte via `message_post`) | Ancien échéancier supprimé, seul un résumé texte non structuré est conservé dans le chatter — ajouter un modèle d'historique/snapshot — ampleur petite à moyenne |
| 12 | Comité de crédit / workflow configurable | PAS FAIT | `state` (Selection figée) + `action_manager_validate`/`action_finance_validate`/`action_approve` (un seul validateur par étape) | Workflow à nombre d'étapes fixe codé en dur, aucun modèle de comité multi-validateurs ni de seuils déclenchant des étapes — ampleur moyenne à grande, reste dans ce module |
| 13 | Fonds de crédit (bailleurs/fonds propres) | PAS FAIT | — (rien trouvé) | Nouveau modèle simple + champ sur produit/crédit — petit ajustement, reste dans ce module |

---

## Détail point par point

### 1. PAR 30/60/90/180 et tableau de bord du risque — PARTIELLEMENT FAIT

**Preuve** : `models/microfinance_loan.py::get_par_buckets()` (ligne ~163) définit :
```python
tranches = [('1-30', 1, 30), ('31-60', 31, 60), ('61-90', 61, 90), ('90+', 91, None)]
```
Consommé tel quel par `controllers/microfinance_dashboard_controller.py` (`par_buckets = Loan.get_par_buckets(company.id)`, ligne 81) et affiché par `static/src/js/microfinance_loan_dashboard.js` (`data.par_buckets.labels`/`.values`, lignes 140-141).

Ce sont bien 4 tranches, mais **1-30/31-60/61-90/90+**, pas 30/60/90/180. Il n'y a pas de tranche distincte à 180 jours (91+ regroupe tout au-delà de 90 jours en une seule tranche "90+").

**Ampleur** : petit ajustement — remplacer la liste `tranches` par les bornes souhaitées (ex. ajouter une 5ᵉ tranche 91-180/181+ si "30/60/90/180" doit vraiment donner 4 tranches avec 180 comme borne, ou clarifier la nomenclature attendue).

---

### 2. Module Épargne complet — HORS PÉRIMÈTRE

**Preuve** : recherche exhaustive (`grep -rniE "savings|epargne|deposit|dépôt|withdrawal|retrait"`) sur tout le module : aucun résultat. Aucun modèle, vue, champ ou menu lié à un compte d'épargne, dépôt ou retrait.

**Conclusion** : ce n'est pas une extension du module crédit existant, c'est un domaine fonctionnel séparé (comptes, mouvements, intérêts créditeurs, etc.). À traiter comme un module Odoo à part entière.

---

### 3. Groupes solidaires — PAS FAIT

**Preuve** : recherche exhaustive (`solidar|group_loan|village.*bank|grameen|credit.*group`) : seule occurrence trouvée est un filtre de vue `group_by` générique sans rapport (`views/microfinance_loan_installment_views.xml:61`, `context="{'group_by':'loan_id'}"`). Aucun modèle de crédit de groupe, de membres, de banque de village.

**Ampleur** : contrairement à l'épargne, ceci reste conceptuellement dans le domaine "crédit" — un nouveau modèle `microfinance.loan.group` (ou similaire) avec membres liés à des `microfinance.loan` individuels serait une extension plausible de ce module, mais représente un développement de taille moyenne (nouveau modèle, workflow de groupe, vues, règles de garantie mutuelle éventuelles).

---

### 4. Scoring interne configurable avec règles et pondérations — FAIT

**Résolution** : les deux systèmes parallèles (`risk_score` codé en dur vs `internal_score`
configurable) ont été fusionnés en un seul. `risk_score` et `_compute_risk_score()` ont été
retirés de `models/microfinance_loan.py`. `internal_score` (0-100, plus haut = plus sûr) est
désormais **le seul** champ de score, calculé par `action_calculate_scoring()` à partir des
règles de `microfinance.scoring.profile`/`microfinance.scoring.rule`.

Pour ne perdre aucun comportement, `microfinance.scoring.rule` a gagné un champ
`computation` (`threshold` seuil existant / `linear` nouveau : points = poids × valeur de la
métrique, condition ignorée), et 4 nouvelles métriques par crédit (`loan_overdue_installment_count`,
`loan_max_days_overdue`, `loan_overdue_amount_ratio`, `loan_partial_payment_count`) plus une
métrique `baseline` (constante 1). `data/scoring_rules_data.xml` crée un profil générique par
défaut « Profil de scoring standard » avec 5 règles reproduisant exactement l'ancienne formule
(`overdue_installment_count*15 + max_days*1.2 + amount_ratio*40 + partial_count*5`) sous forme
d'un score de base de 100 duquel ces mêmes malus linéaires sont retranchés.

Les vues crédit (`views/microfinance_loan_views.xml`), les vues de scoring
(`views/microfinance_scoring_views.xml`) et le contrôleur de dashboard
(`controllers/microfinance_dashboard_controller.py`, répartition par risque désormais basée
sur `risk_level` au lieu de bornes 35/70 codées en dur) n'exposent plus qu'`internal_score`,
accompagné de `risk_level`/`scoring_decision`. Voir `tests/test_scoring.py` (profil/règles par
défaut chargés, modification d'une règle change le score d'un crédit existant, un seul champ
de score exposé) et `tests/test_write_off.py::test_written_off_loan_excluded_from_scoring`.

---

### 5. Gestion des garanties avec valorisation configurable (114%, 120%...) — PARTIELLEMENT FAIT

**Preuve — types de garantie** : `models/microfinance_loan_guarantee.py` (ligne 12) :
```python
guarantee_type = fields.Selection([('asset', 'Garantie matérielle'), ('guarantor', 'Caution personnelle')], ...)
```
Seulement deux types génériques. Le détail (terrain, véhicule, maison, meuble, salaire) n'existe qu'en texte libre dans `description` (Char), pas comme valeur structurée.

**Preuve — ratio de valorisation** : `models/microfinance_loan_product.py` (`min_guarantee_ratio`, Float, défaut 0.0, sans plafond) et son usage dans `models/microfinance_loan.py::_check_eligibility()` (ligne ~353) :
```python
if product.min_guarantee_ratio > 0:
    required_guarantee = loan.loan_amount * product.min_guarantee_ratio / 100.0
    if loan.guarantee_total < required_guarantee:
        ...
```
Ce champ **peut déjà être positionné à 114.0 ou 120.0** (aucune contrainte d'upper bound dans `_check_values`) — le mécanisme de ratio de couverture configurable par produit existe donc réellement, contrairement à ce qu'un simple champ `estimated_value` brut sans ratio laisserait supposer.

**Ce qui manque** : une valorisation différenciée par type de garantie (ex. un terrain valorisé différemment d'un véhicule), et des types de garantie structurés au-delà de asset/guarantor.

**Ampleur** : petit ajustement — enrichir la `Selection` `guarantee_type` et, si une décote différente par type est voulue, ajouter un champ de type de garantie paramétrable (pas nécessairement un nouveau modèle).

---

### 6. Notifications automatiques (SMS, WhatsApp, e-mail) — PAS FAIT

**Preuve** : recherche exhaustive (`sms|whatsapp|mail\.template|mail\.mail|send_mail`) : aucun résultat en dehors de `mail.thread`/`mail.activity.mixin` (chatter interne, pas des notifications sortantes vers le client). `data/cron.xml` ne contient que 2 crons (`cron_update_overdue_and_penalties`, `cron_post_provisions`), aucun n'envoie de notification — le premier ne fait qu'appliquer les pénalités et recalculer le risque.

**Ampleur** : nouveau sous-système. Un cron + `mail.template` pour les rappels e-mail resterait dans le périmètre de ce module. Une intégration SMS/WhatsApp nécessite une passerelle/API tierce (module `sms` d'Odoo Enterprise ou connecteur externe) — à évaluer séparément selon le fournisseur retenu.

---

### 7. Historique complet des modifications (audit trail) — PARTIELLEMENT FAIT

**Preuve** : `_inherit = ['mail.thread', 'mail.activity.mixin']` présent sur `microfinance.loan`, `microfinance.loan.product`, `microfinance.loan.payment`, `microfinance.collection.visit`, `microfinance.scoring.profile` (5 modèles). `tracking=True` posé sur les champs clés de `microfinance.loan` (nom, partenaire, produit, montant, durée, état, agents, score, `reschedule_count`, `co_borrower_id`, etc. — 17 occurrences).

**Ce qui manque** : `microfinance.loan.installment`, `microfinance.loan.guarantee` et `microfinance.provision.rule` n'ont **aucun** `mail.thread` (aucune trace de qui a modifié une échéance ou une garantie). Sur les modèles trackés, tous les champs ne portent pas `tracking=True` (ex. `application_date`, `note`, `guarantee_total`, `fee_amount_due`). Les modifications d'échéances lors d'une annulation de paiement ou d'un rééchelonnement sont résumées en texte dans le chatter du crédit (`message_post`), pas dans un journal structuré par champ.

**Ampleur** : petit ajustement pour combler les trous listés ci-dessus (ajouter `mail.thread`/`tracking` où manquant). Un audit trail "complet" au sens strict (chaque lecture, chaque champ, chaque suppression, y compris hors mail.thread) dépasserait ce que `mail.thread` peut offrir nativement et nécessiterait un mécanisme de journalisation dédié.

---

### 8. Décaissement automatique planifié — PAS FAIT

**Preuve** : `models/microfinance_loan.py::action_disburse()` (ligne ~606) est déclenché manuellement (bouton), s'exécute immédiatement et fixe `disbursement_date = fields.Date.context_today(loan)`. Aucun champ de date planifiée, aucun cron ne référence `action_disburse`.

**Ampleur** : petite à moyenne — ajouter un champ `scheduled_disbursement_date` et un cron qui recherche les crédits approuvés à cette date pour appeler `action_disburse()`. Reste dans ce module.

---

### 9. Calcul des jours ouvrables et jours fériés — PAS FAIT

**Preuve** : `models/microfinance_loan.py::_period_delta()` (ligne ~412) et `action_generate_schedule()` (ligne ~423) utilisent uniquement `dateutil.relativedelta` sur des dates calendaires brutes (`due_date = schedule_start + (delta * idx)`), sans aucune référence à `resource.calendar` ni à un calendrier de jours fériés. Aucune occurrence de `resource.calendar`/`holiday` dans tout le module.

**Ampleur** : moyenne — intégrer `resource.calendar` (dépendance à ajouter) et adapter le calcul de `due_date` dans `action_generate_schedule()`, `_reschedule_installments()` et le bucket de délai de grâce pour décaler les échéances tombant un jour non ouvré/férié. Reste dans ce module mais touche plusieurs points d'ancrage.

---

### 10. Prélèvement automatique des arriérés sur l'épargne — HORS PÉRIMÈTRE

**Preuve** : dépend directement du point 2 (module Épargne), qui n'existe pas dans ce module. Sans compte d'épargne, aucun prélèvement automatique n'est possible.

**Conclusion** : hors périmètre pour la même raison que le point 2 — nécessite d'abord le module Épargne séparé.

---

### 11. Rééchelonnement avancé avec conservation de l'ancien échéancier — PARTIELLEMENT FAIT

**Preuve** : `models/microfinance_loan.py::_reschedule_installments()` (ligne ~480). Le compteur `reschedule_count` est bien incrémenté et tracké (`tracking=True`). Mais :
```python
(unpaid - partially_paid).unlink()
```
(ligne ~516) — les échéances non payées sont **supprimées**, pas archivées. L'ancien échéancier n'est conservé que sous forme de texte non structuré dans le chatter :
```python
self.message_post(body=_(
    'Rééchelonnement n°%(count)s effectué.<br/>Ancien échéancier restant :<br/>%(old)s ...'
))
```
(ligne ~549). Ce résumé texte n'est interrogeable ni par requête ORM, ni par rapport, ni par filtre — seulement lisible manuellement dans le fil de discussion.

**Ampleur** : petite à moyenne — introduire un modèle d'historique (ex. `microfinance.loan.schedule.snapshot` ou un flag `active=False`/`reschedule_id` sur les anciennes lignes d'échéance au lieu de `unlink()`) pour rendre l'ancien échéancier requêtable.

---

### 12. Comité de crédit et workflow configurable — PAS FAIT

**Preuve** : `state` (ligne 25) est une `Selection` figée en dur (`draft`/`submitted`/`manager_validated`/`finance_validated`/`approved`/`active`/`closed`/`defaulted`/`written_off`/`cancelled`). Chaque transition est une méthode dédiée sans paramétrage :
```python
def action_manager_validate(self):
    self.write({'state': 'manager_validated', 'manager_id': self.env.user.id})

def action_finance_validate(self):
    self.write({'state': 'finance_validated', 'finance_user_id': self.env.user.id})
```
Un seul utilisateur (`self.env.user`) est enregistré par étape (`manager_id`, `finance_user_id`) — aucune notion de comité (plusieurs validateurs sur une même étape), aucun modèle de configuration des étapes, aucun seuil (ex. montant > X ⇒ étape supplémentaire).

**Ampleur** : moyenne à grande — nécessiterait un modèle de workflow paramétrable (étapes, rôles, seuils) et un modèle de comité (plusieurs validateurs, quorum, décision collégiale). Reste dans le périmètre de ce module mais représente une refonte structurelle du workflow actuel, pas un simple ajout de champ.

---

### 13. Fonds de crédit (bailleurs, fonds propres) — PAS FAIT

**Preuve** : recherche exhaustive (`bailleur|fund.*source|funding|fonds.*propre|lender`) sur tout le module : aucun résultat. Ni `microfinance.loan.product` ni `microfinance.loan` ne portent de champ ou modèle traçant l'origine des fonds prêtés.

**Ampleur** : petite — un nouveau modèle simple (ex. `microfinance.funding.source`, nom + type fonds propres/bailleur externe + éventuel plafond) avec un Many2one sur `microfinance.loan.product` et/ou `microfinance.loan` suffirait. Reste dans ce module.
