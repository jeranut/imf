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
        ('biweekly', 'Quinzaine (15 jours)'),
        ('four_weekly', 'Toutes les 4 semaines'),
        ('monthly', 'Mensuel'),
        ('bimonthly', 'Bimestriel (2 mois)'),
        ('quarterly', 'Trimestriel'),
        ('four_monthly', 'Tous les 4 mois'),
        ('semiannual', 'Semestriel'),
        ('annual', 'Annuel'),
    ], required=True, default='monthly')
    grace_period_days = fields.Integer(string='Délai de grâce (jours)', default=0)
    min_membership_days = fields.Integer(string='Ancienneté minimum client (jours)', default=0)
    allow_second_loan = fields.Boolean(string='Autoriser un 2e crédit actif', default=True)
    block_second_if_arrears = fields.Boolean(string='Bloquer le 2e crédit si le 1er a des arriérés', default=True)
    guarantee_required = fields.Boolean(string='Garantie obligatoire', default=False)
    min_guarantee_ratio = fields.Float(
        string='Ratio minimum de garantie (%)', default=0.0,
        help='Pourcentage minimum du montant du crédit que la somme des garanties validées doit couvrir. '
             '0 = pas de minimum même si une garantie est obligatoire.',
    )
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
    fee_type = fields.Selection([
        ('fixed', 'Montant fixe'),
        ('percentage', 'Pourcentage du montant du crédit'),
    ], default='fixed', required=True)
    fee_amount = fields.Monetary(string='Frais fixes', default=0.0)
    fee_rate = fields.Float(string='Taux de frais (%)', default=0.0)
    fee_journal_id = fields.Many2one(
        'account.journal', string='Journal encaissement frais', domain="[('type', 'in', ('bank','cash'))]",
        help='Journal utilisé pour encaisser les frais de dossier, distinct des journaux de '
             'décaissement/remboursement si l\'institution le souhaite (peut être identique à l\'un des deux).',
    )
    fee_charged_before_disbursement = fields.Boolean(
        string='Frais exigés avant décaissement', default=True,
        help='Si activé, le décaissement est bloqué tant que les frais de dossier dus n\'ont pas été encaissés.',
    )
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

    @api.constrains('min_amount', 'max_amount', 'min_term', 'max_term', 'interest_rate', 'grace_period_days',
                     'min_membership_days', 'min_guarantee_ratio', 'fee_amount', 'fee_rate')
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
            if product.min_guarantee_ratio < 0:
                raise ValidationError(_('Le ratio minimum de garantie ne peut pas être négatif.'))
            if product.fee_amount < 0 or product.fee_rate < 0:
                raise ValidationError(_('Les frais de dossier ne peuvent pas être négatifs.'))
