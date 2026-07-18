# -*- coding: utf-8 -*-
from odoo import api, fields, models

_EXCLUDED_FIELDS = ('id', 'application_id', 'display_name', 'create_date', 'create_uid', 'write_date', 'write_uid')


class MicrofinanceLoanApplicationCaCdagWizard(models.TransientModel):
    """Wizard popup — Section VII : Avis du CA et du CDAG."""
    _name = 'microfinance.loan.application.ca.cdag.wizard'
    _description = 'Modifier les avis CA et CDAG'

    application_id = fields.Many2one('microfinance.loan.application', required=True)
    currency_id = fields.Many2one(related='application_id.currency_id', readonly=True)

    requested_amount = fields.Monetary(string='Montant demandé')
    required_savings = fields.Monetary(string='Épargne exigée (demande)')
    repayment_amount = fields.Monetary(string='Remboursement (demande)')
    period = fields.Integer(string='Durée demandée (échéances)')
    available_savings = fields.Monetary(string='Épargne disponible')
    ca_amount = fields.Monetary(string='Montant avis CA')
    ca_required_savings = fields.Monetary(string='Épargne exigée (CA)')
    ca_repayment_amount = fields.Monetary(string='Remboursement (CA)')
    ca_period = fields.Integer(string='Durée avis CA (échéances)')
    cdag_amount = fields.Monetary(string='Montant avis CDAG')
    cdag_required_savings = fields.Monetary(string='Épargne exigée (CDAG)')
    cdag_repayment_amount = fields.Monetary(string='Remboursement (CDAG)')
    cdag_period = fields.Integer(string='Durée avis CDAG (échéances)')
    previous_loan_amount = fields.Monetary(string='Montant du prêt précédent')
    previous_loan_repayment_behavior = fields.Selection([
        ('early', 'En avance'),
        ('normal', 'Normal'),
        ('irregular', 'Irrégulier'),
        ('late', 'En retard'),
    ], string='Comportement de remboursement précédent')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        application = self.env['microfinance.loan.application'].browse(
            self.env.context.get('default_application_id')
        )
        if application:
            for field_name in fields_list:
                if field_name in application._fields and field_name not in _EXCLUDED_FIELDS:
                    res[field_name] = application[field_name]
        return res

    def action_validate(self):
        self.ensure_one()
        vals = {f: self[f] for f in self._fields if f not in _EXCLUDED_FIELDS and f != 'currency_id'}
        self.application_id.write(vals)
        return {'type': 'ir.actions.act_window_close'}
