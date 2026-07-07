# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

CREDIT_TYPES = ('deposit', 'interest_credit')
DEBIT_TYPES = ('withdrawal', 'fee_debit', 'auto_debit', 'transfer')


class MicrofinanceSavingsTransaction(models.Model):
    _name = 'microfinance.savings.transaction'
    _description = "Transaction sur compte d'épargne microfinance"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    account_id = fields.Many2one('microfinance.savings.account', string='Compte épargne', required=True, ondelete='restrict', tracking=True)
    transaction_type = fields.Selection([
        ('deposit', 'Dépôt'),
        ('withdrawal', 'Retrait'),
        ('interest_credit', 'Intérêt crédité'),
        ('fee_debit', 'Frais prélevés'),
        ('auto_debit', 'Prélèvement automatique'),
        ('transfer', 'Virement entre comptes'),
    ], string='Type de transaction', required=True, tracking=True)
    amount = fields.Monetary(string='Montant', required=True)
    date = fields.Date(string='Date', default=fields.Date.context_today, required=True)
    payment_method = fields.Selection([
        ('cash', 'Espèces'),
        ('bank_transfer', 'Virement'),
        ('mobile_money', 'Mobile money'),
    ], string='Moyen de paiement', default='cash')
    state = fields.Selection([
        ('draft', 'Brouillon'),
        ('posted', 'Comptabilisé'),
        ('cancelled', 'Annulé'),
    ], string='État', default='draft', tracking=True)
    move_id = fields.Many2one('account.move', string='Écriture comptable', readonly=True, copy=False)
    note = fields.Text(string='Note')
    related_loan_payment_id = fields.Many2one(
        'microfinance.loan.payment', readonly=True, copy=False, string='Paiement crédit lié',
        help='Renseigné uniquement pour un prélèvement automatique (auto_debit).',
    )
    bypass_min_balance = fields.Boolean(
        string='Déroger au solde minimum', default=False,
        help='Si activé, ce retrait peut faire descendre le solde sous le solde minimum du produit '
             "(clôture de compte, ou prélèvement automatique quand le produit de crédit l'autorise "
             'explicitement).',
    )
    partner_id = fields.Many2one(related='account_id.partner_id', store=True, readonly=True)
    company_id = fields.Many2one(related='account_id.company_id', store=True, readonly=True)
    currency_id = fields.Many2one(related='account_id.currency_id', readonly=True)
    product_id = fields.Many2one(related='account_id.product_id', readonly=True)

    @api.constrains('amount')
    def _check_amount(self):
        for txn in self:
            if txn.amount <= 0:
                raise ValidationError(_('Le montant de la transaction doit être positif.'))

    @api.constrains('transaction_type', 'amount', 'bypass_min_balance', 'account_id')
    def _check_minimum_balance(self):
        # Ce contrôle se déclenche à la création de la transaction (encore en 'draft', donc pas
        # encore comptée dans account_id.balance) : le solde projeté est simplement le solde actuel
        # diminué du montant du retrait.
        for txn in self:
            if txn.transaction_type not in ('withdrawal', 'auto_debit') or txn.bypass_min_balance:
                continue
            min_balance = txn.account_id.product_id.min_balance
            projected_balance = txn.account_id.balance - txn.amount
            if projected_balance < min_balance - 0.01:
                raise ValidationError(_(
                    'Retrait refusé : le solde après retrait (%(projected).2f) descendrait sous le '
                    'solde minimum du produit (%(minimum).2f).'
                ) % {'projected': projected_balance, 'minimum': min_balance})

    def _prepare_transaction_move(self):
        self.ensure_one()
        account = self.account_id
        product = account.product_id
        if not product.deposit_account_id:
            raise UserError(_("Configurez le compte passif épargne clients sur le produit %s.") % product.name)
        label_by_type = {
            'deposit': _('Dépôt épargne %s') % account.name,
            'withdrawal': _('Retrait épargne %s') % account.name,
            'interest_credit': _('Intérêt crédité épargne %s') % account.name,
            'fee_debit': _('Frais de tenue de compte %s') % account.name,
            'auto_debit': _('Prélèvement automatique sur épargne %s') % account.name,
            'transfer': _('Virement épargne %s') % account.name,
        }
        label = label_by_type[self.transaction_type]
        if self.transaction_type in CREDIT_TYPES:
            if self.transaction_type == 'interest_credit':
                if not product.interest_expense_account_id:
                    raise UserError(_("Configurez le compte charge intérêts versés sur le produit %s.") % product.name)
                counterpart_account = product.interest_expense_account_id
            else:
                journal = product.deposit_journal_id
                if not journal or not journal.default_account_id:
                    raise UserError(_('Configurez le journal de dépôt et son compte par défaut sur le produit %s.') % product.name)
                counterpart_account = journal.default_account_id
            lines = [
                (0, 0, {'name': label, 'partner_id': account.partner_id.id, 'account_id': counterpart_account.id, 'debit': self.amount, 'credit': 0.0}),
                (0, 0, {'name': label, 'partner_id': account.partner_id.id, 'account_id': product.deposit_account_id.id, 'debit': 0.0, 'credit': self.amount}),
            ]
        else:
            if self.transaction_type == 'fee_debit':
                if not product.fee_income_account_id:
                    raise UserError(_('Configurez le compte produit frais sur le produit %s.') % product.name)
                counterpart_account = product.fee_income_account_id
            else:
                journal = product.withdrawal_journal_id
                if not journal or not journal.default_account_id:
                    raise UserError(_('Configurez le journal de retrait et son compte par défaut sur le produit %s.') % product.name)
                counterpart_account = journal.default_account_id
            lines = [
                (0, 0, {'name': label, 'partner_id': account.partner_id.id, 'account_id': product.deposit_account_id.id, 'debit': self.amount, 'credit': 0.0}),
                (0, 0, {'name': label, 'partner_id': account.partner_id.id, 'account_id': counterpart_account.id, 'debit': 0.0, 'credit': self.amount}),
            ]
        journal_for_move = (
            product.deposit_journal_id if self.transaction_type in CREDIT_TYPES and self.transaction_type != 'interest_credit'
            else product.withdrawal_journal_id or product.deposit_journal_id
        )
        if not journal_for_move:
            raise UserError(_('Configurez au moins un journal (dépôt ou retrait) sur le produit %s.') % product.name)
        return {
            'date': self.date,
            'journal_id': journal_for_move.id,
            'ref': label,
            'microfinance_savings_account_id': account.id,
            'microfinance_savings_transaction_id': self.id,
            'line_ids': lines,
        }

    def action_post(self):
        for txn in self:
            if txn.state != 'draft':
                continue
            if txn.transaction_type in ('withdrawal', 'auto_debit', 'transfer') and txn.account_id.state != 'active':
                raise UserError(_('Les retraits ne sont autorisés que sur un compte épargne actif.'))
            if txn.transaction_type == 'deposit' and txn.account_id.state not in ('draft', 'active'):
                raise UserError(_('Dépôt impossible sur un compte clôturé ou dormant.'))
            move = self.env['account.move'].with_context(
                default_loan_id=False, default_loan_line_id=False,
            ).create(txn._prepare_transaction_move())
            move.action_post()
            txn.write({'move_id': move.id, 'state': 'posted'})
            txn.account_id.message_post(body=_('Transaction %(type)s de %(amount).2f comptabilisée. Écriture : %(move)s') % {
                'type': dict(txn._fields['transaction_type'].selection).get(txn.transaction_type),
                'amount': txn.amount, 'move': move.name,
            })
        return True


class AccountMove(models.Model):
    _inherit = 'account.move'
    microfinance_savings_account_id = fields.Many2one('microfinance.savings.account', string='Compte épargne microfinance', index=True, copy=False)
    microfinance_savings_transaction_id = fields.Many2one('microfinance.savings.transaction', string='Transaction épargne microfinance', index=True, copy=False)
