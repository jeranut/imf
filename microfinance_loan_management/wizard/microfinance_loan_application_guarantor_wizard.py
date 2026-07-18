# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MicrofinanceLoanApplicationGuarantorWizardLine(models.TransientModel):
    """Ligne garant (wizard) — mirroir de microfinance.loan.application.guarantor.line."""
    _name = 'microfinance.loan.application.guarantor.wizard.line'
    _description = 'Garant (wizard)'

    wizard_id = fields.Many2one(
        'microfinance.loan.application.guarantor.wizard', required=True, ondelete='cascade')
    partner_id = fields.Many2one('res.partner', string='Garant (fiche contact)')
    name = fields.Char(string='Nom', required=True)
    id_card_number = fields.Char(string='N° CIN')
    address = fields.Char(string='Adresse')
    phone = fields.Char(string='Téléphone')
    profession = fields.Char(string='Profession')
    relationship_to_borrower = fields.Char(string="Lien avec l'emprunteur")


class MicrofinanceLoanApplicationGuarantorWizard(models.TransientModel):
    """Wizard popup — Section II : Identification du garant."""
    _name = 'microfinance.loan.application.guarantor.wizard'
    _description = 'Modifier les garants'

    application_id = fields.Many2one('microfinance.loan.application', required=True)
    line_ids = fields.One2many(
        'microfinance.loan.application.guarantor.wizard.line', 'wizard_id', string='Garants')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        application = self.env['microfinance.loan.application'].browse(
            self.env.context.get('default_application_id')
        )
        if application and 'line_ids' in fields_list:
            res['line_ids'] = [(0, 0, {
                'partner_id': line.partner_id.id,
                'name': line.name,
                'id_card_number': line.id_card_number,
                'address': line.address,
                'phone': line.phone,
                'profession': line.profession,
                'relationship_to_borrower': line.relationship_to_borrower,
            }) for line in application.guarantor_line_ids]
        return res

    def action_validate(self):
        self.ensure_one()
        self.application_id.guarantor_line_ids.unlink()
        self.application_id.write({
            'guarantor_line_ids': [(0, 0, {
                'partner_id': line.partner_id.id,
                'name': line.name,
                'id_card_number': line.id_card_number,
                'address': line.address,
                'phone': line.phone,
                'profession': line.profession,
                'relationship_to_borrower': line.relationship_to_borrower,
            }) for line in self.line_ids],
        })
        return {'type': 'ir.actions.act_window_close'}
