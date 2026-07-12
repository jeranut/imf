# Format dataset MOWGLI

Le format officiel de connaissance MOWGLI est YAML. Un fichier ZIP n'est pas un format de dataset : c'est uniquement un moyen optionnel de transporter plusieurs fichiers YAML.

Chaque workflow possède un fichier :

```text
<chemin_configure>/<workflow>/dataset.yaml
```

Le chemin racine est configuré dans Odoo via `Paramètres > MOWGLI > Chemin des datasets MOWGLI`.

## Exemple

```yaml
workflow: creation_produit_credit
name: Création produit de crédit
version: "17.0"
description: Workflow métier Création produit de crédit CEFOR.
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
      - gestionnaire
    suggested: true
    priority: 100
    questions:
      - Comment créer un produit de crédit ?
      - Créer un produit de crédit
      - Nouveau produit de crédit
    menu: Microfinance > Configuration > Produits de crédit
    model: microfinance.loan.product
    prerequisites:
      - Plan comptable PCEC chargé pour la société
    steps:
      - Ouvrir Microfinance > Configuration > Produits de crédit
      - Créer le produit et renseigner nom, code, montants et durées
    tips: Les comptes PCEC et journaux se pré-remplissent automatiquement par défaut.
    errors: Un produit sans compte principal configuré ne peut pas être utilisé pour décaisser un crédit.
    answer: >
      <p>Depuis Microfinance > Configuration > Produits de crédit, créez un nouveau produit...</p>
    keywords:
      - produit
      - crédit
    links:
      - url: https://example.com/guide-produit-credit
        title: Guide produit de crédit
    guide_anchor: creation-produit-credit
    source_reference: microfinance_loan_management
    see_also:
      - creation_produit_credit-002
faq:
  - id: creation_produit_credit-faq-001
    question: Où configurer les comptes comptables d'un produit de crédit ?
    answer: >
      <p>Depuis l'onglet Comptabilité du produit de crédit.</p>
    keywords:
      - compte
      - comptabilité
```

## Règles

- `workflow` est obligatoire.
- `articles[].id` est obligatoire et unique dans le workflow.
- `question` reste accepté pour les anciens datasets.
- `questions` peut remplacer `question` et contenir plusieurs formulations. Toutes pointent vers le même article.
- `answer` est le contenu HTML de réponse. S'il est absent, l'article est importé avec une réponse vide pour ne pas bloquer la synchronisation.
- `keywords` améliore le score de recherche.
- `roles` limite l'article à des groupes CEFOR. Valeurs acceptées : `agent_credit`, `agent_epargne`, `caissier`, `comptable`, `credit_committee`, `gestionnaire`, `admin`.
- `suggested: true` rend l'article éligible aux questions suggérées dans Discuss.
- `priority` trie les suggestions : une priorité élevée apparaît avant une priorité plus faible.
- `see_also` référence les IDs d'articles liés et apparaît en réponse sous `Voir aussi`.
- `menu` et `model` sont informatifs pour afficher le chemin Odoo et le modèle cible.
- `prerequisites`, `steps`, `tips` et `errors` sont optionnels et affichés avec la réponse.
- `youtube` est un ancien champ accepté pour compatibilité, mais il est ignoré par la synchronisation. Les vidéos se gèrent dans Odoo.
- `links` ou `liens` peut contenir des URL simples ou des objets avec titre, URL, description.
- `faq` contient des questions/réponses importées comme articles FAQ.
- `related_questions` reste accepté comme alias historique de `see_also`.
- `images`, `videos` et `documents` sont acceptés comme références, mais ne sont jamais importés automatiquement.
- Les images, vidéos YouTube, documents PDF et pièces jointes restent ajoutés manuellement sur l'article MOWGLI dans Odoo.

## Import ZIP optionnel

L'assistant `MOWGLI > Synchronisation > Importer un ZIP de datasets` extrait le ZIP dans le dossier externe configuré, puis lance la synchronisation YAML.

Le ZIP doit respecter les règles suivantes :

- chemins absolus interdits ;
- chemins contenant `../` interdits ;
- extraction hors du dossier configuré interdite ;
- seuls `.yaml`, `.yml` et `README.md` sont acceptés ;
- les images, PDF et fichiers binaires ne sont pas acceptés.

## Synchronisation

La synchronisation :

- crée ou met à jour les workflows ;
- crée ou met à jour les catégories ;
- crée ou met à jour les articles ;
- remplace les mots-clés et liens déclarés dans le YAML ;
- remplace les formulations déclarées dans `questions` ou `question` ;
- met à jour les questions liées via `see_also` ou `related_questions` ;
- ne crée, modifie ni supprime jamais les images, vidéos YouTube, documents PDF ou pièces jointes ajoutés dans Odoo ;
- conserve les questions sans réponse.

## Discuss

Quand l'utilisateur ouvre la conversation MOWGLI, le canal MOWGLI de cet utilisateur est vidé si l'option de session temporaire est active, puis MOWGLI poste jusqu'à 15 questions suggérées adaptées à ses groupes et workflows autorisés.

Les suggestions viennent uniquement des articles importés avec `suggested: true`. Une suggestion n'est jamais affichée si l'utilisateur ne peut pas voir la réponse.
