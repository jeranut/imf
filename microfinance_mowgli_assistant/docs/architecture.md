# Architecture MOWGLI Knowledge

## Principe

MOWGLI sépare les modules techniques Odoo des workflows métier. Un workflow peut couvrir plusieurs modules, mais l'utilisateur voit uniquement le workflow.

Exemple : le workflow Création produit de crédit peut utiliser `microfinance_loan_management` (produit de crédit, comptes PCEC, journaux) sans que MOWGLI n'en dépende techniquement — MOWGLI n'a aucune dépendance dure sur les modules microfinance.

## Modèles

- `mowgli.knowledge.workflow` : workflow métier, code, description, groupes.
- `mowgli.knowledge.category` : catégories internes au workflow.
- `mowgli.knowledge.article` : question/réponse validée.
- `mowgli.knowledge.keyword` : mots-clés de recherche.
- `mowgli.knowledge.image` : images ajoutées manuellement dans Odoo.
- `mowgli.knowledge.video` : vidéos YouTube ajoutées manuellement dans Odoo.
- `mowgli.knowledge.document` : documents PDF ajoutés manuellement dans Odoo.
- `mowgli.knowledge.link` : liens utiles importés depuis les datasets.
- `mowgli.knowledge.unanswered.question` : questions non répondues.
- `mowgli.knowledge.sync.wizard` : bouton de synchronisation.

## Source des datasets

Le module ne contient aucun dataset métier. Le moteur lit uniquement le dossier externe configuré par le paramètre `microfinance_mowgli_assistant.mowgli_dataset_path`.

Le scanner parcourt récursivement ce dossier et importe chaque fichier `dataset.yaml` ou `dataset.yml` trouvé. Si le paramètre est vide, l'assistant demande de configurer le chemin. Si aucun dataset n'est présent, la synchronisation ne crée aucun contenu et ne génère pas d'erreur.

Le ZIP est uniquement un moyen de dépôt optionnel. L'assistant ZIP extrait des fichiers YAML autorisés dans le dossier externe, refuse les chemins dangereux et lance ensuite la synchronisation standard.

Les datasets ne pilotent que la connaissance métier textuelle : workflows, catégories, articles, FAQ, mots-clés, liens métier et questions liées. Les médias restent administrés depuis Odoo et sont conservés lors des resynchronisations.

## Recherche

Le moteur calcule un score à partir de :

- question ;
- titre ;
- mots-clés ;
- réponse ;
- workflow ;
- catégorie ;
- groupes de l'utilisateur.

Le seuil par défaut est `0.45` via le paramètre `microfinance_mowgli_assistant.mowgli_min_score`.

## Assistant Discuss

Le modèle `mowgli.bot.assistant` (abstrait) porte uniquement la glue Discuss : groupes de rôles, utilisateur bot, canaux de chat et point d'entrée `render_reply` qui délègue au moteur Knowledge. MOWGLI ne comporte aucun moteur de réponse historique par mots-clés : le moteur Knowledge est la seule source de réponse.

## Historique de chat

Le modèle `res.users.log` déclenche le nettoyage du canal MOWGLI à la connexion si `mowgli_auto_clear_history` est actif. Seuls les messages du canal de chat entre l'utilisateur et MOWGLI sont supprimés.
