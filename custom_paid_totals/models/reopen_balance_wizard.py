# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class ReopenBalanceWizard(models.TransientModel):
    _name = 'reopen.balance.wizard'
    _description = "Wizard de réouverture d'une balance clôturée (Cas B : mouvement existant)"

    balance_id = fields.Many2one('account.daily.balance', string='Balance caisse')
    balance_mobile_id = fields.Many2one('account.daily.balance.mobile', string='Balance Mobile Money')
    closing_move_id = fields.Many2one(
        'account.move', string='Écriture de clôture existante',
        compute='_compute_from_balance', readonly=True,
    )
    closing_move_date = fields.Date(string='Date du mouvement', compute='_compute_from_balance', readonly=True)
    closing_move_amount = fields.Monetary(string='Montant du mouvement', compute='_compute_from_balance', readonly=True)
    currency_id = fields.Many2one('res.currency', compute='_compute_from_balance', readonly=True)
    reason = fields.Text(string='Motif de la réouverture', required=True)

    @api.depends('balance_id.closing_move_id', 'balance_mobile_id.closing_move_id')
    def _compute_from_balance(self):
        for wizard in self:
            target = wizard.balance_id or wizard.balance_mobile_id
            move = target.closing_move_id
            wizard.closing_move_id = move
            wizard.closing_move_date = move.date
            wizard.currency_id = move.company_id.currency_id
            wizard.closing_move_amount = sum(move.line_ids.filtered(lambda l: l.debit > 0).mapped('debit'))

    def _target(self):
        self.ensure_one()
        target = self.balance_id or self.balance_mobile_id
        if not target:
            raise UserError(_("Aucune balance liée au wizard."))
        return target

    def action_confirm(self):
        self.ensure_one()
        target = self._target()

        if not self.reason or not self.reason.strip():
            raise UserError(_("Veuillez indiquer le motif de la réouverture."))

        target._check_reouvrir_access()

        if self.balance_id:
            self.balance_id._reouvrir_avec_mouvement(self.reason)
        else:
            self.balance_mobile_id._reouvrir_avec_mouvement_mobile(self.reason)

        return {'type': 'ir.actions.act_window_close'}
