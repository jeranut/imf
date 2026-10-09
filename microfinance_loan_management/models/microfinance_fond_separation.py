# -*- coding: utf-8 -*-
"""Séparation crédit / exploitation côté serveur : un fonds d'exploitation n'est JAMAIS la source d'un crédit,
d'un partage de crédit, d'une répartition par portefeuille, ni le fonds de crédit par défaut d'une société. Les domaines
des champs masquent déjà ces fonds dans l'interface ; ces contraintes bloquent aussi un create()/write()
direct (import, API)."""
from odoo import api, models, _
from odoo.exceptions import ValidationError


def _refuse_exploitation(fond, usage):
    raise ValidationError(_(
        "Le fonds « %(fonds)s » est un fonds d'exploitation : il ne peut pas servir à %(usage)s."
    ) % {'fonds': fond.name, 'usage': usage})


class MicrofinanceLoan(models.Model):
    _inherit = 'microfinance.loan'

    @api.constrains('fond_credit_id')
    def _check_fond_credit_not_exploitation(self):
        for loan in self.filtered(lambda l: l.fond_credit_id.destination == 'exploitation'):
            _refuse_exploitation(loan.fond_credit_id, _('financer un crédit'))


# Partage : un fonds d'exploitation se partage aux agences par le menu « Partage des fonds d'exploitation » (même modèle,
# destination imposée par le contexte de l'action, journal d'exploitation de la même banque) et ne peut JAMAIS passer par
# le partage de crédit : voir MicrofinanceFondPartage._check_expected_destination
# (microfinance_fond_partage_exploitation.py). Il ne crée aucune allocation, donc n'alimente aucun crédit.


class MicrofinancePortfolioAllocation(models.Model):
    _inherit = 'microfinance.portfolio.allocation'

    @api.constrains('fond_id')
    def _check_fond_not_exploitation(self):
        for repartition in self.filtered(lambda r: r.fond_id.destination == 'exploitation'):
            _refuse_exploitation(repartition.fond_id, _('une répartition par portefeuille'))


class ResCompany(models.Model):
    _inherit = 'res.company'

    @api.constrains('microfinance_fond_credit_default_id')
    def _check_default_fond_not_exploitation(self):
        for company in self.filtered(lambda c: c.microfinance_fond_credit_default_id.destination == 'exploitation'):
            _refuse_exploitation(company.microfinance_fond_credit_default_id, _('fonds de crédit par défaut'))
