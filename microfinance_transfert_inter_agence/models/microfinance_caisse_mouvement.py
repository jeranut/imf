# -*- coding: utf-8 -*-
from odoo import fields, models


class MicrofinanceCaisseMouvement(models.Model):
    """Deux nouveaux types de ligne de ticket pour tracer un transfert inter-agences
    dans la caisse de chaque agence concernée :

      - ``transfert_sortant`` : créé dans la session SOURCE au moment de
        l'encaissement (l'argent entre dans le coffre source) ;
      - ``transfert_entrant`` : créé dans la session DESTINATION au moment de la
        validation (l'argent entre dans le coffre destination et le remboursement
        est comptabilisé).

    Ces lignes restent cloisonnées mono-agence (``company_id`` = société de la
    session, comme tous les autres mouvements) : la visibilité croisée source ↔
    destination est portée par ``microfinance.transfert.remboursement`` lui-même.
    """
    _inherit = 'microfinance.caisse.mouvement'

    type = fields.Selection(
        selection_add=[
            ('transfert_sortant', "Transfert inter-agences (encaissement)"),
            ('transfert_entrant', "Transfert inter-agences (validation)"),
        ],
        ondelete={'transfert_sortant': 'cascade', 'transfert_entrant': 'cascade'},
    )
    transfert_remboursement_id = fields.Many2one(
        'microfinance.transfert.remboursement', string='Transfert inter-agences',
        readonly=True, copy=False, index=True,
        help="Transfert de remboursement crédit inter-agences que cette ligne de "
             "caisse trace (côté source pour transfert_sortant, côté destination "
             "pour transfert_entrant).",
    )
