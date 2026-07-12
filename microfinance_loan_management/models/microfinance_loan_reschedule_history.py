# -*- coding: utf-8 -*-
from odoo import fields, models


class MicrofinanceLoanRescheduleHistory(models.Model):
    _name = 'microfinance.loan.reschedule.history'
    _description = 'Historique de rééchelonnement de crédit microfinance'
    _order = 'id desc'

    loan_id = fields.Many2one('microfinance.loan', string='Crédit', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='loan_id.company_id', store=True, readonly=True)
    currency_id = fields.Many2one(related='loan_id.currency_id', readonly=True)
    reschedule_date = fields.Datetime(string='Date de rééchelonnement', default=fields.Datetime.now, required=True, readonly=True)
    user_id = fields.Many2one('res.users', string='Utilisateur', default=lambda self: self.env.user, required=True, readonly=True)
    reason = fields.Text(string='Motif')
    old_installment_ids = fields.One2many(
        'microfinance.loan.reschedule.history.line', 'history_id', string='Ancien échéancier', readonly=True,
    )


class MicrofinanceLoanRescheduleHistoryLine(models.Model):
    _name = 'microfinance.loan.reschedule.history.line'
    _description = 'Ligne d\'ancien échéancier conservée lors d\'un rééchelonnement'
    _order = 'history_id, sequence'

    history_id = fields.Many2one('microfinance.loan.reschedule.history', string='Historique', required=True, ondelete='cascade', index=True)
    currency_id = fields.Many2one(related='history_id.currency_id', readonly=True)
    sequence = fields.Integer(string='Séquence', readonly=True)
    due_date = fields.Date(string="Date d'échéance", readonly=True)
    principal_amount = fields.Monetary(string='Montant principal', readonly=True)
    interest_amount = fields.Monetary(string='Montant intérêt', readonly=True)
    penalty_amount = fields.Monetary(string='Montant pénalité', readonly=True)
    paid_principal = fields.Monetary(string='Principal payé', readonly=True)
    paid_interest = fields.Monetary(string='Intérêt payé', readonly=True)
    paid_penalty = fields.Monetary(string='Pénalité payée', readonly=True)
    residual_amount = fields.Monetary(string='Montant résiduel', readonly=True)
