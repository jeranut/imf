# -*- coding: utf-8 -*-
from odoo import models, fields


class MicrofinanceGeoRegion(models.Model):
    """Région administrative (référentiel Loi n°2018-011, mis à jour par
    les Lois n°2021-012 et n°2023-012). 21 régions actuellement recensées
    dans le référentiel — Madagascar en compte 23 au total, les 2 régions
    manquantes n'apparaissant pas dans le fichier source fourni."""
    _name = 'microfinance.geo.region'
    _description = 'Région (référentiel administratif)'
    _order = 'name'

    name = fields.Char(string='Nom', required=True, index=True)
    district_ids = fields.One2many(
        'microfinance.geo.district', 'region_id', string='Districts')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('name_uniq', 'unique(name)', "Cette région existe déjà."),
    ]
