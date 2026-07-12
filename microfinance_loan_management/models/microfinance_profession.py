# -*- coding: utf-8 -*-
from odoo import fields, models


class MicrofinanceProfession(models.Model):
    _name = 'microfinance.profession'
    _description = 'Profession (référentiel microfinance)'
    _order = 'name'

    name = fields.Char(string='Profession', required=True)
    active = fields.Boolean(string='Actif', default=True)

    _sql_constraints = [
        ('name_unique', 'unique(name)', 'Cette profession existe déjà.'),
    ]
