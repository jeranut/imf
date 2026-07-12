# -*- coding: utf-8 -*-
from odoo import fields, models


class SalaryAttachmentWizard(models.TransientModel):
    """Assistant d'application en masse d'une retenue sur salaire"""
    _name = 'hr.salary.attachment.wizard'
    _description = 'Assistant Retenue sur Salaire'

    employee_ids = fields.Many2many('hr.employee', string='Employés',
                                    required=True)
    attachment_type = fields.Selection([
        ('avance', 'Avance sur salaire'),
        ('pension_alimentaire', 'Pension alimentaire'),
        ('saisie', 'Saisie sur salaire'),
    ], string='Type', required=True, default='avance')
    amount = fields.Monetary(string='Montant', required=True)
    currency_id = fields.Many2one('res.currency', string='Devise',
                                  default=lambda self:
                                  self.env.company.currency_id)
    date_start = fields.Date(string='Date de début', required=True,
                             default=fields.Date.today)
    date_end = fields.Date(string='Date de fin')

    def action_apply(self):
        """Crée la retenue sur salaire pour les employés sélectionnés"""
        self.ensure_one()
        self.env['hr.salary.attachment'].create({
            'employee_ids': [(6, 0, self.employee_ids.ids)],
            'attachment_type': self.attachment_type,
            'amount': self.amount,
            'date_start': self.date_start,
            'date_end': self.date_end,
        })
        return {'type': 'ir.actions.act_window_close'}
