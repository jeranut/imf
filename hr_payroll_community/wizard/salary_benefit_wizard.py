# -*- coding: utf-8 -*-
from odoo import fields, models


class SalaryBenefitWizard(models.TransientModel):
    """Assistant de configuration d'un avantage en nature sur un contrat"""
    _name = 'hr.contract.salary.benefit.wizard'
    _description = 'Assistant Avantage en Nature'

    contract_id = fields.Many2one('hr.contract', string='Contrat',
                                  required=True,
                                  default=lambda self: self.env.context.get(
                                      'active_id'))
    benefit_type = fields.Selection([
        ('vehicule', 'Véhicule'),
        ('logement', 'Logement'),
        ('autre', 'Autre'),
    ], string='Type', required=True, default='vehicule')
    taxable_value = fields.Monetary(string='Valeur imposable')
    non_taxable_value = fields.Monetary(string='Valeur non imposable')
    currency_id = fields.Many2one('res.currency', string='Devise',
                                  default=lambda self:
                                  self.env.company.currency_id)

    def action_apply(self):
        """Ajoute l'avantage en nature au contrat sélectionné"""
        self.ensure_one()
        self.env['hr.contract.salary.benefit'].create({
            'contract_id': self.contract_id.id,
            'benefit_type': self.benefit_type,
            'taxable_value': self.taxable_value,
            'non_taxable_value': self.non_taxable_value,
        })
        return {'type': 'ir.actions.act_window_close'}
