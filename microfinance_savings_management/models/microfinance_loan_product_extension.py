# -*- coding: utf-8 -*-
from odoo import fields, models


class MicrofinanceLoanProduct(models.Model):
    _inherit = 'microfinance.loan.product'

    # --- Prélèvement automatique sur épargne (point 10) ---
    allow_savings_auto_debit = fields.Boolean(
        string='Autoriser le prélèvement automatique sur épargne', default=False,
    )
    auto_debit_grace_days = fields.Integer(
        string='Délai de grâce avant prélèvement (jours)', default=0,
        help="Nombre de jours de retard avant déclenchement du prélèvement automatique.",
    )
    auto_debit_respect_minimum_balance = fields.Boolean(
        string='Respecter le solde minimum épargne', default=True,
        help='Si coché, le prélèvement ne peut jamais faire descendre le solde épargne sous le '
             "solde minimum du produit d'épargne. Si décoché, autorise à vider le compte (cas "
             "d'une épargne obligatoire nantie explicitement en garantie de ce crédit).",
    )

    # --- Éligibilité progressive & apport épargne (§3bis) ---
    # Valeurs par défaut fournies à titre d'hypothèses de configuration à valider avec Micka avant
    # mise en production : elles ne sont pas des constantes métier universelles, chaque
    # institution/programme peut avoir ses propres seuils et ratios.
    savings_requirement_type = fields.Selection([
        ('none', 'Aucune exigence épargne'),
        ('target_during_loan', 'Épargne cible pendant le remboursement'),
        ('upfront_apport', 'Apport épargne exigé avant décaissement'),
    ], string='Exigence épargne', required=True, default='none', tracking=True)
    savings_amount_threshold = fields.Monetary(
        string="Seuil de montant (info)", default=0.0,
        help="Seuil indicatif au-delà duquel ce produit correspond au palier 'apport en amont' "
             "dans le programme progressif de l'institution. Purement informatif ici : c'est bien "
             "savings_requirement_type qui pilote le contrôle, pas ce seuil.",
    )
    savings_target_ratio = fields.Float(
        string='Ratio épargne cible (%)', default=20.0,
        help='Utilisé si "Épargne cible pendant le remboursement" : ratio montant épargne cible / '
             'montant emprunté.',
    )
    savings_apport_ratio = fields.Float(
        string="Ratio d'apport (%)", default=0.0,
        help='Utilisé si "Apport épargne exigé avant décaissement" : ratio apport minimum exigé / '
             'montant demandé.',
    )
    savings_product_id = fields.Many2one(
        'microfinance.savings.product', string="Produit d'épargne du programme",
        help="Produit d'épargne dans lequel la cible/l'apport doit être constitué.",
    )
