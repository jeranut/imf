# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class MicrofinanceLoanProduct(models.Model):
    _name = 'microfinance.loan.product'
    _description = 'Produit de crédit microfinance'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(required=True, tracking=True)
    min_amount = fields.Monetary(string='Montant minimum', required=True, default=0.0)
    max_amount = fields.Monetary(string='Montant maximum', required=True, default=0.0)
    min_term = fields.Integer(string='Durée min.', default=1, required=True)
    max_term = fields.Integer(string='Durée max.', default=12, required=True)
    interest_rate = fields.Float(string='Taux intérêt annuel (%)', required=True, default=0.0)
    interest_method = fields.Selection([
        ('flat', 'Flat rate'),
        ('reducing', 'Reducing balance'),
    ], required=True, default='flat')
    repayment_frequency = fields.Selection([
        ('daily', 'Journalier'),
        ('weekly', 'Hebdomadaire'),
        ('monthly', 'Mensuel'),
    ], required=True, default='monthly')
    grace_period_days = fields.Integer(string='Délai de grâce (jours)', default=0)
    min_membership_days = fields.Integer(string='Ancienneté minimum client (jours)', default=0)
    allow_second_loan = fields.Boolean(string='Autoriser un 2e crédit actif', default=True)
    block_second_if_arrears = fields.Boolean(string='Bloquer le 2e crédit si le 1er a des arriérés', default=True)
    penalty_type = fields.Selection([
        ('fixed', 'Montant fixe'),
        ('percentage', 'Pourcentage'),
    ], default='fixed', required=True)
    penalty_amount = fields.Monetary(string='Pénalité fixe', default=0.0)
    penalty_rate = fields.Float(string='Taux pénalité (%)', default=0.0)
    disbursement_journal_id = fields.Many2one('account.journal', string='Journal décaissement', domain="[('type', 'in', ('bank','cash'))]")
    payment_journal_id = fields.Many2one('account.journal', string='Journal remboursement', domain="[('type', 'in', ('bank','cash'))]")
    loan_account_id = fields.Many2one('account.account', string='Compte prêts clients', required=True)
    interest_account_id = fields.Many2one('account.account', string='Compte intérêts', required=True)
    penalty_account_id = fields.Many2one('account.account', string='Compte pénalités', required=True)
    fee_account_id = fields.Many2one('account.account', string='Compte frais')
    write_off_account_id = fields.Many2one(
        'account.account', string='Compte pertes sur créances irrécouvrables',
        help='Requis uniquement au moment de la radiation d\'un crédit de ce produit.',
    )
    provision_account_id = fields.Many2one(
        'account.account', string='Compte de charge provision',
        help='Requis uniquement au moment de comptabiliser une provision pour ce produit.',
    )
    provision_contra_account_id = fields.Many2one(
        'account.account', string='Compte de contrepartie provision (bilan)',
        help='Requis uniquement au moment de comptabiliser une provision pour ce produit.',
    )
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', readonly=True)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('code_company_unique', 'unique(code, company_id)', 'Le code produit doit être unique par société.'),
    ]

    @api.constrains('min_amount', 'max_amount', 'min_term', 'max_term', 'interest_rate', 'grace_period_days', 'min_membership_days')
    def _check_values(self):
        for product in self:
            if product.min_amount < 0 or product.max_amount <= 0 or product.max_amount < product.min_amount:
                raise ValidationError(_('Vérifiez les montants minimum et maximum.'))
            if product.min_term <= 0 or product.max_term < product.min_term:
                raise ValidationError(_('Vérifiez les durées minimum et maximum.'))
            if product.interest_rate < 0:
                raise ValidationError(_('Le taux intérêt ne peut pas être négatif.'))
            if product.grace_period_days < 0:
                raise ValidationError(_('Le délai de grâce ne peut pas être négatif.'))
            if product.min_membership_days < 0:
                raise ValidationError(_('L\'ancienneté minimum ne peut pas être négative.'))
