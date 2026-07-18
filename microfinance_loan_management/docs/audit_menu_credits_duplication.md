# Audit — Duplication apparente "Dossiers d'instruction" / "Demande de crédit"

Audit uniquement, aucune modification de code/vue/menu/donnée effectuée.

> **Mise en œuvre (2026-07-18)** : l'Option A (section 6) a été implémentée — voir
> `docs_dev/point_entree_unique_credit/STATUS.md` pour le détail des 4 lots (verrou serveur
> sur `microfinance.loan.create()`, menu "Demande de crédit" renommé "Crédits" en
> consultation seule, bouton du tableau de bord redirigé vers le dossier d'instruction,
> documentation et datasets MOWGLI mis à jour). Le menu "Demande de crédit" cité dans cet
> audit n'existe donc plus tel quel ; ce document reste tel quel comme trace historique de
> l'analyse ayant motivé la décision.

## 1. Résumé exécutif

**Oui, il y a une duplication fonctionnelle réelle** : "Demande de crédit" permet de créer et
de faire progresser un crédit (`microfinance.loan`) de bout en bout — jusqu'au décaissement —
sans jamais passer par le dossier d'instruction (`microfinance.loan.application`) ni par son
processus de revue à plusieurs étapes (enquête terrain, analyse, comité, avis CA, avis CDAG) ;
rien dans le modèle ni dans les droits n'empêche ce contournement, et le tableau de bord
Microfinance encourage activement ce raccourci via un bouton "Nouveau prêt" en accès direct.

## 2. Tableau menu → action → modèle → domaine (Étape 1)

Menus sous `menu_credits_root` (`views/microfinance_menus.xml:17-29`) :

| Menu (xmlid) | Libellé | Action | Séquence | Fichier:ligne |
|---|---|---|---|---|
| `menu_microfinance_loan_applications` | Dossiers d'instruction | `action_microfinance_loan_application` | 0 | `microfinance_menus.xml:24` |
| `menu_microfinance_loans` | Demande de crédit | `action_microfinance_loan` | 1 | `microfinance_menus.xml:25` |
| `menu_microfinance_installments` | Échéances | `action_microfinance_installment` | 2 | `microfinance_menus.xml:26` |
| `menu_microfinance_payments` | Remboursements | `action_microfinance_payment` | 3 | `microfinance_menus.xml:27` |
| `menu_microfinance_guarantees` | Garanties | `action_microfinance_guarantee` | 4 | `microfinance_menus.xml:28` |
| `menu_microfinance_fond_contribution` | Contributions bailleurs | `action_microfinance_fond_contribution` | 5 | `microfinance_menus.xml:29` |

Actions des deux entrées en cause :

| Action (xmlid) | `res_model` | `view_mode` | `domain` | `context` | Fichier:ligne |
|---|---|---|---|---|---|
| `action_microfinance_loan_application` | `microfinance.loan.application` | kanban,tree,form | — | — | `microfinance_loan_application_views.xml:188-192` |
| `action_microfinance_loan` | `microfinance.loan` | kanban,tree,form | — | `{'search_default_active': 1}` | `microfinance_loan_views.xml:184-189` |

Ni l'une ni l'autre action ne restreint la vue formulaire (`create="0"`) : les deux permettent
la création libre depuis leur menu respectif. `search_default_active` ne fait qu'activer par
défaut le filtre de recherche nommé `active` (`domain="[('state','=','active')]"`,
`microfinance_loan_views.xml:47`) sur la liste — purement cosmétique, sans effet sur la
création.

Aucune restriction de groupe propre à ces deux `<menuitem>` : les deux héritent uniquement du
groupe du parent `menu_credits_root` (`group_microfinance_user`, `_manager`, `_finance`,
`_auditor`, `_collection_agent` — `microfinance_menus.xml:17-18`). Aucun droit
spécifiquement attaché à l'action ou au menu (au sens de l'Étape 4) ne serait donc perdu par
un retrait/renommage : seuls les droits sur le **modèle** (`ir.model.access.csv`) comptent, et
ils restent nécessaires quelle que soit l'existence du menu (voir section 5).

## 3. Analyse détaillée des deux entrées (Étape 2)

