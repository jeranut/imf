# -*- coding: utf-8 -*-
from odoo import _, models, fields


class AccountMoveLineWriteoffWizardDisbursement(models.TransientModel):
    """Extension du wizard générique account.move.line.writeoff.wizard
    (base_accounting_kit) pour la compensation d'un décaissement crédit réglé par chèque.
    Dépendance dans le sens attendu : ce module dépend de base_accounting_kit, jamais l'inverse
    — base_accounting_kit ne référence rien ici."""
    _inherit = "account.move.line.writeoff.wizard"

    loan_id = fields.Many2one(
        'microfinance.loan', string='Crédit', copy=False,
        default=lambda self: self._default_loan_id(),
        help="Rempli automatiquement si move_line_id correspond à la ligne d'attente d'un "
             "décaissement chèque en cours (recherche sur microfinance.loan.disbursement_move_id "
             "= move_line_id.move_id). Vide dans tout autre usage du wizard générique.")

    def _default_loan_id(self):
        move_line_id = self.env.context.get('default_move_line_id')
        if not move_line_id:
            return False
        move_line = self.env['account.move.line'].browse(move_line_id)
        loan = self.env['microfinance.loan'].search(
            [('disbursement_move_id', '=', move_line.move_id.id)], limit=1)
        return loan.id

    def _post_reconcile(self, move):
        super()._post_reconcile(move)
        if self.loan_id:
            self.loan_id.write({
                'disbursement_cheque_state': 'compense',
                'disbursement_clearing_move_id': move.id,
            })
            self.loan_id.message_post(
                body=_('Chèque de décaissement compensé. Écriture : %s') % move.name)
