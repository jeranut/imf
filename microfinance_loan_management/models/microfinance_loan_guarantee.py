# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

GUARANTEE_TYPE_SELECTION = [
    ('land', 'Terrain'),
    ('vehicle', 'Véhicule'),
    ('house', 'Maison'),
    ('furniture', 'Meuble'),
    ('salary', 'Salaire'),
    ('guarantor', 'Garant / caution personnelle'),
    ('other', 'Autre'),
]


class MicrofinanceLoanGuarantee(models.Model):
    _name = 'microfinance.loan.guarantee'
    _description = 'Garantie / caution de crédit microfinance'
    _order = 'id desc'

    loan_id = fields.Many2one('microfinance.loan', required=True, ondelete='cascade', index=True)
    guarantee_type = fields.Selection(GUARANTEE_TYPE_SELECTION, required=True, default='other')
    description = fields.Char(required=True)
    estimated_value = fields.Monetary(required=True, default=0.0)
    recognized_value = fields.Monetary(
        compute='_compute_recognized_value', store=True, string='Valeur reconnue',
        help='Valeur estimée pondérée par le ratio de valorisation configuré pour ce type de '
             'garantie (microfinance.guarantee.valuation.rule). 100% de la valeur estimée si '
             "aucune règle n'est configurée pour ce type. Utilisée dans le total des garanties "
             'et les contrôles d\'éligibilité, à la place de la valeur brute.',
    )
    guarantor_partner_id = fields.Many2one('res.partner', string='Caution')
    document = fields.Binary(string='Pièce justificative')
    document_filename = fields.Char()
    currency_id = fields.Many2one(related='loan_id.currency_id', store=True, readonly=True)
    company_id = fields.Many2one(related='loan_id.company_id', store=True, readonly=True)
    state = fields.Selection([
        ('draft', 'Brouillon'),
        ('validated', 'Validée'),
        ('released', 'Libérée'),
    ], default='draft', required=True)

    @api.constrains('guarantee_type', 'guarantor_partner_id')
    def _check_guarantor_partner(self):
        for guarantee in self:
            if guarantee.guarantee_type == 'guarantor' and not guarantee.guarantor_partner_id:
                raise ValidationError(_('La caution doit préciser le partenaire qui se porte garant.'))

    @api.constrains('estimated_value')
    def _check_estimated_value(self):
        for guarantee in self:
            if guarantee.estimated_value < 0:
                raise ValidationError(_('La valeur estimée ne peut pas être négative.'))

    @api.depends('estimated_value', 'guarantee_type', 'company_id')
    def _compute_recognized_value(self):
        Rule = self.env['microfinance.guarantee.valuation.rule']
        for guarantee in self:
            rule = Rule.search([
                ('company_id', '=', guarantee.company_id.id),
                ('guarantee_type', '=', guarantee.guarantee_type),
            ], limit=1)
            ratio = rule.valuation_ratio if rule else 100.0
            guarantee.recognized_value = guarantee.estimated_value * ratio / 100.0


class MicrofinanceGuaranteeValuationRule(models.Model):
    _name = 'microfinance.guarantee.valuation.rule'
    _description = 'Règle de valorisation des garanties par type'
    _order = 'company_id, guarantee_type'

    guarantee_type = fields.Selection(GUARANTEE_TYPE_SELECTION, required=True)
    valuation_ratio = fields.Float(
        string='Ratio de valorisation (%)', required=True, default=100.0,
        help='Pourcentage de la valeur estimée reconnu comme garantie effective (ex. 114 pour 114%).',
    )
    max_ratio = fields.Float(
        string='Ratio maximum (%)', required=True, default=150.0,
        help='Plafond au-delà duquel le ratio de valorisation ne peut pas être configuré pour ce type.',
    )
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)

    _sql_constraints = [
        ('type_company_unique', 'unique(guarantee_type, company_id)',
         'Une seule règle de valorisation par type de garantie et par société.'),
    ]

    @api.constrains('valuation_ratio', 'max_ratio')
    def _check_ratio(self):
        for rule in self:
            if rule.max_ratio <= 0:
                raise ValidationError(_('Le ratio maximum doit être strictement positif.'))
            if rule.valuation_ratio < 0:
                raise ValidationError(_('Le ratio de valorisation ne peut pas être négatif.'))
            if rule.valuation_ratio > rule.max_ratio:
                raise ValidationError(_(
                    'Le ratio de valorisation (%(ratio)s%%) dépasse le plafond autorisé pour ce '
                    'type de garantie (%(max)s%%).'
                ) % {'ratio': rule.valuation_ratio, 'max': rule.max_ratio})
