# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError


class MicrofinanceLoanPaymentWizard(models.TransientModel):
    _name = 'microfinance.loan.payment.wizard'
    _description = 'Assistant remboursement crédit'

    loan_id = fields.Many2one('microfinance.loan', string='Crédit', required=True)
    amount = fields.Monetary(string='Montant', required=True)
    payment_date = fields.Date(string='Date de remboursement', default=fields.Date.context_today, required=True)
    journal_id = fields.Many2one('account.journal', string='Journal', required=True, domain="[('type', 'in', ('bank','cash'))]")
    currency_id = fields.Many2one(related='loan_id.currency_id', readonly=True)
    note = fields.Text(string='Note')
    post_now = fields.Boolean(string='Comptabiliser maintenant', default=True)

    def action_create_payment(self):
        self.ensure_one()
        if self.amount <= 0:
            raise UserError(_('Montant invalide.'))
        payment = self.env['microfinance.loan.payment'].create({
            'loan_id': self.loan_id.id,
            'amount': self.amount,
            'payment_date': self.payment_date,
            'journal_id': self.journal_id.id,
            'note': self.note,
        })
        if self.post_now:
            payment.action_post()
        return {'type': 'ir.actions.act_window', 'res_model': 'microfinance.loan.payment', 'res_id': payment.id, 'view_mode': 'form'}
