# -*- coding: utf-8 -*-
from odoo import fields, models


class MicrofinanceEmployeePartnerMatchDismissal(models.Model):
    _name = 'microfinance.employee.partner.match.dismissal'
    _description = (
        "Correspondance employé/client écartée par un agent ou un gestionnaire (bouton "
        "« Ce n'est pas un employé »). Exclut définitivement cette paire des candidats "
        "renvoyés par hr.employee.microfinance_match_candidates (B, D, E) — tant qu'elle "
        "n'est pas supprimée ici, aucun de ces trois écrans ne la re-proposera."
    )

    employee_id = fields.Many2one('hr.employee', required=True, ondelete='cascade', index=True)
    partner_id = fields.Many2one('res.partner', required=True, ondelete='cascade', index=True)
    note = fields.Char(string='Motif')

    _sql_constraints = [
        ('employee_partner_unique', 'unique(employee_id, partner_id)',
         "Cette correspondance employé/client a déjà été écartée."),
    ]
