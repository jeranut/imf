from odoo import models, fields, _
from odoo.exceptions import UserError


class AccountPaymentRegister(models.TransientModel):
    _inherit = "account.payment.register"

    def action_create_payments(self):
        if self.payment_type == "outbound" and self.partner_type == "supplier" and self.journal_id.type == "cash":
            payment_date = self.payment_date or fields.Date.context_today(self)
            balance = self.env['account.daily.balance']._get_current_for_payment(
                self.company_id.id, balance_date=payment_date
            )
            projected_new_balance = balance.nouveau_solde - self.amount
            if projected_new_balance < 0:
                raise UserError(_(
                    f"Paiement CASH impossible !\n\n"
                    f"Solde disponible : {balance.nouveau_solde:,.2f} {self.currency_id.symbol}\n"
                    f"Montant du paiement : {self.amount:,.2f} {self.currency_id.symbol}\n\n"
                    f"Le solde deviendrait négatif ({projected_new_balance:,.2f} {self.currency_id.symbol})"
                ))
        return super(AccountPaymentRegister, self).action_create_payments()
