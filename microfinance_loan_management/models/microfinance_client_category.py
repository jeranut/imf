# -*- coding: utf-8 -*-
from odoo import fields, models


class MicrofinanceClientCategory(models.Model):
    _name = 'microfinance.client.category'
    _description = 'Catégorie de classification client'

    name = fields.Char(string='Nom', required=True)
    active = fields.Boolean(string='Actif', default=True)

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Cette catégorie existe déjà.'),
    ]
