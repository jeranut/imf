# Transfert inter-agences — décisions & limites connues (v1)

Complément d'implémentation à `AUDIT_transfert_inter_agence.md`. Décisions validées par
Micka à l'issue du sous-lot C. Ce fichier n'est pas un audit : il consigne les choix arrêtés
et les limites assumées de la première version.

## 1. Journal d'en-tête des écritures de liaison

Les écritures des étapes 1 à 3 (encaissement source, remise au coursier, réception
destination) sont posées **avec le journal `TRANSIT` en en-tête** (type `general`), leurs
lignes touchant le compte de caisse et le compte de transit `302000`. Le solde caisse du
guichet est calculé sur `account.move.line` **par compte**, pas par journal : il reste donc
exact. Ce choix sépare proprement la numérotation des pièces de liaison.

## 2. Fenêtre de transit non tracée — LIMITE ASSUMÉE

L'étape 2 (`microfinance.transfert.lot.action_valider`) ramène le compte `302000` de
l'agence **source** à zéro (« solde à zéro » demandé au plan). Entre cette remise au coursier
et la réception à l'agence destination (étape 3, `action_valider_destination`), les fonds
sont physiquement chez le coursier mais n'apparaissent **dans aucun compte `302000`** : le
solde consolidé du réseau CEFOR est transitoirement **sous-évalué du montant en transit**.

**Condition d'acceptabilité** : remise et réception le même jour ou le lendemain (coursier
physique à l'échelle d'Antananarivo). Si les délais s'allongent en pratique → chantier
séparé pour un sous-compte « en route » dédié, **pas** un correctif de la v1.

Signalé aussi en commentaire dans le code, à l'endroit de l'étape 2
(`microfinance_transfert_lot.py`, `action_valider`).

## 3. Garde surpaiement

Vérification **préventive** `amount <= destination_loan.balance_total` au moment de la
création du transfert au guichet source (sous-lot D, `register_transfert`), même message que
la garde du remboursement local. **Ce n'est pas une garantie absolue** : le solde du crédit
peut évoluer entre l'encaissement source et la validation destination si un autre
remboursement intervient entre-temps sur le même crédit. Dans ce cas la validation
destination (`action_valider_destination` → `_allocate_to_installments`) lève « Surpaiement
interdit » et le transfert reste bloqué en `en_transit` (correction manuelle).

## 4. `microfinance.loan.payment` sur le journal TRANSIT (`general`)

L'étape 4 crée un `microfinance.loan.payment` normal mais sur le journal `TRANSIT`
(type `general`). Le champ `journal_id` de ce modèle a un **domaine de vue**
`[('type','in',('bank','cash'))]` mais **aucune `@api.constrains` serveur** : l'affectation
programmatique passe, c'est volontaire. Un futur ajout de contrainte de type sur ce champ
casserait l'étape 4 — commentaire explicite posé dans le code
(`microfinance_transfert_remboursement.py`, `action_valider_destination`).

## 5. Transition « Annulé » — REPORTÉE

Aucune conception de contre-passation dans ce chantier. L'état `annule` reste présent dans le
`Selection` de `microfinance.transfert.remboursement` pour l'avenir, **sans méthode
l'implémentant**. En cas d'erreur (mauvais client, montant erroné) avant validation du lot :
correction manuelle (comptable) pour l'instant. Un lot séparé traitera l'annulation propre
(reversal des écritures 1/2/3, éventuel remboursement à annuler côté destination).

## 6. Journal TRANSIT conditionné au plan PCEC

`post_init_hook` du module ne crée le journal `TRANSIT` (et ne s'appuie sur `302000`) que
sur les sociétés dont `chart_template == 'mg_pcec'`. Un transfert exige que **les deux**
agences (source ET destination) aient le plan PCEC ; `_get_company_transit_journal` lève une
`UserError` explicite sinon. Sur l'instance réelle, installer le chart PCEC sur au moins une
seconde société avant tout test bout-en-bout (pris en charge par Micka, hors périmètre du
développement).

## 7. Périmètre v1

Remboursement crédit uniquement. Le dépôt / retrait d'épargne inter-agence est **prévu dans
la conception** (`operation_type` sur le modèle, `loan_id` seul champ cible pour l'instant)
mais **non implémenté**.
