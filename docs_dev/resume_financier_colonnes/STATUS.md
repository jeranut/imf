# LOT 1 — Statut : Mise en 2 colonnes du bloc "Résumé financier"

## Fait

1. **`microfinance_loan_management/views/microfinance_loan_views.xml`** : le
   `<group string="Résumé financier">` natif est remplacé par
   `<group name="resume_financier_wrapper">` contenant 2 sous-groupes :
   - "Résumé financier — Crédit" (17 champs, dont `bypass_cash_balance` — non listé dans le
     prompt, placé ici par défaut comme proposé au Lot 0).
   - "Résumé financier — Épargne / Garanties" (`guarantee_total` uniquement côté natif —
     sert aussi d'ancrage pour l'injection du module épargne, voir point 2).
   - Aucun `attrs`/`readonly`/`invisible` existant modifié, seulement la position des champs.

2. **`microfinance_savings_management/views/microfinance_loan_views_inherit.xml`** :
   le xpath des champs épargne/garanties (`savings_target_amount`, `savings_target_reached`,
   `guarantee_savings_required`, `guarantee_savings_balance`, `guarantee_savings_verified`)
   est déplacé de `fee_move_id` (désormais dans la colonne Crédit) vers `guarantee_total`
   (colonne Épargne / Garanties). Le xpath `co_borrower_id position="after"` (bloc "Dossier",
   `savings_requirement_type`/`savings_account_id`) n'a pas été touché, comme validé au Lot 0.

3. **`microfinance_loan_management/views/microfinance_scoring_views.xml`** : l'ancrage du
   groupe "Scoring interne" est changé de
   `//field[@name='internal_score']/ancestor::group[1]` vers
   `//group[@name='resume_financier_wrapper']` — il reste inséré en pleine largeur juste en
   dessous des 2 colonnes, comme validé au Lot 0, mais sans dépendre de la position interne
   d'`internal_score`.

## Écart signalé (pas un blocage)

`savings_target_booked_amount` et `savings_target_deadline` (chantier
`docs_dev/epargne_cible_progressive/`) **ne sont pas encore codés** au moment de ce lot — ils
n'ont donc pas été ajoutés au xpath épargne (qui aurait provoqué une erreur "champ inconnu"
au chargement de la vue). Quand ils seront implémentés, il suffira de les insérer dans le
même `<field name="guarantee_total" position="after">` de
`microfinance_loan_views_inherit.xml`, aux côtés de `savings_target_amount`/
`savings_target_reached`.

## Vérifications effectuées

- Les 3 fichiers XML modifiés sont bien formés (`xmllint --noout`).
- Cycle complet `stop → -u microfinance_loan_management,microfinance_savings_management
  --stop-after-init --no-http -d SEFOR → start` exécuté sur SEFOR : les 93 modules se
  chargent sans erreur, `microfinance_loan_views.xml`, `microfinance_scoring_views.xml` et
  `microfinance_loan_views_inherit.xml` se chargent tous les trois sans exception (log
  `/opt/odoo17/odoo.log`, aucune erreur d'xpath introuvable ni de champ inconnu). Service
  `odoo17` redémarré et actif.
- Aucun champ perdu ni dupliqué : les 18 champs natifs originaux + les 5 champs épargne
  injectés sont tous présents, comptés dans le fichier restructuré.

## Reste à faire (hors périmètre de ce lot)

- Vérification visuelle dans le navigateur (alignement des 2 colonnes, positionnement de
  "Scoring interne") — non effectuée ici, à faire par Micka ou sur demande explicite.
- Ajout de `savings_target_booked_amount`/`savings_target_deadline` une fois ce chantier
  codé (cf. écart signalé ci-dessus).

Aucun commit effectué — review et commit manuels par Micka.
