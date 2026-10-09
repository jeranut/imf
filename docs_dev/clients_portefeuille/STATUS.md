# STATUS — Clients : suppression de la création + filtre « Portefeuille »

Dernière mise à jour : 2026-10-07. Audit : [AUDIT.md](AUDIT.md). Décisions appliquées : D1-A, D2-A, D3, D4, D5, D6, D7.
Diff **non commité**.

## Fait

### Modèle `res.partner` (microfinance_loan_management/models/res_partner.py)
- `microfinance_officer_id` redéclaré (« Agent crédit (portefeuille) », `index=True`, `tracking`, `copy=False`). Même colonne que `microfinance_payroll_loan`, dont la déclaration est inchangée. Index `res_partner__microfinance_officer_id_index` créé à l'update.
- Garde `create()`, placé **avant** `_check_no_active_loan_elsewhere` (non modifié) : `UserError` « La création d'un client se fait uniquement depuis le portefeuille de l'agent de crédit. » si `microfinance_context` ET pas de `allow_microfinance_partner_create` ET la création produit un client (`microfinance_partner_type='client'` dans `vals`, ou absent de `vals` et `default_microfinance_partner_type='client'` dans le contexte).
- Même garde dans `write()` quand `microfinance_partner_type` passe à `'client'` sur un contact qui ne l'est pas encore (garant/conjoint → client).
- Avec le flag, si un agent est fourni (`vals` ou `default_microfinance_officer_id`), il doit avoir un portefeuille **actif** dans l'agence du client, sinon `UserError`. Ce contrôle existe parce que le flag et le `default_*` transitent par le contexte, donc sont forgeables en RPC.
- Conjoints et garants (type NULL) restent créables sous `microfinance_context` : le client web retire les clés `default_*` du contexte des Many2one (`web/static/src/model/relational_model/utils.js`, `getFieldContext`).

### Chemin légitime (D1)
- `microfinance.loan.get_portfolio_new_client_action()` : l'agent est **toujours** l'utilisateur courant (aucun argument, et le `default_microfinance_officer_id` éventuellement présent dans le contexte d'appel est ignoré). L'utilisateur doit avoir un portefeuille actif dans l'agence active, sinon `UserError`. L'action renvoyée ouvre la fiche verrouillée avec `microfinance_context`, `allow_microfinance_partner_create`, `default_microfinance_partner_type='client'`, `default_microfinance_client_type='individual'`, `default_microfinance_officer_id`, `default_company_id`.
- JS `openAgentShortcut('new_client')` : appel de cette méthode à la place du `doAction` direct.
- Champ « Agent crédit (portefeuille) » affiché en lecture seule dans le groupe Crédit de la fiche client. La valeur est posée par le serveur via le default du contexte : un champ readonly n'est pas renvoyé au save.
- Wizard « Avance spéciale » : création directe et `_open_partner_prefill_form()` passent le flag.
- D6 : `microfinance_load_test._create_fake_partner()` passe le flag.

### Vues
- `view_microfinance_client_tree_clients_menu` / `_kanban_` / `_form_clients_menu` : `mode="primary"` sur `base.view_partner_tree` / `base.res_partner_kanban_view` / `base.view_partner_form`, priorité 100, avec `create="false"` + `import="false"` (tree/kanban) et `create="false"` + `duplicate="false"` (form). Elles sont branchées par `view_ids` sur `action_microfinance_client`. Les vues de base sont inchangées (vérifié par test), et les extensions microfinance et épargne s'appliquent toujours à la fiche (vérifié par test). `create="false"` ne masque que Nouveau/Import/Dupliquer : le bouton d'enregistrement d'un formulaire neuf reste affiché (`form_controller.xml`, `FormStatusIndicator` indépendant de `canCreate`).
- Search view `view_microfinance_client_search` (même vue, même `search_view_id`) : panneau Agence (`company_id`, fa-building), Portefeuille (`microfinance_officer_id`, fa-briefcase, `enable_counters`, `select="one"`, **`hierarchize="0"`**), puis État civil et Commune ; filtre « Sans portefeuille ».
  - `hierarchize="0"` est indispensable : `res.users` hérite `parent_id` de `res.partner` (`_inherits`), et sans cet attribut `search_panel_select_range` plante (`TypeError: inconsistent models`).
- D5 : domaine `[('microfinance_partner_type', '=', 'client')]` + `no_create`/`no_quick_create`/`no_create_edit` sur l'emprunteur du dossier, l'emprunteur et le co-emprunteur du crédit, le titulaire du compte crédit, de la liste noire et du compte épargne. `no_quick_create` seul (création via « Créer et modifier » conservée) sur le conjoint et le garant de la fiche client, le garant du dossier et la caution des garanties. `no_create*` sans domaine sur « Client existant à choisir » du wizard Avance spéciale (domaine déjà limité aux candidats).

### Migration 17.0.1.26.0
- `client_officer_backfill.py` + `migrations/17.0.1.26.0/post-migrate.py`. Pose l'agent si **tous** les crédits du client ont le même `officer_id` (aucun vide) et la même agence, celle du client. Sinon : `AMBIGU_AGENTS`, `AMBIGU_AGENCES`, `SANS_CREDIT`, listés et jamais devinés. Dry-run par défaut (paramètre `microfinance_loan_management.backfill_client_officer_dry_run`, créé à `True` s'il est absent). CSV `rattachement_agent_clients_<base>_<horodatage>_<dryrun|reel>.csv` dans `<dossier du log Odoo>/microfinance_migrations/`, créé avant toute écriture (run réel annulé si la trace ne peut pas être écrite). Idempotent : un client déjà rattaché n'est plus relu.
- Dry-run sur une copie de MOWGLI : 34 clients sans agent → **20 `A_POSER`**, 14 `SANS_CREDIT`, 0 ambigu.

