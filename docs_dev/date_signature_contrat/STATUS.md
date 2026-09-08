# LOT 1 — Statut : Date de signature du contrat

Implémentation complète selon `docs_dev/date_signature_contrat/AUDIT.md` (Lot 0).

## Fichiers modifiés / créés

- `models/microfinance_loan.py` :
  - Nouveau champ `contract_signature_date` (Date, `copy=False`).
  - Nouvelle méthode `action_open_contract_signature_wizard()` (ouvre le wizard, même
    convention que `action_write_off()`/`action_open_payment_wizard()` : dict
    `ir.actions.act_window`, `target='new'`, `context={'default_loan_id': self.id}`).
  - Nouveau `_CONTRACT_SIGNATURE_LOCKED_FIELDS` + `_check_contract_signature_locked()`,
    appelée dans `write()` avant `super().write()` (juste après
    `_check_locked_dossier_fields()`, sans les fusionner — logique **indépendante de
    `state`**, aucune dérogation/contexte d'échappement, contrairement au verrouillage
    existant basé sur les états).
  - `help=` de `signed_contract` mis à jour (ne mentionne plus "remplacement possible").

- `wizard/microfinance_loan_contract_signature_wizard.py` (nouveau) : `TransientModel`,
  structure calquée sur `microfinance.loan.writeoff.wizard` — `loan_id` (Many2one, requis,
  pas de default Python, alimenté par `default_loan_id` du contexte), `signature_date`
  (Date, requis, `default=fields.Date.context_today`, éditable), `signed_contract` (Binary,
  requis), `signed_contract_filename` (Char), `action_confirm()` (un seul `write()` sur
  `loan_id`, puis `ir.actions.act_window_close`).

- `wizard/microfinance_loan_contract_signature_wizard_views.xml` (nouveau) : vue form,
  footer Confirmer/Annuler (`special="cancel"`), même gabarit que
  `microfinance_loan_writeoff_wizard_views.xml`.

- `wizard/__init__.py` : import du nouveau wizard.

- `views/microfinance_loan_views.xml` :
  - Header : le widget `signed_contract_upload` est remplacé par un bouton
    "Téléverser le contrat signé" (`action_open_contract_signature_wizard`, `type="object"`,
    style `btn-cefor-print`), `invisible` si l'état n'autorise pas l'upload **ou** si
    `contract_signature_date` est déjà renseigné.
  - Panneau SUIVI : `contract_signature_date` ajouté en lecture seule, juste après
    "Date de décaissement" (`disbursement_date`). Le champ `signed_contract` (widget
    `binary` natif) passe en `readonly="1"` **inconditionnel** — consultation/
    téléchargement uniquement, plus aucune interaction d'upload direct depuis ce panneau.

- `security/ir.model.access.csv` : 3 lignes ajoutées pour
  `model_microfinance_loan_contract_signature_wizard` (Agent crédit, Manager crédit,
  Finance microfinance — mêmes groupes qu'en écriture sur `microfinance.loan`).

- `__manifest__.py` : ajout de `wizard/microfinance_loan_contract_signature_wizard_views.xml`
  dans `data`.

## Nettoyage (dette du lot précédent, devenue obsolète avec ce lot)

Le widget custom `signed_contract_upload` (introduit dans un lot antérieur pour styliser le
bouton d'upload du header) n'a plus d'utilisation dans la vue une fois remplacé par le bouton
ouvrant le wizard — supprimé pour ne pas laisser de code mort :
- `static/src/js/signed_contract_upload_field.js` (supprimé)
- `static/src/xml/signed_contract_upload_field.xml` (supprimé)
- Entrées correspondantes retirées de `__manifest__.py` (assets) et de
  `static/src/scss/microfinance_loan_form.scss` (règle `.o_upload_contrat_signe_header`).

## Vérifications effectuées

- `-u microfinance_loan_management` : aucune erreur, module chargé proprement.
- `get_view()` côté serveur sur `microfinance.loan` et sur le nouveau wizard : arch compilé
  sans erreur, bouton header et champ `contract_signature_date` bien présents avec les
  bonnes conditions `invisible=`.
- **Flux complet exécuté en conditions réelles** (sur IS/003363, état `approved`, puis
  **nettoyé immédiatement après** — voir note ci-dessous) :
  1. `action_open_contract_signature_wizard()` retourne bien l'action `ir.actions.act_window`
     attendue.
  2. Le wizard, créé avec `default_loan_id` en contexte, résout correctement `loan_id` et
     pré-remplit `signature_date` à la date du jour.
  3. `action_confirm()` écrit les 3 champs en un seul `write()` ; `contract_signature_date`
     et `signed_contract` sont bien renseignés sur le crédit après confirmation.
  4. Une tentative de réécriture directe de `signed_contract` **après** confirmation lève
     bien l'`UserError` attendue ("Le contrat signé et sa date de signature ne peuvent plus
     être modifiés une fois confirmés.").
  5. Une tentative de remise à vide de `contract_signature_date` lève la même erreur.
  6. Une seconde confirmation du wizard sur le même crédit (simulant une réouverture/race)
     est également bloquée par le `write()` du modèle — le verrouillage tient même si
     l'invisibilité du bouton était contournée (défense en profondeur).
- Recherche de `sudo()` existant dans le module touchant `microfinance.loan.write()` :
  aucun trouvé (le seul `sudo()` du fichier porte sur `ir.attachment.search()`, sans
  rapport) — confirmé qu'aucun contournement silencieux du nouveau verrouillage n'existe
  dans le code actuel.

**Note sur le test en conditions réelles** : la vérification du point 3 ci-dessus a
nécessité un `env.cr.commit()` intermédiaire (pour lire l'état après confirmation), ce qui a
temporairement écrit des données de test (fichier/date factices) sur le dossier réel
IS/003363. Ces données ont été **entièrement nettoyées immédiatement après** (suppression
directe en SQL du message de chatter, des deux pièces jointes créées, et remise à `NULL` de
`contract_signature_date` sur le dossier — le nettoyage a nécessité un accès SQL direct
puisque le nouveau verrouillage bloque justement ce genre de correction via l'ORM, comme
prévu). Vérifié après coup : IS/003363 est revenu à son état exact d'avant le test (état
`approved`, `contract_signature_date` vide, aucune pièce jointe/message résiduel).

## Points d'attention pour la review

- Le verrouillage est strictement irréversible via l'ORM (aucune dérogation, aucun groupe,
  comme demandé) : toute correction future d'une erreur de saisie (mauvais fichier, mauvaise
  date) nécessitera une intervention SQL directe — à documenter dans une procédure support
  si ce cas se présente en usage réel.
- Aucune migration de données existantes : les dossiers déjà signés avant ce lot ont
  `contract_signature_date` vide et le resteront tant que personne ne relance le processus
  (qui est désormais bloqué pour ces dossiers si `signed_contract` est déjà rempli... en
  réalité non : le verrouillage ne se déclenche que si `contract_signature_date` est déjà
  renseigné, pas si seul `signed_contract` l'est. Un dossier ancien avec `signed_contract`
  rempli mais `contract_signature_date` vide reste donc réécrivable via le wizard - à
  confirmer avec Micka si c'est le comportement voulu pour l'historique, ou si ces dossiers
  doivent être traités à part).

Non commité — review et commit manuels par Micka.
