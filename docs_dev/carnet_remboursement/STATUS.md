# LOT 1 — Statut : Durée en jours et "Agent BL"

## Fait

1. **`microfinance_loan_management/models/microfinance_loan.py`** : nouvelle méthode
   `get_loan_duration_days()`, ajoutée juste après `get_last_installment_date()` (même bloc de
   méthodes dédiées au rendu des rapports). **Corrigée en cours de lot** (demande explicite :
   ne pas dépendre du décaissement) : calcule désormais
   `(dernière échéance triée - première échéance triée).days`, uniquement à partir de
   l'échéancier — `0` seulement si l'échéancier n'est pas encore généré, disponible même avant
   `disbursement_date` — jamais d'exception, conforme à la convention déjà en place dans ce
   bloc (`_format_contrat_date()`).

2. **`microfinance_loan_management/report/report_carnet_remboursement.xml:195`** : la ligne
   codée en dur `384 andro ... Agent BL : Man` devient :
   ```xml
   <div class="carnet-row"><u>Faharetan'ny findramam-bola</u> : <strong><t t-esc="o.get_loan_duration_days()"/> andro</strong> &#160;&#160; Agent BL : <strong><t t-esc="env.user.name"/></strong></div>
   ```
   Suffixe "andro" resté en texte fixe, comme demandé. Aucune autre ligne du bloc touchée.

## Vérifications effectuées

- XML bien formé (`xmllint --noout`) et module Python compilé (`py_compile`) avant déploiement.
- Cycle complet `stop → -u microfinance_loan_management --stop-after-init --no-http -d SEFOR
  → start` sur SEFOR : 93 modules chargés sans erreur, service actif après redémarrage.
- Test fonctionnel via `odoo-bin shell` sur les deux dossiers de référence des audits
  précédents, après la correction :
  - `IS/001076` (actif, décaissé le 2026-09-05) → **161 andro**.
  - `IS/003363` (non décaissé, `disbursement_date` vide) → **161 andro** également (même
    configuration d'échéancier), aucune exception — confirme que le calcul ne dépend plus du
    décaissement.
- Vérification visuelle du PDF généré (rendu carnet complet) : non effectuée dans ce lot — à
  faire par Micka ou sur demande explicite.

Aucun commit effectué — review et commit manuels par Micka.

---

# LOT 1 (suite) — Statut : Compteur "Findramana faha"

## Fait

1. **`microfinance_loan_management/models/microfinance_loan.py`** : nouvelle méthode
   `get_loan_rank_for_partner()`, ajoutée juste après `get_loan_duration_days()`. Compte les
   crédits engagés (`active`, `closed`, `defaulted`, `written_off`) du même `partner_id` avec
   un `id` inférieur au dossier courant (`search_count`, aucun filtre `company_id`), puis
   ajoute toujours `1` pour le dossier courant lui-même, quel que soit son propre état.

2. **`microfinance_loan_management/report/report_carnet_remboursement.xml:172`** : la ligne
   codée en dur `Findramana faha : 4` devient :
   ```xml
   <div class="carnet-row"><u>Findramana faha</u> : <strong><t t-esc="o.get_loan_rank_for_partner()"/></strong> &#160;&#160; <u>Fifanarahana n°</u> <strong><span t-field="o.name"/></strong></div>
   ```

## Vérifications effectuées

- XML bien formé (`xmllint --noout`) et module Python compilé (`py_compile`) avant déploiement.
- Cycle complet `stop → -u microfinance_loan_management --stop-after-init --no-http -d SEFOR
  → start` sur SEFOR : 93 modules chargés sans erreur, service actif après redémarrage.
- Test fonctionnel via `odoo-bin shell` :
  - `IS/001076` (état `active`) → **rang 1**.
  - `IS/003363` (état `approved`, pas encore décaissé) → **rang 1** également, aucune
    exception — confirme que le dossier courant compte toujours dans son propre rang même
    non engagé.
- **Non testé** : un cas avec rang ≥ 2, impossible sur les données actuelles (aucun partenaire
  de la base SEFOR n'a plus d'un crédit à ce jour, cf. Lot 0) — à revalider dès qu'un cas réel
  se présente.
- Vérification visuelle du PDF généré : non effectuée dans ce lot.

Aucun commit effectué — review et commit manuels par Micka.
