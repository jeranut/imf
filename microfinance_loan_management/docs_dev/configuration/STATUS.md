# Statut dev — Menu Configuration
Dernière inspection : 2026-07-19

## Réorganisation en sous-groupes thématiques, 2026-07-19

### Décision
Le menu **Microfinance > Configuration** contenait 18 entrées à plat (capture d'écran de
Micka). Regroupées en 6 sous-menus thématiques validés avec Micka, sans rien supprimer ni
renommer (mêmes `id`, actions, sécurité — uniquement l'attribut `parent` de chaque
`<menuitem>` a changé) :

| Sous-menu | Entrées |
|---|---|
| **Général** (`menu_microfinance_config_general`) | Paramètres |
| **Crédit** (`menu_microfinance_config_credit`) | Produits de crédit, Périodicités de remboursement, Scoring crédit, Règles de provisionnement, Ratios de valorisation des garanties, Programmes progressifs |
| **Épargne** (`menu_microfinance_config_savings`) | Produits d'épargne |
| **Financement** (`menu_microfinance_config_financing`) | Bailleurs de fonds, Fonds de crédit |
| **Géographie** (`menu_microfinance_config_geography`) | Régions, Districts, Communes, Fokontany |
| **Profil socio-économique** (`menu_microfinance_config_social_profile`) | Professions, Niveaux sociaux, Catégories d'activité, Activités |

Les 6 sous-menus eux-mêmes sont définis dans `views/microfinance_menus.xml` (module
`microfinance_loan_management`). Les entrées "Régions/Districts/Communes/Fokontany" restent
dans `views/microfinance_geo_views.xml` ; "Produits d'épargne" reste dans
`microfinance_savings_management/views/microfinance_savings_menus.xml` (référence cross-module
`microfinance_loan_management.menu_microfinance_config_savings`).

### Point technique découvert en cours de route
`<menuitem parent="xmlid">` **n'est pas résolu en différé** : le xmlid référencé doit déjà
exister au moment où le fichier XML le contenant est chargé, même au sein d'un seul et même
module. `views/microfinance_geo_views.xml` référençait déjà `menu_microfinance_config` (défini
dans `microfinance_menus.xml`, chargé après lui dans le manifeste) — latent avant cette
réorganisation uniquement parce que ce xmlid pré-existait déjà en base sur les instances déjà
installées. L'ajout des 6 nouveaux sous-menus (référencés par `microfinance_geo_views.xml` dès
la même mise à jour) a fait échouer le chargement sur une base où ces nouveaux xmlids
n'existaient pas encore. **Corrigé en réordonnant le manifeste** : `microfinance_geo_views.xml`
est désormais chargé juste après `microfinance_menus.xml` (dernier fichier de la liste `data`)
plutôt qu'avant — toute action définie par ce fichier n'étant référencée par aucun autre
fichier du module, ce déplacement est sans risque. **Règle à retenir** : tout nouveau fichier de
vue ajoutant un `<menuitem parent="...">` vers un menu défini dans `microfinance_menus.xml` doit
être chargé (position dans le manifeste) après ce dernier.

### Vérification
Comparaison avant/après (nombre d'entrées, actions cibles) faite par script sur SEFOR, avec le
compte utilisateur réel de Micka (le compte technique `__system__` utilisé par le shell Odoo
n'appartenant pas au groupe métier `group_microfinance_manager`, il ne voit pas les entrées
restreintes à ce groupe — sans rapport avec la réorganisation, simplement un artefact du
compte utilisé pour vérifier) : 6 sous-groupes, 18 entrées au total, aucune perdue ni dupliquée,
mêmes actions cibles qu'avant.

## Règle de gouvernance — à respecter pour toute nouvelle entrée de configuration

> **Toute nouvelle entrée ajoutée au menu Microfinance > Configuration doit être rattachée à
> l'un des sous-groupes existants (Général, Crédit, Épargne, Financement, Géographie, Profil
> socio-économique) si elle y correspond naturellement. Si aucun groupe existant ne convient,
> créer un nouveau sous-groupe plutôt que d'ajouter l'entrée directement au niveau racine de
> Configuration — l'objectif est de ne jamais revenir à une liste plate de plus de 6-7 entrées
> à ce niveau.**

Cette règle s'applique à Micka comme à Claude Code sur tout futur chantier touchant à une
configuration du module.
