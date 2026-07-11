# Workflow Garanties et scoring crédit

## 1. Objectif métier
Ce workflow couvre deux volets rattachés à l'appréciation du risque d'un crédit :
1. **Garanties/cautions** (`microfinance.loan.guarantee`) : enregistrement des biens ou cautions personnelles adossés à un crédit, valorisation pondérée par type via des règles de valorisation (`microfinance.guarantee.valuation.rule`), et suivi de leur cycle de vie (brouillon / validée / libérée).
2. **Scoring crédit** (`microfinance.scoring.profile`, `microfinance.scoring.rule`, `microfinance.scoring.line`) : configuration de profils de scoring par société/produit, de règles de calcul de points (bonus/malus) selon des métriques du client et du crédit, et historisation des calculs appliqués à chaque crédit.

N'est PAS couvert ici : le cycle de vie complet de la demande de crédit (`microfinance.loan`, workflow « dossier_precredit »), le calcul du montant des provisions comptables (workflow « comptabilite »), ni le paramétrage des produits de crédit eux-mêmes (`microfinance.loan.product`, workflow « creation_produit_credit »). Les méthodes `action_calculate_scoring`, `action_recompute_risk` et `action_view_scoring_lines` de `microfinance.loan` sont documentées ici uniquement comme points d'entrée qui rattachent le crédit au moteur de scoring, pas comme cœur de ce workflow.

## 2. Utilisateurs concernés
D'après `microfinance_loan_management/security/groups.xml` et `ir.model.access.csv` :
- **Manager crédit** (`group_microfinance_manager`) : accès complet (lecture, écriture, création, suppression) sur garanties, règles de valorisation et scoring (profils, règles, lignes).
- **Agent crédit** (`group_microfinance_user`) : lecture/écriture/création sur les garanties (pas de suppression) ; lecture seule sur profils et règles de scoring ; accès complet sur les lignes de scoring (historique).
- **Finance microfinance** (`group_microfinance_finance`) : lecture seule sur les garanties et sur les règles de valorisation des garanties.
- **Auditeur microfinance** (`group_microfinance_auditor`) : lecture seule sur les garanties, les règles de valorisation, les profils/règles/lignes de scoring.

## 3. Menus utilisés
Chemins reconstitués depuis `microfinance_loan_management/views/microfinance_menus.xml` :
- Microfinance > Crédits > Garanties
  (`menu_microfinance_root` > `menu_credits_root` > `menu_microfinance_guarantees`, action `action_microfinance_guarantee`)
- Microfinance > Configuration > Scoring crédit
  (`menu_microfinance_root` > `menu_microfinance_config` > `menu_microfinance_scoring`, action `action_microfinance_scoring_profile`)
- Microfinance > Configuration > Ratios de valorisation des garanties
  (`menu_microfinance_root` > `menu_microfinance_config` > `menu_microfinance_guarantee_valuation_rule`, action `action_microfinance_guarantee_valuation_rule`)

Le menu « Configuration » (`menu_microfinance_config`) n'est affiché qu'au groupe `group_microfinance_manager`. Les garanties d'un crédit précis sont aussi accessibles directement depuis la fiche crédit (onglet « Garanties », voir section 5), sans passer par le menu dédié.

