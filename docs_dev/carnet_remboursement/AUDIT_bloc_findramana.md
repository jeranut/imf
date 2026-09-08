# LOT 0 — Audit : Dynamisation du bloc "MOMBAMOMBA NY FAMPISAMBORAM-BOLA"

Audit en lecture seule. Aucune modification de code, de vue ou de données.

## 1. Extrait XML actuel

`microfinance_loan_management/report/report_carnet_remboursement.xml:156-169` :

```xml
<div class="carnet-box">
    <div class="carnet-box-title">MOMBAMOMBA NY FAMPISAMBORAM-BOLA</div>
    <div class="carnet-row"><u>Datin'ny findramana</u> : <strong>31/07/26</strong> &#160;&#160; Produit : <strong>Ps Rural &gt; 500 000</strong></div>
    <div class="carnet-row"><u>Mpikarakara</u> : <strong>Saraha</strong></div>
    <div class="carnet-row"><u>Findramana faha</u> : <strong>4</strong> &#160;&#160; <u>Fifanarahana n°</u> <strong>TS/01437</strong></div>
    <div class="carnet-row"><u>Renivola</u> : <strong>1 000 000</strong></div>
    <div class="carnet-row"><u>Zana-bola</u> : <strong>330 000</strong></div>
    <div class="carnet-row"><u>Totalin'ny renivola sy zana-bola</u> (1) : <strong>1 330 000</strong></div>
    <div class="carnet-row"><u>Famerenanana sy fotoam-pandoavana</u> : <strong>121 000 Ar / isam-bolana farafaha-keliny</strong></div>
    <div class="carnet-row"><u>Fotoana farany hamerenana ny renivola sy zanabola</u> : <strong>30/06/2027</strong></div>
    <div class="carnet-row"><u>Tahiry</u> (2) : <strong>200 000</strong></div>
    <div class="carnet-row"><u>Totalin'ny vola aloa</u> (1)+(2) : <strong>1 530 000</strong></div>
    <div class="carnet-row"><u>Fe-potoana fandrotsahana ny tahiry</u> : <span class="carnet-highlight"><strong>18/08/2027</strong></span></div>
    <div class="carnet-row"><u>Faharetan'ny findramam-bola</u> : <strong>384 andro</strong> &#160;&#160; Agent BL : <strong>Man</strong></div>
</div>
```

Confirmé : **tout est statique** (aucun `t-field`/`t-esc`/`t-out`), comme pour le bloc audité
précédemment.

**Important — le mapping fourni par Micka ne couvre que 9 des 12 lignes de ce bloc.** Les
lignes suivantes restent hors périmètre de ce lot (à traiter séparément) :
`Findramana faha` (n° de crédit séquentiel du client, "4" en dur), `Tahiry (2)`
("200 000" en dur), `Totalin'ny vola aloa (1)+(2)` ("1 530 000" en dur), `Fe-potoana
fandrotsahana ny tahiry` ("18/08/2027" en dur, surligné), `Faharetan'ny findramam-bola`
("384 andro" en dur) et `Agent BL` ("Man" en dur). **Ne pas les toucher au Lot 1** tant que
Micka ne fournit pas leur mapping — à signaler explicitement pour éviter toute confusion
sur le périmètre.

## 2. Tableau champ demandé → champ réel confirmé

| Libellé | Champ fourni par Micka | Champ réel confirmé | Écart |
|---|---|---|---|
| Datin'ny findramana | `microfinance.loan.disbursment_date` | **`disbursement_date`** (`fields.Date`, string "Date de décaissement") | Coquille : "disbursment" → "disbursement" |
| Produit | `microfinance.loan.product.name` | `product_id` est un Many2one vers **`microfinance.loan.product`** (pas `microfinance.loan.product` employé comme chemin direct) ; champ d'affichage = **`name`** (`Char`, "Nom") → chemin QWeb : `o.product_id.name` | Aucun écart de fond, juste préciser le chemin relationnel exact |
| Mpikarakara | `microfinance.loan.officer_id` | **`officer_id`** confirmé (`Many2one('res.users')`, string **"Agent crédit"**) | Aucun écart — voir point 4 pour la confirmation sémantique |
| Fifanarahana n° | `microfinance.loan.name` | **`name`** confirmé (`Char`, string "Référence") — déjà utilisé en dur comme "TS/01437" dans le gabarit actuel, doit devenir `o.name` | Aucun écart |
| Renivola | `microfinance.loan.principal_total` | **`principal_total`** confirmé (`Monetary`, compute `_compute_totals`, stocké, string "Total capital") | Aucun écart |
| Zana-bola | `microfinance.loan.interest_total` | **`interest_total`** confirmé (`Monetary`, compute `_compute_totals`, stocké, string "Total intérêts") | Aucun écart |
| Totalin'ny renivola sy zana-bola (1) | `principal_total + interest_total` | **Aucun champ combiné n'existe** sur le modèle — voir point 8 | Calcul à faire dans le template |
| Famerenanana sy fotoam-pandoavana | `microfinance.loan.installement_amount` + suffixe | **`installment_amount`** (`Monetary`, string "Montant échéance") | Coquille : "installement" → "installment" (un seul "e") |
| Fotoana farany hamerenana ny renivola sy zanabola | date de la dernière ligne de l'échéancier | **Méthode déjà existante : `o.get_last_installment_date()`**, déjà utilisée dans `report_contrat_credit.xml` — voir point 6 | Aucun champ à créer, méthode prête à réutiliser telle quelle |

