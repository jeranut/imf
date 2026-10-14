# -*- coding: utf-8 -*-
"""Paramètres de cotisations datés (SME, plafond, taux, barème IRSA).

Chaque ligne a une date d'effet ; la valeur en vigueur pour un bulletin est
celle de la dernière ligne dont la date d'effet est <= date_to du bulletin
(ligne de la société si elle existe, sinon ligne globale). Rien n'est
inventé pour le passé : sans ligne applicable, erreur explicite."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

PARAM_CODES = [
    ('SME', "SME (salaire minimum)"),
    ('FACTEUR_PLAFOND', "Facteur de plafond (x SME)"),
    ('PLANCHER', "Plancher (1 = base au moins égale au SME, 0 = sans)"),
    ('CNAPS_SAL', "CNaPS salarié (fraction)"),
    ('OSTIE_SAL', "OSTIE salarié (fraction)"),
    ('CNAPS_ER', "CNaPS patronal (fraction)"),
    ('OSTIE_ER', "OSTIE patronal (fraction)"),
    ('IRSA_B0', "IRSA : seuil d'exonération"),
    ('IRSA_B1', "IRSA : fin de la tranche 1"),
    ('IRSA_B2', "IRSA : fin de la tranche 2"),
    ('IRSA_B3', "IRSA : fin de la tranche 3"),
    ('IRSA_B4', "IRSA : fin de la tranche 4"),
    ('IRSA_R1', "IRSA : taux tranche 1 (fraction)"),
    ('IRSA_R2', "IRSA : taux tranche 2 (fraction)"),
    ('IRSA_R3', "IRSA : taux tranche 3 (fraction)"),
    ('IRSA_R4', "IRSA : taux tranche 4 (fraction)"),
    ('IRSA_R5', "IRSA : taux au-delà de la tranche 4 (fraction)"),
    ('IRSA_MIN', "IRSA : minimum"),
    ('IRSA_ENFANT', "IRSA : réduction par enfant"),
]

# (code, valeur, date d'effet). SME seul est daté du 2026-10-01 ; aucune valeur
# n'est semée pour la période antérieure.
DEFAULT_PARAMS = [
    ('SME', 315000.0, '2026-10-01'),
    ('FACTEUR_PLAFOND', 8.0, '2026-01-01'),
    ('PLANCHER', 1.0, '2026-01-01'),
    ('CNAPS_SAL', 0.01, '2026-01-01'),
    ('OSTIE_SAL', 0.01, '2026-01-01'),
    ('CNAPS_ER', 0.13, '2026-01-01'),
    ('OSTIE_ER', 0.05, '2026-01-01'),
    ('IRSA_B0', 350000.0, '2026-01-01'),
    ('IRSA_B1', 400000.0, '2026-01-01'),
    ('IRSA_B2', 500000.0, '2026-01-01'),
    ('IRSA_B3', 600000.0, '2026-01-01'),
    ('IRSA_B4', 4000000.0, '2026-01-01'),
    ('IRSA_R1', 0.05, '2026-01-01'),
    ('IRSA_R2', 0.10, '2026-01-01'),
    ('IRSA_R3', 0.15, '2026-01-01'),
    ('IRSA_R4', 0.20, '2026-01-01'),
    ('IRSA_R5', 0.25, '2026-01-01'),
    ('IRSA_MIN', 3000.0, '2026-01-01'),
    ('IRSA_ENFANT', 2000.0, '2026-01-01'),
]


class MowgliPayrollParam(models.Model):
    _name = 'mowgli.payroll.param'
    _description = "Paramètre de cotisation daté"
    _order = 'code, date_from desc, company_id'

    code = fields.Selection(PARAM_CODES, required=True, index=True)
    value = fields.Float(string="Valeur", digits=(16, 6), required=True)
    date_from = fields.Date(string="Date d'effet", required=True)
    company_id = fields.Many2one(
        'res.company', string="Société",
        help="Vide : valable pour toutes les sociétés.")
    note = fields.Char(string="Note")

    @api.constrains('code', 'date_from', 'company_id')
    def _check_unique_line(self):
        for line in self:
            if self.search_count([
                    ('id', '!=', line.id), ('code', '=', line.code),
                    ('date_from', '=', line.date_from),
                    ('company_id', '=', line.company_id.id)]):
                raise ValidationError(_(
                    "Une ligne existe déjà pour %(code)s à la date %(date)s "
                    "(même société) : ajoutez plutôt une ligne à une autre "
                    "date d'effet.") % {'code': line.code,
                                         'date': line.date_from})

    @api.model
    def _get_value(self, code, date, company):
        """Valeur en vigueur au `date` pour `company` (ligne de la société
        sinon ligne globale). UserError si aucune ligne n'est applicable."""
        domain = [('code', '=', code), ('date_from', '<=', date)]
        Param = self.sudo()
        line = Param.search(domain + [('company_id', '=', company.id)],
                            order='date_from desc', limit=1) if company \
            else Param
        if not line:
            line = Param.search(domain + [('company_id', '=', False)],
                                order='date_from desc', limit=1)
        if not line:
            raise UserError(_(
                "%(code)s non défini avant cette date (%(date)s) pour la "
                "société %(company)s. Ajoutez une ligne datée dans Paie > "
                "Configuration > Paramètres de cotisations.") % {
                    'code': code, 'date': date,
                    'company': company.name or '-'})
        return line.value

    @api.model
    def _seed_defaults(self):
        """Valeurs initiales, idempotentes : une ligne n'est créée que si
        aucune ligne globale n'existe pour (code, date d'effet) ; une valeur
        existante n'est jamais modifiée."""
        for code, value, date_from in DEFAULT_PARAMS:
            if not self.sudo().search_count([
                    ('code', '=', code), ('date_from', '=', date_from),
                    ('company_id', '=', False)]):
                self.sudo().create({
                    'code': code, 'value': value, 'date_from': date_from,
                    'note': "Valeur initiale"})
