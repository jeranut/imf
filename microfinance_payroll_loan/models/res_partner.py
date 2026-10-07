# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # Rattachement du client au portefeuille d'un agent de crédit, posé par le wizard
    # « Avance spéciale » (microfinance_payroll_loan) avant toute demande de crédit : le
    # concept n'existe pas dans microfinance_loan_management, où un client n'est lié à un
    # agent qu'indirectement, via microfinance.loan.officer_id, une fois un premier crédit
    # créé. Jamais réaffecté silencieusement (cf. contrôle dans le wizard) : un changement
    # d'agent doit toujours être un geste explicite et visible.
    microfinance_officer_id = fields.Many2one(
        'res.users', string='Agent crédit (portefeuille)', tracking=True, copy=False,
        help="Agent de crédit dont ce client dépend. Posé une fois par le wizard « Avance "
             "spéciale » de la fiche employé (ou manuellement) ; ne change jamais tout seul.",
    )
    microfinance_employee_ids = fields.One2many(
        'hr.employee', 'microfinance_partner_id', string='Employé(s) lié(s)',
        help="Employé(s) dont ce client microfinance est l'avance spéciale (normalement un "
             "seul). Sert à restreindre les produits proposés à ceux autorisés pour les "
             "employés (microfinance.loan.product.employee_authorized).",
    )
    microfinance_is_employee_partner = fields.Boolean(
        string='Client lié à un employé', compute='_compute_microfinance_is_employee_partner',
        search='_search_microfinance_is_employee_partner',
    )

    @api.depends('microfinance_employee_ids')
    def _compute_microfinance_is_employee_partner(self):
        for partner in self:
            partner.microfinance_is_employee_partner = bool(partner.microfinance_employee_ids)

    def _search_microfinance_is_employee_partner(self, operator, value):
        linked = (operator == '=') == bool(value)
        domain_op = 'in' if linked else 'not in'
        employee_partner_ids = self.env['hr.employee'].search(
            [('microfinance_partner_id', '!=', False)]).mapped('microfinance_partner_id').ids
        return [('id', domain_op, employee_partner_ids)]

    @api.constrains('microfinance_selected_product_id')
    def _check_microfinance_employee_product_restriction(self):
        if not self.env.context.get('microfinance_context'):
            return
        for partner in self:
            product = partner.microfinance_selected_product_id
            if not product or not partner.microfinance_employee_ids:
                continue
            if not product.employee_authorized:
                raise ValidationError(_(
                    "Ce client est lié à un employé : seuls les produits « Autorisés pour "
                    "les employés » peuvent lui être proposés."
                ))
