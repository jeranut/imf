# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class MicrofinanceLoanGuarantee(models.Model):
    _name = 'microfinance.loan.guarantee'
    _description = 'Garantie / caution de crédit microfinance'
    _order = 'id desc'

    loan_id = fields.Many2one('microfinance.loan', required=True, ondelete='cascade', index=True)
    guarantee_type = fields.Selection([
        ('asset', 'Garantie matérielle'),
        ('guarantor', 'Caution personnelle'),
    ], required=True, default='asset')
    description = fields.Char(required=True)
    estimated_value = fields.Monetary(required=True, default=0.0)
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
