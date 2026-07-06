# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class MicrofinanceLoan(models.Model):
    _name = 'microfinance.loan'
    _description = 'Crédit microfinance'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(default='Nouveau', copy=False, readonly=True, tracking=True)
    partner_id = fields.Many2one('res.partner', string='Emprunteur', required=True, tracking=True)
    product_id = fields.Many2one('microfinance.loan.product', string='Produit', required=True, tracking=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True, tracking=True)
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id, required=True)
    loan_amount = fields.Monetary(string='Montant crédit', required=True, tracking=True)
    term = fields.Integer(string='Nombre échéances', required=True, default=1, tracking=True)
    application_date = fields.Date(default=fields.Date.context_today, required=True)
    approval_date = fields.Date(readonly=True)
    disbursement_date = fields.Date(readonly=True)
    interest_rate = fields.Float(string='Taux intérêt annuel (%)', related='product_id.interest_rate', readonly=False, store=True)
    interest_method = fields.Selection(related='product_id.interest_method', readonly=False, store=True)
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
    ], default='draft', tracking=True, index=True)
    officer_id = fields.Many2one('res.users', default=lambda self: self.env.user, tracking=True)
    manager_id = fields.Many2one('res.users', tracking=True)
    finance_user_id = fields.Many2one('res.users', tracking=True)
    collection_agent_id = fields.Many2one('res.users', tracking=True)
    installment_ids = fields.One2many('microfinance.loan.installment', 'loan_id', string='Échéancier')
    payment_ids = fields.One2many('microfinance.loan.payment', 'loan_id', string='Remboursements')
    visit_ids = fields.One2many('microfinance.collection.visit', 'loan_id', string='Visites')
    move_ids = fields.One2many('account.move', 'microfinance_loan_id', string='Écritures comptables')
    principal_total = fields.Monetary(compute='_compute_totals', store=True)
    interest_total = fields.Monetary(compute='_compute_totals', store=True)
    penalty_total = fields.Monetary(compute='_compute_totals', store=True)
    paid_total = fields.Monetary(compute='_compute_totals', store=True)
    balance_total = fields.Monetary(compute='_compute_totals', store=True)
    overdue_amount = fields.Monetary(compute='_compute_totals', store=True)
    overdue_installment_count = fields.Integer(compute='_compute_totals', store=True)
    risk_score = fields.Integer(compute='_compute_risk_score', store=True)
    provision_amount = fields.Monetary(compute='_compute_provision', store=True, string='Provision requise')
    provision_posted_amount = fields.Monetary(copy=False, readonly=True, default=0.0, string='Provision comptabilisée')
    scoring_profile_id = fields.Many2one(
        'microfinance.scoring.profile',
        string='Profil de scoring',
        domain="['|', ('product_id', '=', False), ('product_id', '=', product_id)]",
        copy=False,
        tracking=True,
    )
    internal_score = fields.Float(string='Score interne', copy=False, readonly=True, tracking=True)
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
    scoring_line_count = fields.Integer(compute='_compute_counts')
    note = fields.Text()
    installment_count = fields.Integer(compute='_compute_counts')
    payment_count = fields.Integer(compute='_compute_counts')
    visit_count = fields.Integer(compute='_compute_counts')
    move_count = fields.Integer(compute='_compute_counts')
    reschedule_count = fields.Integer(default=0, copy=False, readonly=True, tracking=True)
    co_borrower_id = fields.Many2one('res.partner', string='Co-emprunteur', tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('microfinance.loan') or 'Nouveau'
        return super().create(vals_list)

    @api.constrains('loan_amount', 'term', 'product_id')
    def _check_product_limits(self):
        for loan in self:
            product = loan.product_id
            if product and (loan.loan_amount < product.min_amount or loan.loan_amount > product.max_amount):
                raise ValidationError(_('Le montant doit respecter les limites du produit.'))
            if product and (loan.term < product.min_term or loan.term > product.max_term):
                raise ValidationError(_('La durée doit respecter les limites du produit.'))

    @api.depends('installment_ids.principal_amount', 'installment_ids.interest_amount', 'installment_ids.penalty_amount',
                 'installment_ids.paid_principal', 'installment_ids.paid_interest', 'installment_ids.paid_penalty',
                 'installment_ids.residual_amount', 'installment_ids.state')
    def _compute_totals(self):
        for loan in self:
            loan.principal_total = sum(loan.installment_ids.mapped('principal_amount'))
            loan.interest_total = sum(loan.installment_ids.mapped('interest_amount'))
            loan.penalty_total = sum(loan.installment_ids.mapped('penalty_amount'))
            loan.paid_total = sum(loan.installment_ids.mapped('paid_principal')) + sum(loan.installment_ids.mapped('paid_interest')) + sum(loan.installment_ids.mapped('paid_penalty'))
            loan.balance_total = sum(loan.installment_ids.mapped('residual_amount')) or loan.loan_amount
            overdue = loan.installment_ids.filtered(lambda l: l.state == 'overdue')
            loan.overdue_amount = sum(overdue.mapped('residual_amount'))
            loan.overdue_installment_count = len(overdue)

    def _get_max_overdue_days(self):
        self.ensure_one()
        today = fields.Date.context_today(self)
        overdue = self.installment_ids.filtered(lambda l: l.state == 'overdue')
        max_days = 0
        for line in overdue:
            if line.due_date:
                max_days = max(max_days, (today - line.due_date).days)
        return max_days

    @api.depends('state', 'overdue_installment_count', 'overdue_amount', 'installment_ids.due_date', 'installment_ids.state', 'payment_ids.amount')
    def _compute_risk_score(self):
        for loan in self:
            if loan.state == 'written_off':
                # Written-off loans are no longer part of the active risk/PAR calculations.
                loan.risk_score = 0
                continue
            max_days = loan._get_max_overdue_days()
            amount_ratio = loan.loan_amount and (loan.overdue_amount / loan.loan_amount) or 0.0
            partial_count = len(loan.installment_ids.filtered(lambda l: l.state == 'partial'))
            score = min(100, int(loan.overdue_installment_count * 15 + max_days * 1.2 + amount_ratio * 40 + partial_count * 5))
            loan.risk_score = max(score, 0)

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
                    points = rule._get_signed_points()
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

    def action_recompute_risk(self):
        self._compute_risk_score()
        return True

    def _period_delta(self):
        self.ensure_one()
        return {'daily': relativedelta(days=1), 'weekly': relativedelta(weeks=1), 'monthly': relativedelta(months=1)}[self.product_id.repayment_frequency]

    def action_generate_schedule(self):
        for loan in self:
            if loan.state not in ('draft', 'submitted', 'manager_validated', 'finance_validated', 'approved'):
                raise UserError(_('Échéancier autorisé avant activation seulement.'))
            loan.installment_ids.unlink()
            principal = loan.loan_amount / loan.term
            remaining = loan.loan_amount
            start = loan.approval_date or loan.application_date or fields.Date.context_today(loan)
            delta = loan._period_delta()
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
                    interest = loan.loan_amount * (loan.interest_rate / 100.0) / 12.0
                else:
                    interest = remaining * (loan.interest_rate / 100.0) / 12.0
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

    def _reschedule_installments(self, new_term, new_first_due_date):
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
                interest = remaining_principal * (self.interest_rate / 100.0) / 12.0
            else:
                interest = remaining * (self.interest_rate / 100.0) / 12.0
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
        if not journal or not product.loan_account_id or not journal.default_account_id:
            raise UserError(_('Configurez le journal de décaissement, son compte par défaut et le compte prêts clients.'))
        return {
            'date': fields.Date.context_today(self),
            'journal_id': journal.id,
            'ref': _('Décaissement crédit %s') % self.name,
            'microfinance_loan_id': self.id,
            'line_ids': [
                (0, 0, {'name': _('Crédit client %s') % self.name, 'partner_id': self.partner_id.id, 'account_id': product.loan_account_id.id, 'debit': self.loan_amount, 'credit': 0.0}),
                (0, 0, {'name': _('Sortie caisse/banque %s') % self.name, 'partner_id': self.partner_id.id, 'account_id': journal.default_account_id.id, 'debit': 0.0, 'credit': self.loan_amount}),
            ]
        }

    def action_disburse(self):
        for loan in self:
            if loan.state != 'approved':
                raise UserError(_('Le crédit doit être approuvé avant décaissement.'))
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
        if not product.write_off_account_id:
            raise UserError(_('Configurez le compte de pertes sur créances irrécouvrables pour ce produit avant de radier ce crédit.'))
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
                (0, 0, {'name': _('Perte sur créance %s') % self.name, 'partner_id': self.partner_id.id, 'account_id': product.write_off_account_id.id, 'debit': self.balance_total, 'credit': 0.0}),
                (0, 0, {'name': _('Sortie prêt client %s') % self.name, 'partner_id': self.partner_id.id, 'account_id': product.loan_account_id.id, 'debit': 0.0, 'credit': self.balance_total}),
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
        if not product.provision_account_id or not product.provision_contra_account_id:
            raise UserError(_(
                'Configurez les comptes de provision (charge et contrepartie) pour le produit %s '
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
                (0, 0, dict(charge_vals, name=label, partner_id=self.partner_id.id, account_id=product.provision_account_id.id)),
                (0, 0, dict(contra_vals, name=label, partner_id=self.partner_id.id, account_id=product.provision_contra_account_id.id)),
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
        self.env['microfinance.loan.installment'].search([('state', 'in', ('pending', 'partial', 'overdue'))]).action_apply_penalty()
        self.search([('state', '=', 'active')])._compute_risk_score()
        return True


class AccountMove(models.Model):
    _inherit = 'account.move'
    microfinance_loan_id = fields.Many2one('microfinance.loan', string='Crédit microfinance', index=True, copy=False)
    microfinance_payment_id = fields.Many2one('microfinance.loan.payment', string='Paiement microfinance', index=True, copy=False)
