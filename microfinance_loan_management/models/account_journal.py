# -*- coding: utf-8 -*-
from odoo import fields, models

MICROFINANCE_USAGES = [
    ('fund', 'Fonds (réception des bailleurs avant partage)'),
    ('credit', 'Crédit'),
    ('savings', 'Épargne'),
    ('operating', 'Exploitation'),
    ('mobile', 'Mobile money'),
    ('cash', 'Caisse'),
]


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    microfinance_bank_id = fields.Many2one(
        'res.bank', string='Banque (microfinance)', index='btree_not_null',
        help="Banque à laquelle appartient ce journal de trésorerie (BMOI, BNI…). Sert à déduire "
             "automatiquement le journal d'un fonds, d'une contribution ou d'un partage.",
    )
    microfinance_usage = fields.Selection(
        MICROFINANCE_USAGES, string='Usage (microfinance)', index='btree_not_null',
        help="Rôle du journal dans la structure de trésorerie. « Fonds » : journal de réception des "
             "fonds des bailleurs ; un fonds = une seule banque = un journal de fonds par société.",
    )

    def write(self, vals):
        res = super().write(vals)
        if {'microfinance_bank_id', 'microfinance_usage', 'active', 'company_id'} & set(vals):
            # le journal de fonds de chaque fonds ayant une banque est un champ calculé stocké : recalcul
            # différé (les fonds sans banque gardent leur valeur historique jusqu'à renseignement)
            funds = self.env['microfinance.fond.credit'].sudo().with_context(active_test=False).search(
                [('bank_id', '!=', False)])
            self.env.add_to_compute(funds._fields['fund_journal_id'], funds)
        return res
