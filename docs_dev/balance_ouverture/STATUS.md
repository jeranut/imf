# Balance d'ouverture — statut

**Statut : implémenté (V1 comptable), déployé sur MOWGLI, en attente de relecture/commit** (branche `feat/balance-ouverture`).

## Fait
- Modèles `microfinance.opening.balance` (+ lignes), `microfinance.opening.template` (comptes du modèle, 58 comptes en
  données, éditables), assistant d'import `microfinance.opening.balance.import`.
- Menus Comptabilité > **Balance d'ouverture** (Finance, Comptable, Auditeur en lecture, gestionnaire comptable) et
  **Comptes du modèle d'ouverture** (Comptable, gestionnaire comptable).
- Validation : écriture unique, journal des à-nouveaux (code `AN`, paramètre `microfinance.opening_journal_code`), à la date
  d'ouverture, puis verrouillage (date, société, lignes, suppression). Refus si débit ≠ crédit, si une autre balance est
  validée pour la société, ou s'il existe des écritures comptabilisées antérieures à la date.
- « Charger le modèle » (comptes de la liste + comptes des journaux bank/cash + comptes de fonds, montants à 0),
  « Télécharger le modèle Excel », import du fichier rempli avec rapport d'erreurs ligne par ligne (tout ou rien).
- Les soldes bancaires de la balance validée préremplissent le solde initial du premier relevé (`balance_start`).
- Tests : `tests/test_opening_balance.py` (16 tests).

## Choix à connaître
- Pas de réouverture d'une balance validée (l'écriture n'est jamais modifiée) : pour refaire un test, supprimer l'écriture
  d'ouverture et la balance par la purge de simulation.
- Lecture du .xlsx sans openpyxl (absent du venv) : lecteur minimal `models/microfinance_opening_xlsx.py`.
- L'écriture d'ouverture native d'Odoo (`account_opening_move_id`) n'est pas utilisée.

## Suite (hors périmètre V1)
- Import clients / crédits / épargnes avec contrôle de concordance (somme du détail = solde du compte de regroupement :
  203001/2 principal, 213xxx épargne, etc.).

## Reprise de portefeuille : implémentée, déployée sur MOWGLI, en attente de relecture/commit
Audit : [AUDIT_reprise_portefeuille.md](AUDIT_reprise_portefeuille.md) (décisions D1 à D9 validées). Versions : `microfinance_loan_management` 17.0.1.31.0, `microfinance_savings_management` 17.0.1.8.0.

