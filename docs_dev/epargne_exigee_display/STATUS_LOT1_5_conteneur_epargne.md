# Statut — Lot 1.5 : Migration (renumérotation + création rétroactive)

**Exécuté sur SEFOR (production), avec confirmation explicite de Micka avant écriture -
deux fois, la seconde après correction d'une prédiction erronée (cf. ci-dessous).**

## Incident sans conséquence : prédiction initiale des numéros incorrecte

Ma première table "avant → après" (numéros 000001/2/3) était fausse. Cause : j'avais lu la
colonne `ir_sequence.number_next`, qui **ne reflète pas l'état réel** d'une séquence en
implémentation `standard` - celui-ci vit dans un objet séquence PostgreSQL séparé
(`ir_sequence_<id>`), jamais synchronisé en retour vers cette colonne. En interrogeant
directement ces séquences, elles étaient déjà largement avancées (2718 pour le numéro
permanent, 38 pour le type I épargne) - vraisemblablement des données de test/démo créées puis
effacées via `microfinance_data_reset_wizard`, qui ne réinitialise jamais les séquences
PostgreSQL sous-jacentes.

Un premier script (avec assertions strictes sur les valeurs exactes prédites) a échoué
proprement sur ces assertions, **avant tout `commit()`** - vérifié en lecture seule : aucune
écriture n'a été persistée. Seul effet de bord, sans conséquence fonctionnelle : 2 valeurs de
séquence "brûlées" (2717, 2718, jamais assignées) - les séquences PostgreSQL n'annulent jamais
un `nextval()`, même sur rollback de la transaction appelante. Un second script, avec les mêmes
étapes mais des vérifications structurelles (unicité, cohérence) plutôt que des valeurs figées,
a ensuite été exécuté après confirmation de Micka sur les numéros réels corrigés.

## Résultat final (vérifié en lecture seule après commit)

| Partenaire | Numéro permanent | Compte réel (avant → après) | Conteneur créé |
|---|---|---|---|
| RANDRIAMISEZA (2555) | IS/000400 *(inchangé)* | IS/I/000400 → **IS/I/000039** | **IS/I/000400** |
| BM (235, bailleur) | *(aucun)* → **IS/002719** | IS/I/000012 → **IS/I/000040** | **IS/I/002719** |
| RANDRIANIRINA FERDINAND (7054) | *(aucun)* → **IS/002720** | IS/I/000038 → **IS/I/000041** | **IS/I/002720** |

3 nouveaux enregistrements conteneurs créés (ids 646, 647, 648) : `is_container=True`,
`product_id` vide, aucun solde ni transaction - conforme au Lot 1.2. Les 3 comptes réels
existants gardent leur solde/historique/transactions intacts (seul `name` a changé). Aucun
autre dossier touché.

## Recommandation distincte, hors périmètre de ce Lot

La désynchronisation `ir_sequence.number_next` vs séquence PostgreSQL réelle touche
potentiellement **toutes** les séquences `standard` du système (confirmé sur 3 : numéro
permanent, épargne type I, compte crédit conteneur) - sans risque de collision immédiat
(les séquences PostgreSQL réelles avancent toujours, jamais de retour en arrière), mais les
numéros visibles côté client sont désormais nettement plus élevés que ce que suggérerait une
lecture rapide de `ir_sequence` dans l'UI Odoo (Réglages > Technique > Séquences). Aucune action
requise, signalé pour information/vigilance future.

## Rappel

Migration de données pure - aucun changement de code dans ce Lot, donc aucun `-u`/restart
nécessaire. Reste l'étape finale du chantier : **Lot 1.6 (commit)**, à la charge de Micka après
revue complète du diff cumulé (Lots 1.1 à 1.5, hors cette migration de données elle-même,
indépendante de git).
