# Workflow Garanties et scoring crédit

## 1. Objectif métier
Ce workflow couvre deux volets rattachés à l'appréciation du risque d'un crédit :
1. **Garanties/cautions** (`microfinance.loan.guarantee`) : enregistrement des biens ou cautions personnelles adossés à un crédit, valorisation pondérée par type via des règles de valorisation (`microfinance.guarantee.valuation.rule`), et suivi de leur cycle de vie (brouillon / validée / libérée).
2. **Scoring crédit** (`microfinance.scoring.profile`, `microfinance.scoring.rule`, `microfinance.scoring.line`) : configuration de profils de scoring par société/produit, de règles de calcul de points (bonus/malus) selon des métriques du client et du crédit, et historisation des calculs appliqués à chaque crédit.

N'est PAS couvert ici : le cycle de vie complet de la demande de crédit (`microfinance.loan`, workflow « dossier_precredit »), le calcul du montant des provisions comptables (workflow « comptabilite »), ni le paramétrage des produits de crédit eux-mêmes (`microfinance.loan.product`, workflow « creation_produit_credit »). Les actions de calcul et de consultation du score sur la fiche crédit sont documentées ici uniquement comme points d'entrée qui rattachent le crédit au moteur de scoring, pas comme cœur de ce workflow.

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
7. À la clôture du crédit, les garanties non libérées sont automatiquement passées à l'état « Libérée ».