### Comptage D5 (MOWGLI, lecture seule, 2026-10-07)
| Champ | Partenaires de type client | Autre type / NULL |
|---|---|---|
| `microfinance.loan.partner_id` | 21 | 0 |
| `microfinance.loan.co_borrower_id` | 0 enregistrement | 0 |
| `microfinance.loan.application.partner_id` | 15 | 0 |
| `microfinance.loan.account.partner_id` | 29 | 0 |
| `microfinance.savings.account.partner_id` | 32 | 0 |
| `microfinance.client.blacklist.partner_id` | 0 enregistrement | 0 |
| `microfinance.loan.guarantee.guarantor_partner_id` | 0 enregistrement | 0 |
| `microfinance.caisse.mouvement.partner_id` (lecture seule, non modifié) | 33 | 0 |

Aucun enregistrement existant ne devient illisible à l'édition à cause des nouveaux domaines.

### Tests
- Nouveau : `microfinance_loan_management/tests/test_clients_portefeuille.py` (18 tests, `MicrofinanceNoFundMixin`) : garde create/write, conjoint/garant, hors contexte, inter-agences avec flag, vues de l'action et vues de base, chemin Mon portefeuille (id forgé ignoré, agent forcé refusé, utilisateur sans portefeuille refusé), panneau (agent : son agence seulement ; auditeur : toutes), filtre « Sans portefeuille », migration (dry-run par défaut, run réel idempotent, ambigus).
- Nouveau : `microfinance_payroll_loan/tests/test_payroll_advance_wizard.py::test_wizard_prefill_form_permet_la_creation`.
- Tests existants : le flag est ajouté aux `with_context(microfinance_context=True)` des tests qui créent des clients (16 fichiers, sans changement de logique). Sans lui, ils échoueraient sur le garde avant d'atteindre ce qu'ils testent (notamment `test_client_blocage_inter_agences`).
- Résultats : voir « Résultats des suites » ci-dessous.

## Résultats des suites
Exécutées sur des copies jetables de MOWGLI (supprimées depuis) : suites complètes de `microfinance_loan_management`, `microfinance_savings_management`, `microfinance_payroll_loan` et `microfinance_load_test`, comparées à une exécution de référence sur le code **d'avant** ce lot.

