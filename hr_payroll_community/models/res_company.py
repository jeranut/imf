# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    """Hérite de res.company pour ajouter la configuration paie Madagascar"""
    _inherit = 'res.company'

    sme_amount = fields.Monetary(
        string='Montant SME',
        help="Salaire Minimum d'Embauche, utilisé comme base de calcul du "
             "plafond CNAPS/OSTIE.")
    cnaps_ceiling_multiplier = fields.Integer(
        string='Multiplicateur du plafond CNAPS',
        default=8,
        help="Nombre de fois le montant SME qui constitue le plafond de "
             "cotisation CNAPS/OSTIE.")
    payroll_journal_id = fields.Many2one(
        'account.journal', string='Journal de paie',
        help="Journal comptable utilisé pour générer l'écriture comptable "
             "à la validation des bulletins de paie.")
    hr_payroll_entries = fields.Boolean(
        string='Écritures de paie', default=False,
        help="Équivalent Community du paramètre Enterprise "
             "res.company.payroll_journal_id + toggle des écritures : si "
             "désactivé, aucune écriture comptable n'est générée à la "
             "validation des bulletins, quel que soit le journal configuré.")
