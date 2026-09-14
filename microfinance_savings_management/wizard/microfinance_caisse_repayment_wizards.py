# -*- coding: utf-8 -*-
"""Assistants de confirmation du remboursement guichet (sous-lot B).

Fait suite à docs_dev/guichet_caisse/AUDIT_cascade_remboursement.md et au sous-lot A
(microfinance.loan.payment.analyze_repayment_situation). Deux assistants, ouverts par le
guichet OWL via microfinance.caisse.mouvement.get_repayment_flow_action() :

- cascade  : le montant solde la 1re échéance en retard ET déborde sur au moins une autre
             échéance en retard -> confirmation avant d'encaisser.
- surplus  : le « dû immédiat » (retards cumulés, ou prochaine échéance si aucun retard) est
             soldé et il reste un surplus -> choix explicite : anticiper les échéances
             futures, ou verser le surplus sur le compte d'épargne lié au crédit.

Aucun `sudo()` ici : la comptabilisation est déléguée à
microfinance.caisse.mouvement.register_repayment_confirmed(), où le sudo reste circonscrit
(cf. AUDIT §6.4).
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class MicrofinanceCaisseRepaymentCascadeWizard(models.TransientModel):
    _name = 'microfinance.caisse.repayment.cascade.wizard'
    _description = "Confirmation de remboursement sur plusieurs échéances en retard"

    session_id = fields.Many2one('microfinance.caisse.session', required=True)
    loan_id = fields.Many2one('microfinance.loan', required=True)
    currency_id = fields.Many2one(related='loan_id.currency_id')
    amount = fields.Monetary(string='Montant remis par le client', readonly=True)
    line_ids = fields.One2many(
        'microfinance.caisse.repayment.cascade.wizard.line', 'wizard_id',
        string='Échéances en retard concernées', compute='_compute_line_ids', readonly=True,
    )

    @api.depends('loan_id', 'amount')
    def _compute_line_ids(self):
        Payment = self.env['microfinance.loan.payment']
        for wiz in self:
            wiz.line_ids = [(5, 0, 0)]
            if not wiz.loan_id or not wiz.amount:
                continue
            info = Payment.analyze_repayment_situation(wiz.loan_id.id, wiz.amount)
            wiz.line_ids = [(0, 0, {
                'installment_id': line['id'],
                'sequence': line['sequence'],
                'due_date': line['due_date'],
                'residual_amount': line['residual_amount'],
                'allocated_amount': line['allocated'],
            }) for line in info['overdue_lines']]

    def action_confirm(self):
        self.ensure_one()
        self.env['microfinance.caisse.mouvement'].register_repayment_confirmed(
            self.session_id.id, self.loan_id.id, self.amount,
        )
        return {'type': 'ir.actions.act_window_close'}


class MicrofinanceCaisseRepaymentCascadeWizardLine(models.TransientModel):
    _name = 'microfinance.caisse.repayment.cascade.wizard.line'
    _description = "Ligne d'échéance — confirmation de cascade"
    _order = 'sequence, due_date'

    wizard_id = fields.Many2one(
        'microfinance.caisse.repayment.cascade.wizard', required=True, ondelete='cascade',
    )
    currency_id = fields.Many2one(related='wizard_id.currency_id')
    installment_id = fields.Many2one('microfinance.loan.installment', string='Échéance')
    sequence = fields.Integer(string='N°')
    due_date = fields.Date(string="Date d'échéance")
    residual_amount = fields.Monetary(string='Restant dû avant paiement')
    allocated_amount = fields.Monetary(string='Imputé par ce paiement')


class MicrofinanceCaisseRepaymentSurplusWizard(models.TransientModel):
    _name = 'microfinance.caisse.repayment.surplus.wizard'
    _description = "Surplus de remboursement — anticipation ou épargne"

    session_id = fields.Many2one('microfinance.caisse.session', required=True)
    loan_id = fields.Many2one('microfinance.loan', required=True)
    currency_id = fields.Many2one(related='loan_id.currency_id')
    savings_account_id = fields.Many2one(
        'microfinance.savings.account', string='Compte épargne lié',
        compute='_compute_savings_account_id', readonly=True,
    )

    @api.depends('loan_id')
    def _compute_savings_account_id(self):
        for wiz in self:
            wiz.savings_account_id = (
                wiz.loan_id._get_repayment_surplus_savings_account()
                if wiz.loan_id else False
            )

    amount = fields.Monetary(string='Montant remis par le client', readonly=True)
    overdue_total = fields.Monetary(
        string='Échéances en retard soldées', compute='_compute_amounts', readonly=True,
    )
    base_due = fields.Monetary(
        string='Imputé au crédit (dû immédiat)', compute='_compute_amounts', readonly=True,
    )
    surplus = fields.Monetary(
        string='Surplus à traiter', compute='_compute_amounts', readonly=True,
    )
    future_anticipable = fields.Boolean(compute='_compute_amounts', readonly=True)

    @api.depends('loan_id', 'amount')
    def _compute_amounts(self):
        Payment = self.env['microfinance.loan.payment']
        for wiz in self:
            info = (
                Payment.analyze_repayment_situation(wiz.loan_id.id, wiz.amount)
                if wiz.loan_id and wiz.amount else {}
            )
            wiz.overdue_total = info.get('overdue_total', 0.0)
            wiz.base_due = info.get('base_due', 0.0)
            wiz.surplus = info.get('surplus', 0.0)
            wiz.future_anticipable = info.get('future_anticipable', False)

    def action_anticipate(self):
        self.ensure_one()
        if not self.future_anticipable:
            raise UserError(_(
                "Aucune échéance future à anticiper : le surplus dépasse le capital restant "
                "dû du crédit. Versez-le sur l'épargne ou réduisez le montant."))
        # Montant plein imputé au crédit : la cascade _allocation_plan s'étend d'elle-même aux
        # échéances futures (comportement automatique déjà existant, ici confirmé).
        self.env['microfinance.caisse.mouvement'].register_repayment_confirmed(
            self.session_id.id, self.loan_id.id, self.amount,
        )
        return {'type': 'ir.actions.act_window_close'}

    def action_to_savings(self):
        self.ensure_one()
        if not self.savings_account_id:
            raise UserError(_(
                "Aucun compte épargne n'est lié à ce crédit : impossible d'y verser le "
                "surplus."))
        # Paiement crédit plafonné au dû immédiat, puis dépôt du surplus sur l'épargne liée
        # (deux microfinance.caisse.mouvement distincts, cf. décision actée).
        self.env['microfinance.caisse.mouvement'].register_repayment_confirmed(
            self.session_id.id, self.loan_id.id, self.base_due, deposit_amount=self.surplus,
        )
        return {'type': 'ir.actions.act_window_close'}
