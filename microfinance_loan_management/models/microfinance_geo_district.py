# -*- coding: utf-8 -*-
from odoo import api, models, fields


class MicrofinanceGeoDistrict(models.Model):
    """District administratif, rattaché à une région. 112 districts
    recensés dans le référentiel source (Loi n°2018-011 et mises à jour)."""
    _name = 'microfinance.geo.district'
    _description = 'District (référentiel administratif)'
    _order = 'region_id, name'
    _rec_name = 'display_name'

    name = fields.Char(string='Nom', required=True, index=True)
    region_id = fields.Many2one(
        'microfinance.geo.region', string='Région', required=True,
        index=True, ondelete='restrict')
    commune_ids = fields.One2many(
        'microfinance.geo.commune', 'district_id', string='Communes')
    active = fields.Boolean(default=True)
    display_name = fields.Char(compute='_compute_display_name', store=True)

    _sql_constraints = [
        ('name_region_uniq', 'unique(name, region_id)',
         "Ce district existe déjà pour cette région."),
    ]

    @api.depends('name', 'region_id.name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.name} ({rec.region_id.name})" \
                if rec.region_id else rec.name
