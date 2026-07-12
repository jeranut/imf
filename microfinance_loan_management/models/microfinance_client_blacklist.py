# -*- coding: utf-8 -*-
from odoo import fields, models


class MicrofinanceClientBlacklist(models.Model):
    _name = 'microfinance.client.blacklist'
    _description = 'Entrée de liste noire client'

    partner_id = fields.Many2one('res.partner', string='Client', required=True, ondelete='cascade')
    reason = fields.Char(string='Motif', required=True)
    date_start = fields.Date(string='Date de début', default=fields.Date.context_today)
    date_end = fields.Date(string='Date de fin')
    active = fields.Boolean(string='Actif', default=True)
    notes = fields.Text(string='Notes')
