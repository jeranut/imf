MOWGLI - Assistant métier CEFOR
================================

MOWGLI est le centre d'aide officiel CEFOR. Il répond depuis une base de connaissances métier organisée par workflows et importée depuis un dossier externe configurable.

Workflows
---------

- Création produit de crédit
- Création produit d'épargne
- Garanties et scoring
- Rééchelonnement
- Dossier précrédit
- Comptabilité
- PAR et reporting
- Administration

Les modules Odoo restent techniques (``microfinance_loan_management``, ``microfinance_savings_management``). Les utilisateurs voient seulement les workflows métier.

Source de connaissance
----------------------

MOWGLI ne lit pas automatiquement les ``README.md`` ni les ``USER_GUIDE.md``.

La source principale est le dataset YAML de chaque workflow. Le YAML est le format officiel de connaissance MOWGLI. Le dossier racine se configure dans Odoo, par exemple ``/opt/mowgli-datasets``.

::

    <chemin_configure>/<workflow>/dataset.yaml

Les médias ne sont jamais importés depuis les datasets YAML ni depuis les ZIP. Images, vidéos YouTube, documents PDF et pièces jointes sont ajoutés manuellement dans Odoo sur la fiche article.

Un ZIP peut être importé depuis ``MOWGLI > Synchronisation``, mais il sert uniquement de moyen de transport : il doit contenir des fichiers YAML et le système les extrait dans le dossier externe avant de lancer la synchronisation.

Synchronisation
---------------

Menu :

::

    MOWGLI > Synchronisation > Synchroniser les datasets MOWGLI

La synchronisation est idempotente : elle crée ou met à jour workflows, catégories, articles, formulations de questions, mots-clés, liens métier, FAQ et questions liées sans modifier les médias manuels.

Le moteur accepte l'ancien format :

::

    question: Comment créer un bien ?

Il accepte aussi le format enrichi :

::

    questions:
      - Comment créer un bien ?
      - Créer un bien
      - Nouveau bien

Toutes les formulations pointent vers le même article.

Réponse MOWGLI
-----------

MOWGLI cherche dans la base Knowledge. Si aucun article validé n'est trouvé avec un score suffisant, la question est enregistrée dans ``MOWGLI > Questions sans réponse``.

La recherche tient compte des formulations multiples, du titre, de la réponse, des mots-clés, de la catégorie et du workflow.

Suggestions dans Discuss
------------------------

Les articles avec ``suggested: true`` peuvent apparaître dans la conversation MOWGLI. Les suggestions sont filtrées par les rôles et groupes Microfinance de l'utilisateur, puis triées par ``priority`` décroissante.

À l'ouverture du chat MOWGLI, MOWGLI vide la session de cet utilisateur si l'option est active, puis poste un bloc ``Questions suggérées`` avec au maximum 15 questions copiables. Cette première version privilégie un affichage fiable ; le clic interactif pourra être ajouté ensuite.

Rôles et médias
---------------

Le champ ``roles`` accepte ``agent_credit``, ``agent_epargne``, ``caissier``, ``comptable``, ``credit_committee``, ``gestionnaire`` et ``admin``.

Les champs ``images``, ``videos`` et ``documents`` peuvent rester dans le YAML comme références, mais ils ne déclenchent aucun import automatique. Les médias attachés manuellement dans Odoo sont conservés à chaque synchronisation.
