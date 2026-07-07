# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MicrofinanceLoanInstallment(models.Model):
    _name = 'microfinance.loan.installment'
    _description = 'Échéance de crédit microfinance'
    _order = 'loan_id, sequence, due_date'

    loan_id = fields.Many2one('microfinance.loan', string='Crédit', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(string='Séquence', required=True, default=1)
    due_date = fields.Date(string="Date d'échéance", required=True, index=True)
    principal_amount = fields.Monetary(string='Montant principal', default=0.0)
    interest_amount = fields.Monetary(string='Montant intérêt', default=0.0)
    penalty_amount = fields.Monetary(string='Montant pénalité', default=0.0)
    total_amount = fields.Monetary(string='Montant total', compute='_compute_amounts', store=True)
    paid_principal = fields.Monetary(string='Principal payé', default=0.0)
    paid_interest = fields.Monetary(string='Intérêt payé', default=0.0)
    paid_penalty = fields.Monetary(string='Pénalité payée', default=0.0)
    residual_amount = fields.Monetary(string='Montant résiduel', compute='_compute_amounts', store=True)
    state = fields.Selection([
        ('pending', 'À payer'),
        ('partial', 'Partiel'),
        ('paid', 'Payé'),
        ('overdue', 'En retard'),
    ], string='État', compute='_compute_state', store=True, readonly=False, default='pending')
    penalty_applied = fields.Boolean(string='Pénalité appliquée', default=False)
    payment_ids = fields.Many2many('microfinance.loan.payment', 'microfinance_installment_payment_rel', 'installment_id', 'payment_id', string='Paiements')
    partner_id = fields.Many2one(related='loan_id.partner_id', store=True, readonly=True)
    company_id = fields.Many2one(related='loan_id.company_id', store=True, readonly=True)
    currency_id = fields.Many2one(related='loan_id.currency_id', store=True, readonly=True)

    @api.depends('principal_amount', 'interest_amount', 'penalty_amount', 'paid_principal', 'paid_interest', 'paid_penalty')
    def _compute_amounts(self):
        for line in self:
            line.total_amount = line.principal_amount + line.interest_amount + line.penalty_amount
            paid = line.paid_principal + line.paid_interest + line.paid_penalty
            line.residual_amount = max(line.total_amount - paid, 0.0)

    @api.depends('residual_amount', 'total_amount', 'due_date')
    def _compute_state(self):
        today = fields.Date.context_today(self)
        for line in self:
            if line.total_amount and line.residual_amount <= 0.01:
                line.state = 'paid'
            elif line.residual_amount < line.total_amount:
                line.state = 'partial'
            elif line.due_date and line.due_date < today:
                line.state = 'overdue'
            else:
                line.state = 'pending'

    def action_apply_penalty(self):
        for inst in self.filtered(lambda x: not x.penalty_applied and x.state in ('pending', 'partial', 'overdue')):
            product = inst.loan_id.product_id
            if not product:
                continue
            penalty_date = fields.Date.add(inst.due_date, days=product.grace_period_days or 0)
            if penalty_date >= fields.Date.context_today(inst):
                continue
            amount = product.penalty_amount if product.penalty_type == 'fixed' else inst.residual_amount * product.penalty_rate / 100.0
            inst.write({'penalty_amount': inst.penalty_amount + amount, 'penalty_applied': True})
        return True
