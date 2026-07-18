# -*- coding: utf-8 -*-
from odoo import fields, models


class MicrofinanceSocialCategoryLevel(models.Model):
    """Niveau de catégorisation sociale (Niv 1 à 8 sur la fiche papier), dérivé du total de
    points de la grille sociale (microfinance.loan.application.total_points) via ce modèle
    de référence à bornes éditables — même pattern que
    microfinance.loan.application.tier (rang de prêt -> libellé de palier)."""
    _name = 'microfinance.social.category.level'
    _description = 'Niveau de catégorisation sociale (grille de points)'
    _order = 'sequence, id'

    name = fields.Char(string='Libellé', required=True, translate=True)
    min_points = fields.Integer(string='Points minimum', required=True)
    max_points = fields.Integer(string='Points maximum', required=True)
    sequence = fields.Integer(string='Séquence', default=10)
    company_id = fields.Many2one(
        'res.company', string='Société',
        help='Laisser vide pour un barème commun à toutes les sociétés.',
    )
    active = fields.Boolean(string='Actif', default=True)