## 3. "Produit" — modèle et champ de relation

`models/microfinance_loan.py:27` :

```python
product_id = fields.Many2one('microfinance.loan.product', string='Produit', required=True, tracking=True)
```

`models/microfinance_loan_product.py:36` :

```python
name = fields.Char(string='Nom', required=True, tracking=True)
```

Chemin QWeb confirmé : `o.product_id.name` (`t-field="o.product_id.name"` ou `t-esc`).

## 4. "Mpikarakara" — confirmation sémantique

Quatre champs de type "intervenant" existent sur `microfinance.loan` (tous `Many2one`
vers `res.users`) :

```python
officer_id           = fields.Many2one('res.users', string='Agent crédit', default=...)
manager_id           = fields.Many2one('res.users', string='Manager')
finance_user_id      = fields.Many2one('res.users', string='Utilisateur finance')
collection_agent_id  = fields.Many2one('res.users', string='Agent recouvrement')
```

"Mpikarakara" (littéralement "celui qui s'occupe de/traite le dossier") correspond
sémantiquement à **`officer_id`** ("Agent crédit" — l'agent instructeur qui a monté le
dossier), **pas** à `collection_agent_id` ("Agent recouvrement", qui n'intervient qu'après
défaut de paiement) ni à `manager_id`/`finance_user_id` (validation/décaissement, pas
instruction). Le mapping fourni par Micka (`officer_id`) est confirmé correct.

## 5. Valeurs de `repayment_frequency_id` — modèle et codes réels

**Écart de structure important à signaler** : `repayment_frequency_id` n'est **pas** un champ
`Selection` avec des clés `monthly`/`weekly`/`daily` directement sur `microfinance.loan` — 
c'est un **Many2one vers `microfinance.repayment.frequency`**, un modèle de données
paramétrable (menu Configuration), avec un champ `code` (`Char`) servant d'identifiant
technique stable. Valeurs actuellement seedées (`data/repayment_frequency_data.xml`,
`noupdate="1"`) :

| `code` | `name` (affiché) | Pertinent pour ce lot |
|---|---|---|
| `daily` | Journalier | ✅ (Famerenanana : "isan'andro") |
| `weekly` | Hebdomadaire | ✅ (Famerenanana : "isankerinandro") |
| `biweekly` | Quinzaine (15 jours) | ❌ non couvert par le mapping fourni |
| `four_weekly` | Toutes les 4 semaines | ❌ non couvert |
| `monthly` | Mensuel | ✅ (Famerenanana : "isam-bolana") |
| `bimonthly` | Bimestriel (2 mois) | ❌ non couvert |
| `quarterly` | Trimestriel | ❌ non couvert |
| `four_monthly` | Tous les 4 mois | ❌ non couvert |
| `semiannual` | Semestriel | ❌ non couvert |
| `annual` | Annuel | ❌ non couvert |

**Les codes `daily`/`weekly`/`monthly` fournis par Micka sont confirmés exacts** (aucune
coquille). En revanche, **7 des 10 périodicités configurables n'ont aucun texte de suffixe
prévu par le mapping fourni** — à faire trancher par Micka avant le Lot 1 : afficher un
suffixe générique (ex. juste le `name` de la périodicité) pour ces 7 cas, ou les considérer
comme non utilisés en pratique pour ce produit de carnet (à confirmer, pas à supposer).

**Texte du suffixe "Journalier" incomplet dans le prompt** : la formulation fournie
("isan'andro ... farafaha-keliny") contient une ellipsis explicite — **à faire confirmer mot
à mot par Micka avant implémentation**, même précaution que pour le texte d'attestation
malgache d'un lot précédent (aucune source tierce dans le dépôt pour deviner le texte
manquant).

## 6. Dernière date d'échéance — méthode déjà existante, prête à réutiliser

`models/microfinance_loan.py:2219-2222` :

```python
def get_last_installment_date(self):
    """Date (JJ/MM/AAAA) de la dernière échéance de l'échéancier."""
    self.ensure_one()
    return self._format_contrat_date(self._contrat_sorted_installments()[-1:].due_date)
```

