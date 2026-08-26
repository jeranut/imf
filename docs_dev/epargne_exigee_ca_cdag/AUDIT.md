# Audit (Lot 0) — Champ "Épargne exigée" (CA/CDAG) : affichage conditionnel + lecture seule

Audit en lecture seule. **Aucune modification de code, de vue ou de donnée.** Toutes les valeurs
ci-dessous ont été vérifiées directement sur le dépôt (`microfinance_loan_management/models/
microfinance_loan.py`, `microfinance_loan_application.py`, `microfinance_savings_management/
models/microfinance_loan_extension.py`, `microfinance_loan_product_extension.py`, et les vues
correspondantes).

## Résumé exécutif

**Le "Ar 0,00" observé n'est pas un bug de calcul : `avis_ca_epargne_exigee`/`avis_cdag_epargne_
exigee` (les champs réellement affichés dans l'onglet "Avis CA / CDAG") sont des champs de saisie
libre, sans aucune formule, jamais reliés à la configuration produit** - ils valent 0 tant que
personne n'a tapé de valeur, ce qui est le cas sur tous les dossiers existants. **Un mécanisme de
calcul correct et déjà en production existe par ailleurs**, sur le même modèle `microfinance.
loan`, mais ailleurs dans le formulaire (groupe "Résumé financier", pas l'onglet Avis CA/CDAG) :
`guarantee_savings_required` (calculé depuis `product_id.guarantee_savings_percent × loan_
amount`), déjà `invisible`/`readonly` conditionnellement, exactement le pattern demandé par
Micka - **une référence d'implémentation directement réutilisable**, pas à inventer. Vérifié sur
les deux seuls dossiers réels de SEFOR (produit PRET RURAL, `guarantee_savings_percent=5%`) :
`guarantee_savings_required` y affiche correctement **25 000 Ar**, pendant que `avis_ca_epargne_
exigee`/`avis_cdag_epargne_exigee`, sur ce même crédit, restent à Ar 0,00 - la confusion
rapportée par Micka est donc bien réelle et actuelle, pas un cas limite hypothétique.

Sur `microfinance.loan.application`, les champs équivalents (`ca_required_savings`/`cdag_
required_savings`) **existent déjà et sont déjà en lecture seule au niveau Python** (`related`
avec `readonly=True` explicite) - la demande n°2 (lecture seule systématique) est donc déjà
satisfaite sur ce modèle, sans rien à faire. Seul l'affichage conditionnel y reste à ajouter.

---

## Section 1 — Configuration produit

**Champ confirmé : `guarantee_savings_percent`**, sur `microfinance.loan.product`
(`microfinance_savings_management/models/microfinance_loan_product_extension.py:47-53`) :

```python
guarantee_savings_percent = fields.Float(
    string='Épargne garantie exigée (%)', default=0.0,
    help="Pourcentage du montant du crédit demandé qui doit être disponible sur le compte "
         "d'épargne garantie du client ... Si à 0, aucune vérification n'est effectuée. ...",
)
guarantee_savings_product_id = fields.Many2one(
    'microfinance.savings.product', string="Produit d'épargne garantie de crédit",
    help="... Requis si un pourcentage d'épargne garantie exigée est renseigné ci-dessus. ...",
)
```

- **Type** : `Float` (pourcentage, pas un `Boolean`), `default=0.0`. **"Pas d'exigence" =
  `0.0`** (falsy en Python, donc `if product.guarantee_savings_percent:` suffit comme condition
  "le produit a une épargne exigée configurée" - pas besoin d'un champ booléen séparé).
- Un `@api.constrains` (`_check_guarantee_savings_config`, même fichier) impose déjà
  `guarantee_savings_product_id` renseigné dès que `guarantee_savings_percent` est non nul -
  cohérence garantie à la source.
- **Correction préalable au périmètre** : contrairement à l'hypothèse de la demande, il
  **n'existe pas d'onglet "Épargne" dans `microfinance_loan_management` seul** (les 4 onglets
  réels du produit dans ce module sont "Calcul crédit", "Éligibilité", "Pénalités",
  "Comptabilité", confirmé par grep exhaustif des `<page string=...>`). L'onglet "Épargne" existe
  bien, mais est **ajouté par `microfinance_savings_management`** (vue héritée, `microfinance_
  loan_product_views_inherit.xml`) - n'existe donc que si ce second module est installé (il
  l'est dans cette instance SEFOR, confirmé par le manifeste). Sans incidence sur l'audit
  (le champ existe et est bien accessible), mais à savoir si jamais ce chantier est mené dans un
  contexte où seul `microfinance_loan_management` serait actif.

### Distinction demandée : "épargne garantie vérifiée" vs paramètre produit

**Confirmé, une seule notion calculée, pas deux notions distinctes à confondre.**
`guarantee_savings_verified` (`microfinance_loan_extension.py`) est un `Boolean` **entièrement
calculé** (`compute='_compute_guarantee_savings_verified'`, `@api.depends('guarantee_savings_
required', 'guarantee_savings_balance')` → `balance >= required`) - **ce n'est pas une case à
cocher manuelle malgré son apparence visuelle** (un `Boolean` s'affiche toujours comme une case à
cocher dans le client web Odoo, y compris en lecture seule - c'est très probablement ce qui a
donné l'impression d'une "vérification manuelle" sur la capture). Il n'existe aucun champ de
vérification manuelle séparé nulle part dans le module - la chaîne est entièrement automatique :
`product_id.guarantee_savings_percent` (config) → `guarantee_savings_required` (calculé,
`loan_amount × pourcentage`) → `guarantee_savings_balance` (calculé, solde réel du compte
épargne garantie du client) → `guarantee_savings_verified` (calculé, comparaison des deux).

---

## Section 2 — Champs "Épargne exigée" sur `microfinance.loan`

**Noms techniques confirmés** (`microfinance_loan_management/models/microfinance_loan.py:104,
123`) : `avis_ca_epargne_exigee` et `avis_cdag_epargne_exigee` - **pas** `epargne_exigee_ca`/
`epargne_exigee_cdag` comme supposé dans la demande.

```python
avis_ca_epargne_exigee = fields.Monetary(
    string='Épargne exigée (CA)',
    help="Saisie libre : aucune règle de calcul automatique existante à réutiliser pour ce "
         "champ n'a été trouvée dans le module (vérifié à l'audit) - ne participe pas au "
         "recalcul bidirectionnel montant/durée/échéance ci-dessous.")
avis_cdag_epargne_exigee = fields.Monetary(
    string='Épargne exigée (CDAG)',
    help="Saisie libre, mêmes règles que avis_ca_epargne_exigee ci-dessus.")
```

- **Type** : `Monetary` simple, `store` implicite (True, champ normal) - **ni `compute`, ni
  `related`, ni `@api.depends`, ni aucun `@api.onchange` ne les touche** (grep exhaustif des deux
  noms sur tout `microfinance_loan.py` : uniquement leur définition et leur présence en vue,
  confirmé par le `help` de leur propre code, écrit lors du chantier Avis CA/CDAG précédent).
- **`readonly` en vue actuel : aucun.** (`views/microfinance_loan_views.xml:165,171`, simples
  `<field name="avis_ca_epargne_exigee"/>` / `<field name="avis_cdag_epargne_exigee"/>`, sans
  attribut).

### Pourquoi "Ar 0,00" - confirmé, pas une hypothèse

**Ce sont des champs de saisie libre jamais préremplis par défaut** (contrairement à `avis_ca_
amount`/`avis_ca_term`, qui sont explicitement initialisés à `loan.loan_amount`/`loan.term` dans
`action_ca_review()`) : rien dans le code n'assigne jamais de valeur par défaut à `avis_ca_
epargne_exigee`/`avis_cdag_epargne_exigee`. `Monetary` sans valeur saisie vaut `0.0` par défaut
Odoo standard. **Sur les dossiers réels de SEFOR (IS/000289, IS/001076), ces deux champs valent effectivement
vide/0** (vérifié en base, `NULL` en colonne - lu comme `0.0` côté ORM) - cohérent avec "personne
n'a jamais tapé de valeur dedans", pas avec un bug de formule (il n'y a pas de formule à casser).

**Le produit réel de ces deux dossiers A pourtant une épargne exigée configurée - le "Ar 0,00" est
donc bien trompeur sur ce cas précis, pas une fausse alerte.** Vérifié en base : **les deux seuls
crédits de SEFOR utilisent PRET RURAL**, dont `guarantee_savings_percent = 5` (%) et
`guarantee_savings_product_id` renseigné. Le champ calculé correspondant, `guarantee_savings_
required` (section "Résumé financier", hors onglet Avis CA/CDAG), affiche bien la valeur
correcte sur ces deux dossiers : **25 000 Ar** (500 000 × 5 %, vérifié en base, champ stocké).
**Les deux autres produits (PRET SUCESSIVE RURAL, PRET FONCTIONNAIRE) sont à `0.0`** - le
comportement souhaité n°1 (masquer si pas configuré) les concernerait bien s'ils étaient
utilisés, mais ce n'est le cas d'aucun dossier existant aujourd'hui.

**Résumé du contraste, concret et vérifié sur les deux seuls dossiers réels de SEFOR** : le même
crédit affiche simultanément *"Épargne exigée (CA)" = Ar 0,00* dans l'onglet Avis CA/CDAG et
*"Épargne garantie requise" = Ar 25 000,00* dans le résumé financier - deux champs différents,
sur le même modèle, censés représenter la même notion métier, avec des valeurs radicalement
différentes parce qu'ils ne sont reliés par aucun mécanisme. C'est exactement la confusion
rapportée par Micka.

---

## Section 3 — Équivalent sur `microfinance.loan.application`

**Les champs existent déjà** (contrairement à l'hypothèse "création de champ" envisagée par la
demande si absents) : `ca_required_savings` et `cdag_required_savings`
(`microfinance_loan_application.py:712-713, 722-723`, bloc commenté "Bloc E — Avis CA / CDAG") :

```python
ca_required_savings = fields.Monetary(
    related='loan_id.avis_ca_epargne_exigee', string='Épargne exigée (CA)', readonly=True)
cdag_required_savings = fields.Monetary(
    related='loan_id.avis_cdag_epargne_exigee', string='Épargne exigée (CDAG)', readonly=True)
```

- **Type** : `related='loan_id.avis_ca_epargne_exigee'` / `'loan_id.avis_cdag_epargne_exigee'`,
  **`readonly=True` explicite dans la définition Python du champ** - pas un `readonly` de vue
  conditionnel, un readonly permanent posé au niveau du champ lui-même.
- **Conséquence directe pour la demande n°2 (lecture seule systématique sur les deux modèles)** :
  **déjà satisfaite sur `microfinance.loan.application`, sans aucune modification nécessaire.**
  Un champ `related` avec `readonly=True` ne peut être modifié par aucune vue ni aucun onchange -
  seule une écriture directe sur le champ source (`loan_id.avis_ca_epargne_exigee`, non protégé
  aujourd'hui) peut en changer la valeur, ce qui reflète le design voulu ("reprend
  automatiquement... à modifier sur le crédit, pas depuis ce dossier", cf. commentaire du bloc E
  ligne 678-684 : *"décision confirmée avec Micka : une seule source de vérité, pas de logique
  dupliquée ici"*).
- **`readonly`/`invisible` en vue actuel** (`views/microfinance_loan_application_views.xml:650,
  656`) : bare `<field name="ca_required_savings"/>` / `<field name="cdag_required_savings"/>`,
  aucun `invisible`, aucun `readonly` de vue (inutile, déjà couvert côté Python).

**Champ adjacent, hors périmètre de cette demande mais à ne pas confondre** : `required_savings`
(ligne 690, "Épargne exigée (demande)") est un champ **distinct**, saisie libre elle aussi, mais
sans rapport avec CA/CDAG - c'est l'épargne exigée de la demande initiale, avant tout avis, sans
équivalent sur `microfinance.loan` par conception ("*aucune notion d'épargne exigée pour la
demande initiale, avant tout avis CA/CDAG*", commentaire du champ lui-même). Non concerné par
cette demande, qui porte explicitement sur les sections Avis CA et Avis CDAG.

---

## Section 4 — État actuel des `readonly`/`invisible` en vue (récapitulatif)

| Champ | Modèle | `readonly` | `invisible` |
|---|---|---|---|
| `avis_ca_epargne_exigee` | `microfinance.loan` | **Aucun** | **Aucun** |
| `avis_cdag_epargne_exigee` | `microfinance.loan` | **Aucun** | **Aucun** |
| `ca_required_savings` | `microfinance.loan.application` | **Déjà verrouillé au niveau Python** (`readonly=True` sur le champ) | **Aucun** |
| `cdag_required_savings` | `microfinance.loan.application` | **Déjà verrouillé au niveau Python** | **Aucun** |

**Pour comparaison, pattern déjà en place et fonctionnel sur `microfinance.loan` pour le vrai
mécanisme calculé** (`microfinance_savings_management/views/microfinance_loan_views_inherit.
xml:20-22`, groupe "Résumé financier", hors onglet Avis CA/CDAG) :

```xml
<field name="guarantee_savings_required" invisible="not guarantee_savings_required" readonly="1"/>
<field name="guarantee_savings_balance" invisible="not guarantee_savings_required" readonly="1"/>
<field name="guarantee_savings_verified" invisible="not guarantee_savings_required" readonly="1"/>
```

C'est exactement le comportement demandé par Micka (masqué si pas d'exigence, toujours lecture
seule) - déjà en production sur ce même modèle, pour une valeur différente mais la même notion
métier. Référence directement réutilisable pour la conception du Lot 1, pas à réinventer.

---

## Proposition de condition d'affichage (`invisible="..."`)

**Point technique à connaître avant de chiffrer le Lot 1** : les conditions `invisible=`/
`readonly=` de vue Odoo 17 n'évaluent que des champs déjà présents sur l'enregistrement courant
de la vue - **pas de chemin en pointillé vers un champ d'un enregistrement lié** (confirmé par
grep exhaustif : aucune vue du module n'utilise `invisible="xxx.yyy"` pour une relation, seul
`context.get(...)` apparaît avec un point, ce qui est différent). Une condition du type
`invisible="not product_id.guarantee_savings_percent"` **ne fonctionnerait donc pas telle
quelle**.

- **Sur `microfinance.loan`** : pas de problème, un champ approprié existe déjà sur ce modèle -
  `guarantee_savings_required` (déjà calculé depuis `product_id.guarantee_savings_percent`).
  Proposition : `invisible="not guarantee_savings_required"` sur `avis_ca_epargne_exigee` et
  `avis_cdag_epargne_exigee`, à l'identique du pattern déjà utilisé ligne 20 ci-dessus - aucun
  nouveau champ à créer sur ce modèle.
- **Sur `microfinance.loan.application`** : aucun champ équivalent n'existe aujourd'hui pour
  servir de condition. Un nouveau champ relais serait nécessaire, ex. `guarantee_savings_
  required = fields.Monetary(related='loan_id.guarantee_savings_required', readonly=True)` (même
  pattern que `ca_required_savings` ci-dessus, juste une related vers le champ *calculé* du
  crédit plutôt que vers le champ de saisie libre) - **c'est une petite création de champ**, à
  signaler explicitement à Micka avant chiffrage (le point 3 de la demande envisageait une
  création de champ seulement si `ca_required_savings`/`cdag_required_savings` eux-mêmes
  n'existaient pas - ce n'est pas le cas, mais un champ relais supplémentaire reste nécessaire
  pour la seule condition d'affichage).

---

## Point à trancher avec Micka avant le Lot 1 (rappel de la consigne)

**Le calcul de la valeur elle-même n'est pas concerné par cette demande** (affichage + lecture
seule uniquement) - mais l'audit met en évidence, avec un exemple réel et actuel (pas
hypothétique, cf. section 2) que `avis_ca_epargne_exigee`/`avis_cdag_epargne_exigee` **n'ont, et
n'auront toujours, aucun rapport avec `guarantee_savings_required`** (le vrai calcul) une fois ce
Lot appliqué tel que demandé : les rendre lecture seule + conditionnellement visibles ne change
rien à leur valeur, qui restera 0/vide sur tout dossier où personne n'a jamais tapé de chiffre
dedans - il n'existe aujourd'hui aucun mécanisme pour les préremplir automatiquement
(contrairement à `avis_ca_amount`/`avis_ca_term`). **Appliqué tel quel sur IS/000289 et
IS/001076 aujourd'hui, ce Lot afficherait "Épargne exigée (CA)" en lecture seule, visible (le
produit a bien une exigence configurée), mais toujours à Ar 0,00** - un champ verrouillé qui
affiche silencieusement une valeur fausse est arguablement pire qu'un champ éditable à Ar 0,00
(l'utilisateur perd la possibilité de corriger lui-même l'incohérence qu'il voit). À signaler
explicitement à Micka avant de chiffrer le Lot 1 : soit c'est acceptable en l'état pour cette
itération (champ préparé pour un usage futur non encore branché, comme d'autres scaffolds déjà
rencontrés dans ce module), soit cela justifie une question complémentaire (faut-il, au minimum,
préremplir ces deux champs avec `guarantee_savings_required` au moment de `action_ca_review()`/
`action_cdag_review()`, sur le modèle de ce qui est déjà fait pour `avis_ca_amount`/`avis_ca_
term` ? - ce serait un changement de calcul, donc explicitement hors périmètre de ce Lot 0/1 sans
validation séparée, conformément à la consigne).

Stop après ce rapport, conformément à la consigne.
