# -*- coding: utf-8 -*-
#############################################################################
#    A part of Open HRMS Project <https://www.openhrms.com>
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2023-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Cybrosys Techno Solutions(<https://www.cybrosys.com>)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    (LGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
#############################################################################
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    """Inherit res_config_settings model for adding some fields in Settings"""
    _inherit = 'res.config.settings'

    module_account_accountant = fields.Boolean(string='Account Accountant',
                                               help="Is Account Accountant")
    module_l10n_fr_hr_payroll = fields.Boolean(string='French Payroll',
                                               help="Is French Payroll")
    module_l10n_be_hr_payroll = fields.Boolean(string='Belgium Payroll',
                                               help="Is Belgium Payroll")
    module_l10n_in_hr_payroll = fields.Boolean(string='Indian Payroll',
                                               help="Is Indian Payroll")
    sme_amount = fields.Monetary(
        related='company_id.sme_amount', readonly=False,
        string='Montant SME',
        help="Salaire Minimum d'Embauche, utilisé comme base de calcul du "
             "plafond CNAPS/OSTIE.")
    cnaps_ceiling_multiplier = fields.Integer(
        related='company_id.cnaps_ceiling_multiplier', readonly=False,
        string='Multiplicateur du plafond CNAPS',
        help="Nombre de fois le montant SME qui constitue le plafond de "
             "cotisation CNAPS/OSTIE.")
    payroll_journal_id = fields.Many2one(
        related='company_id.payroll_journal_id', readonly=False,
        string='Journal de paie',
        help="Journal comptable utilisé pour générer l'écriture comptable "
             "à la validation des bulletins de paie.")
    hr_payroll_entries = fields.Boolean(
        related='company_id.hr_payroll_entries', readonly=False,
        string='Écritures de paie',
        help="Active la génération d'une écriture comptable à la "
             "validation des bulletins de paie.")
