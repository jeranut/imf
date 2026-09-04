# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MicrofinanceLoanApplication(models.Model):
    _inherit = 'microfinance.loan.application'

    savings_amount = fields.Monetary(
        string='Épargne (montant)', compute='_compute_savings_amount', store=True, readonly=True,
        help="Somme des soldes des comptes épargne actifs du client — calculée automatiquement "
             "depuis microfinance_savings_management (remplace la saisie manuelle du module "
             "crédit seul).",
    )

    @api.depends('partner_id.microfinance_savings_account_ids.balance',
                 'partner_id.microfinance_savings_account_ids.state')
    def _compute_savings_amount(self):
        for application in self:
            accounts = application.partner_id.microfinance_savings_account_ids.filtered(
                lambda a: a.state == 'active')
            application.savings_amount = sum(accounts.mapped('balance'))

    # Champ relais, sans équivalent direct sur ce modèle avant ce champ : sert uniquement de
    # condition invisible= pour ca_required_savings/cdag_required_savings (cf. vue héritée) - un
    # invisible= de vue Odoo 17 ne peut pas traverser loan_id.guarantee_savings_percent
    # directement, cf. docs_dev/epargne_exigee_ca_cdag/AUDIT.md. Valeur elle-même sans intérêt
    # propre ici (ca_required_savings/cdag_required_savings, déjà related='loan_id.avis_ca_
    # epargne_exigee'/'loan_id.avis_cdag_epargne_exigee', portent déjà la vraie valeur calculée).
    guarantee_savings_required = fields.Monetary(
        related='loan_id.guarantee_savings_required', string='Épargne garantie requise (crédit)', readonly=True,
    )
    # required_savings/available_savings (chantier "Épargne exigée/disponible", docs_dev/
    # epargne_exigee_disponible/AUDIT.md) : redéfinis directement dans microfinance_loan_
    # management/models/microfinance_loan_application.py (pas ici) - un champ related= dont la
    # CIBLE n'existe pas encore au chargement se résout paresseusement sans problème, mais le
    # CHAMP lui-même doit exister dès le chargement du module de base (sa propre vue le
    # référence) - cf. commentaire détaillé sur ces deux champs dans ce fichier.