**Volet scoring** :
1. Configurer, dans Microfinance > Configuration > Scoring crédit, un profil de scoring (générique société ou spécifique à un produit de crédit), avec ses bornes de score (min/max) et ses trois seuils de décision.
2. Ajouter les règles de scoring du profil (onglet « Règles ») : métrique suivie, mode de calcul (seuil ou linéaire), opérateur/valeur, type (bonus/malus) et points.
3. Sur une demande de crédit, le calcul du score se déclenche automatiquement à la soumission du dossier, ou manuellement à tout moment via le bouton « Recalculer le score » présent dans l'en-tête de la fiche crédit.
4. Le système sélectionne le profil de scoring applicable (celui déjà lié au crédit s'il est actif, sinon le profil actif du produit, sinon le profil générique de la société), calcule chaque métrique, applique les règles actives et cumule les points en un score borné entre le score minimum et le score maximum du profil.
5. Le score alimente le Score interne, le Niveau de risque et la Décision scoring sur le crédit, et génère une ligne d'historique par règle qui s'est appliquée.
6. Consulter le détail du calcul via le bouton statistique « Scoring » sur la fiche crédit, ou l'onglet « Scoring » de la fiche.
7. Une tâche planifiée recalcule aussi automatiquement le scoring de tous les crédits actifs.

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
- `metric` (Métrique) : liste de 17 métriques possibles, parmi lesquelles Constante (score de base), Total crédits, Crédits actifs/clôturés/en défaut, Échéances en retard, Maximum/moyenne jours de retard, Taux de remboursement, Montant total emprunté/payé, Nombre de paiements partiels, Ancienneté client, et les métriques limitées au crédit courant (Échéances en retard, Maximum jours de retard, Montant en retard / montant crédit en %, Paiements partiels).
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
- Fiche crédit, bouton statistique « Scoring » (dans la barre de boutons, toujours visible) : ouvre la liste des lignes de scoring du crédit.
- Fiche crédit, bouton « Recalculer le score » (dans l'en-tête) : relance le calcul du score à tout moment.
- La soumission de la demande de crédit (bouton « Soumettre ») recalcule automatiquement le score avant de faire passer le crédit à l'état « Soumis ».
- Les écrans Garanties et Ratios de valorisation des garanties ne comportent pas de bouton d'action dédié : la saisie se fait uniquement par les champs. Il en va de même pour les profils et règles de scoring.
- Les lignes de l'historique de scoring ne sont pas créables, modifiables ni supprimables manuellement : elles sont uniquement produites par le calcul automatique du score.

## 7. Règles métier
**Garanties**
- Si le type est « Garant / caution personnelle », le partenaire caution est obligatoire.
- La valeur estimée ne peut pas être négative.
- La valeur reconnue se recalcule automatiquement dès que la valeur estimée, le type de garantie ou la société changent : elle applique le ratio de valorisation du type de garantie pour la société (100 % par défaut si aucune règle n'est configurée).

**Règles de valorisation des garanties**
- Le ratio maximum doit être strictement positif ; le ratio de valorisation ne peut pas être négatif ni dépasser le ratio maximum.
- Une seule règle de valorisation par type de garantie et par société.

**Profils de scoring**
- Un seul profil actif par société et par produit (ou par société pour les profils génériques sans produit).
- Le score minimum doit être inférieur au score maximum ; chaque seuil doit être compris entre le score minimum et le score maximum ; le seuil d'approbation doit être supérieur ou égal au seuil de revue manuelle.

**Règles de scoring**
- En mode « Seuil », un opérateur et une valeur sont obligatoires, et la valeur doit être numérique (ou une paire numérique valide pour l'opérateur « between », borne basse inférieure ou égale à la borne haute).
- Les points sont toujours appliqués en valeur absolue puis signés selon le type de règle (positif pour bonus, négatif pour malus) ; en mode linéaire, ils sont multipliés par la valeur de la métrique.

**Calcul du score sur un crédit**
- Un crédit à l'état « Radié » reçoit systématiquement score = 0, risque = « Critique », décision = « Risqué / Rejet recommandé », et son historique de scoring est vidé.
- Le profil applicable est déterminé ainsi : profil déjà lié au crédit s'il est actif, sinon profil actif du produit du crédit, sinon profil générique actif de la société. Si aucun profil n'est trouvé lors d'un calcul déclenché explicitement par l'utilisateur, une erreur bloque le calcul.
- Les métriques sont calculées à partir de l'historique du client (tous crédits/paiements/échéances) et du crédit courant.
- Chaque règle active du profil est évaluée dans l'ordre défini par sa séquence ; les points des règles qui correspondent sont cumulés puis le score final est borné entre le score minimum et le score maximum du profil.
- Décision : « Recommandé » si le score atteint le seuil d'approbation ; « Revue manuelle » si le score atteint le seuil de revue manuelle ; sinon « Risqué / Rejet recommandé ».
- Niveau de risque : « Faible » si le score se situe dans le quart supérieur de l'échelle du profil, « Moyen » dans la moitié supérieure, « Élevé » si le score atteint au moins le seuil de rejet, sinon « Critique ».

**Eligibilité liée aux garanties** (vérifiée à la soumission du crédit) : si le produit exige une garantie, au moins une garantie à l'état « Validée » est requise ; si le produit fixe un ratio minimum de garantie, le total des garanties validées doit couvrir ce ratio appliqué au montant du crédit.

**Libération automatique des garanties** : à la clôture d'un crédit, toutes les garanties non encore « Libérée » sont automatiquement passées à cet état, avec un message posté dans le chatter du crédit listant les garanties libérées.

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
- À la soumission d'un crédit, blocage si le produit exige une garantie et qu'aucune n'est validée, ou si le total des garanties validées est inférieur au ratio minimum requis (message détaillant le montant manquant).

## 9. Statuts
- Statut d'une garantie : Brouillon (valeur par défaut) → Validée → Libérée. Le champ Statut se modifie directement sur la fiche de la garantie (ou dans la liste éditable), sans bouton dédié. La transition vers « Libérée » se produit aussi automatiquement pour toutes les garanties non encore libérées lors de la clôture du crédit.
- Les ratios de valorisation des garanties n'ont pas de statut : ce sont des paramétrages statiques.
- Les profils et règles de scoring n'ont pas de statut ; seule la case « Actif » gère leur archivage/désactivation.
- Les lignes d'historique de scoring n'ont pas de statut (lecture seule).
- Sur la fiche crédit, le Niveau de risque (Faible/Moyen/Élevé/Critique) et la Décision scoring (Recommandé/Revue manuelle/Risqué-Rejet recommandé) sont des indicateurs calculés automatiquement par le scoring, pas des statuts à faire progresser manuellement.

## 10. Rapports ou PDF
Aucun rapport dédié à ce jour.

## 11. Tableaux de bord
Aucun tableau de bord dédié aux garanties ou au scoring à ce jour. À compléter.

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
3. **Calcul du score à la soumission d'un crédit.** Un Agent crédit clique sur le bouton de soumission de la demande de crédit ; le système vérifie l'éligibilité (garanties suffisantes si requises), calcule automatiquement le score via le profil applicable, affiche le niveau de risque et la décision recommandée sur la fiche, et alimente l'historique consultable via le bouton statistique « Scoring ».

## 14. Erreurs fréquentes
- « La caution doit préciser le partenaire qui se porte garant. » (garantie de type caution sans partenaire renseigné).
- « La valeur estimée ne peut pas être négative. »
- « Le ratio de valorisation (X%) dépasse le plafond autorisé pour ce type de garantie (Y%). »
- « Un profil de scoring actif existe déjà pour cette société et ce produit. » (tentative d'activer un second profil pour le même périmètre).
- « Les seuils doivent être compris entre le score minimum et le score maximum. »
- « Un opérateur et une valeur sont requis pour une règle à seuil. »
- « La valeur de scoring doit être numérique. » (règle « between » ou seuil mal saisie).
- « Garanties insuffisantes : il manque X pour atteindre le ratio minimum requis... » (à la soumission d'un crédit dont le produit impose un ratio de garantie minimum).
- « Ce produit exige une garantie validée avant soumission. » (produit exigeant une garantie et aucune garantie à l'état « Validée »).

## 15. Bonnes pratiques
- Configurer les ratios de valorisation par type de garantie avant la saisie des garanties elles-mêmes, afin que la valeur reconnue calculée automatiquement reflète la politique de risque de l'IMF dès la création (sinon le ratio par défaut de 100 % s'applique).
- Ne conserver qu'un seul profil de scoring actif par société/produit ; désactiver (`active = False`) plutôt que supprimer un ancien profil pour garder l'historique des lignes de scoring cohérent.
- Ordonner les règles de scoring avec le champ `sequence` en commençant par une règle « Constante » (métrique `baseline`) servant de score de base, puis les malus, comme dans le profil par défaut fourni par `scoring_rules_data.xml`.
- Faire valider les garanties (passage à l'état « Validée ») avant la soumission du crédit, car seules les garanties validées comptent dans `guarantee_total` et dans le contrôle d'éligibilité.
- Recalculer le scoring manuellement (bouton « Recalculer le score ») après toute modification manuelle du profil de scoring rattaché à un crédit, le score n'étant pas recalculé automatiquement à chaque écriture.

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
