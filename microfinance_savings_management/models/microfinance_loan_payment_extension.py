# -*- coding: utf-8 -*-
from odoo import fields, models


class MicrofinanceLoanPayment(models.Model):
    _inherit = 'microfinance.loan.payment'

    payment_origin = fields.Selection([
        ('manual', 'Manuel'),
        ('savings_auto_debit', 'Prélèvement automatique sur épargne'),
    ], string='Origine du paiement', default='manual', required=True, tracking=True)