**Modèles différents, pas le même objet** :
- "Dossiers d'instruction" ouvre `microfinance.loan.application` — cycle de vie en 8 états
  (`draft` → `field_survey` → `analysis` → `committee` → `ca_review` → `cdag_review` →
  `accepted`/`accepted_condition`/`refused` → `loan_created`), avec contrôle de rôle par étape
  (`STATE_TARGET_GROUP`) et calcul d'éligibilité informatif (programme progressif). Un dossier
  accepté crée un crédit via le wizard `action_create_loan()` (voir chantier "Programmes
  progressifs" de cette session — ce wizard était manquant, corrigé récemment).
- "Demande de crédit" ouvre directement `microfinance.loan` — cycle de vie propre en 6 états
  actifs (`draft` → `submitted` → `manager_validated` → `finance_validated` → `approved` →
  `active` → `closed`/`defaulted`/`written_off`/`cancelled`), avec sa propre validation
  (`_check_eligibility()` : ancienneté, second crédit parallèle, arriérés co-emprunteur,
  garanties) et son propre calcul de scoring.

**Absence de lien structurel entre les deux** : `microfinance.loan` **n'a aucun champ**
`application_id` ni équivalent pointant vers le dossier qui l'aurait éventuellement créé
(seul `microfinance.loan.application.loan_id` pointe dans l'autre sens, à sens unique). Rien
au niveau du modèle ni de la vue n'empêche donc de créer un crédit depuis "Demande de crédit"
sans qu'aucun dossier d'instruction n'existe : le crédit passe alors par son propre
`action_submit`/`action_manager_validate`/`action_finance_validate`/`action_approve`/
`action_disburse`, **sans jamais passer par l'enquête terrain, l'analyse, le comité, l'avis CA
ni l'avis CDAG** que le dossier d'instruction impose.

**Le tableau de bord aggrave le constat** : le bouton primaire "Nouveau prêt"
(`btn-primary`, `static/src/xml/microfinance_loan_dashboard.xml:245`, méthode `openNewLoan()`
dans `static/src/js/microfinance_loan_dashboard.js:183-191`) ouvre directement un formulaire
`microfinance.loan` vierge — le point d'entrée le plus visible du module (tableau de bord,
page d'accueil Microfinance) pousse donc activement vers le contournement du dossier
d'instruction, pas vers "Dossiers d'instruction".

**Historique git** (Étape 2, demandé explicitement) :
- Le menu "Demande de crédit" s'appelait à l'origine simplement **"Crédits"**, présent dès le
  commit initial du projet (`9b4a37f`, "Initial commit"), sous un menu `menu_microfinance_operations`
  alors inexistant sous sa forme actuelle.
- `microfinance.loan.application` (modèle **et** vue, y compris le menu "Dossiers d'instruction")
  a été introduit d'un seul coup dans le commit `6546bb2` ("Ajouter la gestion des
  représentants, listes noires, catégories et groupes de clients", 9 juillet) — un message de
  commit qui **ne mentionne pas du tout** l'ajout du dossier d'instruction, ce qui suggère un
  ajout secondaire/opportuniste plutôt qu'un chantier annoncé comme tel. C'est dans ce même
  commit que "Crédits" a été renommé en "Demande de crédit" et déplacé sous le nouveau
  `menu_credits_root` — cohérent avec l'hypothèse d'un remplacement voulu mais jamais finalisé
  (l'ancien menu a été renommé/rétrogradé, pas retiré).

**Conclusion de l'étape 2** : "Demande de crédit" est un résidu antérieur à l'introduction du
workflow d'instruction CEFOR, jamais retiré ni restreint après l'arrivée de
`microfinance.loan.application`.

## 4. Écarts avec la documentation existante (Étape 3)

- **`README.md`**, section "Le parcours d'un dossier de crédit" (lignes 60-76) : décrit
  intégralement le cycle de `microfinance.loan` (Création du dossier → Soumission → Validation
  manager → Validation finance → Approbation → Génération de l'échéancier et décaissement →
  Remboursements → Clôture) — **`microfinance.loan.application` et "Dossiers d'instruction" ne
  sont mentionnés nulle part dans tout le fichier.**
- **`USER_GUIDE_FR.md`**, section "Gestion des dossiers de crédit" (lignes 230-281) : chemin de
  menu indiqué "**Microfinance → Demandes de crédit → Dossiers de crédit**" — un intitulé à
  trois niveaux qui **ne correspond à aucun des deux menus réels actuels** (tous deux à un seul
  niveau sous Crédits, libellés "Dossiers d'instruction" et "Demande de crédit"). Les champs
  documentés juste après (Emprunteur, Produit, Montant crédit, Nombre échéances, Date de
  candidature) et les étapes (Brouillon → Soumis → Validé manager → Validé finance → Approuvé →
  Décaisser) confirment sans ambiguïté qu'il s'agit de `microfinance.loan`, pas du dossier
  d'instruction.
- **MOWGLI** (`microfinance_mowgli_assistant/datasets/dossier_precredit/dataset.yaml`) : les
  deux premiers articles (`dossier_precredit-001`, `dossier_precredit-002`, sur 2 au total dans
  ce fichier avec un champ `menu:` pointant ici) documentent explicitement `model:
  microfinance.loan` avec `menu: Microfinance > Crédits > Demande de crédit (...
  action_microfinance_loan)` — la description du workflow MOWGLI ("Instruction et
  qualification du dossier crédit avant décaissement") **ne mentionne pas non plus
  `microfinance.loan.application`.**

**Constat global** : les trois sources de documentation (guide utilisateur, README technique,
base de connaissances MOWGLI) documentent **exclusivement** le chemin "Demande de crédit"
comme étant LE processus d'instruction de crédit, et aucune des trois ne mentionne même
l'existence de "Dossiers d'instruction" — alors que ce dernier modèle porte tout le travail
récent de fidélité à la fiche papier CEFOR (sections I-VIII, garants, visites terrain, grille
sociale, programmes progressifs). La documentation n'a manifestement jamais été mise à jour
au moment de l'introduction du dossier d'instruction.

## 5. Impact d'un retrait ou d'un renommage (Étape 4)

- **Droits d'accès** : aucun droit n'est attaché spécifiquement au menu ou à l'action (voir
  section 2) — seuls les droits de modèle (`ir.model.access.csv` sur `microfinance.loan`)
  comptent, et ils doivent être **conservés dans tous les cas** : `microfinance.loan` reste
  utilisé pour tout le cycle de vie post-acceptation (validation, décaissement, remboursement,
  clôture, rééchelonnement, radiation) quel que soit le sort du menu "Demande de crédit". Ne
  jamais toucher `ir.model.access.csv` sur ce point.
- **MOWGLI** : 2 articles du dataset `dossier_precredit` (`dossier_precredit-001`,
  `dossier_precredit-002`) référencent explicitement `menu_microfinance_loans`/
  `action_microfinance_loan` dans leur champ `menu:` et leur texte de réponse (`answer:`). Un
  retrait ou un renommage du menu **casserait la justesse de ces réponses MOWGLI** (chemin de
  menu obsolète affiché à l'utilisateur final) — à corriger dans le même lot que tout retrait,
  ou à réécrire pour documenter le vrai parcours recommandé (dossier d'instruction → wizard de
  création de crédit → suivi sur `microfinance.loan`).
- **Tableau de bord** : le bouton "Nouveau prêt" (`openNewLoan()`,
  `static/src/js/microfinance_loan_dashboard.js:183-191`) et `openAllLoans()` (ligne 194)
  référencent respectivement une création directe de `microfinance.loan` et l'action
  `action_microfinance_loan` — à ajuster dans le même lot si la décision est de ne plus exposer
  la création directe.
- **Modèle toujours utilisé ailleurs même sans menu direct** : `microfinance.loan` reste
  référencé par de très nombreux wizards (paiement, rééchelonnement, radiation, annulation de
  paiement), par le nouveau wizard `microfinance.loan.application.create.loan.wizard`, par les
  rapports QWeb (reçu de décaissement, échéancier), par le tableau de bord (KPI, PAR), et par
  `action_view_loan()` sur le dossier. **Retirer le menu direct ne rendrait aucun crédit
  existant inaccessible** : un crédit créé via le dossier reste ouvrable via le bouton "Voir le
  crédit" du dossier, sans jamais passer par le menu "Demande de crédit".
- **`README.md`/`USER_GUIDE_FR.md`** : à mettre à jour dans tous les cas (documentation déjà
  fausse aujourd'hui, indépendamment de la décision finale — voir section 4).

## 6. Recommandation — point de décision pour Micka

Ceci est une proposition à trancher, aucune action n'a été prise.

**Option A (recommandée) — Restreindre "Demande de crédit" à un usage technique/consultation,
faire de "Dossiers d'instruction" le seul point d'entrée de création.**
Renommer "Demande de crédit" en quelque chose comme "Crédits" (rôle : consultation/suivi du
cycle de vie post-acceptation), retirer ou masquer sa capacité de création libre (`create="0"`
sur la vue, ou restriction de groupe), retirer le bouton "Nouveau prêt" du tableau de bord (ou
le rediriger vers "Dossiers d'instruction"), et mettre à jour les 3 sources de documentation
(README, USER_GUIDE_FR, dataset MOWGLI) pour décrire le vrai parcours : dossier d'instruction
→ wizard de création de crédit → suivi sur la fiche crédit. Justification : c'est le seul
scénario cohérent avec tout le travail réalisé sur la fidélité au processus papier CEFOR, et il
supprime un contournement réel du comité de crédit/avis CA/CDAG.

**Option B — Garder les deux, mais documenter et cloisonner explicitement leurs rôles
distincts.**
Si un usage légitime existe pour créer un crédit sans passer par l'instruction complète (ex.
migration de données historiques, crédit accordé hors process normal avec traçabilité
différente), garder "Demande de crédit" mais le renommer clairement (ex. "Crédit (saisie
directe)"), restreindre son accès à un groupe précis (ex. seulement Manager crédit, pas Agent
crédit), documenter explicitement dans les 3 sources cette distinction et la raison d'être du
contournement, et ajouter un champ de traçabilité (ex. `creation_mode` ou équivalent) sur
`microfinance.loan` pour distinguer a posteriori les crédits créés directement de ceux issus
d'un dossier d'instruction.

**Ne pas garder le statu quo** (les deux menus identiques en accès, sans distinction ni
documentation) : c'est la seule option qui laisse subsister un contournement non maîtrisé et
non documenté du processus de revue.

## 7. Fichiers et lignes concernés pour un futur lot d'implémentation (si Option A retenue)

- `views/microfinance_menus.xml:25` — renommer le libellé du `<menuitem
  id="menu_microfinance_loans">` (et éventuellement changer sa séquence/position).
- `views/microfinance_loan_views.xml:184-189` (`action_microfinance_loan`) — envisager un
  `context` ou des vues dédiées limitant la création si Option A ; `views/microfinance_loan_views.xml`
  (vue formulaire/tree/kanban) — ajouter `create="0"` aux vues concernées si la création directe
  doit être bloquée à ce niveau plutôt qu'au niveau de l'action.
- `static/src/js/microfinance_loan_dashboard.js:183-191` (`openNewLoan`) et son bouton associé
  `static/src/xml/microfinance_loan_dashboard.xml:245` — à retirer ou rediriger vers l'action
  `action_microfinance_loan_application`.
- `README.md:60-76` ("Le parcours d'un dossier de crédit") — à réécrire pour démarrer par le
  dossier d'instruction et son passage en crédit via le wizard.
- `USER_GUIDE_FR.md:230-281` (section "Gestion des dossiers de crédit") et son chemin de menu
  (lignes 234, 674) — à réécrire entièrement sur le modèle `microfinance.loan.application`.
- `microfinance_mowgli_assistant/datasets/dossier_precredit/dataset.yaml` (articles
  `dossier_precredit-001` lignes 21-76, `dossier_precredit-002` lignes 78-100+) — à réécrire
  pour documenter le dossier d'instruction comme point d'entrée, en conservant un renvoi vers le
  cycle `microfinance.loan` pour la partie post-acceptation (validation/décaissement) qui reste
  correcte telle quelle.
- `docs/workflows/programme_progressif/README.md` (section 1, déjà rédigé dans ce projet) fait
  déjà référence à `action_create_loan()`/au wizard de création de crédit comme pont entre les
  deux modèles — cohérent avec l'Option A, à ne pas modifier.

Ne rien modifier de ce qui précède tant qu'un lot d'implémentation n'est pas explicitement
demandé.
