# -*- coding: utf-8 -*-
from odoo import fields, models


class MicrofinanceBailleurFonds(models.Model):
    _name = 'microfinance.bailleur.fonds'
    _description = 'Bailleur de fonds microfinance'
    _order = 'name'

    name = fields.Char(string='Nom du bailleur', required=True)
    code = fields.Char(string='Code')
    active = fields.Boolean(string='Actif', default=True)
    note = fields.Text(string='Remarques')
