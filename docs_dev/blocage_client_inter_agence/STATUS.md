# Statut dev — blocage_client_inter_agence
Dernière inspection : 2026-09-18

Un client (même CIN) avec un prêt en cours dans une autre agence ne peut être ni créé dans
l'agence courante ni obtenir un crédit. Rien n'a été commité par ce chantier ; revue manuelle attendue.

## Fait
- [x] Constante unique `ACTIVE_LOAN_STATES = ('active', 'defaulted')` (`active` inclut le crédit activé non décaissé ; `approved` et `written_off` exclus) — `microfinance_loan_management/models/res_partner.py`
- [x] Helper central `res.partner._check_no_active_loan_elsewhere(cin, company_id)` : recherche en `sudo()` limitée aux crédits d'autres agences, `ValidationError` qui ne nomme que les agences — `microfinance_loan_management/models/res_partner.py`
- [x] Blocage à la création (`create`) et à la modification du CIN, du type de pièce ou de la société (`write`), uniquement sous `context.get('microfinance_context')` — `microfinance_loan_management/models/res_partner.py`
- [x] Garde-fou sur `microfinance.loan` : `create`, `action_approve`, `action_activate`, `action_process_disbursement` — `microfinance_loan_management/models/microfinance_loan.py`
- [x] CIN obligatoire (type de pièce `cin` + numéro) pour un client particulier (`microfinance_partner_type == 'client'`, `microfinance_client_type == 'individual'`) sous `microfinance_context`, en contrainte et en `required` sur le formulaire ; garants, conjoints et sociétés exclus — `microfinance_loan_management/models/res_partner.py` ; `microfinance_loan_management/views/microfinance_partner_views.xml`
- [x] Tests : 20 cas — `microfinance_loan_management/tests/test_client_blocage_inter_agences.py`

## À faire / incomplet
- [ ] Transfert de compte client après solde du crédit — `docs_dev/transfert_client/STATUS.md` — impact: moyen

## Incohérences relevées
- Limite connue et acceptée : aucun verrou inter-agences, deux agences qui décaissent au même instant pour un même CIN peuvent passer toutes les deux — `microfinance_loan_management/models/res_partner.py` — impact: faible (fenêtre de course très étroite).
- Les clients particuliers déjà créés sans CIN (ex. 1 client sur 4 dans MOWGLI) échappent encore aux garde-fous : la contrainte ne se déclenche qu'à leur prochaine modification du CIN, du type de pièce ou du type de client. À régulariser en saisissant leur CIN — `microfinance_loan_management/models/res_partner.py` — impact: moyen.
- Un client de nationalité étrangère avec passeport ne peut plus être créé en contexte microfinance : la contrainte exige un CIN, sans exception — `microfinance_loan_management/models/res_partner.py` — impact: faible (à trancher si le cas existe).
- `/todo` de MOWGLI ne lit que `microfinance_mowgli_assistant/docs_dev/<workflow>/STATUS.md`, pas `docs_dev/` à la racine de `custom_addons` où vivent ces fichiers — `microfinance_mowgli_assistant/models/dev_status.py` — impact: faible.
