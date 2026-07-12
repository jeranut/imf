# Guide utilisateur MOWGLI

## Consulter MOWGLI

Ouvrez le chat Discuss avec MOWGLI et posez une question métier. MOWGLI répond dans cet ordre :

1. réponse texte ;
2. images ajoutées sur l'article ;
3. vidéos YouTube ;
4. documents PDF ;
5. liens utiles ;
6. questions similaires ;
7. lien vers le guide si un ancrage existe.

## Questions suggérées

MOWGLI peut proposer jusqu'à 15 questions suggérées selon les groupes de l'utilisateur et les workflows autorisés. Une question n'est proposée que si l'utilisateur a aussi le droit de voir la réponse.

## Synchroniser les datasets

Ouvrez :

```text
MOWGLI > Synchronisation
```

Cliquez sur `Synchroniser les datasets MOWGLI`.

La synchronisation lit le dossier externe configuré dans `Paramètres > MOWGLI > Chemin des datasets MOWGLI`.

Dans les paramètres MOWGLI, le bouton `Créer l’arborescence datasets` crée les dossiers standards et les fichiers `dataset.yaml` minimaux s'ils n'existent pas déjà. Les datasets existants ne sont jamais écrasés.

Si aucun chemin n'est configuré, le bouton affiche `Veuillez configurer le chemin des datasets MOWGLI dans les paramètres.`

Si le dossier configuré ne contient aucun `dataset.yaml` ou `dataset.yml`, aucun article n'est créé et le bouton affiche `Aucun dataset trouvé.`

## Importer un ZIP de datasets

Le format officiel reste YAML. Le ZIP sert uniquement à déposer plusieurs fichiers `dataset.yaml` en une seule opération.

Dans `MOWGLI > Synchronisation`, chargez un fichier `.zip`, puis cliquez sur `Importer un ZIP de datasets`. Le système extrait les fichiers YAML autorisés dans le dossier externe configuré, puis lance automatiquement la synchronisation.

Le ZIP ne doit contenir que des fichiers `.yaml`, `.yml` ou `README.md`. Les images, vidéos YouTube, documents PDF et pièces jointes ne sont jamais importés par ZIP et restent ajoutés manuellement dans Odoo.

## Ajouter une image

Ouvrez un article dans :

```text
MOWGLI > Articles
```

Dans l'onglet Images, ajoutez l'image, son titre, sa légende et sa séquence. Les images sont conservées lors des prochaines synchronisations.

## Ajouter une vidéo YouTube

Ouvrez l'article, onglet Vidéos YouTube, puis renseignez le titre, l'URL YouTube, la durée et la séquence.

## Ajouter un document PDF

Ouvrez l'article, onglet Documents PDF, puis chargez le fichier, son nom, sa description et sa séquence.

Les documents PDF sont aussi accessibles depuis `MOWGLI > Médias > Documents PDF`.

## Ajouter un lien utile

Ouvrez l'article, onglet Liens, puis renseignez le titre, l'URL, la description et la séquence.

## Traiter une question sans réponse

Ouvrez :

```text
MOWGLI > Questions sans réponse
```

Vous pouvez analyser la question, créer un article, lier un article existant, marquer la question comme traitée ou l'ignorer.

## Historique

Par défaut, l'historique du canal MOWGLI de l'utilisateur est effacé à chaque connexion. Les autres discussions, articles, médias et questions sans réponse ne sont pas supprimés.
