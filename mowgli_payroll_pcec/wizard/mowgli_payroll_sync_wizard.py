# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import AccessError

MANAGER_GROUP = 'hr_payroll_community.group_hr_payroll_community_manager'


class _RollbackDryRun(Exception):
    """Signal interne : annule la transaction du savepoint sans remonter
    d'erreur à l'utilisateur (utilisé pour le mode Aperçu)."""


class MowgliPayrollSyncWizard(models.TransientModel):
    _name = 'mowgli.payroll.sync.wizard'
    _description = "Synchronisation de la structure de paie vers les agences"

    structure_id = fields.Many2one(
        'hr.payroll.structure', string='Structure source', required=True,
        readonly=True)
    target_company_ids = fields.Many2many(
        'res.company', string='Sociétés cibles')
    create_journal_if_missing = fields.Boolean(
        string='Créer le journal de paie manquant', default=False,
        help="Si une société cible n'a pas de journal de paie, en crée un "
             "(nom « Salaires », type général, code SAL) seulement s'il "
             "manque vraiment. Ne modifie jamais un journal existant ; si "
             "le code SAL est déjà pris, le signale sans l'écraser.")
    state = fields.Selection(
        [('draft', 'Paramètres'), ('report', 'Rapport')], default='draft')
    report_text = fields.Text(string='Rapport', readonly=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        structure_id = self.env.context.get('default_structure_id')
        if structure_id and 'target_company_ids' in fields_list:
            structure = self.env['hr.payroll.structure'].browse(
                structure_id)
            companies = self.env['res.company'].search(
                [('id', '!=', structure.company_id.id)])
            res['target_company_ids'] = [(6, 0, companies.ids)]
        return res

    def _check_manager(self):
        if not self.env.user.has_group(MANAGER_GROUP):
            raise AccessError(_(
                "Seuls les utilisateurs du groupe Paie / Manager peuvent "
                "synchroniser la structure de paie vers les agences."))

    def action_preview(self):
        self._check_manager()
        self.ensure_one()
        reports = self._run_sync(apply=False)
        self.write({
            'state': 'report',
            'report_text': self._format_report(reports, apply=False),
        })
        return self._reopen()

    def action_apply(self):
        self._check_manager()
        self.ensure_one()
        reports = self._run_sync(apply=True)
        report_text = self._format_report(reports, apply=True)
        self.write({'state': 'report', 'report_text': report_text})
        self.structure_id.message_post(body=_(
            "Synchronisation vers les agences lancée par %(user)s.<br/>"
            "Sociétés : %(companies)s<br/><pre>%(report)s</pre>") % {
                'user': self.env.user.name,
                'companies': ', '.join(
                    self.target_company_ids.mapped('name')),
                'report': report_text,
            })
        return self._reopen()

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _run_sync(self, apply):
        self._check_manager()
        structure = self.structure_id
        reports = []
        try:
            with self.env.cr.savepoint():
                for company in self.target_company_ids:
                    reports.append(structure._mowgli_sync_to_company(
                        company,
                        create_journal=self.create_journal_if_missing))
                if not apply:
                    raise _RollbackDryRun()
        except _RollbackDryRun:
            pass
        return reports

    def _format_report(self, reports, apply):
        lines = [_("Mode : %s") % (
            _("Application réelle") if apply else
            _("Aperçu (dry-run, aucune donnée modifiée)"))]
        for r in reports:
            lines.append("")
            lines.append("== %s ==" % r['company_name'])
            lines.append(_("Structure : %s") % r['structure']['status'])
            if r['structure'].get('parent_warning'):
                lines.append(
                    _("  Avertissement : %s") % r['structure']['parent_warning'])
            for rl in r['rules']:
                lines.append(_("  Règle %s : %s") % (rl['code'], rl['status']))
            for w in r['accounts_missing']:
                lines.append(
                    _("  Avertissement compte (%s) : %s")
                    % (w['rule_code'], w['message']))
            if r['extra_rules']:
                lines.append(
                    _("  Règles en trop chez la cible (conservées) : %s")
                    % ', '.join(r['extra_rules']))
            journal_action = r.get('journal_action')
            if journal_action:
                if journal_action['status'] == 'created':
                    lines.append(_(
                        "  Journal de paie créé : Salaires (SAL)."))
                elif journal_action['status'] == 'code_taken':
                    lines.append("  " + journal_action['message'])
            if r['journal_missing']:
                lines.append(_(
                    "  Avertissement : aucun journal de paie configuré "
                    "pour cette société."))
            for c in r['other_structure_contracts']:
                lines.append(
                    _("  Contrat sur une autre structure : %(contract)s "
                      "(%(employee)s) -> %(structure)s") % {
                          'contract': c['contract'],
                          'employee': c['employee'],
                          'structure': c['structure']})
        return '\n'.join(lines)
