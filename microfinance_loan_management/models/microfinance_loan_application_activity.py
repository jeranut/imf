# -*- coding: utf-8 -*-
from odoo import fields, models


class MicrofinanceLoanApplicationActivityCategory(models.Model):
    """Catégorie d'activité (Bloc IV) — référentiel configuré uniquement depuis Configuration,
    jamais créable depuis la fiche d'enquête (cf. microfinance.loan.application.activity,
    dont le widget de création rapide restreint la sélection à une catégorie existante)."""
    _name = 'microfinance.loan.application.activity.category'
    _description = "Catégorie d'activité (Bloc IV)"
    _order = 'code'

    code = fields.Char(string='Code catégorie', required=True)
    name = fields.Char(string='Catégorie', required=True)
    activity_ids = fields.One2many(
        'microfinance.loan.application.activity', 'category_id', string='Activités')

    _sql_constraints = [
        ('code_unique', 'unique(code)', 'Ce code de catégorie existe déjà.'),
    ]


class MicrofinanceLoanApplicationActivity(models.Model):
    """Activité (Bloc IV), rattachée à une catégorie d'activité. Unicité de code globale
    (pas relative à la catégorie) : deux activités ne peuvent jamais partager le même code,
    même dans des catégories différentes — cf. décision confirmée sur les doublons du jeu de
    données initial (docs_dev/programme_progressif/STATUS.md)."""
    _name = 'microfinance.loan.application.activity'
    _description = 'Activité (Bloc IV)'
    _order = 'code'

    code = fields.Char(string='Code activité', required=True)
    name = fields.Char(string='Activité', required=True)
    category_id = fields.Many2one(
        'microfinance.loan.application.activity.category', string='Catégorie', required=True)

    _sql_constraints = [
        ('code_unique', 'unique(code)', 'Ce code d\'activité est déjà utilisé par une autre activité.'),
    ]
