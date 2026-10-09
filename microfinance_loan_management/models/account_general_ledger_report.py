# -*- coding: utf-8 -*-
"""Grand livre interactif (même famille d'écrans que le Journal de banque : base_accounting_kit.journal_ledger_report).
Totaux par compte via read_group, lignes d'un compte chargées à la demande par pages. Aucun sudo : les règles
d'accès et de société de l'utilisateur s'appliquent à chaque lecture."""
from odoo import api, models

PAGE_SIZE = 80
DISPLAY_ACCOUNTS = ('all', 'movement', 'not_zero')
SORT_ORDERS = {
    'sort_date': 'date, move_id, id',
    'sort_journal_partner': 'journal_id, partner_id, move_id, id',
}


class AccountGeneralLedgerReport(models.AbstractModel):
    _name = 'account.general.ledger.report'
    _description = 'Grand livre (écran interactif)'

    # ------------------------------------------------------------------ domaines
    @api.model
    def _base_domain(self, company, journal_ids):
        domain = [('company_id', '=', company.id), ('display_type', 'not in', ('line_section', 'line_note'))]
        if journal_ids:
            domain.append(('journal_id', 'in', journal_ids))
        return domain

    @api.model
    def _period_domain(self, company, journal_ids, date_from, date_to, target_move):
        domain = self._base_domain(company, journal_ids)
        domain.append(('parent_state', '=', 'posted') if target_move != 'all' else ('parent_state', '!=', 'cancel'))
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        return domain

    @api.model
    def _opening_domain(self, company, journal_ids, date_from):
        """Solde initial : toutes les écritures comptabilisées (ouverture comprise) datées avant la date de début."""
        return self._base_domain(company, journal_ids) + [('parent_state', '=', 'posted'), ('date', '<', date_from)]

    @api.model
    def _sum_by_account(self, domain):
        groups = self.env['account.move.line'].read_group(domain, ['debit:sum', 'credit:sum'], ['account_id'], lazy=False)
        return {g['account_id'][0]: (g['debit'] or 0.0, g['credit'] or 0.0, g['__count']) for g in groups if g['account_id']}

    @api.model
    def _account_domain(self, company, search):
        domain = [('company_id', '=', company.id)]
        if search:
            domain += ['|', ('code', 'ilike', search), ('name', 'ilike', search)]
        return domain

    # ------------------------------------------------------------------ une ligne par compte
    @api.model
    def get_accounts(self, company, journal_ids, date_from, date_to, target_move, display_account='all',
                     init_balance=True, search=None):
        display_account = display_account if display_account in DISPLAY_ACCOUNTS else 'all'
        period = self._sum_by_account(self._period_domain(company, journal_ids, date_from, date_to, target_move))
        opening = self._sum_by_account(self._opening_domain(company, journal_ids, date_from)) if init_balance and date_from else {}
        currency = company.currency_id
        rows = []
        for account in self.env['account.account'].search(self._account_domain(company, search), order='code'):
            debit, credit, count = period.get(account.id, (0.0, 0.0, 0))
            op_debit, op_credit, _count = opening.get(account.id, (0.0, 0.0, 0))
            opening_balance = currency.round(op_debit - op_credit)
            closing = currency.round(opening_balance + debit - credit)
            if display_account == 'movement' and not count:
                continue
            if display_account == 'not_zero' and currency.is_zero(closing):
                continue
            rows.append({
                'id': account.id, 'code': account.code, 'name': account.name, 'account_type': account.account_type,
                'opening': opening_balance, 'debit': currency.round(debit), 'credit': currency.round(credit),
                'closing': closing, 'count': count,
            })
        totals = {key: currency.round(sum(r[key] for r in rows)) for key in ('opening', 'debit', 'credit', 'closing')}
        return {'accounts': rows, 'totals': totals}

    # ------------------------------------------------------------------ lignes d'un compte (pages de 80)
    @api.model
    def get_lines(self, company, account_id, journal_ids, date_from, date_to, target_move, sortby='sort_date',
                  init_balance=True, offset=0, limit=PAGE_SIZE):
        account = self.env['account.account'].search([('id', '=', account_id), ('company_id', '=', company.id)], limit=1)
        empty = {'rows': [], 'total_rows': 0, 'offset': offset, 'has_more': False}
        if not account:
            return empty
        MoveLine = self.env['account.move.line']
        currency = company.currency_id
        order = SORT_ORDERS.get(sortby, SORT_ORDERS['sort_date'])
        domain = self._period_domain(company, journal_ids, date_from, date_to, target_move) + [('account_id', '=', account.id)]
        balance = 0.0
        if init_balance and date_from:
            op_debit, op_credit, _count = self._sum_by_account(
                self._opening_domain(company, journal_ids, date_from) + [('account_id', '=', account.id)]
            ).get(account.id, (0.0, 0.0, 0))
            balance = op_debit - op_credit
        offset = max(int(offset or 0), 0)
        limit = int(limit) if limit else PAGE_SIZE
        if offset:  # cumul des lignes des pages déjà affichées, dans le même ordre : le solde reste exact d'une page à l'autre
            previous = MoveLine.search(domain, order=order, limit=offset)
            balance += sum(previous.mapped('debit')) - sum(previous.mapped('credit'))
        total = MoveLine.search_count(domain)
        rows = []
        for line in MoveLine.search(domain, order=order, offset=offset, limit=limit):
            balance += line.debit - line.credit
            rows.append({
                'line_id': line.id, 'move_id': line.move_id.id, 'date': str(line.date), 'piece': line.move_id.name or '',
                'journal': line.journal_id.code or '', 'partner_name': line.partner_id.name or '',
                'label': line.name or line.ref or '', 'debit': line.debit, 'credit': line.credit,
                'balance': currency.round(balance),
            })
        return {'rows': rows, 'total_rows': total, 'offset': offset, 'has_more': offset + len(rows) < total}

    @api.model
    def get_all_lines_for_export(self, company, accounts, journal_ids, date_from, date_to, target_move, sortby, init_balance):
        """Export PDF/XLSX : toutes les lignes, compte par compte (hors écran, donc sans pagination)."""
        result = []
        for account in accounts:
            if not account['count']:
                result.append(dict(account, rows=[]))
                continue
            lines = self.get_lines(company, account['id'], journal_ids, date_from, date_to, target_move, sortby,
                                   init_balance, 0, account['count'])
            result.append(dict(account, rows=lines['rows']))
        return result
