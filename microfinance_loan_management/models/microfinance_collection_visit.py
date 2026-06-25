# -*- coding: utf-8 -*-
from odoo import fields, models


class MicrofinanceCollectionVisit(models.Model):
    _name = 'microfinance.collection.visit'
    _description = 'Visite de recouvrement microfinance'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'visit_date desc, id desc'

    loan_id = fields.Many2one('microfinance.loan', required=True, ondelete='cascade')
    partner_id = fields.Many2one(related='loan_id.partner_id', store=True, readonly=True)
    agent_id = fields.Many2one('res.users', string='Agent terrain', default=lambda self: self.env.user, required=True)
    visit_date = fields.Datetime(default=fields.Datetime.now, required=True)
    next_visit_date = fields.Datetime()
    status = fields.Selection([('planned', 'Planifiée'), ('done', 'Réalisée'), ('missed', 'Manquée'), ('cancelled', 'Annulée')], default='planned', required=True)
    remarks = fields.Text(string='Remarques')
    promise_to_pay_date = fields.Date(string='Promesse de paiement')
    promised_amount = fields.Monetary(string='Montant promis')
    company_id = fields.Many2one(related='loan_id.company_id', store=True, readonly=True)
    currency_id = fields.Many2one(related='loan_id.currency_id', store=True, readonly=True)
