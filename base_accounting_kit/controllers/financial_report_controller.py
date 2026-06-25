# -*- coding: utf-8 -*-
from odoo import http, fields
from odoo.http import request


class FinancialReportController(http.Controller):

    @http.route('/base_accounting_kit/financial_report/data', type='json', auth='user')
    def financial_report_data(self, report_name='Balance Sheet', date_to=None, target_move='posted', **kwargs):
        company = request.env.company
        date_to = date_to or fields.Date.context_today(request.env.user)

        account_report = request.env['account.financial.report'].sudo().search([
            ('name', 'ilike', report_name)
        ], limit=1)

        if not account_report:
            return {
                'success': False,
                'error': 'Rapport comptable introuvable : %s' % report_name,
                'lines': [],
            }

        wizard = request.env['financial.report'].sudo().create({
            'account_report_id': account_report.id,
            'date_to': date_to,
            'target_move': target_move,
            'debit_credit': False,
            'company_id': company.id,
            'view_format': 'vertical',
        })

        data = {
            'date_from': False,
            'date_to': date_to,
            'enable_filter': False,
            'debit_credit': False,
            'account_report_id': [account_report.id, account_report.name],
            'target_move': target_move,
            'view_format': 'vertical',
            'company_id': [company.id, company.name],
        }

        used_context = wizard._build_contexts({'form': data})
        data['used_context'] = dict(used_context, lang=request.env.context.get('lang') or 'fr_FR')

        lines = wizard.get_account_lines(data)

        def level(line):
            try:
                return int(line.get('level') or 1)
            except Exception:
                return 1

        clean_lines = []
        for line in lines:
            clean_lines.append({
                'id': line.get('id') or line.get('a_id') or str(line.get('name')),
                'parent': line.get('parent'),
                'name': line.get('name'),
                'balance': round(line.get('balance') or 0.0, 2),
                'type': line.get('type'),
                'level': level(line),
                'account_type': line.get('account_type'),
            })

        return {
            'success': True,
            'report_name': account_report.name,
            'date_to': str(date_to),
            'currency': company.currency_id.symbol or '',
            'company_name': company.name,
            'lines': clean_lines,
        }