# -*- coding: utf-8 -*-
"""Diagnostic perf dashboard "Mon portefeuille" (sous-lot A) : microfinance.loan.officer_id et
.disbursement_date passent à index=True (cf. models/microfinance_loan.py) - toutes les
méthodes du portefeuille agent (_agent_portfolio_domain notamment) filtrent systématiquement
sur ces colonnes, non indexées jusqu'ici (seul `state` l'était). S'y ajoute un index composite
(company_id, officer_id, state), pas exprimable en `index=True` côté champ, pour la combinaison
de filtres réellement utilisée par _agent_portfolio_domain.

Exécuté en PRE-migrate (avant le check_indexes standard d'Odoo qui tourne pendant le chargement
du module, cf. odoo/modules/loading.py:load_module_graph -> migrate_module(package, 'pre') puis
seulement ensuite registry.load()) : les deux index simples sont créés ici en CONCURRENTLY sous
le même nom que celui qu'Odoo aurait généré (odoo.tools.sql.make_index_name), afin que
check_indexes les trouve déjà présents et n'émette pas son propre CREATE INDEX bloquant.
Toujours idempotent (index_exists() avant chaque création) : ré-exécuter l'upgrade ne recrée
rien.

Pas de gate applicatif (pas de dry-run) dans ce script : CREATE INDEX CONCURRENTLY ne pose pas
de verrou d'écriture par construction, donc rien à protéger derrière un flag - un flag n'aurait
de toute façon PAS empêché les deux index simples d'être créés en mode bloquant standard par le
check_indexes natif d'Odoo (index=True côté champ Python), puisque ce dernier n'a aucune notion
d'un tel flag. La seule protection réelle est procédurale : NE PAS exécuter cette mise à jour de
module (-u microfinance_loan_management) sur une base de production (SEFOR) sans confirmation
explicite de Micka au préalable - même en CONCURRENTLY, la construction d'un index sur une table
volumineuse consomme de l'I/O et peut prendre du temps, à planifier plutôt qu'à pousser
silencieusement. Cf. mémoire déploiement : redémarrer le service, puis lancer l'upgrade, toujours
après backup.

IMPORTANT (incident du 2026-09-26 corrigé ici) : `cr` (le curseur ambiant de la migration) reste
ouvert - Odoo ne le commit qu'en fin de chargement du module, pas au retour de `migrate()`. Tant
qu'il reste une transaction ouverte dessus, PostgreSQL fait attendre indéfiniment tout
`CREATE INDEX CONCURRENTLY` lancé sur une AUTRE connexion (CONCURRENTLY doit attendre que toutes
les transactions ayant un instantané de la table se terminent) - `cr` se bloque alors lui-même.
D'où le `cr.commit()` explicite juste avant d'ouvrir la connexion CONCURRENTLY ci-dessous : sans
danger ici (pre-migrate tourne avant tout changement de schéma/données de CE module pour cette
version, donc rien d'inachevé à perdre), indispensable pour que CONCURRENTLY puisse aboutir.
"""
import logging

import psycopg2.extensions

import odoo
from odoo.tools import sql

_logger = logging.getLogger(__name__)

# (indexname, table, expression SQL des colonnes) - les deux premiers noms suivent exactement
# la convention odoo.tools.sql.make_index_name("microfinance_loan", "<colonne>") pour que le
# check_indexes natif d'Odoo (odoo/modules/registry.py) les reconnaisse comme déjà présents.
_INDEXES = [
    ('microfinance_loan__officer_id_index', 'microfinance_loan', 'officer_id'),
    ('microfinance_loan__disbursement_date_index', 'microfinance_loan', 'disbursement_date'),
    # Composite : pas de déclaration ORM équivalente à index=True pour plusieurs colonnes -
    # nom libre, couvre exactement le triplet filtré ensemble par _agent_portfolio_domain.
    ('microfinance_loan_agent_portfolio_idx', 'microfinance_loan', 'company_id, officer_id, state'),
]


def migrate(cr, version):
    cr.execute("SELECT reltuples::bigint FROM pg_class WHERE relname = 'microfinance_loan'")
    row = cr.fetchone()
    approx_rows = row[0] if row else 0

    to_create = [(name, table, cols) for name, table, cols in _INDEXES if not sql.index_exists(cr, name)]
    if not to_create:
        _logger.info(
            "Microfinance (index portefeuille agent) : les %d index attendus sont déjà présents "
            "- rien à faire.", len(_INDEXES),
        )
        return

    names = ", ".join(name for name, _, _ in to_create)
    _logger.warning(
        "Microfinance (index portefeuille agent) : création de %d index en CONCURRENTLY sur "
        "microfinance_loan (~%d lignes estimées) : %s. Rappel : ne pas lancer cette mise à jour "
        "sur SEFOR sans feu vert explicite de Micka.",
        len(to_create), approx_rows, names,
    )
    # Indispensable : sans ce commit, `cr` reste "idle in transaction" et bloque indéfiniment
    # chaque CREATE INDEX CONCURRENTLY ci-dessous (cf. note "IMPORTANT" en tête de fichier).
    cr.commit()
    connection = odoo.sql_db.db_connect(cr.dbname)
    concurrent_cr = connection.cursor()
    try:
        concurrent_cr._cnx.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        for indexname, table, columns in to_create:
            if sql.index_exists(concurrent_cr, indexname):
                continue
            _logger.info(
                "Microfinance (index portefeuille agent) : CREATE INDEX CONCURRENTLY %s ON "
                "%s(%s)...", indexname, table, columns,
            )
            concurrent_cr.execute(
                'CREATE INDEX CONCURRENTLY "%s" ON %s (%s)' % (indexname, table, columns)
            )
            _logger.info("Microfinance (index portefeuille agent) : %s créé.", indexname)
    finally:
        concurrent_cr.close()
