# Audit — Échéanciers obsolètes silencieux (`installment_ids` readonly + onchange)

Audit en lecture seule (Lot 0). **Aucune modification de code effectuée, aucune écriture en
base** (recensement DB fait via `odoo-bin shell`, transaction annulée par `env.cr.rollback()`
avant la fin du script, et contre-vérifié indépendamment par requête SQL brute en lecture seule).

## Résumé exécutif

Le mécanisme est confirmé avec une source Odoo précise (§1). Le recensement exhaustif en base
(§2) trouve **2 crédits affectés sur 2 crédits existants dans SEFOR** — ce n'est pas un problème
de volume (la base ne contient aujourd'hui que ces deux dossiers de test), mais c'est **100 %**
des crédits existants, ce qui confirme que le bug se déclenche systématiquement dès qu'un crédit
déjà généré est retouché sans repasser par le bouton "Générer échéancier". Le grep systématique
(§3) montre que l'anti-pattern n'est **pas répété ailleurs** dans les deux modules : un seul champ
est concerné, `installment_ids` sur `microfinance.loan`. Point aggravant découvert pendant cet
audit (hors périmètre strict de la demande, signalé en §2) : `action_disburse()` ne régénère
l'échéancier que si `installment_ids` est **vide** — un crédit décaissé avec un échéancier
obsolète mais non vide passerait au décaissement sans correction automatique.

---

## Étape 1 — Mécanisme exact confirmé

**Un seul mécanisme écrit dans `installment_ids`, et il existe bien deux chemins distincts, l'un
cassé, l'autre correct — exactement comme le suspectait la demande.**

### Chemin cassé : onchange d'aperçu, jamais persisté

Deux `@api.onchange` sur `microfinance.loan` (`microfinance_loan.py:811-875`) réécrivent
`installment_ids` en mémoire à chaque frappe sur `loan_amount`/`term`/`repayment_frequency_id`/
`interest_rate`/`installment_amount` :

```python
loan.installment_ids = [(5, 0, 0)] + loan._build_installment_commands()
```
Ce sont `_onchange_loan_amount_recompute_installment` (ligne 839) et
`_onchange_installment_amount_recompute_terms` (ligne 875).

`installment_ids` est marqué `readonly="1"` dans la vue (`microfinance_loan_views.xml:168`,
`<field name="installment_ids" readonly="1"/>`, onglet "Échéancier"). **Confirmé, avec la source
exacte** : `odoo/tests/form.py:486` — `if mode == 'save' and self._get_modifier(field_name,
'readonly', ...)`, qui exclut explicitement tout champ readonly des valeurs envoyées lors de la
sauvegarde, quel que soit son type (scalaire ou relationnel) et qu'il ait été modifié par un
onchange ou non. `Form()` reproduit fidèlement le comportement du client web réel — ce n'est pas
une limitation propre aux tests, c'est le même filtre appliqué en production. Ce fait était déjà
documenté dans le dépôt à deux endroits, tous deux non commités au moment de cet audit (`git
status`) :
- `microfinance_loan_views.xml:141-149` (commentaire sur la page "Avis CA / CDAG", chantier Avis
  CA/CDAG, constaté empiriquement pendant ce chantier),
- `docs_dev/correction_diviseur_echeancier/AUDIT.md:321-334` (addendum IS/001076, cause du même
  symptôme déjà entièrement diagnostiquée et reproduite via `Form()` avant cet audit).

**Résultat** : l'utilisateur voit un aperçu correct dans le formulaire avant d'enregistrer, mais
dès qu'il clique "Enregistrer", `installment_ids` repart tel qu'il était en base — silencieusement,
sans erreur, sans avertissement.

### Chemin correct : écriture serveur directe (pas de la sauvegarde de formulaire)

Deux points d'entrée écrivent réellement `installment_ids`, tous deux en dehors de tout cycle
onchange/formulaire :

1. **`action_generate_schedule()`** (`microfinance_loan.py:1144`), appelée par le bouton
   "Générer échéancier" via le wizard `microfinance.loan.schedule.rounding.wizard`
   (`wizard/microfinance_loan_schedule_rounding_wizard.py:17`). L'assignation
   `loan.installment_ids = [(5, 0, 0)] + loan._build_installment_commands(...)` y a lieu dans une
   méthode Python appelée directement côté serveur (bouton → action_generate_schedule), pas dans
   le cycle de sauvegarde RPC du client web filtré par `readonly` — elle persiste normalement.
2. **`_propagate_avis_to_loan()`** (`microfinance_loan.py:256-293`), mécanisme du chantier Avis
   CA/CDAG : appelée depuis `write()` (override, ligne 249-254) dès qu'un champ avis CA/CDAG est
   écrit pendant que le crédit est en état `avis_ca`/`avis_cdag`. Elle appelle elle-même
   `self.action_generate_schedule()` en toute fin (ligne 293) — donc passe par le même chemin
   correct, pas par l'onchange.

**Confirmation empirique indirecte** : le dossier IS/001076 contient réellement 27 lignes en
base (pas 24, pas un nombre incohérent) — cohérent avec le fait que ces 27 lignes ont bien été
*écrites* via `_propagate_avis_to_loan()`/`action_generate_schedule()` (chemin correct) au moment
des tests du chantier Avis CA/CDAG avec `term=27`, puis jamais régénérées depuis que `term` est
repassé à 24 via une simple modification du formulaire (chemin cassé, onchange seul).

### Circonstance précise de déclenchement

Le bug se produit uniquement quand les trois conditions suivantes sont réunies :
1. `installment_ids` a déjà été généré une première fois (via un des deux chemins corrects
   ci-dessus) — sur un crédit tout neuf, jamais généré, `installment_ids` est simplement vide
   jusqu'au premier passage par un chemin correct (pas de "obsolescence" à proprement parler).
2. `loan_amount`, `term`, `repayment_frequency_id`, `interest_rate` ou `installment_amount` est
   ensuite modifié directement sur le formulaire crédit (pas via les champs `avis_ca_*`/
   `avis_cdag_*`, qui ont leur propre onchange à part, ligne 877-899 - eux-mêmes non affectés
   directement puisqu'ils ne sont pas marqués `readonly="1"` en vue, cf. commentaire
   `microfinance_loan_views.xml:141-149`).
3. Le formulaire est enregistré **sans** repasser explicitement par le bouton "Générer
   échéancier" après coup.

**Point important, hors périmètre strict mais découvert pendant cet audit** : `action_disburse()`
(`microfinance_loan.py:1487-1504`) ne régénère l'échéancier que si `installment_ids` est
**vide** :
```python
if not loan.installment_ids:
    loan.action_generate_schedule()
```
Un crédit dont l'échéancier est obsolète (non vide, mais périmé) **passe donc au décaissement sans
correction automatique** — le bug n'est pas cantonné à l'affichage en cours d'instruction, il peut
atteindre un crédit actif. À signaler à Micka comme un facteur de gravité supplémentaire, même si
aucun des deux dossiers recensés ci-dessous n'est allé jusqu'au décaissement (IS/000289 :
`enquete` ; IS/001076 : `avis_cdag`).

---

## Étape 2 — Recensement exhaustif en base (SEFOR)

**Recensement complet, aucune limitation de portée** : requête sur `microfinance.loan`
(`search([])`, aucun domaine) via `odoo-bin shell` (transaction annulée avant sortie), et
contre-vérifiée indépendamment par SQL brut (`SELECT count(*) FROM microfinance_loan`, hors ORM,
hors tout filtre de sécurité).

**Constat central : la base SEFOR ne contient à ce jour que 2 crédits au total** (`microfinance_
loan`, tous états confondus) — confirmé par les deux méthodes indépendamment (ORM et SQL brut,
mêmes 2 lignes). Ce n'est pas un périmètre partiel de l'audit : c'est l'intégralité de la table.
La base est encore au stade des dossiers de test/démonstration des chantiers récents, pas un
portefeuille de production.

| Dossier | id | État | Agence | `term` actuel | `loan_amount` | Lignes attendues (calcul actuel) | Lignes réelles en base | Dernière écriture |
|---|---|---|---|---|---|---|---|---|
| IS/000289 | 1449 | `enquete` | CEFOR Isotry (IS) | 24 | 500 000 | **24** | **8** | 2026-08-25 11:29:06 |
| IS/001076 | 2327 | `avis_cdag` | CEFOR Isotry (IS) | 24 | 500 000 | **24** | **27** | 2026-08-25 11:29:06 |

**Les deux dossiers existants sont affectés — 2 sur 2 (100 %).** Dans les deux cas, la somme des
`principal_amount` de l'échéancier réel coïncide malgré tout avec `loan_amount` actuel
(500 000 Ar) : ceci n'est **pas** un signe que l'échéancier est correct — c'est une coïncidence
mécanique de l'algorithme (`_build_installment_commands` fait toujours absorber le reliquat par
la dernière tranche, donc la somme des principaux vaut toujours `loan_amount` tant que
`loan_amount` lui-même n'a pas changé depuis la génération — seul `term` a changé ici). **Le
signal fiable est le nombre de lignes**, pas la somme des montants — à retenir pour tout futur
recensement (une comparaison basée uniquement sur les totaux aurait manqué ces deux cas).

- **IS/000289** (`enquete`, jamais rééchelonné, `reschedule_count=0`) : 8 lignes en base — résidu
  de l'incident déjà documenté dans `docs_dev/regression_nb_echeances/AUDIT.md` ("nombre
  d'échéances revient à 8"), lui-même antérieur à la découverte du bug readonly/onchange. Déjà
  signalé dans `docs_dev/correction_diviseur_echeancier/AUDIT.md:404-409`.
- **IS/001076** (`avis_cdag`, jamais rééchelonné) : 27 lignes en base — résidu direct des tests du
  chantier Avis CA/CDAG (`avis_cdag_term=27` testé sur ce dossier), écrit correctement à l'époque
  via `_propagate_avis_to_loan()`, jamais régénéré depuis le retour à `term=24`. Déjà signalé dans
  `docs_dev/correction_diviseur_echeancier/AUDIT.md:266-334` (addendum).

**Aucun troisième cas** : les deux seuls crédits de la base sont déjà les deux cas connus cités
dans la demande — le recensement exhaustif ne révèle aucun dossier supplémentaire.

**Évaluation de gravité, telle que demandée** : à ne pas dramatiser en volume (2 dossiers, tous
deux déjà connus, aucun décaissé) — mais à ne pas minimiser non plus : c'est **100 % des crédits
existants**, ce qui montre que le bug n'est pas un cas limite rare mais se déclenche à la première
occasion venue (toute modification de `term`/`loan_amount` après une première génération). Le
volume restera faible tant que la base reste au stade de test ; il grandira mécaniquement au
rythme de l'usage réel si rien n'est corrigé avant la mise en production du portefeuille.

---

## Étape 3 — Recherche de l'anti-pattern ailleurs dans le module

**Grep systématique effectué** sur tous les `readonly="1"` (vues XML) et `readonly=True`/
`readonly=...` (champs Python) des deux modules (`microfinance_loan_management`,
`microfinance_savings_management`) — plus de 70 champs marqués readonly en vue au total.

**Verdict : l'anti-pattern n'est pas répété — un seul champ est concerné dans les deux modules,
`installment_ids` sur `microfinance.loan`.** Méthode de vérification : recherche de toute
assignation par commande o2m/m2m (`= [(5, 0, ...`, `= [(6, 0, ...`, `= [(0, 0, ...`) à l'intérieur
du corps de **tous** les `@api.onchange` des deux modules. Un seul champ relationnel est réécrit
ainsi par un onchange : `installment_ids`, aux deux lignes déjà citées en Étape 1. Aucun autre
onchange, dans aucun des deux modules, n'assigne de commandes o2m/m2m à un champ marqué readonly.

Détail des autres champs relationnels marqués `readonly="1"` rencontrés, tous non concernés (et
pourquoi) :
- `child_ids` (`microfinance.geo.commune`), `reschedule_history_ids`, `scoring_line_ids`,
  `transaction_ids`, `payment_ids` (sur `microfinance.loan`), `microfinance_savings_account_ids`,
  `microfinance_loan_ids` : tous des One2many **inverses** d'un Many2one porté par le modèle lié
  (ex. `payment.loan_id`) — leur contenu reflète toujours l'état réel de la table liée sans jamais
  être assigné directement ; aucun risque structurel de ce bug.
- `installment_ids` sur `microfinance.loan.payment` (Many2many, `readonly=True` déjà en Python) :
  écrit une seule fois, via `self.write({'installment_ids': [(6, 0, touched.ids)], ...})` dans
  `_allocate_to_installments()` (`microfinance_loan_payment.py:150-155`) — une méthode Python
  ordinaire (pas un onchange), appelée depuis un flux de validation de paiement. Chemin correct,
  non affecté.
- Les autres champs readonly listés (`balance_total`, `principal_total`, `interest_total`,
  `paid_total`, `risk_level`, les `*_score_display`, etc.) sont des champs `compute=...
  store=True` avec `@api.depends` — mécanisme de calcul serveur totalement différent de
  l'onchange, non filtré par `readonly` au moment de la sauvegarde (le calcul se redéclenche à
  l'écriture via l'ORM lui-même, pas via une simulation d'édition de formulaire).

**Lien avec la "régression Section VI" mentionnée dans la demande — confirmé partiellement, avec
une précision.** Aucune section numérotée "VI" n'existe sur `microfinance.loan` (les sections
à numéros romains I à VIII appartiennent au formulaire `microfinance.loan.application`, un modèle
différent — cf. `docs_dev/workflow_avis_ca_cdag/AUDIT.md` et `docs_dev/comite_octroi/AUDIT.md`,
où "Section VI" désigne `field_visit_ids`, un champ sans rapport, jamais marqué readonly, jamais
concerné par ce bug). En revanche, **le même phénomène concret (tableau `installment_ids`
affichant un ancien `term`) avait déjà été observé et documenté avant la découverte de sa cause
réelle** : `docs_dev/regression_nb_echeances/STATUS.md` (commentaire "ancien", lignes 645-646,
remplacé depuis) le décrivait comme un "symptôme voisin déjà partiellement traité" par la
correction de la boucle de rétroaction `term`↔`installment_amount`, sans alors identifier le
readonly comme cause de fond. Cette explication antérieure est donc **incomplète plutôt que
fausse** : la boucle de rétroaction (Lot 1-bis) et le readonly/onchange (ce rapport) sont deux
causes distinctes du même type de symptôme visible (échéancier détaillé désynchronisé de
`term`), la seconde n'ayant été isolée et prouvée qu'après coup, pendant le chantier Avis
CA/CDAG puis l'addendum `correction_diviseur_echeancier`.