### Fait
- Menu Comptabilité > **Reprise de portefeuille** (séq. 6, à côté de « Balance d'ouverture »). Assistant `microfinance.opening.reprise` : balance en brouillon + fichier Excel, **simulation cochée par défaut** (aucune création, pas même de numéro de séquence), rapport d'erreurs par feuille et par ligne, tout ou rien.
- Droits : import réel réservé à Finance et Manager crédit (contrôle serveur) ; simulation et menu ouverts en lecture à comptable, gestionnaire comptable (`account.group_account_manager`) et auditeur.
- Gabarit téléchargeable (Clients, Crédits, Épargne, Mode d'emploi) ; exemple rempli : [gabarit_reprise_exemple_analakely.xlsx](gabarit_reprise_exemple_analakely.xlsx) (2 clients fictifs, encours 3 000 000, épargne 400 000, CIN 999000000001/2).
- Lecteur Excel multi-feuilles, dates texte (jj/mm/aaaa, aaaa-mm-jj) ou série Excel.
- Clients créés dans le portefeuille indiqué (garde-fou création, règle portefeuille, inter-agences respectés) ; CIN contrôlés dans toutes les sociétés (lecture `sudo()` ciblée) ; clé d'idempotence = référence client (`microfinance_internal_reference`), par société.
- Crédits : `state='active'`, `disbursement_date`, échéances restantes seules (principal, intérêts et pénalités à 0), hors fonds (`fond_credit_id` vide), `fee_paid=True`, limites du produit neutralisées par la clé de contexte `mf_reprise_skip_product_limits` posée côté serveur. Marqueur `opening_balance_id` sur le crédit.
- Épargne (module épargne) : produit souscrit + transaction de dépôt déjà « comptabilisée » sans écriture ni mouvement de caisse, marqueur `opening_balance_id`, montant verrouillé.
- Concordance : blocage de la validation de la balance si une reprise existe et si un écart subsiste (par compte, principal restant vs 203xxx, épargne vs 213xxx) ; avertissement dans le fil si ces comptes sont non nuls sans reprise ; tableau d'écarts sur la fiche de la balance. Comptes configurables : paramètres système `microfinance.reprise_credit_codes` (défaut `203001,203002`) et `microfinance.reprise_savings_codes` (défaut `213001,213002,213003`).
- Tests : `microfinance_savings_management/tests/test_opening_reprise.py`, 15 tests, 0 échec (nominal, simulation, doublon, erreurs ligne à ligne, CIN d'une autre société, inter-agences, concordance en écart puis conforme, aucune `account.move`, absence de « Décaissements en attente », dashboard agent, droits, verrou du montant, lecteur Excel, gabarit). Régression : TestOpeningBalance, TestClientsPortefeuille, verrou de montant et compte épargne : 40 tests, 0 échec. Contrôle de bout en bout du gabarit d'exemple sur une copie jetable (aucune écriture, 2e import sans effet).
- Déploiement : sauvegarde `backups/MOWGLI_avant_reprise_portefeuille_20261010_201232.dump`, redémarrage du service, `-u` des deux modules (versions confirmées en base).

### Hors périmètre (V1)
- Intérêts et pénalités échus ou restants (laissés à 0 ; manque à gagner d'intérêts sur la durée restante, aucun effet sur la concordance).
- Historique de remboursements des crédits repris.
- Reprise depuis le fichier réel de l'ancien système (le gabarit est le seul format).
- Clients de type « groupe » (203002 / 213002 restent à 0) : chantier à part.
- Annulation d'une reprise : pas de bouton, le raz de la base de test suffit.
- Reprise rattachée aux fonds de crédit (option a de l'audit).

### À savoir
- Aucun commit. Si la 1ʳᵉ échéance reprise est dans le passé, elle est refusée (erreur) ; un crédit repris devient en retard comme les autres si l'échéance passe sans paiement (cron quotidien).
- Les séquences ne sont pas transactionnelles : un import réel qui échoue en cours de route peut laisser des numéros inutilisés (la simulation n'en consomme aucun).
- La contrainte d'unicité du CIN du modèle partenaire reste limitée à l'agence de la session ; seul l'import contrôle toutes les sociétés.

## Garde-fou « une balance par société », zéro négatif, format des montants (2026-10-10)
Audit : [AUDIT_garde_fou.md](AUDIT_garde_fou.md). Versions : loan 17.0.1.32.0, RAZ 17.0.1.2.0. Déployé sur MOWGLI, en attente de relecture/commit.
- **Blocage** : au clic sur Nouveau (`default_get`, message « Une balance d'ouverture existe déjà pour cette société (brouillon / validée) »), dans `create()` (RPC, import, lots), « Dupliquer » refusé (`copy()` + `duplicate="false"`), index unique partiel `WHERE state = 'draft'`. Portée = société concernée seulement. La liste ne déclenche rien. Clé de contexte `mf_opening_allow_multiple` lue uniquement en mode test.
- **Zéro négatif** : `_no_negative_zero()` (arrondi à la devise + 0.0) pour totaux, écart des totaux, balance / détail / écart de la concordance.
- **Format** : la concordance utilise `format_amount` (langue de l'utilisateur, symbole Ar) comme les lignes.
- **RAZ microfinance** (administrateur technique) : deux blocs ajoutés, cochés par défaut : « Balances d'ouverture et leur écriture » (écriture remise en brouillon puis supprimée, balance même validée supprimée ; le verrou de suppression reste actif hors RAZ) et « Clients créés par la reprise » (marqueur `res.partner.opening_balance_id` ; les autres clients ne sont jamais touchés). Crédits, épargne et comptes de la reprise étaient déjà couverts. Aperçu mis à jour.
- **Nettoyage** : `balance_cleanup.py` (paramètre `microfinance_loan_management.opening_cleanup_dry_run`, dry-run par défaut, idempotent) ; brouillon vide 44 (Analakely) supprimé ; reste la balance validée 43.
- Pas de bouton « Annuler l'ouverture » : le RAZ est le chemin de test retenu.
- Tests : `test_opening_balance_guard.py` (6), concordance sans -0.0 et formatée (reprise), `test_opening_purge.py` (3) : 65 tests ciblés, 0 échec. `TestMicrofinanceDataResetWizard` (anciens tests du RAZ) : 10 échecs/erreurs sans lien avec ces changements (génération d'échéancier négative sur les données de test, verrou, société sans code agence), non comparés à un état antérieur.
