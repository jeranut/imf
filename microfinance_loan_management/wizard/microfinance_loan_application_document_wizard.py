# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MicrofinanceLoanApplicationDocumentWizardLine(models.TransientModel):
    """Ligne document (wizard) — mirroir de microfinance.loan.application.document.line."""
    _name = 'microfinance.loan.application.document.wizard.line'
    _description = 'Document administratif fourni (wizard)'

    wizard_id = fields.Many2one(
        'microfinance.loan.application.document.wizard', required=True, ondelete='cascade')
    name = fields.Char(string='Document', required=True)
    is_provided = fields.Boolean(string='Fourni')
    comment = fields.Char(string='Commentaire')


class MicrofinanceLoanApplicationDocumentWizard(models.TransientModel):
    """Wizard popup — Section III : Dossiers administratifs fournis."""
    _name = 'microfinance.loan.application.document.wizard'
    _description = 'Modifier les documents administratifs fournis'

    application_id = fields.Many2one('microfinance.loan.application', required=True)
    line_ids = fields.One2many(
        'microfinance.loan.application.document.wizard.line', 'wizard_id', string='Documents')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        application = self.env['microfinance.loan.application'].browse(
            self.env.context.get('default_application_id')
        )
        if application and 'line_ids' in fields_list:
            res['line_ids'] = [(0, 0, {
                'name': line.name,
                'is_provided': line.is_provided,
                'comment': line.comment,
            }) for line in application.document_line_ids]
        return res

    def action_validate(self):
        self.ensure_one()
        self.application_id.document_line_ids.unlink()
        self.application_id.write({
            'document_line_ids': [(0, 0, {
                'name': line.name,
                'is_provided': line.is_provided,
                'comment': line.comment,
            }) for line in self.line_ids],
        })
        return {'type': 'ir.actions.act_window_close'}
