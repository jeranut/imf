# STATUS — Scission « Compte épargne » / « Produit d'épargne souscrit »

Mise à jour : 2026-10-07. Audit : [AUDIT.md](AUDIT.md). Décisions appliquées : D1 à D9 + synchro compte crédit / compte épargne. Diff **non commité**. `microfinance_savings_management` 17.0.1.6.0 → **17.0.1.7.0**.

## Fait

### Nouveau modèle `microfinance.savings.holder.account` (« Compte épargne »)
[models/microfinance_savings_holder_account.py](../../microfinance_savings_management/models/microfinance_savings_holder_account.py)
- Champs : `name` (readonly, dérivé), `legacy_number`, `partner_id`, `company_id`, `currency_id`, `loan_account_id` (compte crédit couplé), `product_ids`, `product_count`, `active_product_count`, `balance_total` (somme des soldes des produits **non clôturés**), `state`, `next_rank`, `mail.thread`. Tous les calculs sont stockés et dépendent de `product_ids.balance` et `product_ids.state`.
- **Nom = `<préfixe>/<nom du compte crédit de la même agence>`**, par exemple `CE/AD/000003`. C'est la seule façon de garantir le même N pour un client présent dans deux agences : dans la 2e agence, le compte crédit ne reprend pas le numéro permanent mais la séquence de l'agence (`_get_loan_account_name`). Aucune séquence propre au compte épargne. Le préfixe `CE` est un champ de `res.company` (« Préfixe compte épargne », fiche société), verrouillé dès qu'un compte existe dans l'agence.
- **État calculé** (D4) : Actif (≥ 1 produit actif) ; Dormant (≥ 1 dormant, aucun actif) ; Clôturé (tous clôturés, ≥ 1 produit) ; Ouvert sinon, y compris sans produit.
- Contraintes : `unique(partner_id, company_id)`, `unique(name)`. Agence du compte = agence du titulaire (quand le titulaire en a une) ; compte crédit couplé de même titulaire et même agence. Suppression refusée tant qu'il porte des produits.
- `_get_or_create_for(partner, company)` : réutilise le compte, sinon crée le compte crédit s'il manque **puis** le compte épargne, dans la même transaction (savepoint + contraintes uniques pour la concurrence).
- `_reserve_rank()` : `SELECT … FOR UPDATE` sur la ligne du compte, puis incrément de `next_rank`. Le rang n'est jamais réutilisé, même après clôture ou suppression d'un produit.
- **Contrôle d'intégrité** : `get_credit_savings_sync_issues()` liste les comptes crédit sans compte épargne, les comptes épargne sans compte crédit et les N divergents. Menu « Épargne > Contrôle crédit / épargne » (managers) ; cron quotidien « Épargne : contrôle de synchronisation compte crédit / compte épargne » qui journalise sans corriger.