---

## Étape 4 — Intention d'origine du `readonly="1"`

**Historique git : `readonly="1"` sur `installment_ids` existe depuis le commit initial squashé
du dépôt** (`9b4a37f`, "Initial commit - IMF Odoo 17 modules") — aucune granularité antérieure
disponible, `git log -S` ne trouve pas de commit d'introduction plus fin.

**Intention légitime, non remise en cause par ce rapport** : empêcher l'utilisateur d'éditer
manuellement les lignes de l'échéancier détaillé à la main dans le tableau (ajouter/supprimer une
échéance, changer une date ou un montant directement) — l'échéancier doit rester un résultat
calculé par `_build_installment_commands()`, pas un tableau librement éditable. **Le bug ne vient
pas de cette intention, mais de la confusion entre deux garanties différentes** que `readonly="1"`
en vue ne fournit qu'une seule des deux : "l'utilisateur ne peut pas taper directement dans ce
champ" (vrai, et c'est tout ce que `readonly` en vue garantit) versus "le serveur régénère
correctement ce champ à chaque recalcul pertinent" (faux pour le chemin onchange — un onchange
qui modifie un champ readonly ne fait que mettre à jour l'aperçu affiché, sans jamais atteindre la
base, cf. Étape 1).

**Le pattern correct existe déjà dans le module et peut servir de référence directe** :
`action_generate_schedule()` (bouton "Générer échéancier") concilie déjà les deux garanties —
l'utilisateur ne peut toujours pas éditer le tableau à la main (readonly toujours actif en vue),
et le serveur écrit réellement `installment_ids` (parce que l'écriture a lieu dans une méthode
Python appelée par un bouton, pas dans le cycle de sauvegarde de formulaire filtré par
`readonly`). `_propagate_avis_to_loan()` (chantier Avis CA/CDAG) suit déjà ce même pattern
correct pour sa propre repercussion — les deux constituent une référence d'implémentation
directement réplicable pour corriger les deux onchange fautifs, sans qu'aucune nouvelle
architecture ne soit nécessaire.

