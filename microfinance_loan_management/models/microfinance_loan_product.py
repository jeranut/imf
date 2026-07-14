# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


def _pcec_default(code):
    """Défaut calculé pour un champ account.account : recherche par code + société, jamais
    par référence XML statique (les comptes PCEC sont dupliqués par société via le chart
    template plan_compta_pcec). Retourne un recordset vide si le compte n'existe pas pour la
    société courante (plan PCEC non chargé) : le champ reste simplement vide, comme avant
    l'introduction de ce défaut."""
    def _default(self):
        return self.env['account.account'].search([
            ('code', '=', code), ('company_id', '=', self.env.company.id),
        ], limit=1)
    return _default


def _journal_default(code):
    """Défaut calculé pour un champ account.journal : recherche par code + société (les
    journaux créés par post_init_hook sont dupliqués par société, jamais référencés par ID
    statique)."""
    def _default(self):
        return self.env['account.journal'].search([
            ('code', '=', code), ('company_id', '=', self.env.company.id),
        ], limit=1)
    return _default


class MicrofinanceLoanProduct(models.Model):
    _name = 'microfinance.loan.product'
    _description = 'Produit de crédit microfinance'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(string='Nom', required=True, tracking=True)
    code = fields.Char(
        string='Code', required=True, tracking=True, default='Nouveau', copy=False, readonly=True,
        help="Généré automatiquement à la création (préfixe configurable par société "
             "'res.company.loan_product_code_prefix' + numéro séquentiel), jamais saisi "
             "manuellement.",
    )
    min_amount = fields.Monetary(string='Montant minimum', required=True, default=0.0)
    max_amount = fields.Monetary(string='Montant maximum', required=True, default=0.0)
    min_term = fields.Integer(string='Durée min.', default=1, required=True)
    max_term = fields.Integer(string='Durée max.', default=12, required=True)
    interest_rate = fields.Float(string='Taux intérêt annuel (%)', required=True, default=0.0)
    interest_method = fields.Selection([
        ('flat', 'Taux fixe'),
        ('reducing', 'Solde dégressif'),
    ], string='Méthode de calcul des intérêts', required=True, default='flat')
    repayment_frequency_mode = fields.Selection([
        ('fixed', 'Périodicité unique imposée'),
        ('client_choice', 'Choix du client/agent parmi une liste autorisée'),
    ], string='Mode de périodicité de remboursement', required=True, default='fixed', tracking=True,
        help='"Périodicité unique" : le produit impose une seule périodicité, comme un premier '
             'prêt en zone urbaine avec remboursement hebdomadaire obligatoire. "Choix du client" : '
             "le client/agent choisit à la création du crédit parmi une liste de périodicités "
             'autorisées, comme un premier prêt rural où le client choisit hebdomadaire ou mensuel '
             'selon la saisonnalité de ses revenus.')
    repayment_frequency_id = fields.Many2one(
        'microfinance.repayment.frequency', string='Périodicité de remboursement',
        help='Requis si le mode est "Périodicité unique imposée".',
    )
    allowed_repayment_frequency_ids = fields.Many2many(
        'microfinance.repayment.frequency', string='Périodicités autorisées',
        help='Utilisé si le mode est "Choix du client/agent" : liste des périodicités que le '
             "client/agent peut choisir à la création du crédit. Au moins une requise.",
    )
    installment_rounding_unit = fields.Monetary(
        string="Unité d'arrondi de l'échéance", default=1000.0,
        help="Politique interest-first (génération d'échéancier, méthode de calcul "
             "d'intérêts \"Taux fixe\") : le montant total cible par tranche est arrondi au plus "
             "proche multiple de cette unité avant répartition intérêt/principal - la dernière "
             "tranche absorbe le reliquat d'arrondi exact. Aucune règle spéciale pour les petits "
             "crédits : l'arrondi s'applique systématiquement, y compris si la cible arrondie "
             "tombe à 0. Mettre à 0 pour désactiver l'arrondi (cible utilisée telle quelle).",
    )
    grace_period_days = fields.Integer(string='Délai de grâce (jours)', default=0)
    min_membership_days = fields.Integer(string='Ancienneté minimum client (jours)', default=0)
    allow_second_loan = fields.Boolean(string='Autoriser un 2e crédit actif', default=True)
    block_second_if_arrears = fields.Boolean(string='Bloquer le 2e crédit si le 1er a des arriérés', default=True)
    guarantee_required = fields.Boolean(string='Garantie obligatoire', default=False)
    min_guarantee_ratio = fields.Float(
        string='Ratio minimum de garantie (%)', default=0.0,
        help='Pourcentage minimum du montant du crédit que la somme des garanties validées doit couvrir. '
             '0 = pas de minimum même si une garantie est obligatoire.',
    )
    penalty_type = fields.Selection([
        ('fixed', 'Montant fixe'),
        ('percentage', 'Pourcentage'),
    ], string='Type de pénalité', default='fixed', required=True)
    penalty_amount = fields.Monetary(string='Pénalité fixe', default=0.0)
    penalty_rate = fields.Float(string='Taux pénalité (%)', default=0.0)
    disbursement_journal_id = fields.Many2one(
        'account.journal', string='Journal décaissement',
        domain="[('type', 'in', ('bank','cash')), ('company_id', '=', company_id)]",
        default=_journal_default('CRE'),
    )
    payment_journal_id = fields.Many2one(
        'account.journal', string='Journal remboursement',
        domain="[('type', 'in', ('bank','cash')), ('company_id', '=', company_id)]",
        default=_journal_default('CRE'),
    )
    disbursement_limit_amount = fields.Monetary(
        string='Plafond de décaissement en espèces', default=0.0,
        help="Si renseigné, bloque tout décaissement dont le montant net remis au client "
             "dépasse ce plafond — uniquement lorsque le journal de décaissement du produit "
             "(disbursement_journal_id) est de type 'Espèces' (aucun plafond sur un "
             "décaissement par banque). Contrôle par décaissement individuel, pas de cumul "
             "sur une période — même principe que withdrawal_limit_amount côté épargne.",
    )
    check_cash_balance_at_disbursement = fields.Boolean(
        string='Vérifier le solde de caisse au décaissement', default=False,
        help="Si activé, bloque tout décaissement qui ferait passer le solde comptable du "
             "journal de décaissement (uniquement pour un journal de type 'Espèces') sous "
             "zéro. Désactivé par défaut : tant qu'aucune écriture d'ouverture de caisse n'a "
             "été comptabilisée pour ce journal, le solde comptable réel ne reflète pas la "
             "caisse physique et ce contrôle bloquerait tout décaissement à tort. À activer "
             "une fois l'approvisionnement initial du journal effectué dans Odoo — même "
             "principe que verification_disponibilite='never' par défaut sur les fonds "
             "bailleurs (microfinance.fond.credit).",
    )

    # --- Comptabilité : Principal ---
    account_principal_individuel_id = fields.Many2one(
        'account.account', string='Principal en cours - Individuel', required=True,
        domain="[('account_type', 'in', ('asset_receivable', 'asset_current')), ('company_id', '=', company_id)]",
        default=_pcec_default('203001'),
    )
    account_principal_groupe_id = fields.Many2one(
        'account.account', string='Principal en cours - Groupe', required=True,
        domain="[('account_type', 'in', ('asset_receivable', 'asset_current')), ('company_id', '=', company_id)]",
        default=_pcec_default('203002'),
    )

    # --- Comptabilité : Provisions ---
    account_provision_individuel_id = fields.Many2one(
        'account.account', string='Provision mauvaises créances - Individuel',
        domain="[('account_type', 'in', ('liability_current', 'asset_current')), ('company_id', '=', company_id)]",
        default=_pcec_default('293001'),
        help="Compte de contrepartie bilan de la provision. Peut rester vide si la provision n'est pas utilisée par CEFOR pour ce produit.",
    )
    account_provision_groupe_id = fields.Many2one(
        'account.account', string='Provision mauvaises créances - Groupe',
        domain="[('account_type', 'in', ('liability_current', 'asset_current')), ('company_id', '=', company_id)]",
        default=_pcec_default('293002'),
        help="Compte de contrepartie bilan de la provision. Peut rester vide si la provision n'est pas utilisée par CEFOR pour ce produit.",
    )
    account_provision_cout_individuel_id = fields.Many2one(
        'account.account', string='Provision coûts des mauvaises créances - Individuel',
        domain="[('account_type', '=', 'expense'), ('company_id', '=', company_id)]",
        default=_pcec_default('682201'),
        help="Compte de charge de la provision. Peut rester vide si la provision n'est pas utilisée par CEFOR pour ce produit.",
    )
    account_provision_cout_groupe_id = fields.Many2one(
        'account.account', string='Provision coûts des mauvaises créances - Groupe',
        domain="[('account_type', '=', 'expense'), ('company_id', '=', company_id)]",
        default=_pcec_default('682202'),
        help="Compte de charge de la provision. Peut rester vide si la provision n'est pas utilisée par CEFOR pour ce produit.",
    )

    # --- Comptabilité : Intérêts ---
    account_interets_recus_individuel_id = fields.Many2one(
        'account.account', string='Intérêts reçus sur crédits - Individuel', required=True,
        domain="[('account_type', '=', 'income'), ('company_id', '=', company_id)]",
        default=_pcec_default('707301'),
    )
    account_interets_recus_groupe_id = fields.Many2one(
        'account.account', string='Intérêts reçus sur crédits - Groupe', required=True,
        domain="[('account_type', '=', 'income'), ('company_id', '=', company_id)]",
        default=_pcec_default('707302'),
    )
    account_interets_echus_individuel_id = fields.Many2one(
        'account.account', string='Intérêts échus - Individuel',
        domain="[('account_type', 'in', ('asset_current', 'income')), ('company_id', '=', company_id)]",
        default=_pcec_default('208001'),
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR pour ce produit.",
    )
    account_interets_echus_groupe_id = fields.Many2one(
        'account.account', string='Intérêts échus - Groupe',
        domain="[('account_type', 'in', ('asset_current', 'income')), ('company_id', '=', company_id)]",
        default=_pcec_default('208002'),
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR pour ce produit.",
    )
    account_interets_echus_recevoir_individuel_id = fields.Many2one(
        'account.account', string='Intérêts échus à recevoir - Individuel',
        domain="[('account_type', 'in', ('asset_receivable', 'asset_current')), ('company_id', '=', company_id)]",
        default=_pcec_default('208003'),
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR pour ce produit.",
    )
    account_interets_echus_recevoir_groupe_id = fields.Many2one(
        'account.account', string='Intérêts échus à recevoir - Groupe',
        domain="[('account_type', 'in', ('asset_receivable', 'asset_current')), ('company_id', '=', company_id)]",
        default=_pcec_default('208004'),
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR pour ce produit.",
    )
    account_arrieres_declassifies_individuel_id = fields.Many2one(
        'account.account', string='Crédits en arriérés déclassifiés - Individuel',
        domain="[('account_type', '=', 'asset_current'), ('company_id', '=', company_id)]",
        default=_pcec_default('273001'),
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR pour ce produit.",
    )
    account_arrieres_declassifies_groupe_id = fields.Many2one(
        'account.account', string='Crédits en arriérés déclassifiés - Groupe',
        domain="[('account_type', '=', 'asset_current'), ('company_id', '=', company_id)]",
        default=_pcec_default('273002'),
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR pour ce produit.",
    )

    # --- Comptabilité : Pénalités et commissions (ventilées) ---
    account_penalites_avance_individuel_id = fields.Many2one(
        'account.account', string="Pénalités comptabilisées d'avance - Individuel",
        domain="[('account_type', '=', 'liability_current'), ('company_id', '=', company_id)]",
        default=_pcec_default('325001'),
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR pour ce produit.",
    )
    account_penalites_avance_groupe_id = fields.Many2one(
        'account.account', string="Pénalités comptabilisées d'avance - Groupe",
        domain="[('account_type', '=', 'liability_current'), ('company_id', '=', company_id)]",
        default=_pcec_default('325002'),
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR pour ce produit.",
    )
    account_revenu_penalites_avance_individuel_id = fields.Many2one(
        'account.account', string="Revenu des pénalités comptabilisées d'avance - Individuel",
        domain="[('account_type', '=', 'income'), ('company_id', '=', company_id)]",
        default=_pcec_default('326101'),
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR pour ce produit.",
    )
    account_revenu_penalites_avance_groupe_id = fields.Many2one(
        'account.account', string="Revenu des pénalités comptabilisées d'avance - Groupe",
        domain="[('account_type', '=', 'income'), ('company_id', '=', company_id)]",
        default=_pcec_default('326102'),
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR pour ce produit.",
    )
    account_commissions_echues_individuel_id = fields.Many2one(
        'account.account', string='Commissions échues accumulées - Individuel',
        domain="[('account_type', '=', 'liability_current'), ('company_id', '=', company_id)]",
        default=_pcec_default('325003'),
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR pour ce produit.",
    )
    account_commissions_echues_groupe_id = fields.Many2one(
        'account.account', string='Commissions échues accumulées - Groupe',
        domain="[('account_type', '=', 'liability_current'), ('company_id', '=', company_id)]",
        default=_pcec_default('325004'),
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR pour ce produit.",
    )
    account_commissions_accumulees_individuel_id = fields.Many2one(
        'account.account', string='Commissions accumulées gagnées - Individuel',
        domain="[('account_type', '=', 'income'), ('company_id', '=', company_id)]",
        default=_pcec_default('717001'),
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR pour ce produit.",
    )
    account_commissions_accumulees_groupe_id = fields.Many2one(
        'account.account', string='Commissions accumulées gagnées - Groupe',
        domain="[('account_type', '=', 'income'), ('company_id', '=', company_id)]",
        default=_pcec_default('717002'),
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR pour ce produit.",
    )

    # --- Comptabilité : Crédits en perte ---
    account_credits_perte_individuel_id = fields.Many2one(
        'account.account', string='Crédits passés en perte - Individuel',
        domain="[('account_type', '=', 'expense'), ('company_id', '=', company_id)]",
        default=_pcec_default('641201'),
        help="Requis uniquement au moment de la radiation d'un crédit individuel de ce produit.",
    )
    account_credits_perte_groupe_id = fields.Many2one(
        'account.account', string='Crédits passés en perte - Groupe',
        domain="[('account_type', '=', 'expense'), ('company_id', '=', company_id)]",
        default=_pcec_default('641202'),
        help="Requis uniquement au moment de la radiation d'un crédit de groupe de ce produit.",
    )

    # --- Comptabilité : Comptes partagés (tous types de client confondus) ---
    account_recouvrement_id = fields.Many2one(
        'account.account', string='Recouvrement des créances',
        domain="[('account_type', '=', 'income'), ('company_id', '=', company_id)]",
        default=_pcec_default('741000'),
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR.",
    )
    account_commission_credit_id = fields.Many2one(
        'account.account', string='Commission sur crédit',
        domain="[('account_type', '=', 'income'), ('company_id', '=', company_id)]",
        default=_pcec_default('717003'),
        help="Compte de comptabilisation des frais de dossier. Requis uniquement si des frais sont encaissés pour ce produit.",
    )
    account_papeterie_id = fields.Many2one(
        'account.account', string='Papeterie',
        domain="[('account_type', '=', 'income'), ('company_id', '=', company_id)]",
        default=_pcec_default('749001'),
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR.",
    )
    account_penalites_id = fields.Many2one(
        'account.account', string='Pénalités crédits',
        domain="[('account_type', '=', 'income'), ('company_id', '=', company_id)]",
        default=_pcec_default('749002'),
        help="Requis uniquement si des pénalités sont perçues sur les remboursements de ce produit.",
    )
    account_surpaiement_id = fields.Many2one(
        'account.account', string='Surpaiement',
        domain="[('account_type', '=', 'liability_current'), ('company_id', '=', company_id)]",
        default=_pcec_default('315000'),
        help="Peut rester vide si ce mécanisme n'est pas utilisé par CEFOR.",
    )

    fee_type = fields.Selection([
        ('fixed', 'Montant fixe'),
        ('percentage', 'Pourcentage du montant du crédit'),
    ], string='Type de frais', default='fixed', required=True)
    fee_amount = fields.Monetary(string='Frais fixes', default=0.0)
    fee_rate = fields.Float(string='Taux de frais (%)', default=0.0)
    fee_journal_id = fields.Many2one(
        'account.journal', string='Journal encaissement frais',
        domain="[('type', 'in', ('bank','cash')), ('company_id', '=', company_id)]",
        default=_journal_default('CRE'),
        help='Journal utilisé pour encaisser les frais de dossier, distinct des journaux de '
             'décaissement/remboursement si l\'institution le souhaite (peut être identique à l\'un des deux).',
    )
    fee_charged_before_disbursement = fields.Boolean(
        string='Frais exigés avant décaissement', default=True,
        help='Si activé, le décaissement est bloqué tant que les frais de dossier dus n\'ont pas été encaissés.',
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
                prefix = company.loan_product_code_prefix or 'CR'
                number = self.env['ir.sequence'].next_by_code('microfinance.loan.product') or '00000'
                vals['code'] = '%s%s' % (prefix, number)
        return super().create(vals_list)

    @api.constrains('min_amount', 'max_amount', 'min_term', 'max_term', 'interest_rate', 'grace_period_days',
                     'min_membership_days', 'min_guarantee_ratio', 'fee_amount', 'fee_rate')
    def _check_values(self):
        for product in self:
            if product.min_amount < 0 or product.max_amount <= 0 or product.max_amount < product.min_amount:
                raise ValidationError(_('Vérifiez les montants minimum et maximum.'))
            if product.min_term <= 0 or product.max_term < product.min_term:
                raise ValidationError(_('Vérifiez les durées minimum et maximum.'))
            if product.interest_rate < 0:
                raise ValidationError(_('Le taux intérêt ne peut pas être négatif.'))
            if product.grace_period_days < 0:
                raise ValidationError(_('Le délai de grâce ne peut pas être négatif.'))
            if product.min_membership_days < 0:
                raise ValidationError(_('L\'ancienneté minimum ne peut pas être négative.'))
            if product.min_guarantee_ratio < 0:
                raise ValidationError(_('Le ratio minimum de garantie ne peut pas être négatif.'))
            if product.fee_amount < 0 or product.fee_rate < 0:
                raise ValidationError(_('Les frais de dossier ne peuvent pas être négatifs.'))

    @api.constrains('repayment_frequency_mode', 'repayment_frequency_id', 'allowed_repayment_frequency_ids')
    def _check_repayment_frequency_mode(self):
        for product in self:
            if product.repayment_frequency_mode == 'fixed' and not product.repayment_frequency_id:
                raise ValidationError(_('Choisissez la périodicité de remboursement imposée par ce produit.'))
            if product.repayment_frequency_mode == 'client_choice' and not product.allowed_repayment_frequency_ids:
                raise ValidationError(_('Autorisez au moins une périodicité pour un produit à choix du client.'))

    def _get_account(self, kind, partner):
        """Retourne le compte account_<kind>_individuel_id ou account_<kind>_groupe_id
        selon le type de client. Un crédit ne distingue que deux variantes comptables :
        "individuel" (particulier ou société, un seul emprunteur) et "groupe" (crédit de
        groupe à caution solidaire, sans variante "entreprise" dédiée côté crédit).
        """
        self.ensure_one()
        variant = 'groupe' if partner.microfinance_client_type == 'group' else 'individuel'
        return self['account_%s_%s_id' % (kind, variant)]
