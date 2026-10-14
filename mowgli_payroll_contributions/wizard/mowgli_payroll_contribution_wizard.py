# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class MowgliPayrollContributionWizard(models.TransientModel):
    _name = 'mowgli.payroll.contribution.wizard'
    _description = "Marquer des cotisations déclarées / versées"

    target_state = fields.Selection(
        [('declare', "Déclaré"), ('verse', "Versé")], string="Nouvel état",
        required=True, default='declare')
    reference = fields.Char(string="Référence de déclaration")
    payment_date = fields.Date(string="Date de versement")

    def action_apply(self):
        """Change l'état des lignes sélectionnées. Aucune écriture comptable
        (le versement comptable est un lot ultérieur)."""
        self.ensure_one()
        lines = self.env['mowgli.payroll.contribution'].browse(
            self.env.context.get('active_ids', [])).exists()
        if not lines:
            raise UserError(_("Aucune ligne sélectionnée."))
        if self.target_state == 'declare':
            if not self.reference:
                raise UserError(_("La référence de déclaration est obligatoire."))
            if lines.filtered(lambda l: l.state != 'a_verser'):
                raise UserError(_("Seules des lignes « À verser » peuvent être déclarées."))
            vals = {'state': 'declare', 'declaration_ref': self.reference}
        else:
            if not self.payment_date:
                raise UserError(_("La date de versement est obligatoire."))
            if lines.filtered(lambda l: l.state == 'verse'):
                raise UserError(_("Certaines lignes sont déjà versées."))
            vals = {'state': 'verse', 'payment_date': self.payment_date}
            if self.reference:
                vals['declaration_ref'] = self.reference
        lines.sudo().write(vals)
        return {'type': 'ir.actions.act_window_close'}
