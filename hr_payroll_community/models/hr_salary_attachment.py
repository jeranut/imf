# -*- coding: utf-8 -*-
from odoo import fields, models

TYPE_INPUT_CODES = {
    'avance': 'ATTACH_AVANCE',
    'pension_alimentaire': 'ATTACH_PENSION',
    'saisie': 'ATTACH_SAISIE',
}


class HrSalaryAttachment(models.Model):
    """Retenue générique sur salaire (avance, pension alimentaire, saisie)
    applicable à un ou plusieurs employés sur une période donnée."""
    _name = 'hr.salary.attachment'
    _description = 'Retenue sur Salaire'

    employee_ids = fields.Many2many('hr.employee', string='Employés',
                                    required=True,
                                    help="Employés auxquels s'applique cette "
                                         "retenue.")
    attachment_type = fields.Selection([
        ('avance', 'Avance sur salaire'),
        ('pension_alimentaire', 'Pension alimentaire'),
        ('saisie', 'Saisie sur salaire'),
    ], string='Type', required=True, default='avance')
    amount = fields.Monetary(string='Montant', required=True)
    currency_id = fields.Many2one('res.currency', string='Devise',
                                  related='company_id.currency_id')
    date_start = fields.Date(string='Date de début', required=True,
                             default=fields.Date.today)
    date_end = fields.Date(string='Date de fin',
                           help="Laisser vide pour une retenue récurrente "
                                "sans date de fin.")
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string='Société',
                                 default=lambda self: self.env.company)

    def get_input_code(self):
        """Code d'input de bulletin correspondant au type de retenue"""
        self.ensure_one()
        return TYPE_INPUT_CODES[self.attachment_type]
