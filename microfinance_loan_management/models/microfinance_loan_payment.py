# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class MicrofinanceLoanPayment(models.Model):
    _name = 'microfinance.loan.payment'
    _description = 'Remboursement crédit microfinance'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(default='Nouveau', copy=False, readonly=True)
    loan_id = fields.Many2one('microfinance.loan', required=True, ondelete='restrict', tracking=True)
    partner_id = fields.Many2one(related='loan_id.partner_id', store=True, readonly=True)
    payment_date = fields.Date(default=fields.Date.context_today, required=True)
    amount = fields.Monetary(required=True)
    journal_id = fields.Many2one('account.journal', required=True, domain="[('type', 'in', ('bank','cash'))]")
    currency_id = fields.Many2one(related='loan_id.currency_id', store=True, readonly=True)
    company_id = fields.Many2one(related='loan_id.company_id', store=True, readonly=True)
    allocated_penalty = fields.Monetary(readonly=True)
    allocated_interest = fields.Monetary(readonly=True)
    allocated_principal = fields.Monetary(readonly=True)
    move_id = fields.Many2one('account.move', readonly=True, copy=False)
    reversal_move_id = fields.Many2one('account.move', readonly=True, copy=False, string='Écriture de contre-passation')
    state = fields.Selection([('draft', 'Brouillon'), ('posted', 'Comptabilisé'), ('cancelled', 'Annulé')], default='draft', tracking=True)
    installment_ids = fields.Many2many('microfinance.loan.installment', 'microfinance_installment_payment_rel', 'payment_id', 'installment_id', readonly=True)
    note = fields.Text()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('microfinance.loan.payment') or 'Nouveau'
        return super().create(vals_list)

    @api.constrains('amount')
    def _check_amount(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(_('Le montant du remboursement doit être positif.'))

    def _allocate_to_installments(self):
        self.ensure_one()
        if self.loan_id.state not in ('active', 'defaulted'):
            raise UserError(_('Le crédit doit être actif ou en défaut pour enregistrer un remboursement.'))
        if self.amount > self.loan_id.balance_total + 0.01:
            raise UserError(_('Surpaiement interdit. Solde restant : %.2f') % self.loan_id.balance_total)
        remaining = self.amount
        alloc_penalty = alloc_interest = alloc_principal = 0.0
        touched = self.env['microfinance.loan.installment']
        installments = self.loan_id.installment_ids.filtered(lambda i: i.residual_amount > 0.01).sorted(lambda i: (i.due_date, i.sequence))
        for inst in installments:
            if remaining <= 0.01:
                break
            penalty_due = max(inst.penalty_amount - inst.paid_penalty, 0.0)
            pay = min(remaining, penalty_due)
            if pay:
                inst.paid_penalty += pay
                alloc_penalty += pay
                remaining -= pay
                touched |= inst
            interest_due = max(inst.interest_amount - inst.paid_interest, 0.0)
            pay = min(remaining, interest_due)
            if pay:
                inst.paid_interest += pay
                alloc_interest += pay
                remaining -= pay
                touched |= inst
            principal_due = max(inst.principal_amount - inst.paid_principal, 0.0)
            pay = min(remaining, principal_due)
            if pay:
                inst.paid_principal += pay
                alloc_principal += pay
                remaining -= pay
                touched |= inst
        self.write({
            'allocated_penalty': alloc_penalty,
            'allocated_interest': alloc_interest,
            'allocated_principal': alloc_principal,
            'installment_ids': [(6, 0, touched.ids)],
        })

    def _prepare_payment_move(self):
        self.ensure_one()
        product = self.loan_id.product_id
        if not self.journal_id.default_account_id:
            raise UserError(_('Le journal de paiement doit avoir un compte par défaut.'))
        lines = [(0, 0, {
            'name': _('Encaissement remboursement %s') % self.name,
            'partner_id': self.partner_id.id,
            'account_id': self.journal_id.default_account_id.id,
            'debit': self.amount,
            'credit': 0.0,
        })]
        if self.allocated_principal:
            lines.append((0, 0, {'name': _('Capital %s') % self.name, 'partner_id': self.partner_id.id, 'account_id': product.loan_account_id.id, 'debit': 0.0, 'credit': self.allocated_principal}))
        if self.allocated_interest:
            lines.append((0, 0, {'name': _('Intérêt %s') % self.name, 'partner_id': self.partner_id.id, 'account_id': product.interest_account_id.id, 'debit': 0.0, 'credit': self.allocated_interest}))
        if self.allocated_penalty:
            lines.append((0, 0, {'name': _('Pénalité %s') % self.name, 'partner_id': self.partner_id.id, 'account_id': product.penalty_account_id.id, 'debit': 0.0, 'credit': self.allocated_penalty}))
        return {
            'date': self.payment_date,
            'journal_id': self.journal_id.id,
            'ref': _('Remboursement crédit %s') % self.loan_id.name,
            'microfinance_loan_id': self.loan_id.id,
            'microfinance_payment_id': self.id,
            'line_ids': lines,
        }

    def action_post(self):
        for payment in self:
            if payment.state != 'draft':
                continue
            payment._allocate_to_installments()
            move = self.env['account.move'].with_context(
                default_loan_id=False,
                default_loan_line_id=False,
            ).create(payment._prepare_payment_move())
            move.action_post()
            payment.write({'move_id': move.id, 'state': 'posted'})
            payment.loan_id.message_post(body=_('Remboursement %s comptabilisé : %s') % (payment.name, move.name))
            if payment.loan_id.balance_total <= 0.01:
                payment.loan_id.state = 'closed'
        return True

    def action_open_cancel_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Annuler le remboursement'),
            'res_model': 'microfinance.loan.payment.cancel.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_payment_id': self.id},
        }

    def action_cancel(self, reason=None):
        for payment in self:
            if payment.state == 'posted':
                payment._reverse_posted_payment(reason or _('Non renseigné'))
            else:
                payment.state = 'cancelled'
        return True

    def _reverse_posted_payment(self, reason):
        self.ensure_one()
        # No separate group check needed here: ir.model.access.csv already restricts write
        # access on this model to the manager/finance groups (agents only have read access),
        # same convention as action_reschedule/action_confirm_write_off.
        move = self.move_id
        # Raises a clear UserError itself if the original entry's date falls within a locked
        # period (period_lock_date/fiscalyear_lock_date) — no reversal is attempted in that case.
        move._check_fiscalyear_lock_date()

        reversal_move = move._reverse_moves(default_values_list=[{
            'date': fields.Date.context_today(self),
            'ref': _('Contre-passation remboursement %s') % self.name,
        }], cancel=True)

        # Give back, per touched installment (most recently touched first, mirroring the
        # penalty -> interest -> principal order of the original allocation), the amounts this
        # payment had allocated to it.
        remaining_penalty = self.allocated_penalty
        remaining_interest = self.allocated_interest
        remaining_principal = self.allocated_principal
        for inst in self.installment_ids.sorted(lambda i: (i.due_date, i.sequence), reverse=True):
            penalty_back = min(remaining_penalty, inst.paid_penalty)
            interest_back = min(remaining_interest, inst.paid_interest)
            principal_back = min(remaining_principal, inst.paid_principal)
            if penalty_back or interest_back or principal_back:
                inst.write({
                    'paid_penalty': inst.paid_penalty - penalty_back,
                    'paid_interest': inst.paid_interest - interest_back,
                    'paid_principal': inst.paid_principal - principal_back,
                })
            remaining_penalty -= penalty_back
            remaining_interest -= interest_back
            remaining_principal -= principal_back

        loan = self.loan_id
        reopened = loan.state == 'closed'
        if reopened:
            loan.state = 'active'

        self.write({'state': 'cancelled', 'reversal_move_id': reversal_move.id})
        loan.message_post(body=_(
            'Remboursement %(name)s annulé. Motif : %(reason)s. Écriture de contre-passation : %(move)s.%(reopened)s'
        ) % {
            'name': self.name,
            'reason': reason,
            'move': reversal_move.name,
            'reopened': _(' Le crédit repasse en actif.') if reopened else '',
        })
        return reversal_move
