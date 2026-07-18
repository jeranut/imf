# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MicrofinanceLoanApplicationCreateLoanWizard(models.TransientModel):
    """Wizard de transformation d'un dossier accepté en crédit (microfinance.loan).

    Formulaire volontairement minimal (produit, montant, durée) : le produit est
    pré-rempli depuis le dossier (application_id.loan_product_id) mais reste modifiable
    ici — jamais deviné de façon rigide, l'agent confirme ou change son choix à cette
    étape. Tout le reste (garanties, périodicité, comptes, scoring...) reste géré
    directement sur microfinance.loan après sa création, jamais dupliqué ici."""
    _name = 'microfinance.loan.application.create.loan.wizard'
    _description = 'Créer le crédit depuis le dossier'

    application_id = fields.Many2one('microfinance.loan.application', required=True, readonly=True)
    partner_id = fields.Many2one(related='application_id.partner_id', readonly=True)
    company_id = fields.Many2one(related='application_id.company_id', readonly=True)
    currency_id = fields.Many2one(related='application_id.currency_id', readonly=True)
    product_id = fields.Many2one(
        'microfinance.loan.product', string='Produit', required=True,
        domain="[('company_id', '=', company_id)]",
    )
    loan_amount = fields.Monetary(string='Montant crédit', required=True)
    term = fields.Integer(string='Nombre échéances', required=True, default=1)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        application = self.env['microfinance.loan.application'].browse(
            self.env.context.get('default_application_id')
        )
        if not application:
            return res
        if 'product_id' in fields_list:
            res['product_id'] = application.loan_product_id.id
        if 'loan_amount' in fields_list:
            res['loan_amount'] = application.cdag_amount or application.ca_amount or application.requested_amount
        return res

    def action_validate(self):
        self.ensure_one()
        loan = self.env['microfinance.loan'].with_context(microfinance_loan_creation_allowed=True).create({
            'partner_id': self.application_id.partner_id.id,
            'product_id': self.product_id.id,
            'company_id': self.company_id.id,
            'loan_amount': self.loan_amount,
            'term': self.term,
            'application_date': self.application_id.application_date,
        })
        self.application_id.with_context(application_create_loan=True).write({
            'loan_id': loan.id, 'state': 'loan_created',
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'microfinance.loan',
            'view_mode': 'form',
            'res_id': loan.id,
        }
