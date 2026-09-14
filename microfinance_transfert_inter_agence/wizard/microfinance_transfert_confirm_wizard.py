# -*- coding: utf-8 -*-
"""Assistant de confirmation d'un remboursement crédit encaissé en transfert
inter-agences (sous-lot D).

Ouvert par le guichet OWL via
microfinance.transfert.remboursement.get_transfert_confirm_action() quand le
caissier a sélectionné un client d'une autre agence + un de ses crédits + un
montant. Purement RÉCAPITULATIF : le crédit, l'agence du client et le solde sont
passés en clair dans le contexte (default_*), l'assistant n'accède donc à aucune
donnée cross-agence par lui-même. La comptabilisation (étape 1) est déléguée à
register_transfert, où le sudo reste circonscrit.
"""
from odoo import _, api, fields, models


class MicrofinanceTransfertConfirmWizard(models.TransientModel):
    _name = 'microfinance.transfert.confirm.wizard'
    _description = "Confirmation — transfert de remboursement inter-agences"

    session_id = fields.Many2one('microfinance.caisse.session', required=True)
    # loan_id : uniquement pour transporter l'id jusqu'à action_confirm. Le formulaire
    # n'affiche que les champs « en clair » ci-dessous — aucune lecture du crédit
    # (agence destination, invisible au caissier) n'est faite par l'assistant.
    loan_id = fields.Many2one('microfinance.loan', required=True)
    currency_id = fields.Many2one(related='session_id.currency_id')
    amount = fields.Monetary(string='Montant remis par le client', required=True)

    partner_name = fields.Char(string='Client', readonly=True)
    partner_agency = fields.Char(string='Agence propriétaire du crédit', readonly=True)
    loan_name = fields.Char(string='Crédit', readonly=True)
    loan_balance = fields.Monetary(string='Solde restant du crédit', readonly=True)

    @api.onchange('amount', 'loan_balance')
    def _onchange_amount_warn_surpaiement(self):
        if self.amount and self.loan_balance and self.amount > self.loan_balance + 0.01:
            return {'warning': {
                'title': _("Surpaiement"),
                'message': _(
                    "Le montant remis (%(a).2f) dépasse le solde restant du crédit "
                    "(%(b).2f). L'encaissement sera refusé.") % {
                    'a': self.amount, 'b': self.loan_balance},
            }}

    def action_confirm(self):
        self.ensure_one()
        self.env['microfinance.transfert.remboursement'].register_transfert(
            self.session_id.id, self.loan_id.id, self.amount)
        return {'type': 'ir.actions.act_window_close'}
