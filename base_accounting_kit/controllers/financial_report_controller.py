# -*- coding: utf-8 -*-
from odoo import http, fields
from odoo.http import request


class FinancialReportController(http.Controller):
    """JSON controller for the Balance Sheet HTML view."""

    @http.route('/base_accounting_kit/financial_report/data', type='json', auth='user')
    def financial_report_data(self, report_name='Balance Sheet', date_to=None,
                              target_move='posted', **kwargs):
        company = request.env.company
        date_to = date_to or fields.Date.context_today(request.env.user)

        account_report = request.env.ref(
            'base_accounting_kit.account_financial_report_balancesheet0',
            raise_if_not_found=False,
        )

        if not account_report:
            return {
                'success': False,
                'error': (
                    'Rapport Bilan introuvable : '
                    'base_accounting_kit.account_financial_report_balancesheet0'
                ),
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
        data['used_context'] = dict(
            used_context,
            lang='en_US',
        )

        raw_lines = wizard.get_account_lines(data)
        lines = self._build_balance_sheet_lines(raw_lines)

        return {
            'success': True,
            'report_name': 'Bilan',
            'date_to': str(date_to),
            'currency': company.currency_id.symbol or '',
            'company_name': company.name,
            'target_move': target_move,
            'target_move_label': (
                'Toutes les écritures'
                if target_move == 'all'
                else 'Pièces comptabilisées'
            ),
            'journals_label': 'Tous les journaux',
            'lines': lines,
        }

    def _build_balance_sheet_lines(self, raw_lines):
        """Normalize get_account_lines output for the Balance Sheet HTML view."""
        report_refs = {
            'root': request.env.ref(
                'base_accounting_kit.account_financial_report_balancesheet0',
                raise_if_not_found=False,
            ),
            'assets': request.env.ref(
                'base_accounting_kit.account_financial_report_assets0',
                raise_if_not_found=False,
            ),
            'liability': request.env.ref(
                'base_accounting_kit.account_financial_report_liabilitysum0',
                raise_if_not_found=False,
            ),
            'debts': request.env.ref(
                'base_accounting_kit.account_financial_report_liability0',
                raise_if_not_found=False,
            ),
            'result': request.env.ref(
                'base_accounting_kit.account_financial_report_profitloss_toreport0',
                raise_if_not_found=False,
            ),
        }
        ref_ids = {
            key: report.id
            for key, report in report_refs.items()
            if report
        }

        root_line = next(
            (
                line for line in raw_lines
                if line.get('type') == 'report'
                and line.get('r_id') == ref_ids.get('root')
            ),
            None,
        )
        root_id = root_line and root_line.get('id')
        skipped_ids = {root_id} if root_id else set()

        normalized = []
        by_id = {}
        for order, raw_line in enumerate(raw_lines):
            line_id = raw_line.get('a_id') if raw_line.get('type') == 'account' else raw_line.get('id')
            if not line_id or line_id in skipped_ids:
                continue

            parent = raw_line.get('parent')
            if parent in skipped_ids:
                parent = False

            line = {
                'id': line_id,
                'parent': parent,
                'name': self._balance_sheet_display_name(raw_line, ref_ids),
                'balance': round(raw_line.get('balance') or 0.0, 2),
                'level': 0,
                'type': raw_line.get('type') or 'report',
                'total': raw_line.get('type') == 'report',
                'account_type': raw_line.get('account_type'),
                '_order': order,
            }
            normalized.append(line)
            by_id[line_id] = line

        for line in normalized:
            if line.get('parent') not in by_id:
                line['parent'] = False

        def compute_level(line, seen=None):
            seen = seen or set()
            parent_id = line.get('parent')
            if not parent_id or parent_id not in by_id or line['id'] in seen:
                return 0
            seen.add(line['id'])
            return compute_level(by_id[parent_id], seen) + 1

        for line in normalized:
            line['level'] = compute_level(line)

        return self._order_balance_sheet_lines(normalized)

    def _order_balance_sheet_lines(self, lines):
        by_parent = {}
        for line in lines:
            by_parent.setdefault(line.get('parent') or False, []).append(line)

        section_rank = {
            'ACTIF': 0,
            'PASSIF': 1,
        }

        def sort_key(line):
            if not line.get('parent'):
                return (section_rank.get(line.get('name'), 99), line.get('_order', 0))
            return (line.get('_order', 0),)

        ordered = []

        def append_children(parent_id=False):
            for child in sorted(by_parent.get(parent_id, []), key=sort_key):
                ordered.append(child)
                append_children(child['id'])

        append_children(False)
        for line in ordered:
            line.pop('_order', None)
        return ordered

    def _balance_sheet_display_name(self, line, ref_ids):
        if line.get('type') == 'account':
            return line.get('name') or ''

        report_id = line.get('r_id')
        if report_id == ref_ids.get('assets'):
            return 'ACTIF'
        if report_id == ref_ids.get('liability'):
            return 'PASSIF'
        if report_id == ref_ids.get('debts'):
            return 'Dettes'
        if report_id == ref_ids.get('result'):
            return "Résultat de l’exercice"

        name = (line.get('name') or '').strip()
        labels = {
            'Assets': 'ACTIF',
            'Asset': 'ACTIF',
            'Les Atouts': 'ACTIF',
            'LES ATOUTS': 'ACTIF',
            'Immobilisations': 'ACTIF',
            'Liability': 'PASSIF',
            'Passif': 'PASSIF',
            'PASSIF': 'PASSIF',
            'Profit (Loss) to report': "Résultat de l’exercice",
            'Profit/Loss to report': "Résultat de l’exercice",
            'Bénéfice (perte) à déclarer': "Résultat de l’exercice",
            'BÉNÉFICE (PERTE) À DÉCLARER': "Résultat de l’exercice",
        }
        return labels.get(name, name)
