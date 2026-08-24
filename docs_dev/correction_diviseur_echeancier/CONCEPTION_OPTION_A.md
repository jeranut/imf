# Conception Option A — auto-détection du diviseur par fréquence

Diagnostic en lecture seule. **Aucune écriture** effectuée sur `microfinance_loan_management`,
`microfinance_savings_management`, `rental_management` ni aucun module `packimmo_*` (ces deux
derniers ne sont de toute façon pas concernés par le sujet — mentionnés ici uniquement pour
confirmer explicitement que la règle de non-modification a été respectée).

**Remarque préalable** : le fichier `docs_dev/correction_diviseur_echeancier/DIAGNOSTIC_OPTIONS.md`
cité en introduction de la demande n'existe pas dans ce dépôt (recherché explicitement, absent).
Seul `AUDIT.md` (le rapport du Lot 0 précédent) est présent dans ce dossier. Cette conception
s'appuie donc uniquement sur `AUDIT.md` et sur le texte de la demande elle-même pour le rappel
des deux cas déjà confirmés — si `DIAGNOSTIC_OPTIONS.md` contient des éléments supplémentaires
(d'autres options envisagées, un raisonnement qui aurait mené au choix de l'Option A), je ne les
ai pas vus et ils ne sont pas repris ici.

---

## 1. Recherche élargie de cas papier — résultat : AUCUN troisième cas trouvé

### Base de données SEFOR (lecture seule)

```sql
SELECT l.id, l.name, p.name, l.loan_amount, l.term, l.interest_rate, f.name, l.state, count(i.id)
FROM microfinance_loan l
JOIN res_partner p ON p.id = l.partner_id
LEFT JOIN microfinance_repayment_frequency f ON f.id = l.repayment_frequency_id
LEFT JOIN microfinance_loan_installment i ON i.loan_id = l.id
GROUP BY l.id, p.name, f.name HAVING count(i.id) > 0;
```

**Résultat : un seul crédit dans toute la base avec un échéancier généré — IS/000289 lui-même**
(8 lignes, échéancier obsolète généré avant les derniers correctifs de ce chantier, cf. §5).
`SELECT count(*) FROM microfinance_loan` = **1** : IS/000289 est **l'unique crédit existant dans
SEFOR**, tous états confondus.

