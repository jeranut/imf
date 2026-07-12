# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


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

    # --- Éligibilité progressive (§3bis) ---
    # Valeurs par défaut fournies à titre d'hypothèses de configuration à valider avec Micka avant
    # mise en production : elles ne sont pas des constantes métier universelles, chaque
    # institution/programme peut avoir ses propres seuils et ratios.
    savings_requirement_type = fields.Selection([
        ('none', 'Aucune exigence épargne'),
        ('target_during_loan', 'Épargne cible pendant le remboursement'),
    ], string='Exigence épargne', required=True, default='none', tracking=True)
    savings_amount_threshold = fields.Monetary(
        string="Seuil de montant (info)", default=0.0,
        help="Seuil indicatif au-delà duquel ce produit correspond au palier supérieur dans le "
             "programme progressif de l'institution. Purement informatif ici : c'est bien "
             "savings_requirement_type qui pilote le contrôle, pas ce seuil.",
    )
    savings_target_ratio = fields.Float(
        string='Ratio épargne cible (%)', default=20.0,
        help='Utilisé si "Épargne cible pendant le remboursement" : ratio montant épargne cible / '
             'montant emprunté.',
    )
    savings_product_id = fields.Many2one(
        'microfinance.savings.product', string="Produit d'épargne du programme",
        help="Produit d'épargne dans lequel la cible doit être constituée (éligibilité "
             "progressive, §3bis). Sans rapport avec l'épargne garantie de crédit ci-dessous.",
    )

    # --- Épargne garantie de crédit (§3, mécanisme LPF) ---
    guarantee_savings_percent = fields.Float(
        string='Épargne garantie exigée (%)', default=0.0,
        help="Pourcentage du montant du crédit demandé qui doit être disponible sur le compte "
             "d'épargne garantie du client (produit ci-dessous) au moment de la demande de "
             "crédit. Si à 0, aucune vérification n'est effectuée. Non applicable aux clients de "
             "type Société (garantie sur compte d'épargne réservée aux particuliers/groupes, "
             "cohérent avec le reste du module épargne).",
    )
    guarantee_savings_product_id = fields.Many2one(
        'microfinance.savings.product', string="Produit d'épargne garantie de crédit",
        help="Produit d'épargne dont le solde sert de garantie de crédit pour ce produit de "
             "crédit (ex. produit dédié « Épargne garantie de crédit »). Requis si un pourcentage "
             "d'épargne garantie exigée est renseigné ci-dessus. Le solde vérifié est la somme des "
             "comptes actifs du client sur ce produit, quel que soit le compte précis choisi.",
    )

    @api.constrains('guarantee_savings_percent', 'guarantee_savings_product_id')
    def _check_guarantee_savings_config(self):
        for product in self:
            if product.guarantee_savings_percent < 0:
                raise ValidationError(_("Le pourcentage d'épargne garantie exigée ne peut pas être négatif."))
            if product.guarantee_savings_percent and not product.guarantee_savings_product_id:
                raise ValidationError(_(
                    "Configurez le produit d'épargne garantie de crédit : un pourcentage d'épargne "
                    "garantie exigée est renseigné sans indiquer sur quel produit d'épargne le "
                    "vérifier."
                ))
