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
    note = fields.Text()
    installment_count = fields.Integer(compute='_compute_counts')
    payment_count = fields.Integer(compute='_compute_counts')
    visit_count = fields.Integer(compute='_compute_counts')
    move_count = fields.Integer(compute='_compute_counts')

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

    @api.depends('overdue_installment_count', 'overdue_amount', 'installment_ids.due_date', 'installment_ids.state', 'payment_ids.amount')
    def _compute_risk_score(self):
        today = fields.Date.context_today(self)
        for loan in self:
            overdue = loan.installment_ids.filtered(lambda l: l.state == 'overdue')
            max_days = 0
            for line in overdue:
                if line.due_date:
                    max_days = max(max_days, (today - line.due_date).days)
            amount_ratio = loan.loan_amount and (loan.overdue_amount / loan.loan_amount) or 0.0
            partial_count = len(loan.installment_ids.filtered(lambda l: l.state == 'partial'))
            score = min(100, int(loan.overdue_installment_count * 15 + max_days * 1.2 + amount_ratio * 40 + partial_count * 5))
            loan.risk_score = max(score, 0)

    def _compute_counts(self):
        for loan in self:
            loan.installment_count = len(loan.installment_ids)
            loan.payment_count = len(loan.payment_ids)
            loan.visit_count = len(loan.visit_ids)
            loan.move_count = len(loan.move_ids)

    def action_submit(self):
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
            vals = []
            for idx in range(1, loan.term + 1):
                if loan.interest_method == 'flat':
                    interest = loan.loan_amount * (loan.interest_rate / 100.0) / 12.0
                else:
                    interest = remaining * (loan.interest_rate / 100.0) / 12.0
                due_date = start + (delta * idx)
                vals.append((0, 0, {
                    'sequence': idx,
                    'due_date': due_date,
                    'principal_amount': principal,
                    'interest_amount': interest,
                }))
                remaining -= principal
            loan.write({'installment_ids': vals})
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
            move = self.env['account.move'].create(loan._prepare_disbursement_move())
            move.action_post()
            loan.write({'state': 'active', 'disbursement_date': fields.Date.context_today(loan)})
            loan.message_post(body=_('Crédit décaissé. Écriture : %s') % move.name)
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

    @api.model
    def cron_update_overdue_and_penalties(self):
        self.env['microfinance.loan.installment'].search([('state', 'in', ('pending', 'partial', 'overdue'))]).action_apply_penalty()
        self.search([('state', '=', 'active')])._compute_risk_score()
        return True


class AccountMove(models.Model):
    _inherit = 'account.move'
    microfinance_loan_id = fields.Many2one('microfinance.loan', string='Crédit microfinance', index=True, copy=False)
    microfinance_payment_id = fields.Many2one('microfinance.loan.payment', string='Paiement microfinance', index=True, copy=False)
