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
    periods_per_year = fields.Integer(
        string='Périodes par an (calcul intérêt)', required=True, default=12,
        help="Nombre conventionnel de périodes de cette fréquence dans une année, utilisé "
             "pour calculer la fraction du taux annuel appliquée par tranche "
             "(_period_interest_factor). Valeur conventionnelle fixe (ex. 52 pour "
             "hebdomadaire), alignée sur LPF — et non un calcul en jours calendaires réels "
             "(qui donnerait 7/365 ≈ 0,019178 au lieu de 1/52 ≈ 0,019231) — car LPF traite "
             "les périodicités infra-mensuelles comme des fractions fixes d'année standard, "
             "pas comme des durées calendaires variables. N'affecte pas les dates "
             "d'échéance réelles (_period_delta reste calendaire), seulement le calcul du "
             "montant d'intérêt.",
    )
    sequence = fields.Integer(string='Séquence', default=10)

    _sql_constraints = [
        ('code_unique', 'unique(code)', 'Le code de périodicité doit être unique.'),
    ]

    @api.constrains('period_value')
    def _check_period_value(self):
        for freq in self:
            if freq.period_value <= 0:
                raise ValidationError(_('La valeur de la période doit être strictement positive.'))

    @api.constrains('periods_per_year')
    def _check_periods_per_year(self):
        for freq in self:
            if freq.periods_per_year <= 0:
                raise ValidationError(_('Le nombre de périodes par an doit être strictement positif.'))
