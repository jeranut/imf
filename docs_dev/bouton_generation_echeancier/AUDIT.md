# Audit — Bouton manuel de génération d'échéancier (`microfinance.loan`)

Audit **lecture seule** (Lot 0). Aucune modification de code. Le Lot 1 (ajout effectif du
bouton) sera scopé après validation de ce rapport par Micka.

Contexte déclencheur : **IS/003362** (id 4777, PRET RURAL, 500 000 Ar, 24 échéances
hebdomadaires, taux 36 %, état `approved`) — `installment_ids` **vide en base**
(`nb_inst = 0`) alors que `loan_amount` / `term` / `installment_amount` /
`repayment_frequency_id` sont tous renseignés. Les trois autres dossiers PRET RURAL
comparables (IS/000289, IS/001076, IS/003363) ont bien leurs 24 lignes.

---

## 1. Méthodes `@api.onchange` déclenchées par `term` et `installment_amount`

Fichier unique : `microfinance_loan_management/models/microfinance_loan.py`.

| Méthode | Ligne | `@api.onchange(...)` | Rôle |
|---|---|---|---|
| `_onchange_loan_amount_recompute_installment` | **1009-1037** | `'loan_amount', 'term', 'repayment_frequency_id', 'interest_rate'` | Recalcule `installment_amount` (cible interest-first) **et** reconstruit `installment_ids` en mémoire. |
| `_onchange_installment_amount_recompute_terms` | **1039-1073** | `'installment_amount'` | Sens inverse : recalcule `term` à partir de l'échéance saisie, puis reconstruit `installment_ids` en mémoire. |

Variantes hors périmètre (même mécanisme, bloc Avis) : `_onchange_avis_ca_recompute_installment`
(1075), `_onchange_avis_ca_installment_recompute_term` (1101), `_onchange_avis_cdag_recompute_installment`
(1127), `_onchange_avis_cdag_installment_recompute_term` (1155).

Les deux onchange du périmètre terminent **tous les deux** par la même ligne :

```python
loan.installment_ids = [(5, 0, 0)] + loan._build_installment_commands()
```

soit : vider l'o2m puis le recréer, **en mémoire du formulaire uniquement**.

Gardes internes communes : `loan.state in _EDITABLE_SCHEDULE_STATES`
(`('draft','enquete','avis_ca','avis_cdag','approved')`, ligne 261) + présence de
`loan_amount` / `term` (ou `installment_amount`) / `repayment_frequency_id`. Gardes
anti-boucle documentées (`docs_dev/regression_nb_echeances/`) : n'écrire `installment_amount` /
`term` que si la cible a réellement changé.

---

## 2. Méthode centrale de génération

### 2.1 `_build_installment_commands` — calcul pur (ligne 1243-1365)

```python
def _build_installment_commands(self, rounding_mode='last_installment',
                                raise_on_negative_reliquat=False):
```

- **Retour** : `list` de commandes o2m `(0, 0, vals)` (`vals` = `sequence`, `due_date`,
  `principal_amount`, `interest_amount`). **Aucun effet de bord** — n'écrit rien, ne touche
  pas `self`.
- `self.ensure_one()`. Retourne **`[]`** si `not repayment_frequency_id or not loan_amount
  or not term` (ligne 1266) — ne lève jamais d'exception par défaut (contrat « onchange ne
  doit pas planter »).
- `raise_on_negative_reliquat=True` : lève `ValidationError` si la dernière tranche
  (absorbe le reliquat) serait négative (`docs_dev/garde_fou_reliquat_negatif/`). **Seul
  `action_generate_schedule()` passe `True`** — point de convergence unique de tous les
  chemins qui persistent.