| | Tests | Échecs + erreurs |
|---|---|---|
| Référence (code d'avant) | 1014 | 26 + 88 = 114 |
| Avec ce lot | 1033 (+19) | 26 + 88 = 114 |

- La liste des 114 échecs est **strictement identique** : aucun nouvel échec, aucun ne contient le message du garde. Les 19 nouveaux tests passent.
- Les 114 échecs sont préexistants et sans lien avec ce lot : surtout le blocage « Un fonds de crédit rotatif actif existe pour cette agence » (fonds réels de MOWGLI, dans les tests qui n'utilisent pas `MicrofinanceNoFundMixin`), ainsi que l'échéancier, la caisse et les fonds bailleurs. C'est un chantier séparé.

## Déployé sur MOWGLI (2026-10-07 15:32)
- Sauvegarde : `/opt/odoo17_2/backups/MOWGLI_avant_clients_portefeuille_20261007_153206.dump`.
- Redémarrage `odoo17_2`, puis `-u microfinance_loan_management,microfinance_payroll_loan,microfinance_load_test,microfinance_savings_management` : aucune erreur, version 17.0.1.26.0, index créé, `view_ids` de l'action en place.
- Une requête web arrivée pendant le `-u` a fait échouer une fois le chargement du registre du service (`could not serialize access due to concurrent update`). Un redémarrage après la mise à jour a rechargé le registre proprement.
- Backfill : **dry-run seulement** (paramètre à `True`, 2 clients sur 36 rattachés comme avant). CSV : `/opt/odoo17_2/odoo/microfinance_migrations/rattachement_agent_clients_MOWGLI_20261007_153224_dryrun.csv`.

## Correctif — ouverture de la fiche client (2026-10-07)
Audit : [AUDIT_ouverture_fiche_client.md](AUDIT_ouverture_fiche_client.md). Symptôme confirmé : Mon portefeuille > Mes clients ouvrait `res.partner` sans `microfinance_context` et sur la form par défaut.

**Points corrigés**
| Point | Correctif |
|---|---|
| Dashboard, onglets « Mes clients » et « Clients à traiter » | `openPortfolioTabRow` appelle `res.partner.action_open_microfinance_client_form` (`orm.call` avec le seul `res_id`) puis `doAction`. Le fil d'Ariane « Mon portefeuille » est conservé (`target: current`). La surcharge et le `context` du patch payroll sont supprimés. |
| Wizard Avance spéciale, retour de `action_validate()` | renvoie `partner.action_open_microfinance_client_form()` |
| Wizard Avance spéciale, fiche préremplie | ouverte sur la form verrouillée. Avant, la form de base affichait « Nouveau », qui créait un autre client avec le flag encore dans le contexte. |
| Clic sur un Many2one partner : crédit (emprunteur, co-emprunteur), dossier, compte crédit, liste noire, garantie (caution), échéance, remboursement, visite, compte épargne, transaction épargne, wizard de régularisation payroll | `context="{'microfinance_context': True}"` sur le champ, et surcharge de `res.partner.get_formview_action()` : sous `microfinance_context` et pour un client, elle renvoie la même action (form verrouillée, contexte propre, sans flag de création). |

`action_open_microfinance_client_form()` vérifie `check_access_rights` et `check_access_rule('read')` : un agent ne peut pas ouvrir un client d'une autre agence (AccessError). Le contexte renvoyé contient `microfinance_context` et `default_microfinance_partner_type`, jamais `allow_microfinance_partner_create`. La fiche d'un client existant reste éditable (seuls Nouveau et Dupliquer sont masqués).

**Laissés tels quels**
- Contact du bailleur (`microfinance.bailleur.fonds.partner_id`) : ce n'est pas un client ; `get_formview_action` reste le standard.
- Arbres (crédits, dossiers, paiements…) : le clic sur une ligne ouvre l'enregistrement de la ligne, pas le partner.
- Guichet caisse, transfert inter-agences (non installé), onglet Fonds, tuiles KPI : n'ouvrent jamais de fiche res.partner.
- Défense en profondeur : un client ouvert **sans** `microfinance_context` (Contacts, Discuss, lien direct) garde la fiche standard. Ce comportement n'est volontairement pas modifié, pour ne pas toucher EAT/MIIA.

**Tests ajoutés**
- `test_clients_portefeuille.py`, 6 tests : action d'ouverture (vue, contexte sans flag), refus d'un client d'une autre agence, `get_formview_action` sous contexte (form client, flag retiré) et hors contexte (standard, et standard aussi pour un non-client sous contexte), sections CIN/état civil/conjoint conditionnées par `microfinance_context`, contexte présent sur les Many2one partner des vues microfinance.
- `test_payroll_advance_wizard.py`, 2 tests : le retour du wizard ouvre la fiche microfinance ; la fiche préremplie s'ouvre sur la form verrouillée.
- Écart avec le prompt : « sans context, les champs CIN… sont absents de get_view » n'est pas possible en Odoo 17 (masquage évalué côté client). Le test vérifie la condition `invisible` à la place.

## À faire
- Valider le CSV dry-run, puis lancer le run réel du backfill (bloc 4 ci-dessous) sur MOWGLI et sur rotas.
- Production rotas : déploiement (commandes ci-dessous).
- Vérification manuelle dans le navigateur : « Nouveau client » depuis Mon portefeuille (agent), enregistrement, panneau Agence/Portefeuille. Les tests couvrent le serveur et les `get_view`, pas le rendu OWL.

## Points ouverts
1. **Le flag reste une clé de contexte.** Un utilisateur qui forge un appel RPC peut toujours créer un client avec `allow_microfinance_partner_create`. Le contrôle d'agent limite l'abus : l'agent posé doit avoir un portefeuille actif dans l'agence. Seule une règle d'accès dédiée fermerait complètement ce chemin, ce qui est hors D2-A.
2. **Isolement par agent (D2-A)** : un agent voit toujours tous les clients de son agence et le panneau liste les autres agents de l'agence, comme aujourd'hui. Il ne voit aucune autre agence.
3. **Managers et gestionnaires sans portefeuille propre** ne peuvent plus créer de client (seul l'agent le fait, depuis son portefeuille). Si un gestionnaire doit créer pour le compte d'un agent, il faut un sélecteur d'agent validé côté serveur (`_resolve_agent_request` existe déjà).
4. **Backfill vers un agent sans portefeuille** : le client 4497 (CEFOR Mahitsy) serait rattaché à `jeranutmickael@gmail.com`, qui n'a pas de portefeuille à Mahitsy. La règle D3 ne l'exige pas ; il apparaîtra dans le panneau sous cet agent. À valider à la lecture du CSV.
5. **Bailleurs** (`view_microfinance_bailleur_fonds_form.partner_id`) non verrouillés : le champ est requis et `create()` du bailleur ne crée le contact que si `partner_id` est vide ; un `no_create` y bloquerait la saisie d'un nouveau bailleur. Hors périmètre clients.
6. **Clients de test « TEST Rakoto … »** (10 fiches créées par `microfinance_load_test` sur MOWGLI) : ils seront rattachés par le backfill comme les autres.

## Déploiement (production rotas)
À lancer sur le serveur rotas (adapter le chemin de config, l'utilisateur et le service si différents de cette machine) :

```bash
# 1. Sauvegarde
sudo -u postgres pg_dump -Fc <BASE> -f /opt/odoo17_2/backups/<BASE>_avant_clients_portefeuille_$(date +%Y%m%d_%H%M%S).dump
# 2. Redémarrage puis mise à jour (le post-migrate tourne en dry-run : rien n'est écrit)
sudo systemctl restart odoo17_2
sudo -u odoo17_2 /opt/odoo17_2/venv/bin/python3 /opt/odoo17_2/odoo/odoo-bin -c /opt/odoo17_2/odoo/odoo.conf -d <BASE> \
  -u microfinance_loan_management,microfinance_payroll_loan,microfinance_load_test,microfinance_savings_management \
  --stop-after-init --http-port=8096
# 3. Relire le CSV dry-run : <dossier du log>/microfinance_migrations/rattachement_agent_clients_<BASE>_*_dryrun.csv
# 4. Run réel du backfill, après validation du CSV
sudo -u odoo17_2 /opt/odoo17_2/venv/bin/python3 /opt/odoo17_2/odoo/odoo-bin shell -c /opt/odoo17_2/odoo/odoo.conf -d <BASE> --no-http <<'PY'
from odoo.addons.microfinance_loan_management.client_officer_backfill import PARAM_DRY_RUN, backfill_client_officer
env['ir.config_parameter'].sudo().set_param(PARAM_DRY_RUN, 'False')
backfill_client_officer(env)
env['ir.config_parameter'].sudo().set_param(PARAM_DRY_RUN, 'True')
env.cr.commit()
PY
sudo systemctl restart odoo17_2
```
`microfinance_savings_management` est inclus parce que sa vue compte épargne a changé (D5).
