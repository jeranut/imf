# -*- coding: utf-8 -*-
import base64
import csv
import io

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

MANAGER_GROUP = 'hr_payroll_community.group_hr_payroll_community_manager'
CSV_FIELDS = ('societe', 'regle', 'role', 'code', 'compte_id', 'statut')


class MowgliPayrollSyncWizard(models.TransientModel):
    _name = 'mowgli.payroll.sync.wizard'
    _description = "Compléter les comptes de paie par société"

    structure_id = fields.Many2one(
        'hr.payroll.structure', string='Structure', readonly=True)
    target_company_ids = fields.Many2many(
        'res.company', string='Sociétés')
    state = fields.Selection(
        [('draft', 'Paramètres'), ('report', 'Rapport')], default='draft')
    applied = fields.Boolean(readonly=True)
    report_text = fields.Text(string='Rapport', readonly=True)
    csv_file = fields.Binary(string='Fichier CSV', readonly=True)
    csv_filename = fields.Char(readonly=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'target_company_ids' in fields_list:
            res['target_company_ids'] = [
                (6, 0, self.env.user.company_ids.ids)]
        if 'structure_id' in fields_list and not res.get('structure_id'):
            structure = self.env['hr.payroll.structure'].search(
                [('code', '=', 'BASE')], limit=1)
            res['structure_id'] = structure.id
        return res

    def _check_manager(self):
        if not self.env.user.has_group(MANAGER_GROUP):
            raise AccessError(_(
                "Seuls les utilisateurs du groupe Paie / Manager peuvent "
                "compléter les comptes de paie par société."))

    def action_preview(self):
        return self._run(apply=False)

    def action_apply(self):
        return self._run(apply=True)

    def _run(self, apply):
        self._check_manager()
        self.ensure_one()
        rules = self.structure_id.sudo().rule_ids
        rows = self.env['hr.salary.rule'].sudo()._mowgli_complete_company_accounts(
            rules, self.target_company_ids.sudo(), apply=apply)
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS, delimiter=';')
        writer.writeheader()
        writer.writerows(rows)
        counts = {}
        for row in rows:
            counts[row['statut']] = counts.get(row['statut'], 0) + 1
        lines = [_("Mode : %s") % (
            _("Application réelle") if apply else
            _("Aperçu (dry-run, aucune donnée modifiée)"))]
        lines += ["%s : %d" % (status, n) for status, n in sorted(counts.items())]
        for company in self.target_company_ids.filtered(
                lambda c: not c.chart_template):
            lines.append(_(
                "%s : société sans plan comptable, refusée. Installez "
                "d'abord le plan PCEC (Paramètres > Comptabilité).")
                % company.name)
        self.write({
            'state': 'report', 'applied': apply,
            'report_text': '\n'.join(lines),
            'csv_file': base64.b64encode(buffer.getvalue().encode('utf-8')),
            'csv_filename': 'comptes_paie_par_societe_%s.csv' % (
                'reel' if apply else 'apercu'),
        })
        if apply and self.structure_id:
            self.structure_id.message_post(body=_(
                "Comptes de paie complétés par %(user)s pour : "
                "%(companies)s.") % {
                    'user': self.env.user.name,
                    'companies': ', '.join(self.target_company_ids.mapped('name'))})
        return {
            'type': 'ir.actions.act_window', 'res_model': self._name,
            'res_id': self.id, 'view_mode': 'form', 'target': 'new',
        }
