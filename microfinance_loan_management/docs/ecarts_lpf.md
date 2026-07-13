# Fonds de crédit rotatifs bailleurs — synchronisation vs Loan Performer (LPF)

Périmètre : `microfinance_loan_management` uniquement. Aucune modification de
`microfinance_savings_management`, `microfinance_mowgli_assistant`, `plan_compta_pcec`,
`res.partner` ni `microfinance.loan.application` (hors-périmètre, voir écart 1 ci-dessous).

## Ce qui a été ajouté

- **Référentiel Bailleurs** (`microfinance.bailleur.fonds`) : fichier de support global, sans
  `company_id`, partagé par toutes les agences (comme "Professions" ou "Périodicités de
  remboursement").
- **Fonds de crédit** (`microfinance.fond.credit`) : code auto-généré (séquence globale
  `FND/%(year)s/`), `scope` (`single_company`/`multi_company`, figé après la première
  sauvegarde ainsi que `company_id`), compte GL (`account_id`, domaine `account_type` — voir
  écart 2), `date_debut`/`date_cloture`, `passer_gl`, `verification_disponibilite`
  (`never`/`at_request`/`at_disbursement`), `solde_disponible` + `total_contributions`/
  `total_decaisse`/`total_rembourse` (champs calculés stockés, agrégation en `sudo()` pour rester
  identique quelle que soit l'agence consultante sur un fonds `multi_company`).
- **Contributions** (`microfinance.fond.contribution`) : dépôts/retraits, mode de paiement,
  `saisie_company_id` (traçabilité de l'agence de saisie, indépendante et toujours renseignée,
  y compris sur un fonds `single_company`), `state` (`draft`/`posted`), comptabilisation optionnelle
  via `_prepare_contribution_move()` + `action_post()` (squelette identique à
  `_prepare_disbursement_move()` du crédit).
- **Rattachement** : `fond_credit_id` sur `microfinance.loan`, domaine limitant aux fonds actifs
  non clôturés de la société courante ou partagés (`multi_company`).
- **Vérification de disponibilité** : `_check_fond_disponibilite()`, méthode réutilisable avec un
  seul point d'ancrage réel (`action_disburse()`, valeur `at_disbursement`). Ordre des contrôles :
  `date_debut` → `date_cloture` → fonds vide → solde insuffisant, messages en français avec
  valeurs réelles interpolées.
- **Sécurité** : `ir.model.access.csv` complété selon le pattern existant ; nouveau fichier
  `security/microfinance_fond_bailleur_rules.xml` avec la règle de partage optionnel
  (`'|', ('company_id', 'in', company_ids), ('company_id', '=', False)`) — première occurrence de
  ce pattern dans le module, documentée en commentaire pour ne pas être signalée à tort comme un
  oubli d'isolation lors d'un futur audit multi-société.
- **Vues/menus** : "Bailleurs de fonds" et "Fonds de crédit" sous Configuration ; "Contributions
  bailleurs" sous Crédits ; rapport "Utilisation des fonds" (liste + pivot) sous Analyse.
- **Tests** : 17 tests automatisés (`tests/test_fond_bailleur.py`), exécutés réellement sur une
  base Odoo jetable (pas seulement écrits/relus). Deux bugs réels détectés et corrigés en cours de
  route :
  - la vue crédit ne se chargeait plus (`ParseError` à l'installation) car le domaine de
    `fond_credit_id` référence `company_id`, restreint par `groups="base.group_multi_company"` —
    corrigé à l'identique du précédent déjà documenté dans `microfinance_loan_product_views.xml` ;
  - la vérification de disponibilité confondait "fonds vide" et "solde insuffisant" car le crédit
    en cours de décaissement (déjà à l'état `approved`) était déjà déduit de son propre solde —
    corrigé via une méthode partagée `_get_principal_outstanding()`.
  - Suite complète du module rejouée (125 tests) : un seul échec,
    `TestFee.test_disburse_nets_fee_in_single_move`, confirmé **pré-existant et sans rapport** avec
    ce chantier (reproduit sur une base neuve, module fraîchement installé, sans aucun fichier de
    ce chantier impliqué dans l'exécution).

## Écarts vs LPF (à confirmer)

1. **`verification_disponibilite='at_request'` sans effet observable.** Son point d'ancrage naturel
   (transition de `microfinance.loan.application` vers un état "soumis") n'existe pas : ce modèle
   est absent de `models/__init__.py` (hors registre Odoo), et sa méthode de transformation
   demande→crédit référence un wizard inexistant. Câbler ce modèle est un chantier séparé,
   identifié deux fois maintenant (audit initial du module + ce travail), hors périmètre ici.
2. **Comptes GL classe 2/3.** Le PCEC Madagascar 2005 ne suit pas la convention
   classe 2 = Dettes / classe 3 = Fonds propres supposée au départ (classe 2 = opérations
   clientèle mixtes actif/passif, classe 3 = comptes divers mixtes ; les vrais fonds propres sont
   en classe 5). Le domaine de `account_id` est donc basé sur `account_type`
   (`liability_current`/`liability_non_current`/`equity`), conformément à la convention déjà
   utilisée dans `microfinance_loan_product.py`, et non sur un préfixe de code.
3. **Rapports consolidés multi-agences.** Le rapport "Utilisation des fonds" agrège au niveau du
   fonds (une ligne par fonds) ; le filtre "période" ne porte donc que sur `date_debut` du fonds,
   pas sur la date des transactions individuelles. Un filtrage transactionnel réel par période
   nécessiterait un pivot dédié sur les contributions/échéances elles-mêmes.
4. **Import Excel "Branch Planning Model" (LPF) non repris** : jugé hors périmètre (non demandé
   explicitement, et hors du périmètre strict `microfinance_loan_management` défini au départ) —
   à confirmer que ce n'est effectivement pas un besoin actuel.
5. **Pas de QWeb PDF** pour le rapport "Utilisation des fonds" dans cette itération (liste + pivot
   seulement), comme spécifié dès le départ.
6. **Résolution du compte GL pour un fonds `multi_company`** : `account_id` reste un Many2one vers
   un compte d'une société précise même quand `scope='multi_company'` ; la question de savoir dans
   quelle société une écriture de contribution doit être postée quand le fonds est partagé entre
   agences n'est pas résolue (voir point de décision 2 ci-dessous).
7. **Pas de contrainte serveur dure** empêchant `microfinance.loan.fond_credit_id` de pointer vers
   un fonds `single_company` d'une autre société via l'API — seul le domaine de la vue (soft) l'en
   empêche dans l'usage normal de l'interface.

## Points de décision explicite laissés à Micka

1. **Option A/B bailleurs partagés** : déjà tranchée en amont (Option B, `multi_company` partagé,
   `ir.rule` avec clause `company_id` vide) — à reconfirmer maintenant que le code est en place et
   testé.
2. **Compte GL d'un fonds `multi_company`** : quand une contribution est saisie depuis l'agence B
   sur un fonds partagé dont `account_id` appartient à l'agence A, dans quelle société l'écriture
   comptable doit-elle être postée ? `action_post()` utilise actuellement tel quel `fond.account_id`
   et le `journal_id` choisi par l'utilisateur, sans validation de cohérence société. Arbitrage
   métier nécessaire avant un usage réel multi-agences avec `passer_gl=True` sur un fonds partagé.
3. **Emplacement des menus** : "Bailleurs de fonds"/"Fonds de crédit" sous Configuration,
   "Contributions bailleurs" sous Crédits, "Utilisation des fonds" sous Analyse — à valider ou
   ajuster.
4. **Tuile dashboard "Fonds bailleurs"** : non ajoutée (aurait sa place dans la section "Vue
   d'ensemble" du dashboard KPI existant) — à confirmer si souhaitée ; toucherait le contrôleur JS
   du dashboard, hors du périmètre initial de ce chantier.
5. **Formule du solde disponible** : calculée sur le principal restant dû uniquement (intérêts et
   pénalités exclus), interprétation retenue comme la plus sûre en l'absence de précision LPF — à
   confirmer que c'est la lecture métier voulue.
6. **Visibilité de `verification_disponibilite='at_request'`** : la valeur reste sélectionnable
   dans l'interface bien qu'elle n'ait aucun effet réel tant que `microfinance.loan.application`
   n'est pas câblé. Faut-il la masquer/désactiver temporairement dans la vue pour éviter une
   fausse impression de contrôle actif, ou la garder telle quelle (docstring + ce document suffisent
   à la documenter) ?
7. **Câblage de `microfinance.loan.application`** : chantier séparé, identifié à deux reprises —
   à prioriser ou non.
