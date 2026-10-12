# -*- coding: utf-8 -*-
"""Trésorerie des journaux d'exploitation : solde en banque, paiements/encaissements en transit, solde disponible.

Calcul AGRÉGÉ (read_group, 2 requêtes pour tout un lot de journaux), jamais ligne par ligne. Sert au tableau de bord
(tuile « Trésorerie d'exploitation ») et à l'avertissement de solde d'un paiement de salaires.
"""
from odoo import models


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    def _mf_treasury_amounts(self):
        """{journal.id: {'bank', 'out_transit', 'in_transit', 'available', 'bank_account_id', 'out_account_id',
        'in_account_id'}} pour les journaux de `self`.

          bank        : solde comptable du compte du journal (balance d'ouverture et tout mouvement compris) ;
          out_transit : lignes 139500 (paiement sortant en suspens) NON lettrées de CE journal ;
          in_transit  : lignes 139100 (encaissement en suspens) NON lettrées de ce journal ;
          available   : bank - out_transit.
        Lecture en sudo bornée aux journaux fournis (la visibilité des journaux est décidée par l'appelant)."""
        Line = self.env['account.move.line'].sudo()
        Partage = self.env['microfinance.fond.partage']
        journals = self.sudo()
        info = {}
        for journal in journals:
            info[journal.id] = {
                'bank': 0.0, 'out_transit': 0.0, 'in_transit': 0.0, 'available': 0.0,
                'bank_account_id': journal.default_account_id.id,
                'out_account_id': Partage._payment_account(journal, 'outbound').id,
                'in_account_id': Partage._payment_account(journal, 'inbound').id,
            }
        bank_accounts = {i['bank_account_id'] for i in info.values() if i['bank_account_id']}
        if bank_accounts:
            balances = {g['account_id'][0]: g['balance'] for g in Line.read_group(
                [('account_id', 'in', list(bank_accounts)), ('parent_state', '=', 'posted')],
                ['balance:sum'], ['account_id'], lazy=False)}
            for values in info.values():
                values['bank'] = balances.get(values['bank_account_id'], 0.0)
        transit_accounts = {a for i in info.values() for a in (i['out_account_id'], i['in_account_id']) if a}
        if transit_accounts:
            for group in Line.read_group(
                    [('journal_id', 'in', journals.ids), ('account_id', 'in', list(transit_accounts)),
                     ('reconciled', '=', False), ('parent_state', '=', 'posted')],
                    ['amount_residual:sum'], ['journal_id', 'account_id'], lazy=False):
                values = info[group['journal_id'][0]]
                account_id = group['account_id'][0]
                if account_id == values['out_account_id']:
                    values['out_transit'] = -group['amount_residual']
                elif account_id == values['in_account_id']:
                    values['in_transit'] = group['amount_residual']
        for values in info.values():
            values['available'] = values['bank'] - values['out_transit']
        return info