- `_format_contrat_date()` (ligne 2164) formate en `%d/%m/%Y`, chaîne vide si la date est
  absente — correspond exactement au format déjà visible dans le gabarit en dur
  ("30/06/2027").
- `_contrat_sorted_installments()` trie les échéances par date puis séquence (inclut la
  ligne de délai de grâce éventuelle).
- **Déjà utilisée telle quelle** dans `report_contrat_credit.xml:207` :
  `<b t-esc="o.get_last_installment_date()"/>`.

**Aucun champ à créer, aucune logique à dupliquer** : réutiliser
`t-esc="o.get_last_installment_date()"` directement dans le carnet, comme dans le contrat.

## 7. Convention de formatage monétaire à réutiliser

Deux conventions coexistent dans le module, pour deux styles de document différents :

1. **`report_contrat_credit.xml`** (document narratif, comme l'encart du carnet) : formatage
   Python manuel, sans widget Odoo :
   ```python
   '{:,.0f}'.format(o.loan_amount).replace(',', ' ')
   ```
   suivi du littéral `" Ar"` dans le texte du template. Pas de décimales, séparateur de
   milliers = espace. **Correspond exactement** au format déjà visible dans les valeurs en
   dur du carnet ("1 000 000", "330 000", "121 000" — aucune décimale, espaces).
2. **`microfinance_loan_repayment_schedule_report.xml`** / `microfinance_loan_disbursement_
   receipt.xml` (tableaux d'échéancier/reçu) : `t-field` standard avec
   `t-options="{'widget': 'monetary', 'display_currency': o.currency_id}"`.

**Recommandation** : réutiliser la convention n°1 (`'{:,.0f}'.format(...).replace(',', ' ')`
+ `" Ar"` littéral) pour Renivola/Zana-bola/Totalin'ny.../Famerenanana, car c'est celle déjà
utilisée par l'encart identité du carnet lui-même (`report_contrat_credit.xml`, dont
plusieurs autres champs de ce même encart sont déjà repris) et elle correspond exactement au
rendu actuel en dur (pas de décimales, espace comme séparateur) — le widget `monetary`
produirait un format visuellement différent (décimales possibles, symbole monétaire géré
par Odoo selon la devise) qui casserait la cohérence visuelle actuelle du carnet.

## 8. "Totalin'ny renivola sy zana-bola (1)" — pas de champ combiné existant

Recherche confirmée : aucun champ stocké ou calculé ne combine `principal_total` +
`interest_total` sur `microfinance.loan` (le champ `balance_total` existant est le **solde
restant dû**, pas la somme principal+intérêt initiale — à ne pas confondre). **Calcul à
faire directement dans le template** :

```xml
<t t-esc="'{:,.0f}'.format(o.principal_total + o.interest_total).replace(',', ' ')"/>
```

## Synthèse des écarts à corriger avant le Lot 1

1. `disbursment_date` → **`disbursement_date`** (coquille confirmée).
2. `installement_amount` → **`installment_amount`** (coquille confirmée).
3. `microfinance.loan.account.name` n'est PAS le bon chemin pour "Produit" (ça, c'était le
   sujet de l'audit précédent sur "Nomerao" — sans rapport avec ce bloc) : ici c'est bien
   `o.product_id.name` sur `microfinance.loan.product`, confirmé correct dans le mapping
   fourni pour ce lot.
4. `officer_id` confirmé être le bon champ pour "Mpikarakara" (agent instructeur, pas agent
   de recouvrement).
5. `repayment_frequency_id` est un Many2one vers un modèle de données, pas un Selection —
   les codes `daily`/`weekly`/`monthly` sont corrects, mais **7 autres périodicités
   configurables n'ont pas de suffixe prévu** (point à trancher).
6. Texte du suffixe "Journalier" **incomplet** dans le prompt (ellipsis) — à faire
   confirmer mot à mot.
7. `get_last_installment_date()` existe déjà et est déjà utilisée dans
   `report_contrat_credit.xml` — à réutiliser telle quelle, aucun nouveau code serveur.
8. Aucun champ combiné principal+intérêt — calcul Python inline dans le template.
9. Convention de formatage monétaire à réutiliser : `'{:,.0f}'.format(x).replace(',', ' ')`
   + `" Ar"` littéral (cohérent avec le reste de l'encart, pas le widget `monetary`).
10. **6 lignes du même bloc restent hors périmètre** de ce lot (`Findramana faha`, `Tahiry
    (2)`, `Totalin'ny vola aloa (1)+(2)`, `Fe-potoana fandrotsahana ny tahiry`,
    `Faharetan'ny findramam-bola`, `Agent BL`) — à ne pas toucher tant qu'un mapping n'est
    pas fourni pour elles.

Aucune modification de code effectuée dans ce lot.
