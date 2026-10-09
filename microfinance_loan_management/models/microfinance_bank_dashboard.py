# -*- coding: utf-8 -*-
"""Kanban des journaux bancaires : « Saisir un relevé » remplace « Connecter », avec solde du relevé, solde
comptable, écart et nombre de lignes à traiter."""
from odoo import models, _


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    def _fill_bank_cash_dashboard_data(self, dashboard_data):
        super()._fill_bank_cash_dashboard_data(dashboard_data)
        Statement = self.env['account.bank.statement'].sudo()
        Entry = self.env['microfinance.bank.statement.entry'].sudo()
        for journal in self.filtered(lambda j: j.type == 'bank'):
            data = dashboard_data[journal.id]
            currency = journal.currency_id or journal.company_id.sudo().currency_id
            last = Statement.search([('journal_id', '=', journal.id), ('mf_state', '=', 'validated')],
                                    order='mf_date_to desc, id desc', limit=1)
            self.env.cr.execute(
                "SELECT COALESCE(SUM(balance), 0) FROM account_move_line "
                "WHERE account_id = %s AND company_id = %s AND parent_state = 'posted'",
                (journal.default_account_id.id, journal.company_id.id))
            book = self.env.cr.fetchone()[0] if journal.default_account_id else 0.0
            statement_balance = last.balance_end_real if last else 0.0
            data.update({
                'mf_enabled': True,
                'mf_statement_balance': currency.format(statement_balance),
                'mf_book_balance': currency.format(book),
                'mf_gap': currency.format(currency.round(statement_balance - book)),
                'mf_gap_nonzero': not currency.is_zero(statement_balance - book),
                'mf_last_statement': last.mf_date_to and last.mf_date_to.strftime('%d/%m/%Y') or '',
                'mf_todo_count': Entry.search_count([('journal_id', '=', journal.id), ('state', '=', 'todo')]),
            })

    def action_mf_new_statement(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('microfinance_loan_management.action_microfinance_bank_statement')
        action.update({'views': [(False, 'form')], 'view_mode': 'form', 'target': 'current',
                       'context': {'default_journal_id': self.id, 'default_mf_state': 'draft'}})
        return action

    def action_mf_open_statements(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('microfinance_loan_management.action_microfinance_bank_statement')
        action['domain'] = [('journal_id', '=', self.id), ('mf_state', '!=', False)]
        action['context'] = {'default_journal_id': self.id, 'default_mf_state': 'draft'}
        return action
