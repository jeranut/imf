# Registre de configuration agence — guichet caisse

Suivi des réglages qui doivent être renseignés explicitement pour chaque agence
provisionnée (`res.company`), au-delà des valeurs par défaut. Un champ non coché ici
signifie soit qu'il reste à configurer, soit que l'agence tourne encore sur le
comportement par défaut (rétrocompatibilité) — vérifier avant de considérer l'agence
comme complètement configurée.

## disbursement_journal_ids (Journaux de décaissement autorisés — guichet)

Champ `res.company.disbursement_journal_ids` (Many2many vers `account.journal`,
`microfinance_loan_management/models/res_company.py`). Restreint la liste des journaux
proposés à l'écran « Décaissement crédit » du guichet caisse (`availableJournals`,
`microfinance_caisse_pos.js::loadLists()`). Laissé vide, TOUS les journaux bank/cash de
l'agence sont proposés sans distinction — y compris Épargne / Banque-Épargne, sans
rapport avec un décaissement de crédit.

**Règle : pour chaque agence provisionnée, `disbursement_journal_ids` doit être
renseigné explicitement avec les seuls journaux Crédits / Caisse / Banque-Crédits
pertinents, jamais Épargne / Banque-Épargne.**

| Agence (company_id) | Crédits (code CRE) | Caisse (code CAI) | Banque-Crédits (code BQCR) | `disbursement_journal_ids` configuré ? |
|---|---|---|---|---|
| Isotry (1) | journal id 26 | journal id 25 | journal id 24 | À renseigner |
| Ambanidia (2) | journal id 1510 | journal id 1509 | journal id 1508 | À renseigner |
| Ampitatafika (3) | journal id 1526 | journal id 1525 | journal id 1524 | À renseigner |
| Mahitsy (6) | journal id 1494 | journal id 1493 | journal id 1492 | À renseigner |
| Andoharanofotsy (9) | journal id 2164 | journal id 2163 | journal id 2162 | À renseigner |

Toute nouvelle agence provisionnée doit ajouter une ligne à ce tableau et renseigner
`disbursement_journal_ids` avant sa mise en production du guichet caisse.
