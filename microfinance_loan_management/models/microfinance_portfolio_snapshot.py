# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MicrofinancePortfolioSnapshot(models.Model):
    """Instantané mensuel du PAR cumulatif par agent (et par agence), figé le 1ᵉʳ du mois par
    le cron `cron_snapshot_portfolio_par`. Seule source de l'historique alimentant le graphe
    d'évolution du PAR du dashboard portefeuille par agent (Lot 2). Aucune donnée n'existe tant
    que le cron n'a pas tourné au moins une fois : le graphe se peuple mois après mois."""
    _name = 'microfinance.portfolio.snapshot'
    _description = 'Instantané mensuel du PAR par agent'
    _order = 'date desc, company_id, officer_id'

    date = fields.Date(string='Date (1ᵉʳ du mois)', required=True, index=True)
    officer_id = fields.Many2one('res.users', string='Agent crédit', required=True, index=True)
    company_id = fields.Many2one('res.company', string='Agence', required=True, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)
    par30 = fields.Float(string='PAR 30 (%)', digits=(16, 2))
    par60 = fields.Float(string='PAR 60 (%)', digits=(16, 2))
    par90 = fields.Float(string='PAR 90 (%)', digits=(16, 2))
    par120 = fields.Float(string='PAR 120 (%)', digits=(16, 2))
    outstanding_total = fields.Monetary(string='Encours total figé')

    _sql_constraints = [
        ('date_officer_company_unique', 'unique(date, officer_id, company_id)',
         'Un instantané existe déjà pour cet agent, cette agence et ce mois.'),
    ]

    @api.model
    def _cron_capture_date(self):
        """1ᵉʳ jour du mois courant (le cron tourne mensuellement, en début de mois)."""
        return fields.Date.context_today(self).replace(day=1)
