# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class MicrofinanceLoan(models.Model):
    _inherit = 'microfinance.loan'

    savings_requirement_type = fields.Selection(
        related='product_id.savings_requirement_type', string='Exigence épargne (produit)', readonly=True,
    )
    savings_account_id = fields.Many2one(
        'microfinance.savings.account', string="Compte épargne (prélèvement / apport)",
        domain="[('partner_id', '=', partner_id)]", tracking=True,
        help='Compte source du prélèvement automatique et/ou compte dans lequel est vérifié '
             "l'apport/la cible d'épargne progressive.",
    )
    savings_target_amount = fields.Monetary(
        compute='_compute_savings_target_amount', store=True, string='Épargne cible (pendant remboursement)',
    )
    savings_apport_required = fields.Monetary(
        compute='_compute_savings_apport_required', store=True, string="Apport épargne requis",
    )
    savings_apport_verified = fields.Boolean(
        compute='_compute_savings_apport_verified', string='Apport vérifié',
    )
    savings_target_reached = fields.Boolean(
        compute='_compute_savings_target_reached', store=True, string='Épargne cible atteinte',
    )

    @api.depends('loan_amount', 'product_id.savings_requirement_type', 'product_id.savings_target_ratio')
    def _compute_savings_target_amount(self):
        for loan in self:
            if loan.product_id.savings_requirement_type == 'target_during_loan':
                loan.savings_target_amount = loan.loan_amount * loan.product_id.savings_target_ratio / 100.0
            else:
                loan.savings_target_amount = 0.0

    @api.depends('loan_amount', 'product_id.savings_requirement_type', 'product_id.savings_apport_ratio')
    def _compute_savings_apport_required(self):
        for loan in self:
            if loan.product_id.savings_requirement_type == 'upfront_apport':
                loan.savings_apport_required = loan.loan_amount * loan.product_id.savings_apport_ratio / 100.0
            else:
                loan.savings_apport_required = 0.0

    @api.depends('savings_account_id.balance', 'savings_apport_required')
    def _compute_savings_apport_verified(self):
        for loan in self:
            loan.savings_apport_verified = bool(loan.savings_account_id) and loan.savings_account_id.balance >= loan.savings_apport_required

    @api.depends('savings_account_id.balance', 'savings_target_amount')
    def _compute_savings_target_reached(self):
        for loan in self:
            loan.savings_target_reached = (
                bool(loan.savings_account_id)
                and loan.savings_target_amount > 0
                and loan.savings_account_id.balance >= loan.savings_target_amount
            )

    @api.constrains('savings_account_id', 'company_id')
    def _check_savings_account_company(self):
        for loan in self:
            if loan.savings_account_id and loan.savings_account_id.company_id != loan.company_id:
                raise ValidationError(_(
                    'Le compte épargne doit appartenir à la même société que le crédit : un compte '
                    'épargne ne peut pas servir de source de prélèvement pour un crédit d\'une autre société.'
                ))

    def _check_eligibility(self):
        super()._check_eligibility()
        for loan in self:
            loan._check_progressive_savings_eligibility()

    def _check_progressive_savings_eligibility(self):
        """§3bis.4 : contrôle d'éligibilité en amont (pas un débit) — indépendant du contrôle
        d'apport (upfront_apport) du produit demandé. Ne bloque que si le client a un précédent
        crédit dont le produit imposait une épargne cible pendant le remboursement et que cette
        cible n'a pas été atteinte."""
        self.ensure_one()
        previous_loan = self.search([
            ('company_id', '=', self.company_id.id),
            ('partner_id', '=', self.partner_id.id),
            ('id', '!=', self.id),
            ('product_id.savings_requirement_type', '=', 'target_during_loan'),
            ('state', 'in', ('active', 'closed', 'defaulted', 'written_off')),
        ], order='id desc', limit=1)
        if previous_loan and not previous_loan.savings_target_reached:
            raise UserError(_(
                "Épargne cible de %(target).2f non atteinte sur le crédit précédent (%(loan)s) — "
                "solde actuel : %(balance).2f."
            ) % {
                'target': previous_loan.savings_target_amount,
                'loan': previous_loan.name,
                'balance': previous_loan.savings_account_id.balance if previous_loan.savings_account_id else 0.0,
            })

    def action_approve(self):
        for loan in self:
            if loan.product_id.savings_requirement_type == 'upfront_apport' and not loan.savings_apport_verified:
                raise UserError(_(
                    "Apport en épargne insuffisant : requis %(required).2f, solde actuel du compte "
                    "épargne %(balance).2f."
                ) % {
                    'required': loan.savings_apport_required,
                    'balance': loan.savings_account_id.balance if loan.savings_account_id else 0.0,
                })
        return super().action_approve()

    def _process_savings_auto_debit(self):
        """Traite le prélèvement automatique pour CE crédit (une échéance overdue au moins déjà
        filtrée par l'appelant). Réutilise intégralement _allocate_to_installments() et
        _prepare_payment_move() de microfinance.loan.payment : aucune logique d'allocation n'est
        dupliquée ici."""
        self.ensure_one()
        product = self.product_id
        savings_account = self.savings_account_id
        savings_product = savings_account.product_id
        min_floor = savings_product.min_balance if product.auto_debit_respect_minimum_balance else 0.0
        withdrawable = max(savings_account.balance - min_floor, 0.0)
        if withdrawable <= 0.01:
            self.message_post(body=_(
                'Prélèvement automatique impossible — solde épargne insuffisant (solde %(balance).2f, '
                'minimum requis %(minimum).2f).'
            ) % {'balance': savings_account.balance, 'minimum': min_floor})
            return False
        # Jamais plus que ce qui est réellement dû aujourd'hui (échéances déjà en retard) : pas de
        # prélèvement en avance sur des échéances futures non échues, même si le solde le permettrait.
        amount = min(self.overdue_amount, withdrawable)
        if amount <= 0.01:
            return False
        transaction = savings_account._create_transaction(
            'auto_debit', amount, note=_('Prélèvement automatique pour le crédit %s') % self.name,
            bypass_min_balance=not product.auto_debit_respect_minimum_balance,
        )
        payment = self.env['microfinance.loan.payment'].create({
            'loan_id': self.id,
            'amount': amount,
            'journal_id': savings_product.withdrawal_journal_id.id,
            'payment_origin': 'savings_auto_debit',
            'note': _('Prélèvement automatique sur le compte épargne %s') % savings_account.name,
        })
        payment.action_post()
        transaction.write({'related_loan_payment_id': payment.id})
        self.message_post(body=_(
            'Prélèvement automatique sur épargne : %(amount).2f prélevés sur %(account)s '
            '(remboursement %(payment)s).'
        ) % {'amount': amount, 'account': savings_account.name, 'payment': payment.name})
        savings_account.message_post(body=_(
            'Prélèvement automatique de %(amount).2f pour le crédit %(loan)s (remboursement %(payment)s).'
        ) % {'amount': amount, 'loan': self.name, 'payment': payment.name})
        return True

    @api.model
    def cron_process_savings_auto_debit(self):
        today = fields.Date.context_today(self)
        installments = self.env['microfinance.loan.installment'].search([
            ('state', '=', 'overdue'),
            ('loan_id.product_id.allow_savings_auto_debit', '=', True),
            ('loan_id.savings_account_id', '!=', False),
        ], order='loan_id, due_date')
        eligible = installments.filtered(
            lambda inst: inst.due_date and (today - inst.due_date).days >= (inst.loan_id.product_id.auto_debit_grace_days or 0)
        )
        for loan in eligible.mapped('loan_id'):
            try:
                loan._process_savings_auto_debit()
            except Exception:
                _logger.exception('Échec du prélèvement automatique sur épargne pour le crédit %s', loan.name)
        return True
