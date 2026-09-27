# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..models.microfinance_loan_payment import default_payment_amount_and_journal


class MicrofinanceLoanPaymentWizard(models.TransientModel):
    _name = 'microfinance.loan.payment.wizard'
    _description = 'Assistant remboursement crédit'

    loan_id = fields.Many2one('microfinance.loan', string='Crédit', required=True)
    amount = fields.Monetary(
        string='Montant', required=True,
        help="Préempli avec le montant dû (échéances en retard cumulées, ou à défaut la "
             "prochaine échéance) — librement modifiable pour un remboursement partiel ou "
             "anticipé.",
    )
    payment_date = fields.Date(string='Date de remboursement', default=fields.Date.context_today, required=True)
    company_id = fields.Many2one(related='loan_id.company_id', readonly=True)
    journal_id = fields.Many2one(
        'account.journal', string='Journal', required=True,
        domain="[('type', 'in', ('bank','cash')), ('company_id', '=', company_id)]",
    )
    currency_id = fields.Many2one(related='loan_id.currency_id', readonly=True)
    note = fields.Text(string='Note')
    post_now = fields.Boolean(string='Comptabiliser maintenant', default=True)

    @api.onchange('loan_id')
    def _onchange_loan_id(self):
        for wizard in self:
            if not wizard.loan_id:
                continue
            amount, journal = default_payment_amount_and_journal(wizard.loan_id)
            if amount:
                wizard.amount = amount
            if journal:
                wizard.journal_id = journal

    def action_create_payment(self):
        """Bloqué en défense en profondeur (AUDIT_anomalies_ampitatafika_ambanidia_20260921.md
        §1), en plus du retrait du bouton d'ouverture côté fiche crédit
        (action_open_payment_wizard) : ce wizard postait un microfinance.loan.payment sans
        jamais créer de microfinance.caisse.mouvement ni exiger de session de caisse ouverte,
        rendant le remboursement invisible du solde/ticket de session. Le modèle wizard reste en
        place (Form() encore utilisé par tests/test_payment_prefill.py pour vérifier le
        préremplissage montant/journal), seule sa validation est neutralisée."""
        self.ensure_one()
        raise UserError(_(
            "Un remboursement de crédit ne peut plus être enregistré depuis cet assistant : "
            "utilisez le Guichet Caisse (session de caisse ouverte), seul point d'entrée qui "
            "trace l'opération dans le solde et le ticket de la session."))
