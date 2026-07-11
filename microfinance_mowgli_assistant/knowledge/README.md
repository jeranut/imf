# Datasets MOWGLI

Ce dossier ne contient aucun dataset metier.

Le format officiel de connaissance MOWGLI est YAML. Un fichier ZIP n'est pas un format de connaissance : c'est seulement un moyen optionnel de deposer plusieurs fichiers `dataset.yaml` dans le dossier externe configure.

Le module `microfinance_mowgli_assistant` fournit uniquement le moteur Knowledge. Les datasets doivent etre stockes dans un dossier externe configure dans Odoo, par exemple :

```text
/opt/mowgli-datasets
/home/odoo/mowgli_datasets
```

Le chemin se configure dans Odoo :

```text
Parametres > MOWGLI > Chemin des datasets MOWGLI
```

## Structure attendue

Le moteur parcourt recursivement le dossier externe et importe chaque fichier nomme `dataset.yaml`. L'extension `dataset.yml` est aussi acceptee, mais `dataset.yaml` reste la convention recommandee.

Depuis la version multi-fichiers, `dataset.yaml` peut etre soit :

- un dataset complet, comme auparavant ;
- un manifeste qui declare une liste `imports` de fichiers YAML du meme dossier de workflow.

Exemple :

```text
/opt/mowgli-datasets/
    creation_produit_credit/
        dataset.yaml
        01_workflow.yaml
        02_produits.yaml
        15_faq.yaml
    creation_produit_epargne/
        dataset.yaml
    garanties_scoring/
        dataset.yaml
    reechelonnement/
        dataset.yaml
    dossier_precredit/
        dataset.yaml
    comptabilite/
        dataset.yaml
```

Chaque dossier de workflow doit contenir un unique `dataset.yaml`. Les autres fichiers YAML sont lus uniquement s'ils sont declares dans `imports`.

## Format manifeste multi-fichiers

Exemple de `creation_produit_credit/dataset.yaml` :

```yaml
workflow:
  code: creation_produit_credit
  name: Création produit de crédit
  version: "17.0"
  description: Workflow complet de création des produits de crédit CEFOR.

imports:
  - 01_workflow.yaml
  - 02_produits.yaml
  - 15_faq.yaml
```

Exemple de fichier importe `creation_produit_credit/02_produits.yaml` :

```yaml
categories:
  - code: produit_credit
    name: Produit de crédit

articles:
  - id: creation_produit_credit_create
    category: produit_credit
    title: Créer un produit de crédit
    questions:
      - Comment créer un produit de crédit ?
      - Nouveau produit de crédit
    answer: |
      <p>Créer le produit depuis Microfinance > Configuration > Produits de crédit.</p>
    keywords:
      - produit
      - credit
    suggested: true
    priority: 100

links:
  - id: creation_produit_credit_link_001
    article: creation_produit_credit_create
    title: Ouvrir les produits de crédit
    url: /web#menu_id=...
```

Les `categories`, `articles`, `faq` et `links` de tous les fichiers importes sont fusionnes avant synchronisation.

Si `dataset.yaml` ne contient pas `imports`, le moteur conserve le comportement historique et importe directement les blocs `categories`, `articles`, `faq` et `links` contenus dans ce fichier.

## Regles d'import

- Si aucun chemin n'est configure, aucun dataset n'est importe et aucune erreur n'est generee.
- Si le chemin configure ne contient aucun `dataset.yaml` ou `dataset.yml`, aucun workflow ni article n'est cree.
- Le moteur cree les nouveaux enregistrements et met a jour les enregistrements existants.
- La cle d'un workflow est le champ `workflow` ou `workflow.code`.
- La cle d'un article est le couple `workflow` + `external_id` ou `id`.
- La cle d'une categorie est le couple `workflow` + `category.name`.
- Les liens sont dedoublonnes par article et URL.
- Les mots-cles sont dedoublonnes par article et libelle.
- Les images, captures d'ecran, videos YouTube, documents PDF et pieces jointes ne sont jamais importes, modifies ni supprimes par la synchronisation.
- Une erreur dans un dataset est reportee dans le rapport final sans bloquer les autres datasets.

Regles de securite pour `imports` :

- les chemins absolus sont refuses ;
- les chemins contenant `../` sont refuses ;
- les chemins Windows ou avec antislash sont refuses ;
- seuls les fichiers `.yaml` et `.yml` sont acceptes ;
- un import ne peut jamais sortir du dossier du workflow ;
- si un fichier importe est absent, le rapport indique `Fichier import introuvable` et les autres fichiers continuent a etre importes.

La synchronisation se lance depuis :

```text
MOWGLI > Synchronisation > Synchroniser les datasets
```

## Import ZIP optionnel

L'assistant `MOWGLI > Synchronisation` propose aussi `Importer un ZIP de datasets`.

