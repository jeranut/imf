# -*- coding: utf-8 -*-
from odoo import fields, models


class MicrofinanceLoanContractSignatureWizard(models.TransientModel):
    _name = 'microfinance.loan.contract.signature.wizard'
    _description = 'Assistant téléversement du contrat signé'

    loan_id = fields.Many2one('microfinance.loan', string='Crédit', required=True)
    signature_date = fields.Date(
        string='Date de signature du contrat', required=True, default=fields.Date.context_today,
        help="Pré-remplie à la date du jour, librement modifiable avant confirmation. "
             "Définitivement verrouillée sur le crédit une fois ce wizard confirmé.",
    )
    signed_contract = fields.Binary(string='Contrat signé', required=True)
    signed_contract_filename = fields.Char(string='Nom du fichier')

    def action_confirm(self):
        """Écrit les 3 valeurs en un seul write() puis ferme le wizard. Pas de vérification
        préalable ici : microfinance.loan.write() (_check_contract_signature_locked()) lève
        déjà une UserError explicite si contract_signature_date est déjà renseigné - inutile
        de dupliquer ce contrôle, le bouton qui ouvre ce wizard est de toute façon invisible
        dès que le crédit est signé."""
        self.ensure_one()
        self.loan_id.write({
            'signed_contract': self.signed_contract,
            'signed_contract_filename': self.signed_contract_filename,
            'contract_signature_date': self.signature_date,
        })
        return {'type': 'ir.actions.act_window_close'}