### Modèle produit `microfinance.savings.account` (libellé « Produit d'épargne souscrit »)
- Nouveaux champs : `account_id` (compte épargne, index, `ondelete=restrict`, non modifiable après création hors migration), `rank` (contrainte unique `(account_id, rank)`), `legacy_number`.
- `create()` : applique les défauts du contexte (bouton « Épargne » du crédit), résout ou crée le compte, réserve le rang. Nom des nouveaux produits = `<compte>-<rang sur 2 chiffres>`, par exemple `CE/AD/000003-01`.
- `product_id` est obligatoire sans exception (contrainte Python). Le titulaire et l'agence du produit doivent être ceux de son compte.
- Retirés du code : numérotation `AGENCE/I|G|T/N` et séquences associées, logique conteneur (création, index unique partiel, refus d'activation et de clôture, ruban, filtre « Masquer les conteneurs »). Aucun code ne lisait le type I/G/T dans un nom. Les séquences `.I`/`.G` existantes ne sont plus appelées ; elles ne sont pas supprimées.
- `is_container` reste une **colonne en lecture seule** pour la transition (lue seulement par la migration et par `container_migration.py`, désormais marqué obsolète) ; elle n'apparaît plus dans aucune vue.

### Client (`res_partner` épargne)
- À la création du client (`microfinance_context`), le compte épargne est créé juste après le compte crédit, dans la même transaction. Un échec de l'un annule l'autre (testé).
- **Cycle de vie** :
  - changement d'agence refusé dès qu'un compte crédit ou un compte épargne existe (leur N appartient à l'agence d'origine) ;
  - archivage refusé si le compte épargne a un solde ou un produit actif ou dormant, ou si un crédit est approuvé, actif ou en défaut.
  - Aucun flux automatique de changement d'agence n'existe dans le code (le module de transfert n'est pas installé) : la garde porte sur la fiche client.
- Bouton « Épargne » de la fiche client : ouvre le compte épargne. Onglet Épargne : produits.
- Guichet : `search_caisse_clients` renvoie aussi `savings_account_name` ; `get_client_accounts_summary` renvoie `savings_holder_account` (numéro, solde total) et, pour chaque produit, `account_name`. L'écran guichet affiche « Compte épargne <numéro> — <solde> » puis ses produits (nom + produit). Le dépôt et le retrait restent sur un produit, sans changement.

### Crédit
- `savings_account_id` (prélèvement) : domaine = produits actifs du client dans l'agence du crédit.
- Bouton « Épargne » du crédit : liste des produits du client ; la création passe `default_partner_id`, `default_company_id` et `default_microfinance_loan_id`, et le compte est résolu côté serveur.
- `_get_repayment_surplus_savings_account` : plus de filtre conteneur.
- Épargne garantie : toujours la somme des produits correspondant au **produit de garantie configuré** sur le produit de crédit (voir écarts).
- Compte crédit : le bouton « Épargne » ouvre le compte épargne couplé ; le compteur affiche son nombre de produits.

### Vues, menus, droits
- Épargne > **Comptes épargne** (nouveau modèle) : liste avec numéro, titulaire, agence, nombre de produits, solde total et état ; kanban ; panneau Agence / État ; fiche avec onglet « Produits d'épargne » et total en pied. `create="false"` partout, aucun droit create.
- Épargne > **Produits d'épargne** : liste des produits avec filtre et regroupement par compte, produit et état. « Nouveau » est autorisé (le compte est résolu côté serveur) ; le compte est en lecture seule une fois créé ; pas de création rapide du produit.
- Épargne > **Contrôle crédit / épargne** et **Renumérotation des produits** (managers).
- Configuration > « Produits d'épargne » est renommé **« Catalogue des produits d'épargne »**, pour ne pas le confondre avec le nouveau menu (voir écarts).
- `ir.model.access` : mêmes groupes que le produit (agent épargne et managers crédit, finance, auditeur en lecture ; manager épargne en lecture et écriture), **sans create**. `ir.rule` : règle société recopiée, sans isolement par agent (D8).
- Reçu QWeb : « Compte épargne » (numéro du compte) puis « Produit souscrit ».
- Transactions : le champ `account_id` est libellé « Produit d'épargne », et `holder_account_id` (compte épargne, stocké) est ajouté.

### Tableau de bord
3 tuiles, chacune avec exactement le domaine de son lien, ouvertes sur des vues sans création, import ni duplication :
- « Comptes épargne actifs » : comptes à l'état Actif ;
- « Produits d'épargne actifs » : produits `state='active'` rattachés à un compte ;
- « Encours épargne » : somme des soldes de ces produits.

Le critère « rattaché à un compte » sert uniquement pendant la transition, pour exclure les anciens conteneurs (3 sont à l'état actif) ; il devient sans objet après le passage 2.

### Autres
- `microfinance_data_reset_wizard` : supprime les comptes épargne **après** les produits ; l'aperçu les compte.
- `container_migration.py` : marqué **obsolète**, conservé pour les migrations 17.0.1.4.0 et 17.0.1.5.0 d'une base en retard. Le calcul de l'ancien nom de conteneur y est recopié, puisque la méthode a disparu du modèle.

### Migration 17.0.1.7.0 — [savings_split_migration.py](../../microfinance_savings_management/savings_split_migration.py)
- **Passage 1** (post-migrate, dry-run par défaut via `microfinance_savings.split_dry_run`, créé à True s'il est absent) :
  - a. garde D6 : en mode réel, **refus de démarrer** si un conteneur n'est pas dans l'agence de son titulaire (listé « à corriger manuellement avant migration ») ;
  - b. chaque conteneur devient un compte, vides inclus (`legacy_number` = ancien nom) ;
  - c. rattrapage des comptes crédit sans compte épargne ;
  - d. chaque produit est rattaché, le compte étant créé s'il manque ; rang par ordre d'ouverture ; nom conservé et recopié dans `legacy_number` ;
  - e. D5 sur les crédits ;
  - f. vérifications : totaux identiques, aucun produit sans compte, aucun rang en double, même N crédit / épargne, chaque compte crédit a son compte épargne, aucun crédit sur un conteneur.
  - Le dry-run exécute le vrai traitement dans un savepoint annulé : le CSV et les vérifications décrivent exactement le run réel. CSV : `microfinance_migrations/scission_epargne_<base>_<horodatage>_p1_<dryrun|reel>.csv`.
- **Passage 2** (`run_split_pass2`) : uniquement si `microfinance_savings.split_remove_containers` vaut True **et** que toutes les vérifications du passage 1 sont vertes. Il retire les conteneurs qui n'ont plus aucune référence (crédits, transactions, caisse, écritures) ; ceux encore référencés sont conservés et listés. Dry-run aussi par défaut.
- **Assistant de renumérotation** (Épargne > Renumérotation des produits) : renomme les produits en `<compte>-RR`, dry-run par défaut, CSV `renumerotation_produits_epargne_*.csv`. L'ancien nom va dans `legacy_number`. **Ne réécrit jamais** les libellés ni les références des écritures (testé).

## Avant / après — MOWGLI (dry-run sur une copie, 2026-10-07)
| | Avant | Après passage 1 (simulé) |
|---|---|---|
| Comptes épargne (nouveau modèle) | 0 (29 conteneurs) | **31** : 28 conteneurs + 3 rattrapés (SY/000002, SY/000003, MS/000003) |
| Produits | 7, sans compte | 7, tous rattachés, rang 01 |
| Solde des produits | 175 000 | 175 000 |
| Transactions / mouvements de caisse / écritures liées | 8 / 8 / 8 | 8 / 8 / 8 |
| Crédits pointant un conteneur | 5 | 0 : **1 repointé** (AD/000001 → AD/I/000012), **4 vidés** et listés (MS/000001, MS/000002, MS/000003, MS/000015 : aucun produit actif dans l'agence) |
| Garde D6 | — | **1 bloquant** : conteneur 606 `MS/I/000003`, rangé à BD alors que la titulaire est à MS. Le run réel refuse de démarrer tant qu'il n'est pas corrigé. |
| N compte crédit = N compte épargne | — | 31 / 31 |

- En dry-run, le conteneur 606 est écarté et la cliente est rattrapée par son compte crédit MS (`CE/MS/000003`). Une fois sa société corrigée (BD → MS), le conteneur deviendra lui-même ce compte, avec `legacy_number` = `MS/I/000003`.
- **7 clients n'ont ni compte crédit ni conteneur** (créés hors parcours microfinance) et ne sont pas traités par la migration, conformément au périmètre : 732 RAKOTOARIVELO (IS, sans numéro permanent), 1161 / 1164 / 1637 / 1638 / 1643 (BD/000001-000005), 1644 (IS/000245). Le filet de sécurité leur créera compte crédit et compte épargne à leur première souscription.

## Tests
- `test_savings_holder_account.py` (16 tests) :
  - création couplée (même N, même titulaire, même agence) ;
  - préfixe configurable ;
  - rollback complet si le compte épargne échoue, et inversement ;
  - cohérence compte crédit / compte épargne ;
  - changement d'agence refusé ; archivage refusé avec activité, autorisé sans ;
  - contrôle d'intégrité et cron (journalise sans corriger) ;
  - 3 produits : -01/-02/-03, solde égal à la somme SQL, rang non réutilisé après clôture ;
  - rang en double refusé par la base ; création idempotente et filet de sécurité ;
  - même client dans 2 agences : 2 comptes, N différents, chacun égal à son compte crédit ;
  - contraintes produit ; produit d'un client d'une autre agence refusé ;
  - états D4 ; guichet.
- `test_savings_split_migration.py` (7 tests) :
  - dry-run sans écriture, et dry-run par défaut ;
  - passage 1 réel : totaux identiques, conteneurs vides inclus, rattrapage, produit sans conteneur, D5 repointé ou vidé, N égaux ; puis idempotent ;
  - garde D6 bloquante ;
  - passage 2 : paramètre explicite requis, conteneur référencé conservé, refus si le passage 1 n'est pas vert ;
  - renumérotation : dry-run sans écriture, écritures jamais réécrites.
- Adaptés : `test_dashboard_savings_kpis.py` (3 tuiles égales à leurs listes, vues sans création, masquées sans droit) et `test_savings_account_menu_creation_lock.py` (nouveaux menus, aucun droit create sur le compte). `test_savings_account_loan_link.py` passe sans modification, après correction d'un vrai défaut : les défauts du contexte n'étaient pas appliqués avant la résolution du compte.
- Non-régression : suites complètes de 5 modules (crédit, épargne, payroll, test de charge, remise à zéro) sur une copie de MOWGLI, comparées au code d'avant ces lots sur la même copie. **Aucun nouvel échec.** Les échecs restants (26 + 96) existaient tous déjà ; ils viennent surtout du fonds rotatif réel de MOWGLI, dans les tests qui n'utilisent pas `MicrofinanceNoFundMixin`.

## Déploiement — rotas (production)
```bash
# 0. Audit lecture seule sur rotas (adapter <BASE>)
sudo -u postgres psql -d <BASE> -c "select s.id, s.name, s.company_id, p.company_id titulaire from microfinance_savings_account s join res_partner p on p.id=s.partner_id where s.is_container and p.company_id is not null and p.company_id<>s.company_id;"
sudo -u postgres psql -d <BASE> -c "select l.name, s.name from microfinance_loan l join microfinance_savings_account s on s.id=l.savings_account_id where s.is_container;"
# 1. Sauvegarde
sudo -u postgres pg_dump -Fc <BASE> -f /opt/odoo17_2/backups/<BASE>_avant_scission_epargne_$(date +%Y%m%d_%H%M%S).dump
# 2. Corriger à la main chaque conteneur listé en 0 (ex. MOWGLI : id 606, société BD -> MS), en le journalisant
# 3. Redémarrage puis mise à jour (le passage 1 tourne en DRY-RUN : rien n'est écrit)
sudo systemctl restart odoo17_2
sudo -u odoo17_2 /opt/odoo17_2/venv/bin/python3 /opt/odoo17_2/odoo/odoo-bin -c /opt/odoo17_2/odoo/odoo.conf -d <BASE> \
  -u microfinance_savings_management,microfinance_loan_management,microfinance_data_reset_wizard,microfinance_payroll_loan \
  --stop-after-init --http-port=8096
# 4. Relire <dossier du log>/microfinance_migrations/scission_epargne_<BASE>_*_p1_dryrun.csv
# 5. Passage 1 réel
sudo -u odoo17_2 /opt/odoo17_2/venv/bin/python3 /opt/odoo17_2/odoo/odoo-bin shell -c /opt/odoo17_2/odoo/odoo.conf -d <BASE> --no-http <<'PY'
from odoo.addons.microfinance_savings_management import savings_split_migration as m
env['ir.config_parameter'].sudo().set_param(m.PARAM_DRY_RUN, 'False')
rows, checks, before, after = m.run_split_pass1(env)
print(checks, before, after)
env['ir.config_parameter'].sudo().set_param(m.PARAM_DRY_RUN, 'True')
env.cr.commit()
PY
# 6. Vérifier la synchro des N : menu Épargne > Contrôle crédit / épargne (doit être vide)
# 7. Passage 2 SEULEMENT après accord : poser microfinance_savings.split_remove_containers=True, puis run_split_pass2(env) (dry-run puis réel)
sudo systemctl restart odoo17_2
```

## Écarts restants
1. **Nom du compte dérivé du nom du compte crédit** (et non directement de `microfinance_account_number`). C'est identique pour la première agence du client et c'est la seule règle qui tienne la synchro des N dans une 2e agence (D1, règle 1).
2. **Changement d'agence** : refus systématique quand le client a un compte crédit ou un compte épargne. Les deux comptes ne « suivent » pas, puisque leur N appartient à l'agence d'origine. Un transfert de client reste un chantier dédié.
3. **Épargne garantie** : calcul conservé sur le produit de garantie configuré sur le produit de crédit (plus précis qu'un filtre `product_type`). Aucun code ne lisait le type dans le nom.
4. **Menu Configuration** renommé « Catalogue des produits d'épargne », pour le distinguer du nouveau menu « Épargne > Produits d'épargne ». À confirmer.
5. **7 clients sans compte crédit** non traités par la migration (liste ci-dessus).
6. **Conteneurs 26 en brouillon** : non activés (D4), sans objet une fois transformés en comptes à l'état calculé.
7. `account_id` n'est **pas encore obligatoire en base** (contrainte Python seulement), tant que le passage 2 n'est pas validé ; à passer en `required=True` dans une version suivante.
8. Tests supprimés car ils figeaient l'ancien comportement (conteneur, numérotation I/G/T, migrations de conteneurs 17.0.1.4/1.5) : `test_savings_account_container`, `test_savings_container_numbering`, `test_savings_container_creation`, `test_savings_principal_account_on_create`, `test_savings_container_migration`, `test_agency_numbering`, et la classe `TestSavingsAccountNumberDerivation`. Leur couverture est reprise par `test_savings_holder_account` et `test_savings_split_migration`.
9. **Non déployé sur MOWGLI** : sans le passage 1 réel, les 7 produits existants n'auraient pas de compte, et seraient donc invisibles au guichet, dans le menu Produits et dans les tuiles. Il faut d'abord corriger le conteneur 606 et valider le CSV.
10. Vérification dans le navigateur non faite : guichet, fiches compte et produit, tuiles. Vider le cache après déploiement.
