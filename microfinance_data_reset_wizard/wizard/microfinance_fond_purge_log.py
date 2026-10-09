# -*- coding: utf-8 -*-
"""Journal d'audit des purges de fonds : enregistrement CONSERVÉ (aucune clé étrangère vers les fonds, les
contributions, les partages ni les écritures : tout est figé en texte) qui survit à la purge."""
from odoo import fields, models


class MicrofinanceFondPurgeLog(models.Model):
    _name = 'microfinance.fond.purge.log'
    _description = 'Journal des purges de fonds'
    _order = 'date desc, id desc'

    name = fields.Char(string='Référence', required=True, readonly=True)
    date = fields.Datetime(string='Date', required=True, readonly=True, default=fields.Datetime.now)
    user_id = fields.Many2one('res.users', string='Utilisateur', readonly=True, ondelete='set null')
    user_name = fields.Char(string="Nom de l'utilisateur", readonly=True)
    state = fields.Selection([('done', 'Exécutée'), ('failed', 'Échec (rien modifié)')],
                             string='Résultat', required=True, readonly=True)
    companies = fields.Char(string='Sociétés touchées', readonly=True)
    scope = fields.Char(string='Périmètre', readonly=True)
    funds = fields.Text(string='Fonds', readonly=True)
    mode_raz = fields.Char(string='Mode de remise à zéro', readonly=True)
    move_mode = fields.Char(string='Écritures', readonly=True)
    options = fields.Char(string='Options', readonly=True)
    counts = fields.Text(string='Comptage par société et par modèle', readonly=True)
    balances_before = fields.Text(string='Soldes des comptes de bilan avant', readonly=True)
    balances_after = fields.Text(string='Soldes des comptes de bilan après', readonly=True)
    anomalies = fields.Text(string='Anomalies signalées', readonly=True)
    kept_moves = fields.Text(string='Écritures conservées (déliées des partages) et extournes créées', readonly=True)
    message = fields.Text(string='Message', readonly=True)
