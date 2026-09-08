# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class MicrofinanceCaisseDenomination(models.Model):
    """Valeur faciale d'une coupure (billet) ou d'une pièce, utilisée pour le comptage de
    billetage à la clôture de session (microfinance.caisse.comptage.line). Liste **éditable
    par un manager/finance** depuis le menu Configuration — pas figée dans le code. Les
    données de `data/microfinance_caisse_denomination_data.xml` ne sont que des valeurs de
    départ (chargées avec noupdate=1)."""
    _name = 'microfinance.caisse.denomination'
    _description = 'Coupure / pièce de caisse (billetage)'
    _order = 'currency_id, value desc'

    name = fields.Char(string='Libellé', required=True)  # ex. « Billet 10 000 Ar »
    value = fields.Monetary(string='Valeur faciale', required=True)
    currency_id = fields.Many2one(
        'res.currency', string='Devise', required=True,
        default=lambda self: self.env.company.currency_id,
    )
    active = fields.Boolean(string='Actif', default=True)

    # Unicité sur (libellé, devise) et non (valeur, devise) : une même valeur faciale peut
    # exister à la fois en billet et en pièce (ex. 100 Ar, 200 Ar en Ariary).
    _sql_constraints = [
        ('name_currency_unique', 'unique(name, currency_id)',
         'Une coupure portant ce libellé existe déjà pour cette devise.'),
    ]

    @api.constrains('value')
    def _check_value_positive(self):
        for denomination in self:
            if denomination.value <= 0:
                raise ValidationError(_('La valeur faciale d\'une coupure doit être strictement positive.'))
