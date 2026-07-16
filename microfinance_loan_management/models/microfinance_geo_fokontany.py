# -*- coding: utf-8 -*-
from odoo import models, fields, api


class MicrofinanceGeoFokontany(models.Model):
    """Fokontany (plus petite unité administrative malgache), toujours
    rattaché à une commune BCM (microfinance.geo.commune) — que cette
    commune soit une ville autonome (Fianarantsoa) ou un arrondissement
    d'une ville mère (Antananarivo I à VI). Le modèle n'a donc pas besoin
    de connaître la structure de la ville : il suffit de pointer vers la
    bonne commune BCM.
    """
    _name = 'microfinance.geo.fokontany'
    _description = 'Fokontany'
    _order = 'commune_id, name'
    _rec_name = 'display_name'

    name = fields.Char(string='Nom', required=True, index=True)
    postal_code = fields.Char(string='Code postal')
    commune_id = fields.Many2one(
        'microfinance.geo.commune', string='Commune', required=True,
        index=True, ondelete='restrict')

    # Champs relationnels pratiques pour filtres/rapports, sans dupliquer
    # la logique de structure (tout dérive de commune_id.parent_city_id)
    parent_city_id = fields.Many2one(
        related='commune_id.parent_city_id', string='Ville mère', store=True)
    unit_label = fields.Selection(related='commune_id.unit_label', store=True)

    active = fields.Boolean(default=True)
    display_name = fields.Char(compute='_compute_display_name', store=True)

    _sql_constraints = [
        ('name_commune_uniq', 'unique(name, commune_id)',
         "Ce fokontany existe déjà pour cette commune."),
    ]

    @api.depends('name', 'commune_id.display_name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.name} ({rec.commune_id.display_name})" \
                if rec.commune_id else rec.name
