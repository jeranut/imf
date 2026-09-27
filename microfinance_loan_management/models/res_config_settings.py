# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    microfinance_product_policy = fields.Selection([
        ('independent', 'Produit indépendant'),
        ('progressive', 'Produit progressif'),
    ], string='Politique de produit',
        config_parameter='microfinance_loan_management.microfinance_product_policy',
        default='independent',
        help="Détermine si les nouveaux dossiers de crédit se créent sur des produits "
             "indépendants ou sur des produits rattachés à un programme progressif. Ce "
             "réglage est unique pour l'ensemble des agences et ne s'applique qu'aux "
             "nouveaux dossiers : les dossiers et crédits déjà créés sous l'ancienne "
             "politique ne sont jamais affectés rétroactivement.",
    )

    microfinance_parent_company_id = fields.Many2one(
        'res.company', string='Société mère (fonds bailleurs)',
        config_parameter='microfinance.parent_company_id',
        help="Société qui configure seule les bailleurs et les fonds de crédit, et les partage "
             "entre les agences (elle-même incluse). Tant qu'aucune société mère n'est "
             "désignée, le fonctionnement des fonds reste celui d'origine (aucune restriction).",
    )
