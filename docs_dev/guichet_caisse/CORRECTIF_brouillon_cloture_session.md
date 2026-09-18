# CORRECTIF — Persistance du brouillon de comptage à la clôture de session

Fait suite à [AUDIT_ecart_cloture_session.md](AUDIT_ecart_cloture_session.md) (Option A du
correctif, garde préalable dans `_post_variance_move`, déjà réglée par la configuration des
comptes d'attente d'écart pour toutes les agences). Ce correctif traite un problème distinct,
plus général : quelle que soit la cause de l'interruption (erreur serveur, clic à côté, onglet
fermé, distraction), tout billetage saisi dans le wizard de clôture en 3 temps est perdu tant
que "Confirmer la clôture" (temps 3) n'a pas réussi — les `TransientModel` du wizard ne
persistent rien avant ce clic final.

## Principe

Un nouveau modèle persistant (pas `TransientModel`), `microfinance.caisse.comptage.brouillon`
(+ `microfinance.caisse.comptage.brouillon.line`), garde une copie des quantités saisies et du
motif d'écart, réécrite à chaque transition d'étape du wizard :

- **Temps 1 → Temps 2** (`close.session.wizard.action_confirm_count`) : sauvegarde des
  quantités et du motif courant (`_save_draft()`).
- **Temps 3 → Temps 1** (`variance.wizard.action_back`) : le motif tapé au temps 3 est reporté
  sur le wizard de comptage (temps 1) puis sauvegardé de la même façon.
- **Clôture réussie** (`variance.wizard.action_confirm_close`, après
  `session.action_close_session()`) : le brouillon est supprimé — le comptage vient de devenir
  définitif (`microfinance.caisse.comptage`). Si un appel antérieur dans la même méthode lève
  une exception, toute la transaction du bouton est annulée (comportement inchangé, cf. l'audit
  ci-dessus) et la suppression du brouillon l'est avec elle : le brouillon reste disponible pour
  une reprise.

Un seul brouillon par session (`_sql_constraints` `unique(session_id)` sur
`comptage.brouillon`) : `_save_draft()` réutilise l'enregistrement existant plutôt que d'en
créer un nouveau à chaque transition.

À l'ouverture du wizard (`close.session.wizard.default_get`), si un brouillon existe pour la
session, ses quantités et son motif pré-remplissent le formulaire (temps 1, toujours — pas de
saut direct au temps 3) et un bandeau d'information ("Comptage en cours retrouvé...") s'affiche.

## Modèle dédié, pas de réutilisation de `microfinance.caisse.comptage`

Volontairement séparé : `microfinance.caisse.comptage` porte des contraintes pensées pour un
enregistrement définitif (`_check_variance_comment` — motif obligatoire si écart non nul,
`variance_state`, écriture comptable via `_post_variance_move`) qui ne doivent pas bloquer un
billetage encore en cours de saisie, potentiellement incomplet.

## Limite connue (assumée, pas d'autosave clavier)

La sauvegarde n'a lieu qu'aux transitions d'étape ci-dessus, pas à chaque frappe. Fermer la
fenêtre sans avoir cliqué aucun bouton depuis la dernière transition (par exemple : taper le
motif au temps 3 puis fermer l'onglet sans cliquer "Retour" ni "Confirmer") ne sauvegarde pas
cette frappe. Si l'usage réel montre que ce cas est fréquent, un autosave plus fin (onchange sur
`variance_comment`, ou sauvegarde périodique des quantités au temps 1) pourra être ajouté
séparément — non fait ici pour ne pas sur-ingénierer sans retour d'usage.

## Sessions déjà ouvertes au moment du correctif

Aucune migration : les sessions ouvertes avant ce correctif (Isotry, Mahitsy, Sabotsy Namehana,
Ambanidia ×2, cf. AUDIT_ecart_cloture_session.md §5) démarrent simplement sans brouillon
existant, comme n'importe quelle session avant ce correctif.

## Fichiers modifiés

- `models/microfinance_caisse_comptage_brouillon.py` (nouveau) : les deux modèles.
- `wizard/microfinance_caisse_close_session_wizard.py` : `default_get` (reprise), `_save_draft`,
  appels aux points de transition, suppression du brouillon en fin de clôture réussie.
- `wizard/microfinance_caisse_close_session_wizard_views.xml` : bandeau "brouillon retrouvé"
  (temps 1).
- `security/ir.model.access.csv` : accès caissier/manager sur les deux nouveaux modèles.
- `tests/test_caisse_close_wizard.py` : couverture de la reprise (quantités, motif, unicité du
  brouillon par session) ; un test existant (`test_step1_wizard_has_no_theoretical_or_variance_
  field`) a été ajusté pour ne plus exiger l'absence de `variance_comment` sur le wizard temps 1
  (le champ y existe désormais délibérément, pour porter le motif d'une étape à l'autre — seuls
  `theoretical_total`/`variance`, les valeurs calculées à ne jamais transmettre avant le temps 3,
  restent absents de ce modèle).
