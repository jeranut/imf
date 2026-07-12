# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


def _pcec_default(code):
    """Défaut calculé pour un champ account.account : recherche par code + société, jamais
    par référence XML statique (les comptes PCEC sont dupliqués par société via le chart
    template plan_compta_pcec). Retourne un recordset vide si le compte n'existe pas pour la
    société courante (plan PCEC non chargé) : le champ reste simplement vide."""
    def _default(self):
        return self.env['account.account'].search([
            ('code', '=', code), ('company_id', '=', self.env.company.id),
        ], limit=1)
    return _default


def _journal_default(code):
    """Défaut calculé pour un champ account.journal : recherche par code + société (les
    journaux créés par microfinance_loan_management.hooks.post_init_hook sont dupliqués par
    société, jamais référencés par ID statique)."""
    def _default(self):
        return self.env['account.journal'].search([
            ('code', '=', code), ('company_id', '=', self.env.company.id),
        ], limit=1)
    return _default


class MicrofinanceSavingsProduct(models.Model):
    _name = 'microfinance.savings.product'
    _description = "Produit d'épargne microfinance"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(string='Nom', required=True, tracking=True)
    code = fields.Char(
        string='Code', required=True, tracking=True, default='Nouveau', copy=False, readonly=True,
        help="Généré automatiquement à la création (préfixe configurable par société "
             "'res.company.savings_product_code_prefix' + numéro séquentiel), jamais saisi "
             "manuellement.",
    )
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
    withdrawal_limit_amount = fields.Monetary(
        string='Plafond de retrait par transaction', default=0.0,
        help="Si renseigné, bloque tout retrait (type 'Retrait' uniquement) dont le montant "
             "dépasse ce plafond, transaction par transaction (pas de cumul sur une période). "
             "Un retrait avec la dérogation 'Déroger au plafond de retrait' (ex. clôture de "
             "compte) n'est pas soumis à ce plafond.",
    )
    maintenance_fee_amount = fields.Monetary(
        string='Frais de tenue de compte', default=0.0, readonly=True,
        help='Non implémenté — sans effet actuellement. Aucun cron ne prélève ces frais '
             "périodiquement ; utiliser une transaction manuelle de type 'Frais prélevés' en "
             'attendant.',
    )
    maintenance_fee_frequency = fields.Selection([
        ('monthly', 'Mensuelle'),
        ('quarterly', 'Trimestrielle'),
        ('annual', 'Annuelle'),
    ], string='Fréquence des frais de tenue de compte', default='monthly', readonly=True,
        help='Non implémenté — sans effet actuellement (lié à Frais de tenue de compte, ci-dessus).')
    early_withdrawal_penalty_rate = fields.Float(
        string='Pénalité de retrait anticipé (%)', default=0.0,
        help="Taux appliqué automatiquement, en ligne comptable séparée sur le compte 'Pénalités "
             "sur épargne' ci-dessous, sur tout retrait comptabilisé avant l'une des deux "
             "échéances suivantes (dès que l'une des deux est configurée et pas encore atteinte, "
             "jamais cumulées) : la date d'échéance du compte (produit à terme uniquement) ou le "
             "délai minimum de rétention ci-dessous (tout type de produit).",
    )
    min_retention_days = fields.Integer(
        string='Délai minimum de rétention (jours)', default=0,
        help="Nombre de jours minimum depuis l'ouverture du compte avant qu'un retrait soit "
             "possible sans pénalité, quel que soit le type de produit (y compris épargne "
             "libre) — contrairement à la date d'échéance, réservée aux produits à terme. "
             "Calculé depuis la date d'ouverture du compte (pas de suivi par dépôt individuel "
             "dans ce modèle). Sans effet si Pénalité de retrait anticipé (%) est à 0.",
    )
    term_months = fields.Integer(string='Durée (mois)', help='Requis pour un produit à terme.')

    # --- Comptabilité : Épargne ---
    account_epargne_individuel_id = fields.Many2one(
        'account.account', string='Épargne - Individuel', required=True,
        domain="[('account_type', '=', 'liability_current'), ('company_id', '=', company_id)]",
        default=_pcec_default('213001'),
    )
    account_epargne_groupe_id = fields.Many2one(
        'account.account', string='Épargne - Groupe', required=True,
        domain="[('account_type', '=', 'liability_current'), ('company_id', '=', company_id)]",
        default=_pcec_default('213002'),
    )
    account_epargne_entreprise_id = fields.Many2one(
        'account.account', string='Épargne - Entreprise', required=True,
        domain="[('account_type', '=', 'liability_current'), ('company_id', '=', company_id)]",
        default=_pcec_default('213003'),
    )

    # --- Comptabilité : Intérêts ---
    account_interet_paye_individuel_id = fields.Many2one(
        'account.account', string='Intérêt payé - Individuel',
        domain="[('account_type', '=', 'expense'), ('company_id', '=', company_id)]",
        default=_pcec_default('607301'),
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR pour ce produit.",
    )
    account_interet_paye_groupe_id = fields.Many2one(
        'account.account', string='Intérêt payé - Groupe',
        domain="[('account_type', '=', 'expense'), ('company_id', '=', company_id)]",
        default=_pcec_default('607302'),
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR pour ce produit.",
    )
    account_interet_paye_entreprise_id = fields.Many2one(
        'account.account', string='Intérêt payé - Entreprise',
        domain="[('account_type', '=', 'expense'), ('company_id', '=', company_id)]",
        default=_pcec_default('607303'),
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR pour ce produit.",
    )
    account_interets_avance_individuel_id = fields.Many2one(
        'account.account', string="Intérêts comptabilisés d'avance - Individuel",
        domain="[('account_type', '=', 'liability_current'), ('company_id', '=', company_id)]",
        default=_pcec_default('325005'),
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR pour ce produit.",
    )
    account_interets_avance_groupe_id = fields.Many2one(
        'account.account', string="Intérêts comptabilisés d'avance - Groupe",
        domain="[('account_type', '=', 'liability_current'), ('company_id', '=', company_id)]",
        default=_pcec_default('325006'),
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR pour ce produit.",
    )
    account_interets_avance_entreprise_id = fields.Many2one(
        'account.account', string="Intérêts comptabilisés d'avance - Entreprise",
        domain="[('account_type', '=', 'liability_current'), ('company_id', '=', company_id)]",
        default=_pcec_default('325007'),
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR pour ce produit.",
    )
    account_cout_interet_payer_individuel_id = fields.Many2one(
        'account.account', string="Coût de l'intérêt à payer - Individuel",
        domain="[('account_type', '=', 'liability_current'), ('company_id', '=', company_id)]",
        default=_pcec_default('218001'),
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR pour ce produit.",
    )
    account_cout_interet_payer_groupe_id = fields.Many2one(
        'account.account', string="Coût de l'intérêt à payer - Groupe",
        domain="[('account_type', '=', 'liability_current'), ('company_id', '=', company_id)]",
        default=_pcec_default('218002'),
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR pour ce produit.",
    )
    account_cout_interet_payer_entreprise_id = fields.Many2one(
        'account.account', string="Coût de l'intérêt à payer - Entreprise",
        domain="[('account_type', '=', 'liability_current'), ('company_id', '=', company_id)]",
        default=_pcec_default('218003'),
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR pour ce produit.",
    )
    # --- Comptabilité : Comptes partagés ---
    account_penalites_id = fields.Many2one(
        'account.account', string='Pénalités sur épargne',
        domain="[('account_type', '=', 'income'), ('company_id', '=', company_id)]",
        default=_pcec_default('749003'),
        help='Requis dès que Pénalité de retrait anticipé (%) est renseigné sur un produit à '
             "terme : la pénalité calculée y est créditée automatiquement. Peut rester vide "
             "si aucune pénalité n'est configurée.",
    )
    account_commission_id = fields.Many2one(
        'account.account', string='Commission sur épargne',
        domain="[('account_type', '=', 'income'), ('company_id', '=', company_id)]",
        default=_pcec_default('717004'),
        help="Compte de comptabilisation des frais de tenue de compte. Requis uniquement si des frais sont prélevés pour ce produit.",
    )
    account_commission_cheques_rejetes_id = fields.Many2one(
        'account.account', string='Commission sur chèques rejetés',
        domain="[('account_type', '=', 'income'), ('company_id', '=', company_id)]",
        default=_pcec_default('719000'), readonly=True,
        help='Non implémenté — sans effet actuellement. Aucun mode de paiement "chèque" ni '
             'transaction "chèque rejeté" ne existe encore sur ce modèle.',
    )
    account_retenue_taxe_id = fields.Many2one(
        'account.account', string='Retenue de taxe',
        domain="[('account_type', '=', 'liability_current'), ('company_id', '=', company_id)]",
        default=_pcec_default('467000'), readonly=True,
        help="Non implémenté — sans effet actuellement. Compte technique 467000 : hors "
             "nomenclature PCEC officielle, créé par ce module faute de poste dédié identifié "
             "dans les classes 1-7 (voir audit_pcg2005_mapping).",
    )
    account_papeterie_id = fields.Many2one(
        'account.account', string="Papeterie pour l'épargne",
        domain="[('account_type', '=', 'income'), ('company_id', '=', company_id)]",
        default=_pcec_default('749004'), readonly=True,
        help='Non implémenté — sans effet actuellement. Aucune transaction ne ventile encore '
             'une part "papeterie" séparée du dépôt/retrait.',
    )

    deposit_journal_id = fields.Many2one(
        'account.journal', string='Journal dépôt', domain="[('type', 'in', ('bank','cash'))]",
        default=_journal_default('EPG'),
    )
    withdrawal_journal_id = fields.Many2one(
        'account.journal', string='Journal retrait', domain="[('type', 'in', ('bank','cash'))]",
        default=_journal_default('EPG'),
    )
    company_id = fields.Many2one('res.company', string='Société', default=lambda self: self.env.company, required=True)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', readonly=True)
    active = fields.Boolean(string='Actif', default=True)

    _sql_constraints = [
        ('code_company_unique', 'unique(code, company_id)', 'Le code produit doit être unique par société.'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('code', 'Nouveau') in (False, '', 'Nouveau'):
                company = self.env['res.company'].browse(vals['company_id']) if vals.get('company_id') else self.env.company
                prefix = company.savings_product_code_prefix or 'EP'
                number = self.env['ir.sequence'].next_by_code('microfinance.savings.product') or '00000'
                vals['code'] = '%s%s' % (prefix, number)
        return super().create(vals_list)

    @api.constrains('interest_rate', 'min_opening_amount', 'min_balance', 'withdrawal_limit_amount',
                     'maintenance_fee_amount', 'early_withdrawal_penalty_rate', 'min_retention_days',
                     'term_months', 'product_type')
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
            if product.min_retention_days < 0:
                raise ValidationError(_('Le délai minimum de rétention ne peut pas être négatif.'))
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