---

## Options de correction (documentées, non tranchées, non codées)

1. **Champ calculé stocké** (`compute=... store=True`, `@api.depends` sur `loan_amount`, `term`,
   `repayment_frequency_id`, `interest_rate`, `product_id.installment_rounding_unit`/`_mode`) au
   lieu d'un onchange. Avantage : se recalcule et se persiste automatiquement à chaque écriture
   pertinente, y compris hors formulaire (import, écriture API). Inconvénient : change la
   sémantique du champ (un compute stocké écrase le contenu à chaque dépendance modifiée,
   y compris les échéances déjà partiellement payées ou rééchelonnées — `_reschedule_installments`
   et `_allocate_to_installments` écrivent aujourd'hui directement sur les lignes existantes, un
   passage en compute devrait explicitement exclure ces cas pour ne pas écraser l'historique de
   paiement).
2. **Garder l'onchange pour l'aperçu (comportement actuel), ajouter une écriture explicite dans
   `write()`** qui régénère réellement `installment_ids` à chaque sauvegarde du crédit tant que
   celui-ci reste dans `_EDITABLE_SCHEDULE_STATES`. Réutiliserait directement
   `_build_installment_commands()`, déjà factorisée et déjà exploitée par les deux chemins
   corrects existants (Étape 1) — le plus proche du pattern déjà en place (`_propagate_avis_to_
   loan` fait déjà exactement cela, mais seulement pour les champs avis CA/CDAG ; il s'agirait de
   généraliser le même geste à `loan_amount`/`term`/`repayment_frequency_id`/`interest_rate`
   directement).
3. **Signal visuel (bandeau d'alerte)** si un écart est détecté entre l'échéancier affiché/
   persisté et ce qu'impliqueraient les champs de tête — filet de sécurité à court terme, n'empêche
   pas la désynchronisation mais la rend visible avant décaissement (couvrirait aussi le point
   soulevé en Étape 1 sur `action_disburse()`, qui ne revérifie pas l'échéancier existant avant de
   décaisser).

Aucune option n'est recommandée ici, conformément à la demande.

## Non-régression

Ce lot ne modifie rien : aucune écriture en base, aucune régénération des deux dossiers déjà
identifiés comme obsolètes. Le choix de correction et le traitement effectif de IS/000289 et
IS/001076 (régénération via le bouton "Générer échéancier", geste déjà disponible et sûr dès
aujourd'hui pour ces deux dossiers précis) sont scopés dans un Lot 1 séparé, après validation de
ce rapport par Micka.
