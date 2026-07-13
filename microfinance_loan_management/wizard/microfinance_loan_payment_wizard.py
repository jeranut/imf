# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..models.microfinance_loan_payment import default_payment_amount_and_journal


class MicrofinanceLoanPaymentWizard(models.TransientModel):
    _name = 'microfinance.loan.payment.wizard'
    _description = 'Assistant remboursement crédit'

    loan_id = fields.Many2one('microfinance.loan', string='Crédit', required=True)
    amount = fields.Monetary(
        string='Montant', required=True,
        help="Préempli avec le montant dû (échéances en retard cumulées, ou à défaut la "
             "prochaine échéance) — librement modifiable pour un remboursement partiel ou "
             "anticipé.",
    )
    payment_date = fields.Date(string='Date de remboursement', default=fields.Date.context_today, required=True)
    company_id = fields.Many2one(related='loan_id.company_id', readonly=True)
    journal_id = fields.Many2one(
        'account.journal', string='Journal', required=True,
        domain="[('type', 'in', ('bank','cash')), ('company_id', '=', company_id)]",
    )
    currency_id = fields.Many2one(related='loan_id.currency_id', readonly=True)
    note = fields.Text(string='Note')
    post_now = fields.Boolean(string='Comptabiliser maintenant', default=True)

    @api.onchange('loan_id')
    def _onchange_loan_id(self):
        for wizard in self:
            if not wizard.loan_id:
                continue
            amount, journal = default_payment_amount_and_journal(wizard.loan_id)
            if amount:
                wizard.amount = amount
            if journal:
                wizard.journal_id = journal

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
