# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    savings_dormancy_months = fields.Integer(
        string="Épargne : mois d'inactivité avant dormance", default=6,
    )
