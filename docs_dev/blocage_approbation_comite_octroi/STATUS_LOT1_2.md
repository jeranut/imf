# Statut — Lot 1.2 : Migration ciblée IS/000289 et IS/001076

**Exécuté sur SEFOR (production), avec confirmation explicite de Micka avant écriture.**

## Audit préalable (lecture seule, avant écriture)

| Dossier | Loan ID | État | Application ID | 1er comité | 2ème comité |
|---|---|---|---|---|---|
| IS/000289 | 1449 | avis_cdag | 1154 | absent (NULL) | absent (NULL) |
| IS/001076 | 2327 | avis_cdag | 1319 | absent (NULL) | absent (NULL) |

`microfinance_credit_committee_review` : 0 ligne sur toute la base, aucune ligne orpheline
retrouvée par recherche directe sur `application_id` pour ces deux dossiers - confirmé identique
à l'audit du 31/08 précédent (`DIAGNOSTIC_refus_silencieux.md`), rien n'a changé entretemps.

## Exécution

Via `odoo-bin shell -d SEFOR` (code du disque, incluant le correctif Lot 1.1), appel direct de
`application._ensure_committee_review_slot()` - la même méthode que le correctif Lot 1.1
appellera désormais automatiquement à la volée, pas un script ad-hoc distinct - sur les deux
`microfinance.loan.application` liées à IS/000289 (id 1154) et IS/001076 (id 1319) uniquement.
Chaque dossier vérifié individuellement avant écriture (`assert len(applications) == 1`,
`assert not application.first_committee_review_id`) pour ne toucher que ces deux enregistrements
précis. Aucune décision pré-remplie (vérifié par `assert not ...decision` juste après création).

## Résultat (vérifié en lecture seule après commit)

| Dossier | first_committee_review_id (avant → après) | decision | review_date |
|---|---|---|---|
| IS/000289 | NULL → 1360 | vide | 2026-08-31 (défaut du modèle) |
| IS/001076 | NULL → 1359 | vide | 2026-08-31 (défaut du modèle) |

`microfinance_credit_committee_review` contient désormais exactement 2 lignes (ids 1359 et
1360), une par dossier, `committee_number='first'`, `decision`/`comment`/`postpone_reason`/
`complement` tous vides - aucune autre ligne, aucun autre dossier touché, état des deux crédits
(`avis_cdag`) inchangé.

## Suite pour Micka

La décision "Refusé" que tu avais tentée sur IS/001076 (commentaire "Tsy ilamina") **n'a pas été
restaurée automatiquement** (conformément à l'hypothèse validée au Lot 1) - le slot est
maintenant prêt à recevoir une décision, à ressaisir manuellement via le formulaire une fois le
Lot 1.1 déployé (`-u` + restart du service).

## Prochaine étape : Lot 1.3 (commit unique)

Rien n'a été commité. Le commit final regroupera, en un seul commit, comme demandé :
- Le code de garde `_check_committee_octroi_accepted()` (Lot 1, `microfinance_loan.py`) - déjà
  présent sur disque depuis avant ce chantier, jamais commité.
- Le correctif d'écriture Comité d'Octroi (Lot 1.1, `microfinance_loan_application.py`).
- Ce Lot 1.2 est une opération de **données**, pas de code - rien à ajouter au commit de ce fait,
  déjà appliqué et commité en base via `env.cr.commit()` (transaction Postgres), indépendant de
  git.
- Les tests associés (Lot 1 + Lot 1.1).

**Micka commit manuellement après revue complète du diff** - je ne déclenche aucun commit moi-même.
