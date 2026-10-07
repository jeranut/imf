# -*- coding: utf-8 -*-
from odoo import fields, models


class MicrofinanceLoanPayment(models.Model):
    _inherit = 'microfinance.loan.payment'

    payslip_id = fields.Many2one(
        'hr.payslip', string='Bulletin de paie', readonly=True, copy=False, index=True,
        help="Bulletin dont la validation a créé ce remboursement (retenue sur salaire). Vide "
             "pour un remboursement guichet normal. Au plus un remboursement NON ANNULÉ par "
             "(bulletin, prêt) : un recalcul ou une revalidation du bulletin sans annulation "
             "préalable ne crée jamais de second remboursement pour le même prêt (contrôle "
             "hr.payslip._microfinance_apply_salary_deduction, pas de contrainte SQL stricte "
             "ici car un bulletin annulé puis revalidé doit au contraire pouvoir recréer un "
             "nouveau remboursement une fois l'ancien extourné).",
    )
