# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class MicrofinanceSavingsProduct(models.Model):
    _name = 'microfinance.savings.product'
    _description = "Produit d'épargne microfinance"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(string='Nom', required=True, tracking=True)
    code = fields.Char(string='Code', required=True, tracking=True)
    product_type = fields.Selection([
        ('compulsory', 'Obligatoire (liée à un crédit)'),
        ('voluntary', 'Volontaire'),
        ('term_deposit', 'À terme (dépôt à terme)'),
    ], string='Type de produit', required=True, default='voluntary', tracking=True)
    interest_rate = fields.Float(string='Taux intérêt annuel (%)', default=0.0)
    balance_method = fields.Selection([
        ('min_balance', 'Solde minimum de la période'),
        ('average_balance', 'Solde moyen de la période'),
        ('closing_balance', 'Solde en fin de période'),
    ], string='Méthode de calcul du solde', required=True, default='min_balance')
    capitalization_frequency = fields.Selection([
        ('monthly', 'Mensuelle'),
        ('quarterly', 'Trimestrielle'),
        ('annual', 'Annuelle'),
    ], string='Fréquence de capitalisation', required=True, default='monthly')
    min_opening_amount = fields.Monetary(string="Montant minimum d'ouverture", default=0.0)
    min_balance = fields.Monetary(
        string='Solde minimum à maintenir', default=0.0,
        help='Solde gelé (frozen balance) : un retrait ne peut pas faire descendre le solde du '
             'compte en dessous de ce montant, sauf prélèvement automatique en dérogation explicite.',
    )
    withdrawal_limit_amount = fields.Monetary(string='Plafond de retrait', default=0.0)
    withdrawal_limit_period = fields.Selection([
        ('transaction', 'Par transaction'),
        ('month', 'Par mois'),
    ], string='Période du plafond de retrait', default='transaction')
    maintenance_fee_amount = fields.Monetary(string='Frais de tenue de compte', default=0.0)
    maintenance_fee_frequency = fields.Selection([
        ('monthly', 'Mensuelle'),
        ('quarterly', 'Trimestrielle'),
        ('annual', 'Annuelle'),
    ], string='Fréquence des frais de tenue de compte', default='monthly')
    early_withdrawal_penalty_rate = fields.Float(
        string='Pénalité de retrait anticipé (%)', default=0.0,
        help='Uniquement pertinent pour un produit à terme.',
    )
    term_months = fields.Integer(string='Durée (mois)', help='Requis pour un produit à terme.')

    # --- Comptabilité : Épargne ---
    account_epargne_individuel_id = fields.Many2one(
        'account.account', string='Épargne - Individuel', required=True,
        domain="[('account_type', '=', 'liability_current'), ('company_id', '=', company_id)]",
    )
    account_epargne_groupe_id = fields.Many2one(
        'account.account', string='Épargne - Groupe', required=True,
        domain="[('account_type', '=', 'liability_current'), ('company_id', '=', company_id)]",
    )
    account_epargne_entreprise_id = fields.Many2one(
        'account.account', string='Épargne - Entreprise', required=True,
        domain="[('account_type', '=', 'liability_current'), ('company_id', '=', company_id)]",
    )

    # --- Comptabilité : Intérêts ---
    account_interet_paye_individuel_id = fields.Many2one(
        'account.account', string='Intérêt payé - Individuel',
        domain="[('account_type', '=', 'expense'), ('company_id', '=', company_id)]",
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR pour ce produit.",
    )
    account_interet_paye_groupe_id = fields.Many2one(
        'account.account', string='Intérêt payé - Groupe',
        domain="[('account_type', '=', 'expense'), ('company_id', '=', company_id)]",
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR pour ce produit.",
    )
    account_interet_paye_entreprise_id = fields.Many2one(
        'account.account', string='Intérêt payé - Entreprise',
        domain="[('account_type', '=', 'expense'), ('company_id', '=', company_id)]",
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR pour ce produit.",
    )
    account_interets_avance_individuel_id = fields.Many2one(
        'account.account', string="Intérêts comptabilisés d'avance - Individuel",
        domain="[('account_type', '=', 'liability_current'), ('company_id', '=', company_id)]",
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR pour ce produit.",
    )
    account_interets_avance_groupe_id = fields.Many2one(
        'account.account', string="Intérêts comptabilisés d'avance - Groupe",
        domain="[('account_type', '=', 'liability_current'), ('company_id', '=', company_id)]",
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR pour ce produit.",
    )
    account_interets_avance_entreprise_id = fields.Many2one(
        'account.account', string="Intérêts comptabilisés d'avance - Entreprise",
        domain="[('account_type', '=', 'liability_current'), ('company_id', '=', company_id)]",
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR pour ce produit.",
    )
    account_cout_interet_payer_individuel_id = fields.Many2one(
        'account.account', string="Coût de l'intérêt à payer - Individuel",
        domain="[('account_type', '=', 'liability_current'), ('company_id', '=', company_id)]",
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR pour ce produit.",
    )
    account_cout_interet_payer_groupe_id = fields.Many2one(
        'account.account', string="Coût de l'intérêt à payer - Groupe",
        domain="[('account_type', '=', 'liability_current'), ('company_id', '=', company_id)]",
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR pour ce produit.",
    )
    account_cout_interet_payer_entreprise_id = fields.Many2one(
        'account.account', string="Coût de l'intérêt à payer - Entreprise",
        domain="[('account_type', '=', 'liability_current'), ('company_id', '=', company_id)]",
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR pour ce produit.",
    )
    account_charge_interet_negatif_individuel_id = fields.Many2one(
        'account.account', string="Charge de l'intérêt négative - Individuel",
        domain="[('account_type', '=', 'income'), ('company_id', '=', company_id)]",
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR pour ce produit.",
    )
    account_charge_interet_negatif_groupe_id = fields.Many2one(
        'account.account', string="Charge de l'intérêt négative - Groupe",
        domain="[('account_type', '=', 'income'), ('company_id', '=', company_id)]",
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR pour ce produit.",
    )
    account_charge_interet_negatif_entreprise_id = fields.Many2one(
        'account.account', string="Charge de l'intérêt négative - Entreprise",
        domain="[('account_type', '=', 'income'), ('company_id', '=', company_id)]",
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR pour ce produit.",
    )

    # --- Comptabilité : Comptes partagés ---
    account_penalites_id = fields.Many2one(
        'account.account', string='Pénalités sur épargne',
        domain="[('account_type', '=', 'income'), ('company_id', '=', company_id)]",
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR.",
    )
    account_commission_id = fields.Many2one(
        'account.account', string='Commission sur épargne',
        domain="[('account_type', '=', 'income'), ('company_id', '=', company_id)]",
        help="Compte de comptabilisation des frais de tenue de compte. Requis uniquement si des frais sont prélevés pour ce produit.",
    )
    account_cheques_id = fields.Many2one(
        'account.account', string='Comptes chèques',
        domain="[('account_type', '=', 'asset_current'), ('company_id', '=', company_id)]",
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR.",
    )
    account_commission_cheques_rejetes_id = fields.Many2one(
        'account.account', string='Commission sur chèques rejetés',
        domain="[('account_type', '=', 'income'), ('company_id', '=', company_id)]",
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR.",
    )
    account_retenue_taxe_id = fields.Many2one(
        'account.account', string='Retenue de taxe',
        domain="[('account_type', '=', 'liability_current'), ('company_id', '=', company_id)]",
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR.",
    )
    account_papeterie_id = fields.Many2one(
        'account.account', string="Papeterie pour l'épargne",
        domain="[('account_type', '=', 'income'), ('company_id', '=', company_id)]",
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR.",
    )

    deposit_journal_id = fields.Many2one('account.journal', string='Journal dépôt', domain="[('type', 'in', ('bank','cash'))]")
    withdrawal_journal_id = fields.Many2one('account.journal', string='Journal retrait', domain="[('type', 'in', ('bank','cash'))]")
    company_id = fields.Many2one('res.company', string='Société', default=lambda self: self.env.company, required=True)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', readonly=True)
    active = fields.Boolean(string='Actif', default=True)

    _sql_constraints = [
        ('code_company_unique', 'unique(code, company_id)', 'Le code produit doit être unique par société.'),
    ]

    @api.constrains('interest_rate', 'min_opening_amount', 'min_balance', 'withdrawal_limit_amount',
                     'maintenance_fee_amount', 'early_withdrawal_penalty_rate', 'term_months', 'product_type')
    def _check_values(self):
        for product in self:
            if product.interest_rate < 0:
                raise ValidationError(_("Le taux d'intérêt ne peut pas être négatif."))
            if product.min_opening_amount < 0 or product.min_balance < 0:
                raise ValidationError(_('Les montants minimum ne peuvent pas être négatifs.'))
            if product.withdrawal_limit_amount < 0:
                raise ValidationError(_('Le plafond de retrait ne peut pas être négatif.'))
            if product.maintenance_fee_amount < 0:
                raise ValidationError(_('Les frais de tenue de compte ne peuvent pas être négatifs.'))
            if product.early_withdrawal_penalty_rate < 0:
                raise ValidationError(_('La pénalité de retrait anticipé ne peut pas être négative.'))
            if product.product_type == 'term_deposit' and not product.term_months:
                raise ValidationError(_('Un produit à terme doit avoir une durée en mois.'))

    def _get_account(self, kind, partner):
        """Retourne le compte account_<kind>_individuel_id / _groupe_id / _entreprise_id
        selon le type de client (les 3 variantes existent côté épargne)."""
        self.ensure_one()
        variant = {
            'company': 'entreprise',
            'group': 'groupe',
        }.get(partner.microfinance_client_type, 'individuel')
        return self['account_%s_%s_id' % (kind, variant)]