- Prend en compte : délai de grâce (`product_id.grace_period_days`, tranche dédiée),
  arrondi de la cible (`product_id.installment_rounding_unit` /
  `installment_rounding_mode`), `rounding_mode` (`last_installment` par défaut ;
  `distributed` accessible par code seulement, plus d'UI).

### 2.2 `action_generate_schedule` — wrapper qui **persiste** (ligne 1367-1382)

```python
def action_generate_schedule(self, rounding_mode='last_installment'):
    for loan in self:
        if loan.state not in loan._EDITABLE_SCHEDULE_STATES:
            raise UserError(_('Échéancier autorisé avant activation seulement.'))
        if not loan.repayment_frequency_id:
            raise UserError(_('… choisissez une périodicité … avant de générer l'échéancier.'))
        loan.installment_ids = [(5, 0, 0)] + loan._build_installment_commands(
            rounding_mode=rounding_mode, raise_on_negative_reliquat=True)
    return True
```

- **Effet de bord** : réassigne `loan.installment_ids` → sur un enregistrement réel (hors
  cycle onchange), Odoo émet immédiatement `DELETE` des lignes existantes + `INSERT` des
  nouvelles. Retourne `True`.
- C'est **la** méthode socle : appelée par `write()` (`_SCHEDULE_TRIGGER_FIELDS`, ligne
  396), `_propagate_avis_to_loan()` (ligne 441), `action_disburse()` (filet, ligne 1714),
  et ~30 tests. C'était aussi le socle de l'**ancien bouton** « Générer échéancier »
  (retiré, cf. §6).

Helpers de calcul (inchangés, pour référence) : `_compute_installment_target` (956),
`_compute_term_from_installment_amount` (990), `_compute_installment_targets` (1197),
`_period_delta` (934), `_period_interest_factor` (945).

---

## 3. Algorithme : **interest-first**, déjà en place (pas l'ancien linéaire)

`_build_installment_commands` branche sur `self.interest_method`
(`related='product_id.interest_method'`, ligne 64) :

