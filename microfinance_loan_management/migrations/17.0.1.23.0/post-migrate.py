# -*- coding: utf-8 -*-
"""R1/R2 (AUDIT_portefeuille_agent.md, Phase 2 correction §1) : le modèle microfinance.portfolio
est nouveau dans cette version. Backfill NON destructif - CREATE uniquement, aucune donnée
existante modifiée ni supprimée - d'un portefeuille (agent_id, company_id) par couple déjà présent
sur microfinance.loan.officer_id/company_id. amount_allocated reste à 0 : c'est au gestionnaire de
chaque agence de répartir ensuite le fonds reçu via « Répartition du fonds d'agence » (microfinance.
portfolio.allocation). Idempotent : un portefeuille déjà existant pour un couple (reprise d'upgrade,
création manuelle anticipée) n'est jamais recréé ni modifié.

Doublons : aucune fusion automatique (consigne explicite). Un « doublon » ici ne peut pas être un
conflit de contrainte SQL (agent_id, company_id) puisque create() ne s'exécute que pour des couples
distincts issus d'un GROUP BY - mais un même agent physique représenté par DEUX comptes res.users
distincts (compte recréé historiquement) produirait deux portefeuilles séparés pour la même
personne. Ce script détecte ce cas (même nom de partenaire, officer_id différents) et le journalise
sans y toucher : à vérifier/fusionner manuellement si le rapport en liste."""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Portfolio = env['microfinance.portfolio']

    cr.execute("""
        SELECT DISTINCT officer_id, company_id
        FROM microfinance_loan
        WHERE officer_id IS NOT NULL AND company_id IS NOT NULL
    """)
    pairs = cr.fetchall()

    created = 0
    for officer_id, company_id in pairs:
        if Portfolio.search_count([('agent_id', '=', officer_id), ('company_id', '=', company_id)]):
            continue
        Portfolio.create({'agent_id': officer_id, 'company_id': company_id})
        created += 1

    cr.execute("""
        SELECT p.name, array_agg(DISTINCT u.id) AS user_ids
        FROM microfinance_loan l
        JOIN res_users u ON u.id = l.officer_id
        JOIN res_partner p ON p.id = u.partner_id
        WHERE l.officer_id IS NOT NULL
        GROUP BY p.name
        HAVING count(DISTINCT u.id) > 1
    """)
    duplicate_identities = cr.fetchall()

    _logger.info(
        "Microfinance (portefeuilles agent, R1/R2) : %d portefeuille(s) créé(s) pour %d "
        "couple(s) (agent, agence) distincts trouvés sur les crédits existants.",
        created, len(pairs),
    )
    if duplicate_identities:
        _logger.warning(
            "Microfinance (portefeuilles agent) : %d nom(s) de partenaire partagé(s) par "
            "plusieurs comptes agent distincts (doublon d'identité possible, à vérifier "
            "manuellement - AUCUNE fusion automatique) : %s",
            len(duplicate_identities),
            ', '.join('%s (user_ids=%s)' % (name, ids) for name, ids in duplicate_identities),
        )
    else:
        _logger.info(
            "Microfinance (portefeuilles agent) : aucun doublon d'identité agent détecté.")
