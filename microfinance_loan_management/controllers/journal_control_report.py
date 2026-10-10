# -*- coding: utf-8 -*-
"""Contrôle des journaux interactif : mêmes règles d'accès, de société et de filtres que le Grand livre (dont on hérite
les aides), sans sudo sur le calcul."""
import io

from odoo import http
from odoo.http import request
from odoo.tools.misc import xlsxwriter

from ..models.account_journal_control_report import ANOMALY_KINDS, MOVE_ORDERS, PAGE_SIZE
from .general_ledger_report import GeneralLedgerReportController

TITLE = 'Contrôle des journaux'
REPORT_REF = 'microfinance_loan_management.action_report_journal_control_mf'
KIND_LABELS = {'unbalanced': 'Pièces déséquilibrées', 'draft': 'Pièces en brouillon', 'cancel': 'Pièces annulées'}


class JournalControlReportController(GeneralLedgerReportController):

    def _control_filters(self, kw):
        f = self._filters(kw.get('company_id'), kw.get('journal_ids'), 'all', None, True)
        sortby = kw.get('sortby')
        f['sortby'] = sortby if sortby in MOVE_ORDERS else 'sort_date'
        f['target_move'] = 'all' if kw.get('target_move') == 'all' else 'posted'
        return f

    def _journals(self, kw):
        f = self._control_filters(kw)
        company = f['company']
        data = request.env['account.journal.control.report'].with_company(company).get_journals(
            company, f['journal_ids'], kw.get('date_from'), kw.get('date_to'), f['target_move'], kw.get('search') or None)
        return f, company, data

    @http.route('/microfinance/journal_control/data', type='json', auth='user')
    def journal_control_data(self, date_from=None, date_to=None, target_move='posted', journal_ids=None, search=None,
                             company_id=None, sortby='sort_date', **kwargs):
        if not date_from or not date_to:
            self._check_access()
            return {'success': False, 'error': 'Période (Du / Au) requise.'}
        f, company, data = self._journals(dict(
            date_from=date_from, date_to=date_to, target_move=target_move, journal_ids=journal_ids, search=search,
            company_id=company_id, sortby=sortby))
        return {
            'success': True, 'title': TITLE, 'date_from': date_from, 'date_to': date_to,
            'currency': company.currency_id.symbol or '', 'company_name': company.name,
            'target_move_label': 'Toutes les écritures' if f['target_move'] == 'all' else 'Pièces comptabilisées',
            'journals_label': self._journal_label(f['selected'], f['journals']),
            'journals': [{'id': j.id, 'name': j.display_name or j.name} for j in f['journals']],
            'selected_journal_ids': f['selected'],
            'unposted_entries_exist': self._get_unposted_entries_exist(company, date_to, f['journal_ids']),
            'page_size': PAGE_SIZE, 'data': data,
        }

    @http.route('/microfinance/journal_control/moves', type='json', auth='user')
    def journal_control_moves(self, journal_id=None, date_from=None, date_to=None, target_move='posted', journal_ids=None,
                              company_id=None, sortby='sort_date', search=None, anomaly=None, offset=0, **kwargs):
        f = self._control_filters(dict(company_id=company_id, journal_ids=journal_ids, sortby=sortby,
                                       target_move=target_move))
        company = f['company']
        return request.env['account.journal.control.report'].with_company(company).get_moves(
            company, int(journal_id or 0), date_from, date_to, f['target_move'], f['sortby'], search or None,
            anomaly if anomaly in ANOMALY_KINDS else None, offset, PAGE_SIZE)

    @http.route('/microfinance/journal_control/move_lines', type='json', auth='user')
    def journal_control_move_lines(self, move_id=None, company_id=None, **kwargs):
        f = self._control_filters(dict(company_id=company_id))
        company = f['company']
        return request.env['account.journal.control.report'].with_company(company).get_move_lines(
            company, int(move_id or 0))

    def _export_payload(self, kw):
        f, company, data = self._journals(kw)
        details = request.env['account.journal.control.report'].with_company(company).get_anomaly_moves_for_export(
            company, data['journals'], kw.get('date_from'), kw.get('date_to'), f['target_move'], kw.get('search') or None)
        return f, company, data, details

    @http.route('/microfinance/journal_control/pdf', type='http', auth='user')
    def journal_control_pdf(self, **kw):
        f, company, data, details = self._export_payload(kw)
        pdf_content, _type = request.env['ir.actions.report'].sudo()._render_qweb_pdf(REPORT_REF, [], data={
            'title': TITLE, 'company': company, 'date_from': kw.get('date_from'), 'date_to': kw.get('date_to'),
            'target_move_label': 'Toutes les écritures' if f['target_move'] == 'all' else 'Pièces comptabilisées',
            'journals_label': self._journal_label(f['selected'], f['journals']),
            'report_data': data, 'details': details, 'kind_labels': KIND_LABELS})
        filename = 'Controle_journaux_%s_%s.pdf' % (kw.get('date_from'), kw.get('date_to'))
        return request.make_response(pdf_content, headers=[
            ('Content-Type', 'application/pdf'), ('Content-Disposition', 'attachment; filename="%s"' % filename)])

    @http.route('/microfinance/journal_control/xlsx', type='http', auth='user')
    def journal_control_xlsx(self, **kw):
        f, company, data, details = self._export_payload(kw)
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        bold = workbook.add_format({'bold': True})
        money = workbook.add_format({'num_format': '#,##0.00'})
        money_bold = workbook.add_format({'num_format': '#,##0.00', 'bold': True})
        sheet = workbook.add_worksheet(TITLE)
        sheet.write_row(0, 0, [company.name], bold)
        sheet.write_row(1, 0, ['Période du %s au %s' % (kw.get('date_from'), kw.get('date_to'))])
        sheet.write_row(2, 0, ['Pièces : %s' % ('Toutes les écritures' if f['target_move'] == 'all' else 'Pièces comptabilisées')])
        row = 4
        sheet.write_row(row, 0, ['Code', 'Journal', 'Type', 'Pièces', 'Débit', 'Crédit', 'Écart', 'Statut', 'Déséquilibrées',
                                 'Brouillons', 'Annulées', 'Trous de numérotation'], bold)
        row += 1
        status = {'ok': 'OK', 'info': 'À noter', 'anomaly': 'Anomalie'}
        for j in data['journals']:
            a = j['anomalies']
            sheet.write_row(row, 0, [j['code'], j['name'], j['type'], j['count']])
            for col, key in ((4, 'debit'), (5, 'credit'), (6, 'gap')):
                sheet.write_number(row, col, j[key], money)
            sheet.write_row(row, 7, [status[j['status']], a['unbalanced'], a['draft'], a['cancel'], a['gaps']])
            row += 1
        totals = data['totals']
        sheet.write_row(row, 0, ['', 'TOTAL GÉNÉRAL', '', totals['count']], bold)
        for col, key in ((4, 'debit'), (5, 'credit'), (6, 'gap')):
            sheet.write_number(row, col, totals[key], money_bold)
        sheet.write(row, 7, 'Équilibrée' if data['balanced'] else 'Déséquilibrée', bold)
        # Anomalies détaillées
        sheet2 = workbook.add_worksheet('Anomalies')
        sheet2.write_row(0, 0, ['Journal', 'Anomalie', 'Date', 'Pièce', 'État', 'Tiers', 'Libellé', 'Débit', 'Crédit'], bold)
        row = 1
        for j in data['journals']:
            for kind, moves in details.get(j['id'], {}).items():
                for m in moves:
                    sheet2.write_row(row, 0, [j['code'], KIND_LABELS[kind], m['date'], m['piece'], m['state_label'],
                                              m['partner_name'], m['label']])
                    sheet2.write_number(row, 7, m['debit'], money)
                    sheet2.write_number(row, 8, m['credit'], money)
                    row += 1
            for gap in j['gap_details']:
                sheet2.write_row(row, 0, [j['code'], 'Trou de numérotation (information)', '', ', '.join(gap['labels'])])
                row += 1
        workbook.close()
        output.seek(0)
        filename = 'Controle_journaux_%s_%s.xlsx' % (kw.get('date_from'), kw.get('date_to'))
        return request.make_response(output.read(), headers=[
            ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
            ('Content-Disposition', 'attachment; filename="%s"' % filename)])