## 4. Étapes principales
**Volet garanties** (dérivé du formulaire `view_microfinance_guarantee_form` et de l'onglet « Garanties » de la fiche crédit) :
1. Depuis la fiche d'un crédit, ouvrir l'onglet « Garanties » (ou le menu Microfinance > Crédits > Garanties).
2. Ajouter une ligne : choisir le type de garantie, saisir une description et la valeur estimée.
3. Si le type est « Garant / caution personnelle », renseigner obligatoirement le partenaire caution.
4. Joindre éventuellement une pièce justificative (document scanné).
5. La valeur reconnue se calcule automatiquement selon le ratio de valorisation configuré pour ce type de garantie.
6. Faire passer la garantie de « Brouillon » à « Validée » une fois le dossier vérifié.
7. À la clôture du crédit (`action_close`), les garanties non libérées sont automatiquement passées à l'état « Libérée ».

**Volet scoring** (dérivé du formulaire `view_microfinance_scoring_profile_form` et des méthodes de `microfinance_loan.py`) :
1. Configurer, dans Microfinance > Configuration > Scoring crédit, un profil de scoring (générique société ou spécifique à un produit de crédit), avec ses bornes de score (min/max) et ses trois seuils de décision.
2. Ajouter les règles de scoring du profil (onglet « Règles ») : métrique suivie, mode de calcul (seuil ou linéaire), opérateur/valeur, type (bonus/malus) et points.
3. Sur une demande de crédit, le calcul du score se déclenche automatiquement à la soumission (`action_submit` appelle `action_calculate_scoring`) ou manuellement via le bouton « Recalculer le risque »/« Scoring » présent sur la fiche crédit (bouton `action_recompute_risk` du modèle `microfinance.loan`).
4. Le système sélectionne le profil de scoring applicable (celui déjà lié au crédit s'il est actif, sinon le profil actif du produit, sinon le profil générique de la société), calcule chaque métrique, applique les règles actives et cumule les points en un score borné entre `min_score` et `max_score`.
5. Le score alimente `internal_score`, `risk_level` et `scoring_decision` sur le crédit, et génère une ligne d'historique (`microfinance.scoring.line`) par règle qui s'est appliquée.
6. Consulter le détail du calcul via le bouton statistique « Scoring » (`action_view_scoring_lines`) sur la fiche crédit, ou l'onglet « Scoring » de la fiche.
7. Une tâche planifiée (`cron_update_overdue_and_penalties`, hors périmètre direct) recalcule automatiquement le scoring de tous les crédits actifs.

## 5. Champs importants
**Écran Garantie (`microfinance.loan.guarantee`)**
- `loan_id` (Crédit) : crédit rattaché, suppression en cascade.
- `guarantee_type` (Type de garantie) : Terrain / Véhicule / Maison / Meuble / Salaire / Garant-caution personnelle / Autre.
- `description` (Description) : libellé de la garantie, obligatoire.
- `estimated_value` (Valeur estimée) : montant déclaré, obligatoire, ne peut être négatif.
- `recognized_value` (Valeur reconnue) : champ calculé et stocké = valeur estimée × ratio de valorisation du type (100 % par défaut si aucune règle configurée pour la société/le type).
- `guarantor_partner_id` (Caution) : visible et obligatoire uniquement si type = « Garant / caution personnelle ».
- `document` / `document_filename` (Pièce justificative) : fichier joint.
- `state` (État) : Brouillon / Validée / Libérée.

**Écran Ratio de valorisation (`microfinance.guarantee.valuation.rule`)**
- `guarantee_type` (Type de garantie) : même liste de sélection que ci-dessus, obligatoire.
- `valuation_ratio` (Ratio de valorisation %) : pourcentage de la valeur estimée reconnu comme garantie effective (ex. 114 pour 114 %).
- `max_ratio` (Ratio maximum %) : plafond au-delà duquel `valuation_ratio` ne peut pas être configuré.
- `company_id` (Société) : une seule règle par couple type/société (contrainte SQL).

**Écran Profil de scoring (`microfinance.scoring.profile`)**
- `name` (Nom), `active` (Actif), `company_id` (Société).
- `product_id` (Produit de crédit) : laisser vide pour un profil générique de la société.
- `min_score` / `max_score` (Score minimum/maximum) : bornes du score.
- `approve_threshold` (Seuil d'approbation), `manual_review_threshold` (Seuil de revue manuelle), `reject_threshold` (Seuil de rejet).
- `rule_ids` (Règles) : lignes de règles de scoring rattachées (onglet « Règles »).

**Écran Règle de scoring (`microfinance.scoring.rule`)**
- `profile_id` (Profil de scoring), `sequence`, `active`.
- `metric` (Métrique) : liste de 17 métriques possibles (ex. `baseline`, `total_loans`, `overdue_installments`, `repayment_rate`, `loan_overdue_installment_count`, `loan_max_days_overdue`, `loan_overdue_amount_ratio`, `loan_partial_payment_count`, etc.).
- `computation` (Mode de calcul) : Seuil (points fixes si condition vraie) / Linéaire (points × valeur de la métrique, condition ignorée).
- `operator` (Opérateur) : =, !=, >, >=, <, <=, between.
- `value` (Valeur) : nombre, ou deux nombres séparés par une virgule pour `between`.
- `points` (Points), `rule_type` (Type de règle) : Bonus / Malus.
- `description` (Description).

**Écran Ligne de scoring / historique (`microfinance.scoring.line`, lecture seule, non créable/modifiable/supprimable manuellement)**
- `loan_id` (Crédit), `rule_id` (Règle), `metric_value` (Valeur de la métrique), `points_applied` (Points appliqués), `note` (Note, reprend la description ou le nom de la règle).

**Sur la fiche crédit (`microfinance.loan`, section scoring)**
- `scoring_profile_id` (Profil de scoring), `internal_score` (Score), `risk_level` (Niveau de risque : Faible/Moyen/Élevé/Critique), `scoring_decision` (Décision scoring : Recommandé/Revue manuelle/Risqué-Rejet recommandé), `scoring_line_ids` (Règles appliquées), `scoring_line_count` (bouton statistique).
- `guarantee_ids` (Garanties), `guarantee_total` (Total garanties validées, calculé/stocké, somme des `recognized_value` des garanties à l'état « validated »).

## 6. Boutons et actions
- Fiche crédit, bouton statistique « Scoring » (`action_view_scoring_lines`, icône `fa-sliders`) : ouvre la liste des lignes de scoring du crédit. Toujours visible dans le button box.
- Aucun bouton `type="object"` visible directement dans les vues `microfinance_loan_guarantee_views.xml` ou `microfinance_scoring_views.xml` (les vues de garanties et de règles de scoring sont uniquement composées de champs). Les vues des lignes de scoring (`view_microfinance_scoring_line_tree`/`form`) sont explicitement non créables/éditables/supprimables (`create="0" edit="0" delete="0"`).
- Sur le modèle `microfinance.loan` (fichier `microfinance_loan.py`), les méthodes suivantes pilotent le scoring mais ne sont pas décrites comme boutons dans les fichiers de vues fournis pour ce workflow : `action_calculate_scoring(silent=False)` (calcule/recalcule le score), `action_recompute_risk()` (alias public qui appelle `action_calculate_scoring(silent=True)`), `action_view_scoring_lines()` (ouvre l'historique). `action_submit()` appelle automatiquement `action_calculate_scoring(silent=True)` avant de passer le crédit à l'état « Soumis ».

## 7. Règles métier
**Garanties**
- `_check_guarantor_partner` (`@api.constrains('guarantee_type', 'guarantor_partner_id')`) : si le type est « Garant / caution personnelle », le partenaire caution est obligatoire.
- `_check_estimated_value` (`@api.constrains('estimated_value')`) : la valeur estimée ne peut pas être négative.
- `_compute_recognized_value` (`@api.depends('estimated_value', 'guarantee_type', 'company_id')`) : recherche la règle de valorisation correspondant au type de garantie et à la société ; applique son ratio (défaut 100 % si aucune règle) à la valeur estimée.

**Règles de valorisation des garanties**
- `_check_ratio` (`@api.constrains('valuation_ratio', 'max_ratio')`) : `max_ratio` doit être strictement positif ; `valuation_ratio` ne peut pas être négatif ; `valuation_ratio` ne peut pas dépasser `max_ratio`.
- Contrainte SQL `type_company_unique` : une seule règle par type de garantie et par société.

**Profils de scoring**
- `_check_single_active_profile` (`@api.constrains('active', 'company_id', 'product_id')`) : un seul profil actif par société et par produit (ou par société pour les profils génériques sans produit).
- `_check_thresholds` (`@api.constrains('min_score', 'max_score', 'approve_threshold', 'manual_review_threshold', 'reject_threshold')`) : `min_score < max_score` ; chaque seuil doit être compris entre `min_score` et `max_score` ; `approve_threshold >= manual_review_threshold`.

**Règles de scoring**
- `_check_rule_value` (`@api.constrains('computation', 'operator', 'value')`) : en mode « Seuil », un opérateur et une valeur sont obligatoires, et la valeur doit être numérique (ou une paire numérique valide pour `between`, borne basse ≤ borne haute).
- `_get_points` : les points sont toujours appliqués en valeur absolue puis signés selon `rule_type` (positif pour bonus, négatif pour malus) ; en mode linéaire, multipliés par la valeur de la métrique.

**Calcul du score sur un crédit** (`action_calculate_scoring` dans `microfinance_loan.py`) :
- Un crédit à l'état « Radié » (`written_off`) reçoit systématiquement score = 0, risque = « Critique », décision = « Risqué / Rejet recommandé », et son historique de scoring est vidé.
- Le profil applicable est déterminé par `_get_scoring_profile()` : profil déjà lié au crédit s'il est actif, sinon profil actif du produit du crédit, sinon profil générique actif de la société. Si aucun profil n'est trouvé et que l'appel n'est pas en mode silencieux, une erreur bloque le calcul.
- Les métriques sont calculées par `_get_scoring_metrics()` à partir de l'historique du client (tous crédits/paiements/échéances) et du crédit courant (métriques préfixées `loan_*`).
- Chaque règle active du profil est évaluée dans l'ordre (`sequence`, `id`) ; les points des règles qui matchent sont cumulés puis le score final est borné entre `min_score` et `max_score` du profil.
- Décision (`_get_scoring_decision`) : `recommended` si score ≥ `approve_threshold` ; `manual_review` si score ≥ `manual_review_threshold` ; sinon `reject_recommended`.
- Niveau de risque (`_get_scoring_risk_level`) : ratio = (score − min_score) / (max_score − min_score) ; `low` si ratio ≥ 0,75 ; `medium` si ratio ≥ 0,5 ; `high` si score ≥ `reject_threshold` ; sinon `critical`.

**Eligibilité liée aux garanties** (`_check_eligibility`, appelée par `action_submit`) : si le produit exige une garantie (`product.guarantee_required`), au moins une garantie à l'état « validated » est requise ; si le produit fixe un ratio minimum de garantie (`product.min_guarantee_ratio`), `guarantee_total` (somme des `recognized_value` des garanties validées) doit couvrir ce ratio appliqué au montant du crédit.

**Libération automatique des garanties** : à la clôture d'un crédit (`action_close`), toutes les garanties non encore « Libérée » sont automatiquement passées à cet état, avec un message posté dans le chatter du crédit listant les garanties libérées.

## 8. Contrôles et blocages
- Impossible d'enregistrer une garantie de type « Garant / caution personnelle » sans partenaire caution : « La caution doit préciser le partenaire qui se porte garant. »
- Impossible d'enregistrer une garantie avec une valeur estimée négative : « La valeur estimée ne peut pas être négative. »
- Impossible d'enregistrer une règle de valorisation avec un ratio maximum nul ou négatif : « Le ratio maximum doit être strictement positif. »
- Impossible d'enregistrer une règle de valorisation avec un ratio de valorisation négatif : « Le ratio de valorisation ne peut pas être négatif. »
- Impossible d'enregistrer une règle de valorisation dont le ratio dépasse le plafond : « Le ratio de valorisation (X%) dépasse le plafond autorisé pour ce type de garantie (Y%). »
- Impossible d'activer un deuxième profil de scoring pour la même société/produit : « Un profil de scoring actif existe déjà pour cette société et ce produit. »
- Impossible d'enregistrer un profil dont les bornes/seuils sont incohérents : « Le score minimum doit être inférieur au score maximum. », « Les seuils doivent être compris entre le score minimum et le score maximum. », « Le seuil de recommandation doit être supérieur ou égal au seuil de revue manuelle. »
- Impossible d'enregistrer une règle de scoring à seuil sans opérateur/valeur : « Un opérateur et une valeur sont requis pour une règle à seuil. »
- Valeur `between` invalide : « La valeur between doit contenir deux nombres, par exemple 10,30. » ou borne basse > borne haute : « La borne basse doit être inférieure ou égale à la borne haute. »
- Valeur non numérique : « La valeur de scoring doit être numérique. »
- À la soumission d'un crédit (`action_submit` → `_check_eligibility`), blocage si le produit exige une garantie et qu'aucune n'est validée, ou si le total des garanties validées est inférieur au ratio minimum requis (message détaillant le montant manquant).
- Si aucun profil de scoring n'est configuré pour la société/le produit et que le calcul n'est pas appelé en mode silencieux : « Configurez un profil de scoring crédit pour cette société ou ce produit. »

## 9. Statuts
- `microfinance.loan.guarantee.state` : Brouillon (`draft`, valeur par défaut) → Validée (`validated`) → Libérée (`released`). Aucun bouton `type="object"` de transition d'état identifié dans les vues fournies : le champ `state` est modifiable directement dans le formulaire/la liste éditable. La transition vers « Libérée » peut aussi se produire automatiquement via `action_close()` du crédit.
- `microfinance.guarantee.valuation.rule` : pas de champ `state` (paramétrage statique).
- `microfinance.scoring.profile` / `microfinance.scoring.rule` : pas de champ `state` ; seul un booléen `active` gère l'archivage/désactivation.
- `microfinance.scoring.line` : pas de champ `state` (ligne d'historique en lecture seule).
- Rappel indirect : `microfinance.loan.risk_level` (Faible/Moyen/Élevé/Critique) et `microfinance.loan.scoring_decision` (Recommandé/Revue manuelle/Risqué-Rejet recommandé) sont des champs calculés par le scoring, mais ce ne sont pas des champs `state` avec statusbar.

## 10. Rapports ou PDF
Aucun rapport dédié à ce jour.

## 11. Tableaux de bord
Aucun indicateur lié aux garanties ou au scoring identifié dans `microfinance_loan_management/models/microfinance_dashboard.py` parmi les fichiers listés pour ce workflow. À compléter si un widget dédié existe ailleurs.

## 12. Sécurité et groupes utilisateurs
D'après `microfinance_loan_management/security/ir.model.access.csv` :

**Garanties (`model_microfinance_loan_guarantee`)**

| Groupe | Lecture | Écriture | Création | Suppression |
|---|---|---|---|---|
| Agent crédit (`group_microfinance_user`) | Oui | Oui | Oui | Non |
| Manager crédit (`group_microfinance_manager`) | Oui | Oui | Oui | Oui |
| Finance microfinance (`group_microfinance_finance`) | Oui | Non | Non | Non |
| Auditeur microfinance (`group_microfinance_auditor`) | Oui | Non | Non | Non |

**Règles de valorisation des garanties (`model_microfinance_guarantee_valuation_rule`)**

| Groupe | Lecture | Écriture | Création | Suppression |
|---|---|---|---|---|
| Agent crédit (`group_microfinance_user`) | Oui | Non | Non | Non |
| Manager crédit (`group_microfinance_manager`) | Oui | Oui | Oui | Oui |
| Finance microfinance (`group_microfinance_finance`) | Oui | Non | Non | Non |

**Profils de scoring (`model_microfinance_scoring_profile`)**

| Groupe | Lecture | Écriture | Création | Suppression |
|---|---|---|---|---|
| Agent crédit (`group_microfinance_user`) | Oui | Non | Non | Non |
| Manager crédit (`group_microfinance_manager`) | Oui | Oui | Oui | Oui |
| Auditeur microfinance (`group_microfinance_auditor`) | Oui | Non | Non | Non |

**Règles de scoring (`model_microfinance_scoring_rule`)**

| Groupe | Lecture | Écriture | Création | Suppression |
|---|---|---|---|---|
| Agent crédit (`group_microfinance_user`) | Oui | Non | Non | Non |
| Manager crédit (`group_microfinance_manager`) | Oui | Oui | Oui | Oui |
| Auditeur microfinance (`group_microfinance_auditor`) | Oui | Non | Non | Non |

**Lignes de scoring / historique (`model_microfinance_scoring_line`)**

| Groupe | Lecture | Écriture | Création | Suppression |
|---|---|---|---|---|
| Agent crédit (`group_microfinance_user`) | Oui | Oui | Oui | Oui |
| Manager crédit (`group_microfinance_manager`) | Oui | Oui | Oui | Oui |
| Auditeur microfinance (`group_microfinance_auditor`) | Oui | Non | Non | Non |

En complément, `microfinance_loan_management/security/groups.xml` définit trois règles `ir.rule` de cloisonnement par société (`rule_microfinance_scoring_profile_company`, `rule_microfinance_scoring_rule_company`, `rule_microfinance_scoring_line_company`), toutes avec le domaine `[('company_id', 'in', company_ids)]`, appliquées aux groupes Agent crédit, Manager crédit, Finance microfinance et Auditeur microfinance.

## 13. Cas d'utilisation complets
1. **Ajout d'une garantie sur un crédit.** Un Agent crédit ouvre la fiche du crédit concerné, va dans l'onglet « Garanties », clique sur « Ajouter une ligne », choisit le type « Terrain », saisit la description et la valeur estimée. La valeur reconnue se calcule automatiquement selon le ratio de valorisation défini pour « Terrain » dans Microfinance > Configuration > Ratios de valorisation des garanties. Un Manager crédit fait ensuite passer l'état de la garantie de « Brouillon » à « Validée ».
2. **Paramétrage d'un nouveau profil de scoring pour un produit.** Un Manager crédit va dans Microfinance > Configuration > Scoring crédit, crée un profil, sélectionne le produit de crédit concerné, définit les bornes de score (0-100) et les trois seuils, puis ajoute dans l'onglet « Règles » les métriques pertinentes (ex. « Échéances en retard (ce crédit) » en mode linéaire, malus, 15 points). Il enregistre ; la contrainte d'unicité empêche d'avoir deux profils actifs pour le même produit.
3. **Calcul du score à la soumission d'un crédit.** Un Agent crédit clique sur le bouton de soumission de la demande de crédit (`action_submit`) ; le système vérifie l'éligibilité (garanties suffisantes si requises), calcule automatiquement le score via le profil applicable, affiche le niveau de risque et la décision recommandée sur la fiche, et alimente l'historique consultable via le bouton statistique « Scoring ».

## 14. Erreurs fréquentes
- « La caution doit préciser le partenaire qui se porte garant. » (garantie de type caution sans partenaire renseigné).
- « La valeur estimée ne peut pas être négative. »
- « Le ratio de valorisation (X%) dépasse le plafond autorisé pour ce type de garantie (Y%). »
- « Un profil de scoring actif existe déjà pour cette société et ce produit. » (tentative d'activer un second profil pour le même périmètre).
- « Les seuils doivent être compris entre le score minimum et le score maximum. »
- « Un opérateur et une valeur sont requis pour une règle à seuil. »
- « La valeur de scoring doit être numérique. » (règle `between` ou seuil mal saisie).
- « Configurez un profil de scoring crédit pour cette société ou ce produit. » (aucun profil actif trouvé lors d'un calcul non silencieux).
- « Garanties insuffisantes : il manque X pour atteindre le ratio minimum requis... » (à la soumission d'un crédit dont le produit impose un ratio de garantie minimum).
- « Ce produit exige une garantie validée avant soumission. » (produit avec `guarantee_required` et aucune garantie à l'état « validated »).

## 15. Bonnes pratiques
- Configurer les ratios de valorisation par type de garantie avant la saisie des garanties elles-mêmes, afin que la valeur reconnue calculée automatiquement reflète la politique de risque de l'IMF dès la création (sinon le ratio par défaut de 100 % s'applique).
- Ne conserver qu'un seul profil de scoring actif par société/produit ; désactiver (`active = False`) plutôt que supprimer un ancien profil pour garder l'historique des lignes de scoring cohérent.
- Ordonner les règles de scoring avec le champ `sequence` en commençant par une règle « Constante » (métrique `baseline`) servant de score de base, puis les malus, comme dans le profil par défaut fourni par `scoring_rules_data.xml`.
- Faire valider les garanties (passage à l'état « Validée ») avant la soumission du crédit, car seules les garanties validées comptent dans `guarantee_total` et dans le contrôle d'éligibilité.
- Recalculer le scoring manuellement (bouton lié à `action_recompute_risk`) après toute modification manuelle du profil de scoring rattaché à un crédit, le score n'étant pas recalculé automatiquement à chaque écriture.

## 16. Questions/Réponses MOWGLI potentielles
1. Comment ajouter une garantie à une demande de crédit ?
2. Quels types de garanties peut-on enregistrer dans MOWGLI ?
3. Comment est calculée la valeur reconnue d'une garantie ?
4. Où configurer les ratios de valorisation des garanties par type de bien ?
5. Comment fonctionne le scoring crédit automatique ?
6. Quelles métriques sont utilisées pour calculer le score d'un client ?
7. Pourquoi le système bloque la soumission d'un crédit pour garanties insuffisantes ?
8. Qui peut valider ou modifier un profil de scoring ?
9. Comment consulter le détail du calcul de scoring d'un crédit ?
10. Que se passe-t-il avec les garanties quand un crédit est clôturé ?
