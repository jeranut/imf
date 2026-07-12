# -*- coding: utf-8 -*-
from odoo import fields, models

TAXABLE_INPUT_CODES = {
    'vehicule': 'BENEFIT_TAXABLE_VEHICULE',
    'logement': 'BENEFIT_TAXABLE_LOGEMENT',
    'autre': 'BENEFIT_TAXABLE_AUTRE',
}
NON_TAXABLE_INPUT_CODES = {
    'vehicule': 'BENEFIT_NONTAXABLE_VEHICULE',
    'logement': 'BENEFIT_NONTAXABLE_LOGEMENT',
    'autre': 'BENEFIT_NONTAXABLE_AUTRE',
}


class HrContractSalaryBenefit(models.Model):
    """Avantage en nature configuré sur un contrat (véhicule, logement,
    autre), avec sa part imposable et sa part non imposable."""
    _name = 'hr.contract.salary.benefit'
    _description = 'Avantage en Nature'

    contract_id = fields.Many2one('hr.contract', string='Contrat',
                                  required=True, ondelete='cascade')
    benefit_type = fields.Selection([
        ('vehicule', 'Véhicule'),
        ('logement', 'Logement'),
        ('autre', 'Autre'),
    ], string='Type', required=True, default='vehicule')
    taxable_value = fields.Monetary(string='Valeur imposable',
                                    help="Part de l'avantage en nature "
                                         "soumise à l'IRSA.")
    non_taxable_value = fields.Monetary(string='Valeur non imposable',
                                        help="Part de l'avantage en nature "
                                             "non soumise à l'IRSA.")
    currency_id = fields.Many2one(
        'res.currency', string='Devise',
        related='contract_id.company_id.currency_id')

    def get_taxable_input_code(self):
        """Code d'input de bulletin pour la part imposable"""
        self.ensure_one()
        return TAXABLE_INPUT_CODES[self.benefit_type]

    def get_non_taxable_input_code(self):
        """Code d'input de bulletin pour la part non imposable"""
        self.ensure_one()
        return NON_TAXABLE_INPUT_CODES[self.benefit_type]