Recherche complémentaire, toutes négatives :
- `microfinance_loan.name ILIKE '%01913%'` → 0 résultat. **IS/01913 n'existe pas comme
  enregistrement dans cette instance Odoo.** C'est cohérent avec sa nature : un reçu LPF
  imprimé que Micka a comparé manuellement au calcul Odoo, jamais saisi comme crédit dans le
  système (le cas de référence historique de `test_interest_first_schedule.py` est câblé en dur
  à partir de ce document, pas dérivé d'un enregistrement).
- `ir_attachment` sur `microfinance.loan` / `microfinance.loan.application` → une seule pièce
  jointe dans toute la base : `Calendrier de remboursement - IS/000289.pdf`, générée par
  `action_print_repayment_schedule()` le 2026-08-18 — c'est-à-dire **un PDF produit par Odoo
  lui-même**, pas un document externe LPF. Le comparer à l'échéancier Odoo serait circulaire
  (Odoo comparé à Odoo).
- `res_partner` "BM" (id 235) → confirmé sans aucun crédit ni dossier lié (déjà établi dans
  `AUDIT.md`, revérifié ici : toujours 0 résultat).
- Autre base sur le même serveur Postgres portant le modèle `microfinance.loan` : aucune
  (`CEFOR` ne l'a pas installé — `relation "microfinance_loan" does not exist`). Les autres
  bases visibles sur ce serveur (EAT, PACKIMMO, CUF, etc.) sont des projets sans rapport avec
  la microfinance.

### Système de fichiers

- Aucun fichier `*01913*` ni `*000289*` pertinent trouvé sur le poste (recherche `find /`
  élargie — seuls des faux positifs sans rapport : horodatages Windows, hash de cache, etc.).
- Les PDF présents dans `/home/bozelenina/` sont tous liés à d'autres activités (PACKIMMO,
  CUF, immobilier) — aucun échéancier de crédit microfinance parmi eux.
- `docs_dev/` du dépôt : aucun autre dossier ni document mentionnant un échéancier papier
  comparé, en dehors de `ecarts_lpf_remboursement.md` (qui ne cite que IS/01913 et IS/000289,
  déjà connus) et de l'`AUDIT.md` du Lot 0.

### Google Drive — non vérifié, à dessein

La demande mentionne "PDF, Drive, ou trace physique confirmée par Micka" comme sources
possibles. Je n'ai pas de pointeur (dossier, nom de fichier, lien) vers un emplacement Drive
précis où chercher, et fouiller un compte Drive personnel/professionnel à l'aveugle pour des
documents financiers sans indication explicite de leur emplacement n'est pas une recherche
raisonnable à mener de ma propre initiative. **Si Micka confirme l'existence d'échéanciers LPF
scannés sur un Drive accessible, indiquer le dossier/lien précis et je les examinerai.**

### Conclusion de la recherche élargie

**Il n'existe aujourd'hui aucun troisième cas exploitable**, ni en base, ni dans le dépôt, ni sur
le système de fichiers accessible. Ce n'est pas une ambiguïté d'interprétation — c'est une
**absence totale de donnée**. IS/01913 et IS/000289 restent les deux seuls points de données
disponibles, exactement comme au moment du Lot 0.

---

## 2. Hypothèse fréquence : ni confirmée, ni infirmée — **statu quo, faute de donnée**

Aucun nouveau cas n'ayant été trouvé, l'hypothèse reste dans l'état exact décrit par la demande
elle-même : deux cas, deux fréquences différentes (mensuel/`/n` et hebdomadaire/`/(n-1)`), ce qui
ne suffit structurellement pas à démontrer que la fréquence est *le* facteur déterminant (une
corrélation à deux points ne prouve pas une causalité, et encore moins la forme exacte de la
règle — seuil net entre deux catégories ? dépendance continue à `n` ? à `period_kind` ? aux deux
combinés ?).

**Conformément à la règle explicite de la demande** ("Si l'hypothèse est infirmée ou reste
ambiguë sur le troisième cas, arrêter le diagnostic et documenter précisément le nouveau
désaccord au lieu de forcer une règle non prouvée") : **le diagnostic s'arrête ici sur le fond**.
Je ne conçois pas la logique d'auto-détection (§3 de l'objectif, point 2 du livrable) — la
condition qui l'autoriserait n'est pas remplie. Les sections suivantes (§3 à §5 ci-dessous)
répondent aux points de préparation demandés qui restent utiles indépendamment de l'issue
(cartographie du code, fiabilité de la source fréquence, impact rétroactif), sans pour autant
constituer un début d'implémentation de la règle elle-même.

### Nouveau point de blocage, précisément formulé

Le blocage n'est plus analytique (« les deux cas se contredisent, il faut comprendre pourquoi »
— c'était l'état à la fin du Lot 0) : il est maintenant **un blocage d'accès à la donnée**. Il
n'y a littéralement rien de plus à analyser avec ce qui est disponible dans le dépôt, la base
SEFOR ou le système de fichiers. Pour débloquer, il faut l'une de ces deux choses :
1. **Un troisième échéancier papier LPF réellement consultable** (physique, scanné, ou pointé
   précisément dans un Drive) — idéalement sur une fréquence *ni* mensuelle *ni* hebdomadaire
   (quinzaine, quotidien, bimestriel...) pour élargir la couverture, plutôt qu'un troisième cas
   hebdomadaire qui ne ferait que renforcer un seul des deux points déjà connus sans éclairer la
   frontière entre les deux régimes.
2. **Une réponse directe de Micka** (ou de la documentation LPF elle-même, si accessible) sur le
   principe exact que LPF applique — la logique métier plutôt qu'une inférence statistique sur
   deux échantillons.

---

## 3. La fréquence est-elle déjà un champ fiable et structuré ? — Oui, sans ambiguïté

