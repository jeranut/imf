# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MicrofinanceDashboard(models.Model):
    _name = 'microfinance.dashboard'
    _description = 'Dashboard microfinance'

    active_loan_count = fields.Integer(compute='_compute_dashboard')
    disbursed_amount = fields.Monetary(compute='_compute_dashboard')
    outstanding_amount = fields.Monetary(compute='_compute_dashboard')
    overdue_amount = fields.Monetary(compute='_compute_dashboard')
    default_rate = fields.Float(compute='_compute_dashboard')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)

    @api.depends_context('company')
    def _compute_dashboard(self):
        Loan = self.env['microfinance.loan']
        active = Loan.search([('company_id', '=', self.env.company.id), ('state', '=', 'active')])
        all_loans = Loan.search([('company_id', '=', self.env.company.id), ('state', 'in', ('active', 'closed', 'defaulted'))])
        defaulted = all_loans.filtered(lambda l: l.state == 'defaulted')
        for rec in self:
            rec.active_loan_count = len(active)
            rec.disbursed_amount = sum(all_loans.mapped('loan_amount'))
            rec.outstanding_amount = sum(active.mapped('balance_total'))
            rec.overdue_amount = sum(active.mapped('overdue_amount'))
            rec.default_rate = all_loans and (len(defaulted) / len(all_loans) * 100.0) or 0.0
