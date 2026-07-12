# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class MicrofinanceRepaymentFrequency(models.Model):
    _name = 'microfinance.repayment.frequency'
    _description = 'Périodicité de remboursement microfinance'
    _order = 'sequence, id'

    name = fields.Char(string='Nom', required=True, translate=True)
    code = fields.Char(string='Code', required=True, help='Identifiant technique stable, référencé par la migration.')
    period_kind = fields.Selection([
        ('days', 'Jours'),
        ('months', 'Mois'),
    ], string='Unité de période', required=True)
    period_value = fields.Integer(string='Valeur de la période', required=True, default=1)
    sequence = fields.Integer(string='Séquence', default=10)

    _sql_constraints = [
        ('code_unique', 'unique(code)', 'Le code de périodicité doit être unique.'),
    ]

    @api.constrains('period_value')
    def _check_period_value(self):
        for freq in self:
            if freq.period_value <= 0:
                raise ValidationError(_('La valeur de la période doit être strictement positive.'))