`microfinance.loan.repayment_frequency_id` (Many2one vers `microfinance.repayment.frequency`)
est déjà la source unique de vérité utilisée par tout le moteur de génération d'échéancier
(`_period_delta()`, `_period_interest_factor()`, chantier d'alignement LPF du 2026-08-18). Le
modèle expose deux champs structurés directement exploitables, sans aucune déduction requise :

- `period_kind` : Selection `'days'` / `'months'` — déjà la distinction binaire exacte
  "infra-mensuel / mensuel-et-au-delà" évoquée dans la demande.
- `period_value` et `periods_per_year` : valeurs numériques précises par fréquence (ex. weekly :
  `period_kind='days'`, `period_value=7`, `periods_per_year=52`).

**Il n'y a donc aucun besoin de déduire la fréquence à partir des `due_date` successifs des
lignes générées.** Ce serait une régression de robustesse par rapport à l'existant : le champ
structuré est déjà là, déjà fiable, déjà utilisé ailleurs dans le même modèle pour une décision
de même nature (le facteur d'intérêt par période). La question de fiabilité d'une déduction par
dates (jours fériés, reports, échéances irrégulières) posée dans la demande **ne se pose donc
pas** — elle ne s'appliquerait que si on choisissait de na pas utiliser le champ existant, ce qui
n'a pas de justification apparente ici.

---

## 4. Fréquences non couvertes par la dichotomie mensuel / infra-mensuel

Les 10 fréquences actuellement chargées (`data/repayment_frequency_data.xml`) :

| code | period_kind | period_value | periods_per_year | Bucket "évident" |
|---|---|---|---|---|
| daily | days | 1 | 365 | infra-mensuel |
| weekly | days | 7 | 52 | infra-mensuel — **seul point confirmé (`/(n-1)`)** |
| biweekly | days | 15 | 26 | infra-mensuel, **mais 15 jours ≈ 1/2 mois** |
| four_weekly | days | 28 | 13 | infra-mensuel par `period_kind`, **mais 28 jours ≈ quasi-mensuel** |
| monthly | months | 1 | 12 | mensuel — **seul point confirmé (`/n`)** |
| bimonthly | months | 2 | 6 | mensuel-et-au-delà |
| quarterly | months | 3 | 4 | mensuel-et-au-delà |
| four_monthly | months | 4 | 3 | mensuel-et-au-delà |
| semiannual | months | 6 | 2 | mensuel-et-au-delà |
| annual | months | 12 | 1 | mensuel-et-au-delà |

Le champ `period_kind` fournit mécaniquement une frontière nette (`'days'` vs `'months'`), mais
**cette frontière elle-même n'est pas démontrée comme étant la bonne** — elle n'est qu'une
hypothèse de commodité technique (elle existe déjà dans le modèle), pas une donnée métier
confirmée par un troisième cas. Deux fréquences méritent une vigilance particulière si/quand
l'hypothèse sera un jour testée plus largement, **signalées ici sans être tranchées** :

- **`four_weekly` (28 jours)** : classé "infra-mensuel" par `period_kind`, mais sa durée réelle
  est si proche d'un mois calendaire que rien ne garantit que LPF le traite comme "hebdomadaire"
  plutôt que comme "mensuel". Cas à trancher explicitement avec Micka, pas à classer par
  supposition.
- **`biweekly` (15 jours, "quinzaine")** : à mi-chemin, même remarque à moindre degré.

Toute fréquence `days` avec `period_value` proche de 28-31 jours est structurellement ambiguë
sous la dichotomie proposée — elle ne doit pas être classée par défaut dans un camp ou l'autre
sans validation explicite.

---

## 5. Cartographie confirmée des points de calcul

Reconfirmation exhaustive (grep sur tout `microfinance_loan_management` et
`microfinance_savings_management`, hors tests) : **exactement deux points** calculent une cible
d'échéance de la forme "total dû ÷ nombre de tranches", tous deux déjà identifiés dans
`AUDIT.md` :

| # | Emplacement | Rôle |
|---|---|---|
| 1 | `_compute_installment_targets()` — `models/microfinance_loan.py:687-717`, division à la **ligne 704** (`raw_target = total_due / n`) | Calcule la liste des cibles réellement utilisées par `_build_installment_commands()` pour générer les lignes `installment_ids` (bouton "Générer échéancier", wizard, `action_disburse()` de secours). |
| 2 | `_onchange_loan_amount_recompute_installment()` — `models/microfinance_loan.py:637-663`, division à la **ligne 658** (`target = (loan.loan_amount + total_interest) / loan.term`) | Formule **dupliquée indépendamment**, alimente le champ "Échéance" affiché à l'écran avant toute génération. |

**Deux autres endroits du même fichier effectuent une division par `term`, mais sont
structurellement hors sujet** (vérifié pour clore définitivement la question "existe-t-il un
troisième site caché ?") :
- `models/microfinance_loan.py:805` (`principal = self.loan_amount / self.term`), dans la
  branche `interest_method == 'reducing'` — amortissement dégressif linéaire du principal,
  aucune notion de "cible arrondie + reliquat sur dernière tranche" (le champ
  `installment_rounding_unit` n'y intervient même pas). Hors périmètre de toute la Décision 1
  depuis l'origine (déjà noté dans plusieurs chantiers précédents).
- `_reschedule_installments()` (rééchelonnement), `principal = remaining_principal / term` —
  même remarque : amortissement linéaire sans arrondi, déjà signalé comme hors périmètre dans
  le chantier du wizard de reliquat (2026-08-19).

Aucun autre fichier (`microfinance_savings_management`, rapports QWeb) ne recalcule cette
division ; le rapport imprimable (`report/microfinance_loan_repayment_schedule_report.xml`) se
contente d'afficher `installment_ids` déjà calculées.

**Confirmation de la contrainte de la demande** : si une règle d'auto-détection est un jour
conçue, elle devra remplacer le calcul aux points **1 et 2 uniquement**, par un appel à une
fonction unique partagée (ex. une méthode `_installment_target_divisor()` appelée depuis les
deux endroits) — jamais dupliquée une seconde fois. Ceci reste une contrainte de conception à
respecter *le jour où* l'hypothèse sera confirmée ; aucune fonction de ce type n'a été créée ici.

---

## 6. Impact rétroactif sur les échéanciers déjà générés

**Un seul crédit existe dans SEFOR avec un échéancier généré : IS/000289 lui-même** (établi en
§1). Son échéancier actuel (8 lignes) a été généré **avant** les derniers correctifs de ce
chantier (durée réelle vs bornes produit, alignement LPF `periods_per_year`, wizard de reliquat)
et est déjà connu comme obsolète — signalé dans une session précédente ("le tableau Échéancier
figé à 8 lignes ne reflète pas encore le term=24 corrigé"). Il devra de toute façon être
régénéré via le bouton "Générer échéancier" une fois que la question du diviseur sera tranchée,
indépendamment du résultat de ce diagnostic.

**Conclusion : l'impact rétroactif est nul à négligeable.** Il n'y a pas de volume de dossiers
en production à rattraper — la base ne contient tout simplement pas d'autre échéancier généré
que celui, déjà su obsolète, du dossier même qui a servi de cas de test à ce chantier. Aucune
liste de rattrapage n'est nécessaire à ce stade ; le sujet redeviendra pertinent une fois que
l'instance sera en production réelle avec un volume de crédits actifs.

---

## 7. Recommandation

**Ne pas passer au Lot 1.** La condition posée par la demande elle-même pour concevoir puis
coder la règle d'auto-détection — un troisième cas papier confirmant sans ambiguïté que la
fréquence est le facteur déterminant — n'est pas remplie, et aucune source consultable dans ce
diagnostic ne permet de la remplir davantage à ce stade. Continuer sans cette confirmation
reviendrait à figer une règle produit sur la seule base de deux points de données, ce que la
demande elle-même écarte explicitement.

**Pistes concrètes pour débloquer**, à la main de Micka :
1. Retrouver un troisième échéancier LPF papier — idéalement sur une fréquence intermédiaire
   (quinzaine, quatre-semaines, bimestriel) plutôt qu'un second cas hebdomadaire, pour que le
   nouveau point apporte une information sur la frontière et pas seulement une confirmation d'un
   régime déjà connu.
2. Si un tel document existe sur un Drive ou un support physique, en indiquer l'emplacement
   précis pour que je puisse le consulter et compléter le tableau comparatif du Lot 0.
3. À défaut de document, une clarification directe du principe appliqué par LPF (documentation
   éditeur, ou réponse de quelqu'un qui connaît l'algorithme LPF) trancherait plus vite qu'une
   recherche empirique par accumulation de cas.

En l'état, la conception fonctionnelle de l'auto-détection (source du champ, seuils exacts,
gestion des fréquences non couvertes) **n'a pas été rédigée**, conformément à la règle de la
demande de ne pas forcer une règle non prouvée.
