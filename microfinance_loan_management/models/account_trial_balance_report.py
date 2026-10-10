# -*- coding: utf-8 -*-
"""Balance générale interactive : même moteur que le Grand livre (account.general.ledger.report), dont on réutilise
get_accounts pour garantir les mêmes chiffres (read_group par compte, aucune ligne d'écriture chargée). Ajoute les colonnes
débit/crédit des soldes, le regroupement par classe (premier chiffre du code) et le témoin d'équilibre."""
from odoo import api, models


class AccountTrialBalanceReport(models.AbstractModel):
    _name = 'account.trial.balance.report'
    _inherit = 'account.general.ledger.report'
    _description = 'Balance générale (écran interactif)'

    AMOUNT_KEYS = ('opening_debit', 'opening_credit', 'debit', 'credit', 'closing_debit', 'closing_credit')

    @api.model
    def _split(self, balance):
        """Un solde positif va au débit, un solde négatif au crédit, jamais les deux."""
        return (balance, 0.0) if balance > 0 else (0.0, -balance) if balance < 0 else (0.0, 0.0)

    @api.model
    def _sums(self, currency, rows):
        return {key: currency.round(sum(r[key] for r in rows)) for key in self.AMOUNT_KEYS}

    @api.model
    def _class_of(self, code):
        """Classe PCEC : premier chiffre du code ('?' pour un code qui ne commence pas par un chiffre)."""
        return code[0] if code and code[0].isdigit() else '?'

    @api.model
    def _class_labels(self, company):
        """Libellé de classe lu dans les groupes de comptes de la société (code de groupe d'un seul chiffre)."""
        groups = self.env['account.group'].search([('company_id', '=', company.id)])
        return {g.code_prefix_start: g.name for g in groups
                if g.code_prefix_start and len(g.code_prefix_start) == 1 and g.code_prefix_start == g.code_prefix_end}

    @api.model
    def _decorate(self, currency, accounts):
        rows = []
        for account in accounts:
            row = dict(account)
            row['opening_debit'], row['opening_credit'] = self._split(account['opening'])
            row['closing_debit'], row['closing_credit'] = self._split(account['closing'])
            row['class'] = self._class_of(account['code'])
            rows.append(row)
        return rows

    @api.model
    def get_balance(self, company, journal_ids, date_from, date_to, target_move, display_account='all',
                    init_balance=True, search=None):
        currency = company.currency_id
        data = self.get_accounts(company, journal_ids, date_from, date_to, target_move, display_account, init_balance,
                                 search)
        rows = self._decorate(currency, data['accounts'])
        labels = self._class_labels(company)
        classes = []
        for key in sorted({r['class'] for r in rows}):
            members = [r for r in rows if r['class'] == key]
            classes.append(dict(
                self._sums(currency, members), key=key, count=len(members), accounts=members,
                label=('Classe %s — %s' % (key, labels[key])) if key in labels
                else ('Classe %s' % key if key != '?' else 'Autres comptes')))
        # Témoin d'équilibre : toujours calculé sur tous les comptes, quels que soient l'affichage et la recherche
        # (un filtre « avec mouvements » écarterait des soldes initiaux et fausserait le contrôle)
        full = rows if display_account == 'all' and not search else self._decorate(
            currency, self.get_accounts(company, journal_ids, date_from, date_to, target_move, 'all', init_balance,
                                        None)['accounts'])
        check = self._sums(currency, full)
        gaps = {
            'opening': currency.round(check['opening_debit'] - check['opening_credit']),
            'movements': currency.round(check['debit'] - check['credit']),
            'closing': currency.round(check['closing_debit'] - check['closing_credit']),
        }
        return {
            'accounts': rows, 'classes': classes, 'totals': self._sums(currency, rows),
            'balance_check': {'balanced': not any(gaps.values()), 'gaps': gaps,
                              'gap': max(gaps.values(), key=abs)},
        }