- **`interest_method == 'flat'`** (ligne 1288-1345) → **interest-first** (« intérêt
  d'abord », politique CEFOR taux uniforme, toutes agences/produits) : `total_interest =
  loan_amount × taux/100 × interest_factor × term` ; `total_due = loan_amount +
  total_interest` ; cible/tranche = `total_due / term` arrondie ; l'intérêt total est
  consommé en priorité sur les premières tranches, le principal comble le reste ; la
  dernière tranche absorbe le reliquat exact.
- `interest_method != 'flat'` (ligne 1346-1364) → dégressif (solde restant dû), **hors
  périmètre** de la décision taux uniforme, conservé à l'identique.

**L'algorithme interest-first est déjà mergé** (commits `b6b4e17` correction `ceiling` de
l'arrondi, `3c6cad1` chantier Avis CA/CDAG). `_build_installment_commands` est explicitement
le **point de convergence unique** de tous les chemins de génération. Il n'y a **pas** de
seconde implémentation linéaire en cours en parallèle — ne pas confondre avec un ancien
chantier : le code actuel est la version interest-first définitive.

---

## 4. Persistance : un `write()` explicite est-il nécessaire ?

**Non.** `action_generate_schedule()` fait déjà l'écriture persistante.

### Chaîne du problème (rappelée)

1. `installment_ids` est `<field name="installment_ids" readonly="1"/>` **inconditionnel**
   dans `views/microfinance_loan_views.xml` (cf. `docs_dev/echeancier_obsolete_readonly/`).
2. Un champ `readonly` modifié par un onchange **n'est jamais renvoyé au serveur** à la
   sauvegarde → les deux onchange du §1 ne persistent **jamais** seuls.
3. La persistance vient déjà de l'**override `write()`** (ligne 375-397) : si
   `_SCHEDULE_TRIGGER_FIELDS & set(vals)` — soit
   `{'loan_amount', 'term', 'repayment_frequency_id', 'interest_rate', 'installment_amount'}`
   (ligne 316-318) — **et** `loan.state in _EDITABLE_SCHEDULE_STATES and
   repayment_frequency_id and loan_amount and term`, alors `write()` rappelle
   `action_generate_schedule()`. Le test shell de `docs_dev/retrait_bouton_generer_echeancier/`
   (§3, tests A/B, rollback) confirme le `DELETE + INSERT` réellement émis.

### Pour le bouton du Lot 1

Un bouton `type="object"` qui appelle `action_generate_schedule()` (ou un mince wrapper qui
l'appelle) s'exécute dans une **transaction serveur normale, hors cycle onchange** :
l'affectation `loan.installment_ids = [(5, 0, 0)] + …` y est persistée immédiatement.

- **Pas besoin** de `write()` explicite supplémentaire.
- **Pas besoin** d'un `unlink()` préalable : la commande `(5, 0, 0)` en tête de liste vide
  déjà l'o2m avant recréation (choisie plutôt que `installment_ids.unlink()` pour passer
  par la même API que les onchange — commentaire ligne 1376-1379).
- **Pas besoin** de gérer l'état : la garde `state in _EDITABLE_SCHEDULE_STATES` de
  `action_generate_schedule` suffit (voir §5 pour la nuance `loan_amount`/`term`).

### Pourquoi IS/003362 est vide (cause racine)

C'est la **limite connue et assumée** documentée dans
`docs_dev/retrait_bouton_generer_echeancier/STATUS.md` :

> La création seule d'un crédit (`create()` / premier `Form.save()`) ne génère pas
> l'échéancier : le hook est sur `write()`, et `installment_ids` (readonly) n'est pas
> transmis à la création.

IS/003362 a été créé puis approuvé **sans qu'aucun champ de `_SCHEDULE_TRIGGER_FIELDS` ne
soit ré-écrit via `write()`** entre-temps, et sans passer par le flux Avis
(`_propagate_avis_to_loan()`) ni par `action_disburse()`. Résultat : aucun des chemins de
persistance ne s'est déclenché. Le bouton manuel du Lot 1 est **précisément le remède
prévu** à ce trou (génération à la demande, sans avoir à « faire semblant » de modifier un
champ source).

---

## 5. Gardes existantes / risques d'écrasement et de doublon

| Aspect | Constat |
|---|---|
| État du dossier | `action_generate_schedule` lève `UserError` si `state not in _EDITABLE_SCHEDULE_STATES`. Une fois `active` (paiements possibles), génération **impossible** → pas de risque de détruire un échéancier partiellement payé. |
| Périodicité manquante | `action_generate_schedule` lève `UserError` si `not repayment_frequency_id`. |
| **`loan_amount` / `term` manquants** | ⚠️ `action_generate_schedule` **ne les garde pas** (seul son appelant `write()` le fait, ligne 394-395). `_build_installment_commands` retourne alors `[]` → `installment_ids = [(5, 0, 0)] + []` **vide l'échéancier sans le recréer**. Un bouton qui appelle la méthode directement sur un brouillon incomplet effacerait donc un échéancier existant. → **Le bouton du Lot 1 doit reproduire la garde de `write()`** (`loan_amount and term and repayment_frequency_id`) avant l'appel, ou être masqué dans ce cas. |
| Écrasement d'un échéancier existant | **Systématique et voulu** : `[(5, 0, 0)] + …` vide puis recrée à chaque appel. Aucun garde « un échéancier existe déjà ». Sur un dossier `approved` avec ajustements manuels, ceux-ci seraient perdus — acceptable tant que `approved` est considéré « encore modifiable » (cohérent avec `_EDITABLE_SCHEDULE_STATES` et le flux Avis qui régénère déjà). |
| Doublons si clic multiple | **Aucun risque** : `(5, 0, 0)` purge d'abord. Deux clics successifs (champs sources inchangés) produisent le même échéancier. Seule réserve : `raise_on_negative_reliquat=True` peut lever `ValidationError` sur un paramétrage limite (beaucoup d'échéances / petit montant / arrondi `ceiling`) — comportement identique à l'existant. |
| Interaction avec `write()` | Le bouton et l'override `write()` appellent la **même** méthode socle : pas de divergence de calcul, pas de double génération (le bouton n'écrit pas de champ de `_SCHEDULE_TRIGGER_FIELDS`). |

---

## 6. Mécanisme équivalent existant à réutiliser

**Oui — `action_generate_schedule()` est exactement la brique à réutiliser.** Ne rien
dupliquer.

Historique à connaître :

- Un **ancien bouton « Générer échéancier »** existait, câblé via
  `action_open_generate_schedule_wizard()` → wizard `microfinance.loan.schedule.rounding.wizard`
  (`action_confirm()`) → `action_generate_schedule(rounding_mode=…)`. Le wizard servait
  uniquement à exposer le choix `last_installment` / `distributed`.
- Ce bouton **+ le wizard ont été retirés** par le lot
  `docs_dev/retrait_bouton_generer_echeancier/` (Lot 1, **non commité**, visible dans
  `git status` : `D wizard/microfinance_loan_schedule_rounding_wizard.py`,
  `D …_views.xml`, suppression de `action_open_generate_schedule_wizard()`). Motif :
  « onchange + `write()` couvre la persistance ». La décision Micka de ce lot était
  explicitement de **conserver `action_generate_schedule` / `_build_installment_commands` /
  `_compute_installment_targets` intacts** (« garde le mode arrondi et mode calculé déjà
  géré »).
- Le Lot 1 du présent chantier revient donc à **ré-ajouter un bouton — mais sans wizard**
  (toujours `rounding_mode='last_installment'`, aucun choix exposé), pour couvrir le trou
  fonctionnel resté ouvert (§4 : dossier créé/approuvé sans ré-écriture d'un champ source).
  À signaler à Micka : léger aller-retour avec le lot précédent, mais périmètre différent
  (remède manuel au trou « 1ʳᵉ génération », pas retour du wizard d'arrondi).

Aucun autre mécanisme (cron, action serveur, autre wizard) n'appelle la génération.

---

## 7. Recommandation concrète pour le Lot 1

### 7.1 Emplacement

`microfinance_loan_management/views/microfinance_loan_views.xml`, dans le `<header>`, à
côté de `action_print_contrat_to_chatter` (« Imprimer le contrat »), après elle.

### 7.2 Méthode appelée — wrapper dédié recommandé (ne pas toucher au socle)

Ajouter dans `microfinance_loan.py` un mince wrapper plutôt que câbler le bouton
directement sur `action_generate_schedule` :

```python
def action_generate_schedule_button(self):
    """Point d'entrée UI (bouton en-tête) de la génération manuelle d'échéancier.
    Reproduit la garde de write()/_SCHEDULE_TRIGGER_FIELDS (loan_amount/term/
    repayment_frequency_id présents) — action_generate_schedule() ne la porte pas et
    viderait l'échéancier sur un dossier incomplet — puis délègue au socle inchangé."""
    self.ensure_one()
    if not (self.loan_amount and self.term and self.repayment_frequency_id):
        raise UserError(_(
            "Renseignez le montant, le nombre d'échéances et la périodicité de "
            "remboursement avant de générer l'échéancier."))
    self.action_generate_schedule()  # rounding_mode='last_installment'
    self.message_post(body=_("Échéancier généré manuellement (%d échéances).")
                      % len(self.installment_ids))
    return {
        'type': 'ir.actions.client', 'tag': 'display_notification',
        'params': {'title': _('Échéancier'),
                   'message': _("L'échéancier a été (re)généré."),
                   'type': 'success', 'sticky': False},
    }
```

Justification : garde `loan_amount`/`term` (§5), message chatter cohérent avec
« Contrat de crédit généré. » / « Calendrier de remboursement généré. », notification sans
rechargement complet du formulaire. `action_generate_schedule` et `_build_installment_commands`
restent **strictement inchangés**.

- **Action serveur (`ir.actions.server`) : inutile.** Un bouton `type="object"` sur une
  méthode de modèle suffit (mêmes conventions que `action_print_contrat_to_chatter`,
  `action_disburse`, etc.). Pas d'entrée `ir.model.access.csv` à ajouter (même modèle).

### 7.3 `fa_icon`

`fa-calendar-plus-o` (sémantique « créer l'échéancier »). Alternatives cohérentes avec la
barre existante : `fa-list-ol`, `fa-refresh`. Ne **pas** réutiliser `fa-calendar` (déjà
pris par le stat button « Échéances »). Pas de classe `btn-cefor-print` (réservée aux
impressions) — laisser le style bouton par défaut.

### 7.4 Conditions d'affichage (`invisible`)

Odoo 17 : attribut `invisible` avec expression (pas de `states`/`attrs`).

Option **A — recommandée** (bouton = remède au trou, visible seulement si l'échéancier
manque) :

```xml
<button name="action_generate_schedule_button" type="object"
        groups="microfinance_loan_management.group_microfinance_user"
        invisible="state not in ('draft','enquete','avis_ca','avis_cdag','approved')
                   or installment_count != 0
                   or not loan_amount or not term or not repayment_frequency_id">
    <i class="fa fa-calendar-plus-o"/> Générer l'échéancier
</button>
```

→ n'apparaît que sur un dossier modifiable, données de calcul complètes, **et échéancier
encore vide**. Le rafraîchissement d'un échéancier obsolète reste couvert par le chemin
onchange + `write()` existant ; limiter le bouton au cas `installment_count == 0` évite
toute régénération accidentelle et colle exactement au bug IS/003362.

Option **B** (si Micka veut aussi un « recalcul forcé » manuel) : retirer la clause
`installment_count != 0`. À trancher par Micka — l'énoncé du Lot 0 penche vers B
(« déclencher manuellement exactement le même calcul »), mais A est plus sûr.

`installment_count` est déjà un champ calculé exposé (ligne 666, utilisé par le stat button
et par `action_print_repayment_schedule`) — réutilisable tel quel dans l'expression.

### 7.5 Groupe

`groups="microfinance_loan_management.group_microfinance_user"` (socle impliqué par manager
et gestionnaire) — même choix que « Imprimer le contrat ».

### 7.6 Tests Lot 1 (rappel, hors périmètre ici)

- Dossier `approved` échéancier vide (reproduction IS/003362) → clic → 24 lignes persistées
  (vérif SQL hors cache ORM).
- Double clic → toujours 24 lignes, pas de doublon.
- Dossier `active` → bouton absent / `UserError` si forcé par API.
- Dossier `draft` sans `term` → bouton absent (option A) ou `UserError` explicite du
  wrapper (option B).
- Non-régression : le chemin onchange + `write()` (`_SCHEDULE_TRIGGER_FIELDS`) continue de
  générer/persister sans le bouton.

---

## 8. Synthèse

| Question du Lot 0 | Réponse |
|---|---|
| Méthodes onchange (`term`, `installment_amount`) | `_onchange_loan_amount_recompute_installment` (1009), `_onchange_installment_amount_recompute_terms` (1039), `microfinance_loan.py`. |
| Méthode centrale | `_build_installment_commands(rounding_mode='last_installment', raise_on_negative_reliquat=False)` (1243, calcul pur, retourne des commandes o2m) + `action_generate_schedule(rounding_mode='last_installment')` (1367, wrapper qui **persiste** via `installment_ids = [(5,0,0)] + …`). |
| Algorithme | **interest-first** déjà mergé (`interest_method == 'flat'`), point de convergence unique. Pas de version linéaire concurrente. |
| `write()` explicite nécessaire ? | **Non.** Un bouton `type="object"` → `action_generate_schedule()` persiste (hors cycle onchange). Pas d'`unlink()` préalable (commande `(5,0,0)`). |
| Gardes | `state in _EDITABLE_SCHEDULE_STATES` + `repayment_frequency_id` (dans `action_generate_schedule`). ⚠️ `loan_amount`/`term` **non gardés** par le socle → le bouton doit les vérifier. Écrasement systématique voulu, pas de doublon possible. |
| Réutilisation | `action_generate_schedule()` — brique de l'ancien bouton retiré (`docs_dev/retrait_bouton_generer_echeancier/`). Lot 1 = ré-ajout d'un bouton **sans wizard**. |
