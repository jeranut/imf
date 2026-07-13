# -*- coding: utf-8 -*-
from collections import defaultdict

from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class MicrofinanceLoan(models.Model):
    _name = 'microfinance.loan'
    _description = 'Crédit microfinance'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Référence', default='Nouveau', copy=False, readonly=True, tracking=True)
    partner_id = fields.Many2one('res.partner', string='Emprunteur', required=True, tracking=True)
    product_id = fields.Many2one('microfinance.loan.product', string='Produit', required=True, tracking=True)
    company_id = fields.Many2one('res.company', string='Société', default=lambda self: self.env.company, required=True, tracking=True)
    currency_id = fields.Many2one('res.currency', string='Devise', default=lambda self: self.env.company.currency_id, required=True)
    loan_amount = fields.Monetary(string='Montant crédit', required=True, tracking=True)
    term = fields.Integer(string='Nombre échéances', required=True, default=1, tracking=True)
    application_date = fields.Date(string='Date de demande', default=fields.Date.context_today, required=True)
    approval_date = fields.Date(string="Date d'approbation", readonly=True)
    disbursement_date = fields.Date(string='Date de décaissement', readonly=True)
    interest_rate = fields.Float(string='Taux intérêt annuel (%)', related='product_id.interest_rate', readonly=False, store=True)
    interest_method = fields.Selection(related='product_id.interest_method', readonly=False, store=True)
    repayment_frequency_mode = fields.Selection(
        related='product_id.repayment_frequency_mode', string='Mode périodicité (produit)', readonly=True,
    )
    allowed_repayment_frequency_ids = fields.Many2many(
        related='product_id.allowed_repayment_frequency_ids', string='Périodicités autorisées (produit)',
    )
    repayment_frequency_id = fields.Many2one(
        'microfinance.repayment.frequency', string='Périodicité de remboursement',
        compute='_compute_repayment_frequency_id', store=True, readonly=False,
        domain="[('id', 'in', allowed_repayment_frequency_ids)] if repayment_frequency_mode == 'client_choice' else []",
        help='Reprise automatiquement du produit si celui-ci impose une périodicité unique. '
             "Si le produit laisse le choix au client/agent, à sélectionner obligatoirement parmi "
             "les périodicités autorisées par le produit avant de générer l'échéancier.",
    )
    state = fields.Selection([
        ('draft', 'Brouillon'),
        ('submitted', 'Soumis'),
        ('manager_validated', 'Validé manager'),
        ('finance_validated', 'Validé finance'),
        ('approved', 'Approuvé'),
        ('active', 'Actif'),
        ('closed', 'Clôturé'),
        ('defaulted', 'Défaut'),
        ('written_off', 'Radié'),
        ('cancelled', 'Annulé'),
    ], string='État', default='draft', tracking=True, index=True)
    officer_id = fields.Many2one('res.users', string='Agent crédit', default=lambda self: self.env.user, tracking=True)
    manager_id = fields.Many2one('res.users', string='Manager', tracking=True)
    finance_user_id = fields.Many2one('res.users', string='Utilisateur finance', tracking=True)
    collection_agent_id = fields.Many2one('res.users', string='Agent recouvrement', tracking=True)
    installment_ids = fields.One2many('microfinance.loan.installment', 'loan_id', string='Échéancier')
    payment_ids = fields.One2many('microfinance.loan.payment', 'loan_id', string='Remboursements')
    visit_ids = fields.One2many('microfinance.collection.visit', 'loan_id', string='Visites')
    move_ids = fields.One2many('account.move', 'microfinance_loan_id', string='Écritures comptables')
    principal_total = fields.Monetary(string='Total capital', compute='_compute_totals', store=True)
    interest_total = fields.Monetary(string='Total intérêts', compute='_compute_totals', store=True)
    penalty_total = fields.Monetary(string='Total pénalités', compute='_compute_totals', store=True)
    paid_total = fields.Monetary(string='Total payé', compute='_compute_totals', store=True)
    balance_total = fields.Monetary(string='Solde restant', compute='_compute_totals', store=True)
    overdue_amount = fields.Monetary(string='Montant en retard', compute='_compute_totals', store=True)
    overdue_installment_count = fields.Integer(string="Nombre d'échéances en retard", compute='_compute_totals', store=True)
    provision_amount = fields.Monetary(compute='_compute_provision', store=True, string='Provision requise')
    provision_posted_amount = fields.Monetary(copy=False, readonly=True, default=0.0, string='Provision comptabilisée')
    scoring_profile_id = fields.Many2one(
        'microfinance.scoring.profile',
        string='Profil de scoring',
        domain="['|', ('product_id', '=', False), ('product_id', '=', product_id)]",
        copy=False,
        tracking=True,
    )
    internal_score = fields.Float(
        string='Score', copy=False, readonly=True, tracking=True,
        help='Score de scoring unique du crédit (plus haut = plus sûr), calculé par le moteur de '
             'scoring configurable (microfinance.scoring.profile/rule). Remplace l\'ancien score de '
             'risque codé en dur.',
    )
    risk_level = fields.Selection([
        ('low', 'Faible'),
        ('medium', 'Moyen'),
        ('high', 'Élevé'),
        ('critical', 'Critique'),
    ], string='Niveau de risque', copy=False, readonly=True, tracking=True)
    scoring_decision = fields.Selection([
        ('recommended', 'Recommandé'),
        ('manual_review', 'Revue manuelle'),
        ('reject_recommended', 'Risqué / Rejet recommandé'),
    ], string='Décision scoring', copy=False, readonly=True, tracking=True)
    scoring_line_ids = fields.One2many('microfinance.scoring.line', 'loan_id', string='Règles appliquées', copy=False, readonly=True)
    scoring_line_count = fields.Integer(string='Nombre de règles de scoring', compute='_compute_counts')
    note = fields.Text(string='Note')
    installment_count = fields.Integer(string="Nombre d'échéances", compute='_compute_counts')
    payment_count = fields.Integer(string='Nombre de remboursements', compute='_compute_counts')
    visit_count = fields.Integer(string='Nombre de visites', compute='_compute_counts')
    move_count = fields.Integer(string="Nombre d'écritures", compute='_compute_counts')
    reschedule_count = fields.Integer(string='Nombre de rééchelonnements', default=0, copy=False, readonly=True, tracking=True)
    reschedule_history_ids = fields.One2many(
        'microfinance.loan.reschedule.history', 'loan_id', string='Historique de rééchelonnement', readonly=True,
    )
    co_borrower_id = fields.Many2one('res.partner', string='Co-emprunteur', tracking=True)
    guarantee_ids = fields.One2many('microfinance.loan.guarantee', 'loan_id', string='Garanties')
    guarantee_total = fields.Monetary(
        compute='_compute_guarantee_total', store=True, string='Total garanties validées',
        help='Somme des valeurs reconnues (recognized_value, après application du ratio de '
             'valorisation par type) des garanties validées, pas de la valeur brute estimée.',
    )
    fee_amount_due = fields.Monetary(compute='_compute_fee_amount', store=True, string='Frais de dossier dus')
    fee_paid = fields.Boolean(string='Frais payés', default=False, readonly=True, copy=False)
    fee_move_id = fields.Many2one('account.move', string='Écriture de frais', readonly=True, copy=False)
    net_disbursed_amount = fields.Monetary(
        compute='_compute_net_disbursed_amount', store=True, string='Montant net remis au client',
        help='Montant réellement remis en caisse au client. Égal au montant du crédit tant que les '
             "frais de dossier sont encaissés séparément (fee_charged_before_disbursement=True) ; "
             "sinon égal au montant du crédit diminué des frais de dossier dus, nettés directement "
             "dans l'écriture de décaissement. Le capital dû (loan_amount) reste toujours le montant "
             "plein : les frais ne réduisent jamais le principal remboursable.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                # agency_code est obligatoire sur res.company (NOT NULL) : toute société valide
                # en possède un, pas besoin de re-vérifier ici.
                company = self.env['res.company'].browse(vals.get('company_id') or self.env.company.id)
                number = company._get_or_create_numbering_sequence('microfinance.loan.agency')
                vals['name'] = '%s/%s' % (company.agency_code, number)
        return super().create(vals_list)

    @api.constrains('loan_amount', 'term', 'product_id')
    def _check_product_limits(self):
        for loan in self:
            product = loan.product_id
            if product and (loan.loan_amount < product.min_amount or loan.loan_amount > product.max_amount):
                raise ValidationError(_('Le montant doit respecter les limites du produit.'))
            if product and (loan.term < product.min_term or loan.term > product.max_term):
                raise ValidationError(_('La durée doit respecter les limites du produit.'))

    @api.constrains('repayment_frequency_id', 'product_id')
    def _check_repayment_frequency_allowed(self):
        for loan in self:
            product = loan.product_id
            if product.repayment_frequency_mode == 'client_choice' and loan.repayment_frequency_id:
                if loan.repayment_frequency_id not in product.allowed_repayment_frequency_ids:
                    raise ValidationError(_(
                        'La périodicité "%(freq)s" n\'est pas autorisée par le produit "%(product)s".'
                    ) % {'freq': loan.repayment_frequency_id.name, 'product': product.name})

    @api.depends('installment_ids.principal_amount', 'installment_ids.interest_amount', 'installment_ids.penalty_amount',
                 'installment_ids.paid_principal', 'installment_ids.paid_interest', 'installment_ids.paid_penalty',
                 'installment_ids.residual_amount', 'installment_ids.state')
    def _compute_totals(self):
        for loan in self:
            loan.principal_total = sum(loan.installment_ids.mapped('principal_amount'))
            loan.interest_total = sum(loan.installment_ids.mapped('interest_amount'))
            loan.penalty_total = sum(loan.installment_ids.mapped('penalty_amount'))
            loan.paid_total = sum(loan.installment_ids.mapped('paid_principal')) + sum(loan.installment_ids.mapped('paid_interest')) + sum(loan.installment_ids.mapped('paid_penalty'))
            # Before a schedule exists, fall back to the nominal loan amount; once installments
            # exist, a fully repaid loan legitimately sums to 0 and must not fall back to
            # loan_amount (a plain "or" would treat that 0 as falsy and mask it).
            loan.balance_total = sum(loan.installment_ids.mapped('residual_amount')) if loan.installment_ids else loan.loan_amount
            overdue = loan.installment_ids.filtered(lambda l: l.state == 'overdue')
            loan.overdue_amount = sum(overdue.mapped('residual_amount'))
            loan.overdue_installment_count = len(overdue)

    @api.depends('guarantee_ids.recognized_value', 'guarantee_ids.state')
    def _compute_guarantee_total(self):
        for loan in self:
            validated = loan.guarantee_ids.filtered(lambda g: g.state == 'validated')
            loan.guarantee_total = sum(validated.mapped('recognized_value'))

    @api.depends('loan_amount', 'product_id.fee_type', 'product_id.fee_amount', 'product_id.fee_rate')
    def _compute_fee_amount(self):
        for loan in self:
            product = loan.product_id
            if not product:
                loan.fee_amount_due = 0.0
            elif product.fee_type == 'fixed':
                loan.fee_amount_due = product.fee_amount
            else:
                loan.fee_amount_due = loan.loan_amount * product.fee_rate / 100.0

    @api.depends('product_id.repayment_frequency_mode', 'product_id.repayment_frequency_id')
    def _compute_repayment_frequency_id(self):
        # Uniquement pour les produits à périodicité imposée : la valeur est alors recopiée du
        # produit et rendue readonly côté vue. Pour un produit à choix du client, on ne touche
        # jamais ici à une valeur déjà choisie manuellement par l'agent.
        for loan in self:
            if loan.product_id.repayment_frequency_mode == 'fixed':
                loan.repayment_frequency_id = loan.product_id.repayment_frequency_id

    @api.depends('loan_amount', 'fee_amount_due', 'product_id.fee_charged_before_disbursement')
    def _compute_net_disbursed_amount(self):
        for loan in self:
            if loan.product_id and not loan.product_id.fee_charged_before_disbursement:
                loan.net_disbursed_amount = loan.loan_amount - loan.fee_amount_due
            else:
                loan.net_disbursed_amount = loan.loan_amount

    def _get_max_overdue_days(self):
        self.ensure_one()
        today = fields.Date.context_today(self)
        overdue = self.installment_ids.filtered(lambda l: l.state == 'overdue')
        max_days = 0
        for line in overdue:
            if line.due_date:
                max_days = max(max_days, (today - line.due_date).days)
        return max_days

    @api.model
    def get_recent_loans(self, company_id, limit=5):
        """5 derniers prêts créés, pour le panneau "Derniers prêts" du tableau de bord. L'ordre
        par défaut du modèle (id desc) est équivalent à un tri par date de création décroissante.
        Extrait en méthode de modèle pour rester testable directement, comme get_par_buckets."""
        return self.search([('company_id', '=', company_id)], limit=limit)

    @api.model
    def get_overdue_monthly_flux(self, company_id, month_keys):
        """Nombre de "nouveaux impayés" par mois (flux, pas le stock cumulé) pour le graphique
        "Évolution des impayés" du tableau de bord, à partir de l'historique persistant
        arrears_onset_date/arrears_cured_date des échéances (cf. installment._sync_arrears_state).

        Un prêt compte un nouvel impayé au mois de la première échéance dont le retard est
        constaté, sauf si le prêt a déjà un "épisode" de retard ouvert à ce moment-là (une ou
        plusieurs échéances encore non soldées, chevauchant dans le temps) — auquel cas
        l'échéance rejoint le même épisode sans être recomptée. Un nouvel épisode n'est compté
        que si l'épisode précédent du prêt est bien clos (toutes ses échéances soldées) avant la
        date de retard de la nouvelle échéance : c'est ce qui distingue un retard continu sur
        plusieurs échéances (compté une fois) d'une régularisation suivie d'une rechute (comptée
        deux fois)."""
        installments = self.env['microfinance.loan.installment'].search([
            ('company_id', '=', company_id),
            ('arrears_onset_date', '!=', False),
        ], order='loan_id, arrears_onset_date')

        by_loan = defaultdict(list)
        for inst in installments:
            by_loan[inst.loan_id.id].append(inst)

        counts = defaultdict(int)
        for insts in by_loan.values():
            has_episode = False
            episode_open = False
            episode_cure_date = None
            for inst in insts:
                onset, cured = inst.arrears_onset_date, inst.arrears_cured_date
                starts_new = not has_episode or (not episode_open and onset > episode_cure_date)
                if starts_new:
                    counts[onset.strftime('%Y-%m')] += 1
                    has_episode = True
                    episode_open = False
                    episode_cure_date = None
                if not cured:
                    # Champ Date Odoo vide => False (jamais None) : "not cured" est la bonne
                    # façon de détecter une échéance encore non soldée ici.
                    episode_open = True
                elif not episode_open:
                    episode_cure_date = max(episode_cure_date, cured) if episode_cure_date else cured

        return {key: counts.get(key, 0) for key in month_keys}

    @api.model
    def get_par_buckets(self, company_id):
        """PAR (portefeuille à risque) par tranche d'ancienneté d'arriéré, pour le
        dashboard. Portée sur les crédits actifs/en défaut de la société (les crédits
        written_off/closed en sont donc déjà exclus). Extrait en méthode de modèle
        (plutôt que gardé dans le contrôleur HTTP) pour rester testable directement."""
        tranches = [('1-30', 1, 30), ('31-60', 31, 60), ('61-90', 61, 90), ('90+', 91, None)]
        portfolio_loans = self.search([('company_id', '=', company_id), ('state', 'in', ('active', 'defaulted'))])
        outstanding_amount = sum(portfolio_loans.mapped('balance_total'))
        amounts = dict.fromkeys([label for label, _, _ in tranches], 0.0)
        for loan in portfolio_loans:
            max_days = loan._get_max_overdue_days()
            if max_days <= 0:
                continue
            for label, min_days, max_days_bound in tranches:
                if max_days >= min_days and (max_days_bound is None or max_days <= max_days_bound):
                    amounts[label] += loan.balance_total
                    break
        return {
            'labels': ['PAR %s' % label for label, _, _ in tranches],
            'values': [
                (amounts[label] / outstanding_amount * 100.0) if outstanding_amount else 0.0
                for label, _, _ in tranches
            ],
        }

    @api.depends('state', 'balance_total', 'company_id', 'installment_ids.due_date', 'installment_ids.state')
    def _compute_provision(self):
        Rule = self.env['microfinance.provision.rule']
        for loan in self:
            if loan.state not in ('active', 'defaulted'):
                loan.provision_amount = 0.0
                continue
            max_days = loan._get_max_overdue_days()
            rule = Rule.search([
                ('company_id', '=', loan.company_id.id),
                ('min_days', '<=', max_days),
                '|', ('max_days', '=', 0), ('max_days', '>=', max_days),
            ], order='min_days desc', limit=1)
            rate = rule.provision_rate if rule else 0.0
            loan.provision_amount = min(loan.balance_total * rate / 100.0, loan.balance_total)

    def _compute_counts(self):
        for loan in self:
            loan.installment_count = len(loan.installment_ids)
            loan.payment_count = len(loan.payment_ids)
            loan.visit_count = len(loan.visit_ids)
            loan.move_count = len(loan.move_ids)
            loan.scoring_line_count = len(loan.scoring_line_ids)

    def _get_scoring_profile(self):
        self.ensure_one()
        if self.scoring_profile_id and self.scoring_profile_id.active:
            return self.scoring_profile_id
        domain = [('company_id', '=', self.company_id.id), ('active', '=', True)]
        product_profile = self.env['microfinance.scoring.profile'].search(domain + [('product_id', '=', self.product_id.id)], limit=1)
        if product_profile:
            return product_profile
        return self.env['microfinance.scoring.profile'].search(domain + [('product_id', '=', False)], limit=1)

    def _get_external_scoring_metrics(self):
        self.ensure_one()
        return {}

    def _get_scoring_metrics(self):
        self.ensure_one()
        Loan = self.env['microfinance.loan']
        Payment = self.env['microfinance.loan.payment']
        today = fields.Date.context_today(self)
        loan_domain = [('company_id', '=', self.company_id.id), ('partner_id', '=', self.partner_id.id)]
        loans = Loan.search(loan_domain)
        posted_payments = Payment.search([
            ('company_id', '=', self.company_id.id),
            ('partner_id', '=', self.partner_id.id),
            ('state', '=', 'posted'),
        ])
        installments = loans.mapped('installment_ids')
        overdue_installments = installments.filtered(lambda line: line.state == 'overdue')
        overdue_days = []
        for line in overdue_installments:
            if line.due_date:
                overdue_days.append(max((today - line.due_date).days, 0))
        total_due = sum(installments.mapped('total_amount'))
        total_paid = sum(posted_payments.mapped('amount'))
        partner_create_date = self.partner_id.create_date.date() if self.partner_id.create_date else today
        customer_age_months = max((today.year - partner_create_date.year) * 12 + today.month - partner_create_date.month, 0)
        metrics = {
            'baseline': 1.0,
            'total_loans': len(loans),
            'active_loans': len(loans.filtered(lambda loan: loan.state == 'active')),
            'closed_loans': len(loans.filtered(lambda loan: loan.state == 'closed')),
            'defaulted_loans': len(loans.filtered(lambda loan: loan.state == 'defaulted')),
            'overdue_installments': len(overdue_installments),
            'max_days_overdue': max(overdue_days) if overdue_days else 0.0,
            'average_days_overdue': sum(overdue_days) / len(overdue_days) if overdue_days else 0.0,
            'repayment_rate': total_due and (total_paid / total_due * 100.0) or 0.0,
            'total_borrowed_amount': sum(loans.mapped('loan_amount')),
            'total_paid_amount': total_paid,
            'partial_payment_count': len(installments.filtered(lambda line: line.state == 'partial')),
            'customer_age_months': customer_age_months,
            # Metrics scoped to this loan only (as opposed to the metrics above, aggregated over
            # every loan of the partner) — these reproduce the weights that used to be hardcoded
            # in the retired _compute_risk_score().
            'loan_overdue_installment_count': self.overdue_installment_count,
            'loan_max_days_overdue': self._get_max_overdue_days(),
            'loan_overdue_amount_ratio': self.loan_amount and (self.overdue_amount / self.loan_amount * 100.0) or 0.0,
            'loan_partial_payment_count': len(self.installment_ids.filtered(lambda line: line.state == 'partial')),
        }
        metrics.update(self._get_external_scoring_metrics())
        return metrics

    def _get_scoring_decision(self, profile, score):
        self.ensure_one()
        if score >= profile.approve_threshold:
            return 'recommended'
        if score >= profile.manual_review_threshold:
            return 'manual_review'
        return 'reject_recommended'

    def _get_scoring_risk_level(self, profile, score):
        self.ensure_one()
        span = max(profile.max_score - profile.min_score, 1.0)
        ratio = (score - profile.min_score) / span
        if ratio >= 0.75:
            return 'low'
        if ratio >= 0.5:
            return 'medium'
        if score >= profile.reject_threshold:
            return 'high'
        return 'critical'

    def action_calculate_scoring(self, silent=False):
        for loan in self:
            if loan.state == 'written_off':
                # Written-off loans are no longer part of the active risk/PAR calculations.
                loan.write({
                    'internal_score': 0.0,
                    'risk_level': 'critical',
                    'scoring_decision': 'reject_recommended',
                    'scoring_line_ids': [(5, 0, 0)],
                })
                continue
            profile = loan._get_scoring_profile()
            if not profile:
                if silent:
                    continue
                raise UserError(_('Configurez un profil de scoring crédit pour cette société ou ce produit.'))
            metrics = loan._get_scoring_metrics()
            score = 0.0
            line_values = []
            for rule in profile.rule_ids.filtered(lambda item: item.active).sorted(lambda item: (item.sequence, item.id)):
                metric_value = metrics.get(rule.metric, 0.0)
                if rule._matches(metric_value):
                    points = rule._get_points(metric_value)
                    score += points
                    line_values.append((0, 0, {
                        'rule_id': rule.id,
                        'metric_value': metric_value,
                        'points_applied': points,
                        'note': rule.description or rule.name,
                    }))
            score = min(max(score, profile.min_score), profile.max_score)
            loan.write({
                'scoring_profile_id': profile.id,
                'internal_score': score,
                'risk_level': loan._get_scoring_risk_level(profile, score),
                'scoring_decision': loan._get_scoring_decision(profile, score),
                'scoring_line_ids': [(5, 0, 0)] + line_values,
            })
        return True

    def _check_eligibility(self):
        for loan in self:
            product = loan.product_id
            today = fields.Date.context_today(loan)
            member_since = loan.partner_id.create_date.date() if loan.partner_id.create_date else today
            membership_days = (today - member_since).days
            if product.min_membership_days and membership_days < product.min_membership_days:
                missing_days = product.min_membership_days - membership_days
                raise UserError(_(
                    'Ancienneté client insuffisante pour ce produit : il manque %(missing)s jour(s) '
                    '(ancienneté requise : %(required)s jours, ancienneté actuelle : %(current)s jours).'
                ) % {'missing': missing_days, 'required': product.min_membership_days, 'current': membership_days})

            other_active_loans = self.search([
                ('company_id', '=', loan.company_id.id),
                ('partner_id', '=', loan.partner_id.id),
                ('id', '!=', loan.id),
                ('state', '=', 'active'),
            ])
            if other_active_loans:
                if not product.allow_second_loan:
                    raise UserError(_('Ce client a déjà un crédit actif. Ce produit n\'autorise pas de second crédit en parallèle.'))
                if product.block_second_if_arrears and any(other.overdue_installment_count > 0 for other in other_active_loans):
                    raise UserError(_('Ce client a déjà un crédit actif en arriérés. Un second crédit ne peut pas être soumis.'))

            if loan.co_borrower_id:
                co_borrower_active_loans = self.search([
                    ('company_id', '=', loan.company_id.id),
                    ('partner_id', '=', loan.co_borrower_id.id),
                    ('id', '!=', loan.id),
                    ('state', '=', 'active'),
                ])
                if co_borrower_active_loans:
                    raise UserError(_('Le co-emprunteur a déjà un crédit actif en cours.'))

            if product.guarantee_required and not loan.guarantee_ids.filtered(lambda g: g.state == 'validated'):
                raise UserError(_('Ce produit exige une garantie validée avant soumission.'))
            if product.min_guarantee_ratio > 0:
                required_guarantee = loan.loan_amount * product.min_guarantee_ratio / 100.0
                if loan.guarantee_total < required_guarantee:
                    missing = required_guarantee - loan.guarantee_total
                    raise UserError(_(
                        'Garanties insuffisantes : il manque %(missing).2f pour atteindre le ratio minimum requis '
                        '(%(ratio)s%% du montant du crédit, soit %(required).2f).'
                    ) % {'missing': missing, 'ratio': product.min_guarantee_ratio, 'required': required_guarantee})

    def action_submit(self):
        self._check_eligibility()
        self.action_calculate_scoring(silent=True)
        self.write({'state': 'submitted'})

    def action_manager_validate(self):
        self.write({'state': 'manager_validated', 'manager_id': self.env.user.id})

    def action_finance_validate(self):
        self.write({'state': 'finance_validated', 'finance_user_id': self.env.user.id})

    def action_approve(self):
        self.write({'state': 'approved', 'approval_date': fields.Date.context_today(self)})

    def action_mark_default(self):
        self.write({'state': 'defaulted'})

    def action_close(self):
        for loan in self:
            if loan.balance_total > 0.01:
                raise UserError(_('Impossible de clôturer : solde restant à payer.'))
            loan.state = 'closed'
            guarantees_to_release = loan.guarantee_ids.filtered(lambda g: g.state != 'released')
            if guarantees_to_release:
                guarantees_to_release.write({'state': 'released'})
                loan.message_post(body=_('Garanties libérées suite à la clôture du crédit : %s') % (
                    ', '.join(guarantees_to_release.mapped('description'))
                ))

    def action_recompute_risk(self):
        self.action_calculate_scoring(silent=True)
        return True

    def _period_delta(self):
        """Each repayment frequency is either an exact number of calendar months (clean fraction
        of a year: the annual rate is prorated as months/12) or, when it doesn't evenly divide
        into months (daily/weekly/biweekly/four_weekly), a fixed number of days prorated as
        days/365 — the same day-based method already used for the grace-period interest bucket."""
        self.ensure_one()
        freq = self.repayment_frequency_id
        if not freq:
            raise UserError(_('Choisissez une périodicité de remboursement avant de générer l\'échéancier.'))
        return relativedelta(months=freq.period_value) if freq.period_kind == 'months' else relativedelta(days=freq.period_value)

    def _period_interest_factor(self):
        """Fraction of the annual interest rate to apply for one repayment period."""
        self.ensure_one()
        freq = self.repayment_frequency_id
        if not freq:
            raise UserError(_('Choisissez une périodicité de remboursement avant de générer l\'échéancier.'))
        return freq.period_value / 12.0 if freq.period_kind == 'months' else freq.period_value / 365.0

    def action_generate_schedule(self):
        for loan in self:
            if loan.state not in ('draft', 'submitted', 'manager_validated', 'finance_validated', 'approved'):
                raise UserError(_('Échéancier autorisé avant activation seulement.'))
            if not loan.repayment_frequency_id:
                raise UserError(_(
                    'Ce produit laisse le choix de la périodicité de remboursement : '
                    "choisissez-en une avant de générer l'échéancier."
                ))
            loan.installment_ids.unlink()
            principal = loan.loan_amount / loan.term
            remaining = loan.loan_amount
            start = loan.approval_date or loan.application_date or fields.Date.context_today(loan)
            delta = loan._period_delta()
            interest_factor = loan._period_interest_factor()
            grace_days = loan.product_id.grace_period_days or 0
            schedule_start = start
            vals = []
            sequence_offset = 0
            if grace_days:
                schedule_start = fields.Date.add(start, days=grace_days)
                period_days = ((start + delta) - start).days
                if grace_days > period_days:
                    grace_interest = loan.loan_amount * (loan.interest_rate / 100.0) / 365.0 * grace_days
                    vals.append((0, 0, {
                        'sequence': 1,
                        'due_date': schedule_start,
                        'principal_amount': 0.0,
                        'interest_amount': grace_interest,
                    }))
                    sequence_offset = 1
            for idx in range(1, loan.term + 1):
                if loan.interest_method == 'flat':
                    interest = loan.loan_amount * (loan.interest_rate / 100.0) * interest_factor
                else:
                    interest = remaining * (loan.interest_rate / 100.0) * interest_factor
                due_date = schedule_start + (delta * idx)
                vals.append((0, 0, {
                    'sequence': idx + sequence_offset,
                    'due_date': due_date,
                    'principal_amount': principal,
                    'interest_amount': interest,
                }))
                remaining -= principal
            loan.write({'installment_ids': vals})
        return True

    def action_reschedule(self):
        self.ensure_one()
        if self.state != 'active':
            raise UserError(_('Le rééchelonnement n\'est possible que pour un crédit actif.'))
        if not self.installment_ids.filtered(lambda inst: inst.state != 'paid'):
            raise UserError(_('Aucune échéance restante à rééchelonner.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Rééchelonner le crédit'),
            'res_model': 'microfinance.loan.reschedule.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_loan_id': self.id},
        }

    def _reschedule_installments(self, new_term, new_first_due_date, reason=False):
        self.ensure_one()
        unpaid = self.installment_ids.filtered(lambda inst: inst.state != 'paid').sorted(lambda inst: (inst.due_date, inst.sequence))
        if not unpaid:
            raise UserError(_('Aucune échéance restante à rééchelonner.'))

        def _summary(installments):
            return '<br/>'.join(
                _('Échéance %s : %s - Capital %.2f, Intérêt %.2f, Solde %.2f') % (
                    inst.sequence, inst.due_date, inst.principal_amount, inst.interest_amount, inst.residual_amount
                ) for inst in installments
            ) or _('Aucune échéance')

        old_summary = _summary(unpaid)
        # Structured snapshot of the schedule about to be dropped/rewritten below, kept
        # queryable (ORM/report/filter) instead of only readable in the chatter message.
        self.env['microfinance.loan.reschedule.history'].create({
            'loan_id': self.id,
            'reason': reason,
            'old_installment_ids': [(0, 0, {
                'sequence': inst.sequence,
                'due_date': inst.due_date,
                'principal_amount': inst.principal_amount,
                'interest_amount': inst.interest_amount,
                'penalty_amount': inst.penalty_amount,
                'paid_principal': inst.paid_principal,
                'paid_interest': inst.paid_interest,
                'paid_penalty': inst.paid_penalty,
                'residual_amount': inst.residual_amount,
            }) for inst in unpaid],
        })
        remaining_principal = sum(inst.principal_amount - inst.paid_principal for inst in unpaid)
        # Only arrears (overdue or partially paid) carry interest/penalty already accrued and due;
        # plain future pending installments have their interest recomputed fresh below.
        arrears = unpaid.filtered(lambda inst: inst.state in ('overdue', 'partial'))
        carried_interest = sum(inst.interest_amount - inst.paid_interest for inst in arrears)
        carried_penalty = sum(inst.penalty_amount - inst.paid_penalty for inst in arrears)
        term = new_term or len(unpaid)
        original_first_due_date = unpaid[0].due_date
        start = new_first_due_date or original_first_due_date
        delta = self._period_delta()
        interest_factor = self._period_interest_factor()

        # Partially paid installments keep their history (paid_* amounts stay untouched for
        # accounting purposes) but are locked to what was actually collected; the outstanding
        # part is carried into the new schedule instead. Untouched installments are dropped.
        partially_paid = unpaid.filtered(lambda inst: inst.paid_principal or inst.paid_interest or inst.paid_penalty)
        for inst in partially_paid:
            inst.write({
                'principal_amount': inst.paid_principal,
                'interest_amount': inst.paid_interest,
                'penalty_amount': inst.paid_penalty,
            })
        (unpaid - partially_paid).unlink()
        vals = []
        sequence = 1
        if carried_interest > 0.01 or carried_penalty > 0.01:
            # Interest/penalty already accrued before the reschedule keep their original due date,
            # in a dedicated line so they are not lost nor merged with the new principal schedule.
            vals.append((0, 0, {
                'sequence': sequence,
                'due_date': original_first_due_date,
                'principal_amount': 0.0,
                'interest_amount': max(carried_interest, 0.0),
                'penalty_amount': max(carried_penalty, 0.0),
            }))
            sequence += 1
        principal = remaining_principal / term
        remaining = remaining_principal
        for idx in range(term):
            if self.interest_method == 'flat':
                interest = remaining_principal * (self.interest_rate / 100.0) * interest_factor
            else:
                interest = remaining * (self.interest_rate / 100.0) * interest_factor
            due_date = start + (delta * idx)
            vals.append((0, 0, {
                'sequence': sequence,
                'due_date': due_date,
                'principal_amount': principal,
                'interest_amount': interest,
            }))
            remaining -= principal
            sequence += 1
        self.write({'installment_ids': vals})
        new_summary = _summary(self.installment_ids.filtered(lambda inst: inst.state != 'paid'))
        self.reschedule_count += 1
        self.message_post(body=_(
            'Rééchelonnement n°%(count)s effectué.<br/>Ancien échéancier restant :<br/>%(old)s'
            '<br/><br/>Nouvel échéancier :<br/>%(new)s'
        ) % {'count': self.reschedule_count, 'old': old_summary, 'new': new_summary})
        return True

    def _prepare_disbursement_move(self):
        self.ensure_one()
        product = self.product_id
        journal = product.disbursement_journal_id
        principal_account = product._get_account('principal', self.partner_id)
        if not journal or not principal_account or not journal.default_account_id:
            raise UserError(_('Configurez le journal de décaissement, son compte par défaut et le compte principal en cours du produit.'))
        credit_lines = [
            (0, 0, {'name': _('Sortie caisse/banque %s') % self.name, 'partner_id': self.partner_id.id, 'account_id': journal.default_account_id.id, 'debit': 0.0, 'credit': self.net_disbursed_amount}),
        ]
        # Frais nettés du décaissement (fee_charged_before_disbursement=False) : le capital dû
        # (débit ci-dessous) reste plein, mais la sortie caisse est diminuée des frais, dont la
        # contrepartie est comptabilisée ici plutôt que via une écriture d'encaissement séparée
        # (action_charge_fee(), qui reste le mécanisme utilisé quand fee_charged_before_disbursement=True).
        if not product.fee_charged_before_disbursement and self.fee_amount_due > 0:
            if not product.account_commission_credit_id:
                raise UserError(_('Configurez le compte commission sur crédit du produit pour netter les frais de dossier du décaissement.'))
            credit_lines.append((0, 0, {
                'name': _('Frais de dossier %s') % self.name, 'partner_id': self.partner_id.id,
                'account_id': product.account_commission_credit_id.id, 'debit': 0.0, 'credit': self.fee_amount_due,
            }))
        return {
            'date': fields.Date.context_today(self),
            'journal_id': journal.id,
            'ref': _('Décaissement crédit %s') % self.name,
            'microfinance_loan_id': self.id,
            'line_ids': [
                (0, 0, {'name': _('Crédit client %s') % self.name, 'partner_id': self.partner_id.id, 'account_id': principal_account.id, 'debit': self.loan_amount, 'credit': 0.0}),
            ] + credit_lines
        }

    def _prepare_fee_move(self):
        self.ensure_one()
        product = self.product_id
        journal = product.fee_journal_id
        if not journal or not journal.default_account_id or not product.account_commission_credit_id:
            raise UserError(_('Configurez le journal d\'encaissement des frais, son compte par défaut et le compte commission sur crédit du produit.'))
        return {
            'date': fields.Date.context_today(self),
            'journal_id': journal.id,
            'ref': _('Frais de dossier crédit %s') % self.name,
            'microfinance_loan_id': self.id,
            'line_ids': [
                (0, 0, {'name': _('Encaissement frais %s') % self.name, 'partner_id': self.partner_id.id, 'account_id': journal.default_account_id.id, 'debit': self.fee_amount_due, 'credit': 0.0}),
                (0, 0, {'name': _('Frais de dossier %s') % self.name, 'partner_id': self.partner_id.id, 'account_id': product.account_commission_credit_id.id, 'debit': 0.0, 'credit': self.fee_amount_due}),
            ]
        }

    def action_charge_fee(self):
        for loan in self:
            if loan.state != 'approved':
                raise UserError(_('Les frais de dossier ne peuvent être encaissés que sur un crédit approuvé.'))
            if loan.fee_paid:
                raise UserError(_('Les frais de dossier ont déjà été encaissés.'))
            if loan.fee_amount_due <= 0:
                raise UserError(_('Aucun frais de dossier à encaisser pour ce crédit.'))
            move = self.env['account.move'].with_context(
                default_loan_id=False,
                default_loan_line_id=False,
            ).create(loan._prepare_fee_move())
            move.action_post()
            loan.write({'fee_paid': True, 'fee_move_id': move.id})
            loan.message_post(body=_('Frais de dossier encaissés (%.2f). Écriture : %s') % (loan.fee_amount_due, move.name))
        return True

    def action_disburse(self):
        for loan in self:
            if loan.state != 'approved':
                raise UserError(_('Le crédit doit être approuvé avant décaissement.'))
            if loan.product_id.fee_charged_before_disbursement and not loan.fee_paid and loan.fee_amount_due > 0:
                raise UserError(_('Les frais de dossier doivent être encaissés avant le décaissement.'))
            if not loan.installment_ids:
                loan.action_generate_schedule()
            move = self.env['account.move'].with_context(
                default_loan_id=False,
                default_loan_line_id=False,
            ).create(loan._prepare_disbursement_move())
            move.action_post()
            loan.write({'state': 'active', 'disbursement_date': fields.Date.context_today(loan)})
            loan.message_post(body=_('Crédit décaissé. Écriture : %s') % move.name)
        return True

    def action_write_off(self):
        self.ensure_one()
        if self.state not in ('active', 'defaulted'):
            raise UserError(_('La radiation n\'est possible que pour un crédit actif ou en défaut.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Radier le crédit'),
            'res_model': 'microfinance.loan.writeoff.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_loan_id': self.id},
        }

    def _prepare_writeoff_move(self, write_off_date):
        self.ensure_one()
        product = self.product_id
        write_off_account = product._get_account('credits_perte', self.partner_id)
        if not write_off_account:
            raise UserError(_('Configurez le compte de crédits passés en perte pour ce produit avant de radier ce crédit.'))
        journal = self.env['account.journal'].search([
            ('company_id', '=', self.company_id.id), ('type', '=', 'general'),
        ], limit=1)
        if not journal:
            raise UserError(_('Aucun journal des opérations diverses n\'est configuré pour cette société.'))
        return {
            'date': write_off_date,
            'journal_id': journal.id,
            'ref': _('Radiation crédit %s') % self.name,
            'microfinance_loan_id': self.id,
            'line_ids': [
                (0, 0, {'name': _('Perte sur créance %s') % self.name, 'partner_id': self.partner_id.id, 'account_id': write_off_account.id, 'debit': self.balance_total, 'credit': 0.0}),
                (0, 0, {'name': _('Sortie prêt client %s') % self.name, 'partner_id': self.partner_id.id, 'account_id': product._get_account('principal', self.partner_id).id, 'debit': 0.0, 'credit': self.balance_total}),
            ]
        }

    def action_confirm_write_off(self, reason, write_off_date):
        self.ensure_one()
        if self.state not in ('active', 'defaulted'):
            raise UserError(_('La radiation n\'est possible que pour un crédit actif ou en défaut.'))
        if self.balance_total <= 0.01:
            raise UserError(_('Aucun solde restant à radier. Utilisez la clôture normale.'))
        move = self.env['account.move'].with_context(
            default_loan_id=False,
            default_loan_line_id=False,
        ).create(self._prepare_writeoff_move(write_off_date))
        move.action_post()
        self.write({'state': 'written_off'})
        self.message_post(body=_('Crédit radié le %(date)s. Motif : %(reason)s. Écriture : %(move)s') % {
            'date': write_off_date, 'reason': reason, 'move': move.name,
        })
        return move

    def _get_misc_operations_journal(self):
        self.ensure_one()
        journal = self.env['account.journal'].search([
            ('company_id', '=', self.company_id.id), ('type', '=', 'general'),
        ], limit=1)
        if not journal:
            raise UserError(_('Aucun journal des opérations diverses n\'est configuré pour cette société.'))
        return journal

    def _prepare_provision_move(self, delta, as_of_date):
        self.ensure_one()
        product = self.product_id
        provision_cout_account = product._get_account('provision_cout', self.partner_id)
        provision_contra_account = product._get_account('provision', self.partner_id)
        if not provision_cout_account or not provision_contra_account:
            raise UserError(_(
                'Configurez les comptes de provision (coût et contrepartie) pour le produit %s '
                'avant de comptabiliser une provision.'
            ) % product.display_name)
        journal = self._get_misc_operations_journal()
        amount = abs(delta)
        if delta > 0:
            label = _('Dotation provision %s') % self.name
            charge_vals = {'debit': amount, 'credit': 0.0}
            contra_vals = {'debit': 0.0, 'credit': amount}
        else:
            label = _('Reprise provision %s') % self.name
            charge_vals = {'debit': 0.0, 'credit': amount}
            contra_vals = {'debit': amount, 'credit': 0.0}
        return {
            'date': as_of_date,
            'journal_id': journal.id,
            'ref': label,
            'microfinance_loan_id': self.id,
            'line_ids': [
                (0, 0, dict(charge_vals, name=label, partner_id=self.partner_id.id, account_id=provision_cout_account.id)),
                (0, 0, dict(contra_vals, name=label, partner_id=self.partner_id.id, account_id=provision_contra_account.id)),
            ],
        }

    def action_post_provisions(self, as_of_date=None):
        """Comptabilise, pour chaque crédit actif ou en défaut de la sélection, le delta entre la
        provision déjà comptabilisée (provision_posted_amount) et la provision requise recalculée
        (provision_amount). Une écriture dédiée par crédit : plus facile à tracer/auditer une par
        une dans le chatter qu'une écriture consolidée, au prix d'un nombre d'écritures plus élevé
        lors d'une campagne mensuelle sur tout le portefeuille."""
        as_of_date = as_of_date or fields.Date.context_today(self)
        for loan in self.filtered(lambda l: l.state in ('active', 'defaulted')):
            delta = loan.provision_amount - loan.provision_posted_amount
            if abs(delta) < 0.01:
                continue
            move = self.env['account.move'].with_context(
                default_loan_id=False,
                default_loan_line_id=False,
            ).create(loan._prepare_provision_move(delta, as_of_date))
            move.action_post()
            old_amount = loan.provision_posted_amount
            loan.write({'provision_posted_amount': loan.provision_amount})
            loan.message_post(body=_(
                'Provision ajustée au %(date)s : %(old)s → %(new)s (delta %(delta)s). Écriture : %(move)s'
            ) % {
                'date': as_of_date, 'old': '%.2f' % old_amount, 'new': '%.2f' % loan.provision_amount,
                'delta': '%.2f' % delta, 'move': move.name,
            })
        return True

    @api.model
    def cron_post_provisions(self):
        self.search([('state', 'in', ('active', 'defaulted'))]).action_post_provisions()
        return True

    def action_open_payment_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Enregistrer remboursement'), 'res_model': 'microfinance.loan.payment.wizard',
            'view_mode': 'form', 'target': 'new', 'context': {'default_loan_id': self.id, 'default_journal_id': self.product_id.payment_journal_id.id}
        }

    def action_view_installments(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Échéances'), 'res_model': 'microfinance.loan.installment', 'view_mode': 'tree,form', 'domain': [('loan_id', '=', self.id)]}

    def action_view_payments(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Remboursements'), 'res_model': 'microfinance.loan.payment', 'view_mode': 'tree,form', 'domain': [('loan_id', '=', self.id)]}

    def action_view_visits(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Visites'), 'res_model': 'microfinance.collection.visit', 'view_mode': 'tree,form,calendar', 'domain': [('loan_id', '=', self.id)]}

    def action_view_moves(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Écritures'), 'res_model': 'account.move', 'view_mode': 'tree,form', 'domain': [('microfinance_loan_id', '=', self.id)]}

    def action_view_scoring_lines(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Scoring'), 'res_model': 'microfinance.scoring.line', 'view_mode': 'tree,form', 'domain': [('loan_id', '=', self.id)], 'context': {'default_loan_id': self.id}}

    @api.model
    def cron_update_overdue_and_penalties(self):
        # Domaine étendu par rapport aux seules échéances pending/partial/overdue : inclut aussi
        # celles ayant un épisode de retard ouvert (arrears_onset_date posé, pas encore soldé côté
        # historique) pour que _sync_arrears_state() capture aussi les régularisations (passage à
        # 'paid') et pose arrears_cured_date. La portée de action_apply_penalty() reste identique
        # à avant (filtrée sur pending/partial/overdue juste après).
        installments = self.env['microfinance.loan.installment'].search([
            '|',
            ('state', 'in', ('pending', 'partial', 'overdue')),
            '&', ('arrears_onset_date', '!=', False), ('arrears_cured_date', '=', False),
        ])
        installments._sync_arrears_state()
        installments.filtered(lambda inst: inst.state in ('pending', 'partial', 'overdue')).action_apply_penalty()
        self.search([('state', '=', 'active')]).action_calculate_scoring(silent=True)
        return True


class AccountMove(models.Model):
    _inherit = 'account.move'
    microfinance_loan_id = fields.Many2one('microfinance.loan', string='Crédit microfinance', index=True, copy=False)
    microfinance_payment_id = fields.Many2one('microfinance.loan.payment', string='Paiement microfinance', index=True, copy=False)
