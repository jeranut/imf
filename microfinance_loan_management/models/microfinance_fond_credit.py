# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class MicrofinanceFondCredit(models.Model):
    _name = 'microfinance.fond.credit'
    _description = 'Fonds de crédit rotatif bailleur'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(string='Nom du fonds', required=True, tracking=True)
    bailleur_id = fields.Many2one(
        'microfinance.bailleur.fonds', string='Bailleur de fonds', required=True, tracking=True,
        ondelete='restrict',
    )
    code = fields.Char(
        string='Code', default='Nouveau', copy=False, readonly=True, tracking=True,
        help="Généré automatiquement à la création via la séquence 'microfinance.fond.credit', "
             "jamais saisi manuellement.",
    )
    scope = fields.Selection([
        ('single_company', 'Agence unique'),
        ('multi_company', 'Multi-agences (partagé)'),
    ], string='Portée du fonds', required=True, default='single_company', tracking=True,
        help="Choix figé après la première sauvegarde : « Agence unique » rattache le fonds à "
             "une société précise (company_id requis) ; « Multi-agences » laisse company_id vide "
             "et rend le fonds visible/exploitable depuis toutes les agences (solde et historique "
             "consolidés, alimentés par des contributions/crédits de plusieurs agences).")
    company_id = fields.Many2one(
        'res.company', string='Société', default=lambda self: self.env.company, tracking=True,
        help="Requis et figé sur la société courante si le fonds est « Agence unique » ; forcé "
             "vide si « Multi-agences ». Figé après la première sauvegarde, comme la portée.",
    )
    date_debut = fields.Date(string='Date de début', required=True, default=fields.Date.context_today)
    date_cloture = fields.Date(string='Date de clôture')
    passer_gl = fields.Boolean(
        string='Passer au grand livre', default=True,
        help="Si désactivé, les contributions sur ce fonds ne génèrent aucune écriture comptable "
             "(cas mutualiste) : seul l'historique du mouvement est conservé.",
    )
    account_id = fields.Many2one(
        'account.account', string='Compte comptable bailleur',
        domain="[('account_type', 'in', ('liability_current', 'liability_non_current', 'equity'))]",
        help="Compte de contrepartie GL du fonds (dette envers le bailleur ou fonds propres "
             "assimilés selon le montage retenu). Requis si « Passer au grand livre » est actif. "
             "Domaine basé sur account_type (et non un préfixe de code) : le PCEC Madagascar 2005 "
             "ne suit pas la convention classe 2 = Dettes / classe 3 = Fonds propres (classe 2 = "
             "opérations clientèle mixtes actif/passif, classe 3 = comptes divers mixtes ; les "
             "vrais fonds propres sont en classe 5).",
    )
    verification_disponibilite = fields.Selection([
        ('never', 'Jamais'),
        ('at_request', 'À la demande de crédit'),
        ('at_disbursement', 'Au décaissement'),
    ], string='Vérifier la disponibilité des fonds', required=True, default='at_disbursement',
        help="« À la demande de crédit » n'a aucun effet observable tant que "
             "microfinance.loan.application reste hors-périmètre (absent de models/__init__.py, "
             "non câblé au module) : seule la valeur « Au décaissement » (action_disburse sur "
             "microfinance.loan) déclenche réellement un contrôle pour l'instant.")
    currency_id = fields.Many2one(
        'res.currency', string='Devise', default=lambda self: self.env.company.currency_id,
    )
    contribution_ids = fields.One2many('microfinance.fond.contribution', 'fond_id', string='Contributions')
    loan_ids = fields.One2many('microfinance.loan', 'fond_credit_id', string='Crédits rattachés')
    total_contributions = fields.Monetary(
        string='Total contributions (net)', compute='_compute_fond_totals', store=True,
        help="Somme des contributions validées (dépôts - retraits), pour le rapport « Utilisation "
             "des fonds ».",
    )
    total_decaisse = fields.Monetary(
        string='Total décaissé', compute='_compute_fond_totals', store=True,
        help="Somme des montants (loan_amount) des crédits rattachés à ce fonds ayant dépassé "
             "l'étape de décaissement (état 'active', 'closed', 'defaulted' ou 'written_off').",
    )
    total_rembourse = fields.Monetary(
        string='Total remboursé', compute='_compute_fond_totals', store=True,
        help="Somme des montants payés (principal + intérêts + pénalités) sur les échéances des "
             "crédits décaissés rattachés à ce fonds.",
    )
    solde_disponible = fields.Monetary(
        string='Solde disponible', compute='_compute_fond_totals', store=True,
        help="total_contributions diminué de l'encours actif (principal restant dû uniquement, "
             "intérêts et pénalités exclus) des crédits en statut 'approved'/'active' rattachés à "
             "ce fonds. Agrégation volontairement en sudo (bypass des ir.rule société sur "
             "microfinance.loan) : pour un fonds « Multi-agences », le solde et les totaux "
             "ci-dessus doivent rester identiques quelle que soit l'agence depuis laquelle on les "
             "consulte, y compris pour un utilisateur qui n'a pas accès à toutes les sociétés "
             "ayant contribué au fonds ou décaissé dessus.",
    )
    active = fields.Boolean(string='Actif', default=True)

    _sql_constraints = [
        ('code_unique', 'unique(code)', 'Le code du fonds de crédit doit être unique (séquence globale multi-société).'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('code', 'Nouveau') in (False, '', 'Nouveau'):
                vals['code'] = self.env['ir.sequence'].next_by_code('microfinance.fond.credit') or 'Nouveau'
        return super().create(vals_list)

    def write(self, vals):
        if self.ids and ('scope' in vals or 'company_id' in vals):
            for fond in self:
                if 'scope' in vals and vals['scope'] != fond.scope:
                    raise UserError(_(
                        'La portée (scope) du fonds "%s" ne peut plus être modifiée après sa création.'
                    ) % fond.name)
                if 'company_id' in vals and vals['company_id'] != fond.company_id.id:
                    raise UserError(_(
                        'La société du fonds "%s" ne peut plus être modifiée après sa création.'
                    ) % fond.name)
        return super().write(vals)

    @api.onchange('scope')
    def _onchange_scope(self):
        if self.scope == 'single_company':
            self.company_id = self.env.company
        else:
            self.company_id = False

    @api.onchange('scope', 'company_id')
    def _onchange_scope_account_domain(self):
        # Domaine dynamique non exprimable en attribut statique du champ : filtre account_type
        # toujours, filtre company_id en plus uniquement pour un fonds "Agence unique" (un fonds
        # "Multi-agences" n'a pas de société propre, donc pas de filtre société pertinent).
        account_type_domain = [('account_type', 'in', ('liability_current', 'liability_non_current', 'equity'))]
        if self.scope == 'single_company' and self.company_id:
            domain = account_type_domain + [('company_id', '=', self.company_id.id)]
        else:
            domain = account_type_domain
        return {'domain': {'account_id': domain}}

    @api.constrains('scope', 'company_id')
    def _check_scope_company(self):
        for fond in self:
            if fond.scope == 'single_company' and not fond.company_id:
                raise ValidationError(_(
                    'Un fonds à portée "Agence unique" doit être rattaché à une société.'
                ))
            if fond.scope == 'multi_company' and fond.company_id:
                raise ValidationError(_(
                    'Un fonds à portée "Multi-agences" ne doit pas être rattaché à une société spécifique.'
                ))

    @api.constrains('date_debut', 'date_cloture')
    def _check_dates(self):
        for fond in self:
            if fond.date_cloture and fond.date_cloture < fond.date_debut:
                raise ValidationError(_(
                    'La date de clôture doit être postérieure ou égale à la date de début.'
                ))

    @api.constrains('passer_gl', 'account_id')
    def _check_account_required(self):
        for fond in self:
            if fond.passer_gl and not fond.account_id:
                raise ValidationError(_(
                    'Le compte comptable bailleur est requis lorsque "Passer au grand livre" est actif.'
                ))

    @api.constrains('account_id')
    def _check_account_type(self):
        # Défense en profondeur : le domaine du champ account_id (UI) exclut déjà ces comptes,
        # mais un create()/write() direct (import, API) doit être bloqué aussi, pas seulement
        # masqué dans le widget de sélection.
        allowed_types = ('liability_current', 'liability_non_current', 'equity')
        for fond in self:
            if fond.account_id and fond.account_id.account_type not in allowed_types:
                raise ValidationError(_(
                    'Le compte comptable bailleur doit être un compte de type dette ou fonds '
                    'propres (liability_current, liability_non_current ou equity).'
                ))

    @api.depends('contribution_ids.amount', 'contribution_ids.type_mouvement', 'contribution_ids.state',
                 'loan_ids.state', 'loan_ids.loan_amount',
                 'loan_ids.installment_ids.principal_amount', 'loan_ids.installment_ids.paid_principal',
                 'loan_ids.installment_ids.paid_interest', 'loan_ids.installment_ids.paid_penalty')
    def _compute_fond_totals(self):
        # sudo() sur loan_ids : un fonds "multi_company" doit exposer les mêmes totaux/solde
        # consolidés quelle que soit l'agence consultante, y compris pour un utilisateur qui n'a
        # pas accès à toutes les sociétés ayant décaissé sur ce fonds (cf. ir.rule stricte sur
        # microfinance.loan, qui ne connaît pas la clause de partage optionnel des fonds).
        disbursed_states = ('active', 'closed', 'defaulted', 'written_off')
        outstanding_states = ('approved', 'active')
        for fond in self:
            contributions = fond.contribution_ids.filtered(lambda c: c.state == 'posted')
            deposits = sum(contributions.filtered(lambda c: c.type_mouvement == 'depot').mapped('amount'))
            withdrawals = sum(contributions.filtered(lambda c: c.type_mouvement == 'retrait').mapped('amount'))
            fond.total_contributions = deposits - withdrawals

            loans = fond.sudo().loan_ids
            disbursed_loans = loans.filtered(lambda l: l.state in disbursed_states)
            fond.total_decaisse = sum(disbursed_loans.mapped('loan_amount'))
            fond.total_rembourse = sum(
                sum(loan.installment_ids.mapped('paid_principal'))
                + sum(loan.installment_ids.mapped('paid_interest'))
                + sum(loan.installment_ids.mapped('paid_penalty'))
                for loan in disbursed_loans
            )

            outstanding_loans = loans.filtered(lambda l: l.state in outstanding_states)
            # Boucle Python explicite plutôt que .mapped(lambda ...) : sur un recordset vide,
            # mapped() avec un callable appelle func(self) une seule fois sur le recordset vide
            # lui-même (au lieu de renvoyer une liste vide), ce qui casse ensure_one() dans
            # _get_principal_outstanding(). L'itération Python directe n'a pas ce piège.
            principal_outstanding = sum(loan._get_principal_outstanding() for loan in outstanding_loans)
            fond.solde_disponible = fond.total_contributions - principal_outstanding

    def action_view_contributions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Contributions'),
            'res_model': 'microfinance.fond.contribution',
            'view_mode': 'tree,form',
            'domain': [('fond_id', '=', self.id)],
            'context': {'default_fond_id': self.id},
        }

    def action_view_loans(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Crédits rattachés'),
            'res_model': 'microfinance.loan',
            'view_mode': 'tree,form',
            'domain': [('fond_credit_id', '=', self.id)],
        }
