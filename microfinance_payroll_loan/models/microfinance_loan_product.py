# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class MicrofinanceLoanProduct(models.Model):
    _inherit = 'microfinance.loan.product'

    employee_authorized = fields.Boolean(
        string='Autorisé pour les employés', tracking=True,
        help="Produit proposable en avance spéciale employé (circuit paie MOWGLI). "
             "Strictement mensuel : la périodicité ne peut être qu'une périodicité "
             "mensuelle unique imposée tant que cette case est cochée.",
    )

    def _employee_authorized_is_monthly_only(self):
        """Vrai si la configuration de périodicité actuelle de ce produit est strictement
        mensuelle : mode « Périodicité unique imposée » avec repayment_frequency_id de code
        'monthly' (le mode « Choix du client » n'est jamais strictement mensuel, même si la
        seule périodicité autorisée est le mensuel, car le champ resterait un choix)."""
        self.ensure_one()
        return (
            self.repayment_frequency_mode == 'fixed'
            and bool(self.repayment_frequency_id)
            and self.repayment_frequency_id.code == 'monthly'
        )

    @api.constrains('employee_authorized')
    def _check_employee_authorized_requires_monthly(self):
        for product in self:
            if product.employee_authorized and not product._employee_authorized_is_monthly_only():
                raise ValidationError(_(
                    "Un produit « Autorisé pour les employés » doit être strictement "
                    "mensuel (périodicité unique imposée, mensuelle)."
                ))

    @api.constrains('repayment_frequency_mode', 'repayment_frequency_id', 'allowed_repayment_frequency_ids')
    def _check_monthly_locked_while_employee_authorized(self):
        for product in self:
            if product.employee_authorized and not product._employee_authorized_is_monthly_only():
                raise ValidationError(_(
                    "Décochez d'abord « Autorisé pour les employés » avant de changer la "
                    "périodicité de ce produit."
                ))