Le ZIP doit contenir une arborescence de dossiers avec des fichiers YAML, par exemple :

```text
creation_produit_credit/dataset.yaml
creation_produit_epargne/dataset.yaml
garanties_scoring/dataset.yaml
comptabilite/dataset.yaml
README.md
```

Le systeme extrait le ZIP dans le dossier externe configure, puis lance automatiquement la synchronisation des `dataset.yaml` et `dataset.yml`.

Regles de securite ZIP :

- les chemins absolus sont refuses ;
- les chemins contenant `../` sont refuses ;
- toute extraction hors du dossier configure est refusee ;
- les chemins Windows ou avec antislash sont refuses ;
- seuls les fichiers `.yaml`, `.yml` et `README.md` sont acceptes ;
- les images, PDF et autres fichiers binaires ne sont jamais extraits ni importes.

## Format YAML

Exemple minimal :

```yaml
workflow: creation_produit_credit
name: Création produit de crédit
version: "17.0"
description: Workflow Création produit de crédit CEFOR.
sequence: 10
roles:
  - agent_credit
  - gestionnaire
categories:
  - name: Produit de crédit
    sequence: 10
articles:
  - id: creation_produit_credit-001
    title: Créer un produit de crédit
    category: Produit de crédit
    difficulty: beginner
    roles:
      - agent_credit
    suggested: true
    priority: 10
    question: Comment créer un produit de crédit ?
    answer: >
      <p>Réponse validée.</p>
    keywords:
      - produit
      - credit
    links:
      - url: https://example.com/guide-produit-credit
        title: Guide produit de crédit
        description: Documentation interne
    guide_anchor: creation-produit-credit
    source_reference: guide_produit_credit
    related_questions:
      - creation_produit_credit-002
faq:
  - id: creation_produit_credit-faq-001
    question: Où configurer les comptes comptables d'un produit de crédit ?
    answer: >
      <p>Depuis l'onglet Comptabilité du produit de crédit.</p>
    keywords:
      - compte
      - comptabilite
```

## Champs racine

- `workflow` : code technique du workflow. Obligatoire.
- `name` : nom affiche du workflow.
- `version` : version du dataset.
- `description` : description du workflow.
- `sequence` : ordre d'affichage.
- `roles` ou `groups` : roles ou groupes autorises au niveau workflow.
- `categories` : liste des categories.
- `articles` : liste des articles.
- `faq` : liste optionnelle de questions/reponses importees comme articles FAQ.
- `imports` : liste optionnelle de fichiers YAML a fusionner dans le cas d'un manifeste.

## Champs categorie

- `name` : nom de la categorie. Obligatoire.
- `sequence` : ordre d'affichage.
- `active` : actif ou non.

## Champs article et FAQ

- `id` : identifiant stable dans le workflow. Obligatoire pour les articles.
- `title` : titre affiche. Si absent, la question est utilisee.
- `category` : categorie rattachee.
- `difficulty` : `beginner`, `intermediate` ou `advanced`.
- `roles` : roles ou groupes autorises sur l'article.
- `suggested` : rend la question eligible aux suggestions.
- `priority` : priorite de recherche et de suggestion.
- `question` : question utilisateur.
- `questions` : formulations multiples. Si present, la premiere formulation devient la question principale.
- `answer` : reponse HTML validee.
- `keywords` : mots-cles de recherche.
- `youtube` : ancien champ conserve pour compatibilite, ignore par la synchronisation.
- `links` ou `liens` : liens utiles.
- `guide_anchor` : ancre de guide optionnelle.
- `source_reference` : reference de validation.
- `related_questions` : IDs d'articles lies dans le meme workflow.
- `active` : actif ou non.

## Champs lien

- `url` : URL. Obligatoire.
- `title` : titre affiche.
- `description` : description courte.
- `sequence` : ordre d'affichage.
- `active` : actif ou non.

## Rapport d'import

Le bouton de synchronisation affiche un rapport :

```text
Import termine

✓ Workflows crees
✓ Workflows mis a jour
✓ Fichiers YAML lus
✓ Fichiers YAML absents
✓ Categories creees
✓ Categories mises a jour
✓ Articles crees
✓ Articles mis a jour
✓ Articles ignores
✓ Medias conserves
✓ FAQ creees / mises a jour
✓ Liens crees / mis a jour
✓ Mots-cles
✓ Erreurs
```

## Medias

Les images, captures d'ecran, videos YouTube, documents PDF et pieces jointes ne font pas partie des datasets YAML et ne sont pas importes depuis les ZIP. Ils restent configures manuellement dans Odoo sur les articles MOWGLI.

Une nouvelle synchronisation peut mettre a jour le texte de l'article, ses mots-cles et ses liens metier, mais elle conserve les medias deja associes.
