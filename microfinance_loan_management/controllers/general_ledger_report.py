# -*- coding: utf-8 -*-
"""Grand livre interactif : mêmes règles d'accès, de société et de filtres que le Journal de banque
(base_accounting_kit.controllers.journal_ledger_report_controller), dont on réutilise les méthodes d'aide."""
import io

from odoo import http
from odoo.http import request
from odoo.tools.misc import xlsxwriter

from odoo.addons.base_accounting_kit.controllers.journal_ledger_report_controller import JournalLedgerReportController

from ..models.account_general_ledger_report import DISPLAY_ACCOUNTS, PAGE_SIZE, SORT_ORDERS

TITLE = 'Grand livre'
REPORT_REF = 'microfinance_loan_management.action_report_general_ledger_mf'


def _to_bool(value, default=True):
    if value in (None, ''):
        return default
    if isinstance(value, str):
        return value.lower() in ('1', 'true', 'on', 'yes')
    return bool(value)


class GeneralLedgerReportController(JournalLedgerReportController):

    def _filters(self, company_id, journal_ids, display_account, sortby, init_balance):
        """Société (limitée aux sociétés de l'utilisateur), journaux de cette société, options validées."""
        self._check_access()
        company = self._resolve_company(company_id)
        journals = self._get_company_journals(company, None)
        if isinstance(journal_ids, str):
            journal_ids = journal_ids.split(',') if journal_ids else []
        selected = self._sanitize_journal_ids(journal_ids, company, None)
        # tous les journaux cochés = pas de filtre (les écritures d'un journal archivé restent comptées)
        domain_ids = [] if set(selected) == set(journals.ids) else selected
        return {
            'company': company, 'journals': journals, 'selected': selected, 'journal_ids': domain_ids,
            'display_account': display_account if display_account in DISPLAY_ACCOUNTS else 'all',
            'sortby': sortby if sortby in SORT_ORDERS else 'sort_date',
            'init_balance': _to_bool(init_balance),
        }

    @http.route('/microfinance/general_ledger/data', type='json', auth='user')
    def general_ledger_data(self, date_from=None, date_to=None, target_move='posted', journal_ids=None, search=None,
                            company_id=None, display_account='all', sortby='sort_date', init_balance=True, **kwargs):
        f = self._filters(company_id, journal_ids, display_account, sortby, init_balance)
        if not date_from or not date_to:
            return {'success': False, 'error': 'Période (Du / Au) requise.'}
        company = f['company']
        data = request.env['account.general.ledger.report'].with_company(company).get_accounts(
            company, f['journal_ids'], date_from, date_to, target_move, f['display_account'], f['init_balance'], search)
        return {
            'success': True, 'title': TITLE, 'date_from': date_from, 'date_to': date_to,
            'currency': company.currency_id.symbol or '', 'company_name': company.name,
            'target_move_label': 'Toutes les écritures' if target_move == 'all' else 'Pièces comptabilisées',
            'journals_label': self._journal_label(f['selected'], f['journals']),
            'journals': [{'id': j.id, 'name': j.display_name or j.name} for j in f['journals']],
            'selected_journal_ids': f['selected'],
            'unposted_entries_exist': self._get_unposted_entries_exist(company, date_to, f['journal_ids']),
            'page_size': PAGE_SIZE, 'data': data,
        }

    @http.route('/microfinance/general_ledger/lines', type='json', auth='user')
    def general_ledger_lines(self, account_id=None, date_from=None, date_to=None, target_move='posted', journal_ids=None,
                             company_id=None, sortby='sort_date', init_balance=True, offset=0, **kwargs):
        f = self._filters(company_id, journal_ids, 'all', sortby, init_balance)
        company = f['company']
        return request.env['account.general.ledger.report'].with_company(company).get_lines(
            company, int(account_id or 0), f['journal_ids'], date_from, date_to, target_move, f['sortby'],
            f['init_balance'], offset, PAGE_SIZE)

    def _export_data(self, kw):
        f = self._filters(kw.get('company_id'), kw.get('journal_ids'), kw.get('display_account'), kw.get('sortby'),
                          kw.get('init_balance'))
        company, target_move = f['company'], kw.get('target_move') or 'posted'
        date_from, date_to = kw.get('date_from'), kw.get('date_to')
        model = request.env['account.general.ledger.report'].with_company(company)
        data = model.get_accounts(company, f['journal_ids'], date_from, date_to, target_move, f['display_account'],
                                  f['init_balance'], kw.get('search') or None)
        data['accounts'] = model.get_all_lines_for_export(
            company, data['accounts'], f['journal_ids'], date_from, date_to, target_move, f['sortby'], f['init_balance'])
        return f, data, target_move

    @http.route('/microfinance/general_ledger/pdf', type='http', auth='user')
    def general_ledger_pdf(self, **kw):
        f, data, target_move = self._export_data(kw)
        pdf_content, _type = request.env['ir.actions.report'].sudo()._render_qweb_pdf(REPORT_REF, [], data={
            'title': TITLE, 'company': f['company'], 'date_from': kw.get('date_from'), 'date_to': kw.get('date_to'),
            'target_move_label': 'Toutes les écritures' if target_move == 'all' else 'Pièces comptabilisées',
            'journals_label': self._journal_label(f['selected'], f['journals']),
            'init_balance': f['init_balance'], 'report_data': data})
        filename = 'Grand_livre_%s_%s.pdf' % (kw.get('date_from'), kw.get('date_to'))
        return request.make_response(pdf_content, headers=[
            ('Content-Type', 'application/pdf'), ('Content-Disposition', 'attachment; filename="%s"' % filename)])

    @http.route('/microfinance/general_ledger/xlsx', type='http', auth='user')
    def general_ledger_xlsx(self, **kw):
        f, data, target_move = self._export_data(kw)
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        bold = workbook.add_format({'bold': True})
        money = workbook.add_format({'num_format': '#,##0.00'})
        sheet = workbook.add_worksheet(TITLE)
        sheet.write_row(0, 0, [f['company'].name], bold)
        sheet.write_row(1, 0, ['Période du %s au %s' % (kw.get('date_from'), kw.get('date_to'))])
        sheet.write_row(2, 0, ['Pièces : %s' % ('Toutes les écritures' if target_move == 'all' else 'Pièces comptabilisées')])
        row = 4
        sheet.write_row(row, 0, ['Compte', 'Date', 'Pièce', 'Journal', 'Tiers', 'Libellé', 'Débit', 'Crédit', 'Solde'], bold)
        row += 1
        for account in data['accounts']:
            sheet.write_row(row, 0, ['%s %s' % (account['code'], account['name']), '', '', '', '', 'Solde initial'], bold)
            sheet.write_number(row, 8, account['opening'], money)
            row += 1
            for line in account['rows']:
                sheet.write_row(row, 0, ['', line['date'], line['piece'], line['journal'], line['partner_name'], line['label']])
                for col, key in ((6, 'debit'), (7, 'credit'), (8, 'balance')):
                    sheet.write_number(row, col, line[key], money)
                row += 1
            sheet.write_row(row, 0, ['', '', '', '', '', 'Total %s' % account['code']], bold)
            for col, key in ((6, 'debit'), (7, 'credit'), (8, 'closing')):
                sheet.write_number(row, col, account[key], bold)
            row += 1
        sheet.write_row(row, 0, ['', '', '', '', '', 'TOTAL GÉNÉRAL'], bold)
        sheet.write_number(row, 6, data['totals']['debit'], bold)
        sheet.write_number(row, 7, data['totals']['credit'], bold)
        workbook.close()
        output.seek(0)
        filename = 'Grand_livre_%s_%s.xlsx' % (kw.get('date_from'), kw.get('date_to'))
        return request.make_response(output.read(), headers=[
            ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
            ('Content-Disposition', 'attachment; filename="%s"' % filename)])
