# -*- coding: utf-8 -*-
"""Balance générale interactive : mêmes règles d'accès, de société et de filtres que le Grand livre (dont on hérite
les aides), sans sudo sur le calcul."""
import io

from odoo import http
from odoo.http import request
from odoo.tools.misc import xlsxwriter

from .general_ledger_report import GeneralLedgerReportController

TITLE = 'Balance générale'
REPORT_REF = 'microfinance_loan_management.action_report_trial_balance_mf'
COLUMNS = (('opening_debit', 'Solde initial débit'), ('opening_credit', 'Solde initial crédit'),
           ('debit', 'Mouvements débit'), ('credit', 'Mouvements crédit'),
           ('closing_debit', 'Solde final débit'), ('closing_credit', 'Solde final crédit'))


class TrialBalanceReportController(GeneralLedgerReportController):

    def _balance(self, kw):
        f = self._filters(kw.get('company_id'), kw.get('journal_ids'), kw.get('display_account'), None,
                          kw.get('init_balance'))
        company, target_move = f['company'], kw.get('target_move') or 'posted'
        data = request.env['account.trial.balance.report'].with_company(company).get_balance(
            company, f['journal_ids'], kw.get('date_from'), kw.get('date_to'), target_move, f['display_account'],
            f['init_balance'], kw.get('search') or None)
        return f, company, target_move, data

    @http.route('/microfinance/trial_balance/data', type='json', auth='user')
    def trial_balance_data(self, date_from=None, date_to=None, target_move='posted', journal_ids=None, search=None,
                           company_id=None, display_account='all', init_balance=True, **kwargs):
        if not date_from or not date_to:
            self._check_access()
            return {'success': False, 'error': 'Période (Du / Au) requise.'}
        f, company, target_move, data = self._balance(dict(
            date_from=date_from, date_to=date_to, target_move=target_move, journal_ids=journal_ids, search=search,
            company_id=company_id, display_account=display_account, init_balance=init_balance))
        return {
            'success': True, 'title': TITLE, 'date_from': date_from, 'date_to': date_to,
            'currency': company.currency_id.symbol or '', 'company_name': company.name,
            'target_move_label': 'Toutes les écritures' if target_move == 'all' else 'Pièces comptabilisées',
            'journals_label': self._journal_label(f['selected'], f['journals']),
            'journals': [{'id': j.id, 'name': j.display_name or j.name} for j in f['journals']],
            'selected_journal_ids': f['selected'],
            'unposted_entries_exist': self._get_unposted_entries_exist(company, date_to, f['journal_ids']),
            'data': data,
        }

    @http.route('/microfinance/trial_balance/pdf', type='http', auth='user')
    def trial_balance_pdf(self, **kw):
        f, company, target_move, data = self._balance(kw)
        pdf_content, _type = request.env['ir.actions.report'].sudo()._render_qweb_pdf(REPORT_REF, [], data={
            'title': TITLE, 'company': company, 'date_from': kw.get('date_from'), 'date_to': kw.get('date_to'),
            'target_move_label': 'Toutes les écritures' if target_move == 'all' else 'Pièces comptabilisées',
            'journals_label': self._journal_label(f['selected'], f['journals']),
            'init_balance': f['init_balance'], 'report_data': data})
        filename = 'Balance_generale_%s_%s.pdf' % (kw.get('date_from'), kw.get('date_to'))
        return request.make_response(pdf_content, headers=[
            ('Content-Type', 'application/pdf'), ('Content-Disposition', 'attachment; filename="%s"' % filename)])

    @http.route('/microfinance/trial_balance/xlsx', type='http', auth='user')
    def trial_balance_xlsx(self, **kw):
        f, company, target_move, data = self._balance(kw)
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        bold = workbook.add_format({'bold': True})
        money = workbook.add_format({'num_format': '#,##0.00'})
        money_bold = workbook.add_format({'num_format': '#,##0.00', 'bold': True})
        sheet = workbook.add_worksheet(TITLE)
        sheet.write_row(0, 0, [company.name], bold)
        sheet.write_row(1, 0, ['Période du %s au %s' % (kw.get('date_from'), kw.get('date_to'))])
        sheet.write_row(2, 0, ['Pièces : %s' % ('Toutes les écritures' if target_move == 'all' else 'Pièces comptabilisées')])
        row = 4
        sheet.write_row(row, 0, ['Compte'] + [label for _key, label in COLUMNS], bold)
        row += 1
        for group in data['classes']:
            for account in group['accounts']:
                sheet.write(row, 0, '%s %s' % (account['code'], account['name']))
                for col, (key, _label) in enumerate(COLUMNS, start=1):
                    sheet.write_number(row, col, account[key], money)
                row += 1
            sheet.write(row, 0, 'Sous-total %s' % group['label'], bold)
            for col, (key, _label) in enumerate(COLUMNS, start=1):
                sheet.write_number(row, col, group[key], money_bold)
            row += 1
        sheet.write(row, 0, 'TOTAL GÉNÉRAL', bold)
        for col, (key, _label) in enumerate(COLUMNS, start=1):
            sheet.write_number(row, col, data['totals'][key], money_bold)
        workbook.close()
        output.seek(0)
        filename = 'Balance_generale_%s_%s.xlsx' % (kw.get('date_from'), kw.get('date_to'))
        return request.make_response(output.read(), headers=[
            ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
            ('Content-Disposition', 'attachment; filename="%s"' % filename)])
