# -*- coding: utf-8 -*-
from odoo import models


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    def _get_batch_journal(self, batch_result):
        """Un paiement fournisseur (sortant) propose par défaut le journal bancaire d'exploitation
        de la société (res.company.microfinance_operating_journal_id) quand il est disponible ;
        sans cela Odoo prend le premier journal bancaire/caisse venu (ici un journal de crédit ou
        de caisse). Le choix reste libre dans l'assistant."""
        journal = super()._get_batch_journal(batch_result)
        payment_values = batch_result['payment_values']
        if payment_values.get('payment_type') == 'outbound' and payment_values.get('partner_type') == 'supplier':
            company = min(batch_result['lines'].company_id, key=lambda c: len(c.parent_ids))
            operating = company.microfinance_operating_journal_id
            if operating and operating in self.available_journal_ids:
                return operating
        return journal
