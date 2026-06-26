# -*- coding: utf-8 -*-
from markupsafe import Markup, escape

from odoo import _, fields, models
from odoo.exceptions import UserError


class SofteamMgFinancialReportWizard(models.TransientModel):
    _name = 'softeam.l10n.mg.financial.report.wizard'
    _description = 'Financial report wizard for Madagascar Community reports'

    report_type = fields.Selection([
        ('balance_sheet', 'Bilan'),
        ('income_statement', 'Compte de résultat'),
        ('general_balance', 'Balance générale'),
        ('partner_balance', 'Balance auxiliaire'),
        ('general_ledger', 'Grand livre'),
        ('journals', 'Journaux'),
        ('vat_statement', 'Déclaration TVA'),
        ('account_analysis', 'Analyse des comptes'),
    ], required=True, default='balance_sheet')
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
    )
    date_from = fields.Date(required=True, default=lambda self: fields.Date.today().replace(month=1, day=1))
    date_to = fields.Date(required=True, default=fields.Date.today)
    journal_ids = fields.Many2many('account.journal', string='Journaux')
    target_move = fields.Selection([
        ('posted', 'Écritures comptabilisées'),
        ('all', 'Toutes les écritures'),
    ], default='posted', required=True)
    html_content = fields.Html(readonly=True, sanitize=False)

    def _get_options(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_('La date de début doit être antérieure ou égale à la date de fin.'))
        if self.company_id not in self.env.companies:
            raise UserError(_('Vous ne pouvez pas générer un rapport pour cette société.'))
        return {
            'report_type': self.report_type,
            'company_id': self.company_id.id,
            'date_from': fields.Date.to_string(self.date_from),
            'date_to': fields.Date.to_string(self.date_to),
            'journal_ids': self.journal_ids.ids,
            'target_move': self.target_move,
        }

    def _get_report_data(self):
        self.ensure_one()
        return self.env['softeam.l10n.mg.financial.report.service'].get_report_data(self._get_options())

    def _format_amount(self, amount):
        self.ensure_one()
        return self.env['ir.qweb.field.monetary'].value_to_html(
            amount or 0.0,
            {'display_currency': self.company_id.currency_id},
        )

    def _html_attrs(self, attrs):
        return ''.join(
            ' {}="{}"'.format(escape(key), escape(value))
            for key, value in attrs.items()
            if value not in (None, False)
        )

    def _html_tag(self, tag, content='', **attrs):
        return Markup('<{tag}{attrs}>{content}</{tag}>').format(
            tag=escape(tag),
            attrs=Markup(self._html_attrs(attrs)),
            content=Markup(content),
        )

    def _render_report_styles(self):
        return Markup(''.join([
            '<style>',
            '.o_mg_financial_report .o_mg_report_header {display:flex;justify-content:space-between;gap:16px;margin-bottom:16px;}',
            '.o_mg_financial_report h2 {margin:0;font-size:22px;font-weight:700;}',
            '.o_mg_financial_report .o_mg_report_meta {color:#64748b;font-size:13px;}',
            '.o_mg_financial_report table {width:100%;border-collapse:collapse;background:white;}',
            '.o_mg_financial_report th {background:#f8fafc;color:#475569;text-transform:uppercase;font-size:12px;}',
            '.o_mg_financial_report th,.o_mg_financial_report td {padding:8px;border-bottom:1px solid #e2e8f0;}',
            '.o_mg_financial_report .o_mg_report_section td {background:#eef2ff;font-weight:700;color:#1e293b;}',
            '.o_mg_financial_report .o_mg_report_total td {font-weight:700;border-top:2px solid #94a3b8;}',
            '</style>',
        ]))

    def _render_report_row(self, line):
        classes = ['o_mg_report_line']
        if line.get('is_section'):
            classes.append('o_mg_report_section')
        if line.get('is_total'):
            classes.append('o_mg_report_total')
        indent = max(int(line.get('level', 0)), 0) * 18
        partner = line.get('partner') or ''
        label = escape(line.get('name') or '')
        if partner:
            label = Markup('{}<br/>{}').format(
                label,
                self._html_tag('small', escape(partner), **{'class': 'text-muted'}),
            )
        cells = [
            self._html_tag('td', label, style='padding-left:{}px'.format(indent)),
            self._html_tag('td', self._format_amount(line.get('debit')), **{'class': 'text-end'}),
            self._html_tag('td', self._format_amount(line.get('credit')), **{'class': 'text-end'}),
            self._html_tag('td', self._format_amount(line.get('balance')), **{'class': 'text-end'}),
        ]
        return self._html_tag('tr', Markup('').join(cells), **{'class': ' '.join(classes)})

    def _render_html(self, data):
        self.ensure_one()
        options = data['options']
        move_label = _('Comptabilisées') if options['target_move'] == 'posted' else _('Toutes')
        period = '{} - {}'.format(escape(options['date_from']), escape(options['date_to']))
        header = self._html_tag(
            'div',
            Markup('').join([
                self._html_tag(
                    'div',
                    Markup('').join([
                        self._html_tag('h2', escape(data['title'])),
                        self._html_tag('div', escape(data['company'].display_name), **{'class': 'o_mg_report_meta'}),
                    ]),
                ),
                self._html_tag('div', Markup('{}<br/>{}').format(period, escape(move_label)), **{'class': 'o_mg_report_meta text-end'}),
            ]),
            **{'class': 'o_mg_report_header'}
        )
        table_header = Markup(
            '<thead><tr>'
            '<th>Libellé</th>'
            '<th class="text-end">Débit</th>'
            '<th class="text-end">Crédit</th>'
            '<th class="text-end">Solde</th>'
            '</tr></thead>'
        )
        rows = Markup('').join(self._render_report_row(line) for line in data['lines'])
        table = self._html_tag('table', Markup('').join([table_header, self._html_tag('tbody', rows)]), **{'class': 'table table-sm'})
        return self._html_tag(
            'div',
            Markup('').join([self._render_report_styles(), header, table]),
            **{'class': 'o_mg_financial_report'},
        )

    def action_generate_html(self):
        self.ensure_one()
        data = self._get_report_data()
        self.html_content = self._render_html(data)
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_print_pdf(self):
        self.ensure_one()
        if not self.html_content:
            self.html_content = self._render_html(self._get_report_data())
        return self.env.ref('softeam_l10n_mg_reports.action_report_mg_financial_pdf').report_action(self)

    def action_export_xlsx(self):
        self.ensure_one()
        self.env['softeam.l10n.mg.financial.report.service']._prepare_xlsx_data(self._get_options())
        raise UserError(_('Export Excel prévu par l’architecture, non implémenté dans cette version Community.'))
