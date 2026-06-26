# -*- coding: utf-8 -*-
from odoo import models, _


class SofteamMgFinancialReportService(models.AbstractModel):
    _name = 'softeam.l10n.mg.financial.report.service'
    _description = 'Madagascar financial report computation service'

    REPORT_TITLES = {
        'balance_sheet': _('Bilan'),
        'income_statement': _('Compte de résultat'),
        'general_balance': _('Balance générale'),
        'partner_balance': _('Balance auxiliaire'),
        'general_ledger': _('Grand livre'),
        'journals': _('Journaux'),
        'vat_statement': _('Déclaration TVA'),
        'account_analysis': _('Analyse des comptes'),
    }

    def get_report_data(self, options):
        report_type = options.get('report_type')
        method = getattr(self, '_get_{}_data'.format(report_type), None)
        if not method:
            method = self._get_account_analysis_data
        return {
            'title': self.REPORT_TITLES.get(report_type, _('Rapport financier')),
            'company': self.env['res.company'].browse(options['company_id']),
            'options': options,
            'lines': method(options),
        }

    def _base_line_domain(self, options):
        domain = [
            ('company_id', '=', options['company_id']),
            ('date', '>=', options['date_from']),
            ('date', '<=', options['date_to']),
        ]
        if options.get('target_move') == 'posted':
            domain.append(('move_id.state', '=', 'posted'))
        else:
            domain.append(('move_id.state', '!=', 'cancel'))
        journal_ids = options.get('journal_ids') or []
        if journal_ids:
            domain.append(('journal_id', 'in', journal_ids))
        return domain

    def _sum_balance(self, options, prefixes, sign=1):
        prefixes = tuple(prefixes)
        domain = self._base_line_domain(options)
        prefix_domain = []
        for prefix in prefixes:
            prefix_domain = ['|'] + prefix_domain if prefix_domain else prefix_domain
            prefix_domain.append(('account_id.code', '=like', f'{prefix}%'))
        lines = self.env['account.move.line'].search(domain + prefix_domain)
        return sign * sum(lines.mapped('balance'))

    def _account_totals(self, options, account_domain=None, partner=False):
        domain = self._base_line_domain(options)
        if account_domain:
            domain += account_domain
        groupby = ['account_id'] + (['partner_id'] if partner else [])
        rows = self.env['account.move.line'].read_group(
            domain,
            ['debit:sum', 'credit:sum', 'balance:sum'],
            groupby,
            lazy=False,
        )
        result = []
        for row in rows:
            account = row.get('account_id') and self.env['account.account'].browse(row['account_id'][0])
            partner_rec = row.get('partner_id') and self.env['res.partner'].browse(row['partner_id'][0])
            result.append({
                'name': account.display_name if account else _('Sans compte'),
                'partner': partner_rec.display_name if partner_rec else '',
                'debit': row.get('debit', 0.0),
                'credit': row.get('credit', 0.0),
                'balance': row.get('balance', 0.0),
                'level': 1,
            })
        return sorted(result, key=lambda line: (line['name'], line.get('partner') or ''))

    def _get_balance_sheet_data(self, options):
        sections = [
            ('ACTIFS NON COURANTS', [
                ('Immobilisations incorporelles (20)', ['20'], 1),
                ('Immobilisations corporelles (21)', ['21'], 1),
                ('Immobilisations en concession (22)', ['22'], 1),
                ('Immobilisations en cours (23)', ['23'], 1),
                ('Participations et créances rattachées (26)', ['26'], 1),
                ('Autres immobilisations financières (27)', ['27'], 1),
                ('Amortissements et pertes de valeur (28-29)', ['28', '29'], 1),
                ('Impôts différés actif (133)', ['133'], 1),
            ]),
            ('ACTIFS COURANTS', [
                ('Stocks et en-cours (3)', ['3'], 1),
                ('Clients et comptes rattachés (41)', ['41'], 1),
                ('Autres débiteurs (40, 42, 44, 46, 48)', ['40', '42', '44', '46', '48'], 1),
                ('Trésorerie actif (50, 51, 53, 54, 58)', ['50', '51', '53', '54', '58'], 1),
            ]),
            ('CAPITAUX PROPRES ET PASSIFS', [
                ('Capitaux propres (10-12)', ['10', '11', '12'], -1),
                ('Produits et charges différés (13)', ['13'], -1),
                ('Provisions et dettes financières (15-18)', ['15', '16', '17', '18'], -1),
                ('Fournisseurs et autres créditeurs (40, 42, 44, 45, 46, 48)', ['40', '42', '44', '45', '46', '48'], -1),
            ]),
        ]
        lines = []
        grand_total = 0.0
        for section, items in sections:
            lines.append({'name': section, 'level': 0, 'debit': 0.0, 'credit': 0.0, 'balance': 0.0, 'is_section': True})
            subtotal = 0.0
            for label, prefixes, sign in items:
                amount = self._sum_balance(options, prefixes, sign=sign)
                subtotal += amount
                lines.append({'name': label, 'level': 1, 'debit': 0.0, 'credit': 0.0, 'balance': amount})
            grand_total += subtotal
            lines.append({'name': _('Total {}').format(section), 'level': 0, 'debit': 0.0, 'credit': 0.0, 'balance': subtotal, 'is_total': True})
        lines.append({'name': _('Contrôle global'), 'level': 0, 'debit': 0.0, 'credit': 0.0, 'balance': grand_total, 'is_total': True})
        return lines

    def _get_income_statement_data(self, options):
        rows = [
            ('Chiffre d’affaires (70)', ['70'], -1),
            ('Variation de stocks et production immobilisée (71-72)', ['71', '72'], -1),
            ('Subventions et autres produits opérationnels (74-75, 78)', ['74', '75', '78'], -1),
            ('Achats consommés (60)', ['60'], 1),
            ('Services extérieurs (61-62)', ['61', '62'], 1),
            ('Impôts et taxes (63)', ['63'], 1),
            ('Charges de personnel (64)', ['64'], 1),
            ('Autres charges opérationnelles et dotations (65, 68)', ['65', '68'], 1),
            ('Résultat financier (76 - 66)', ['76'], -1),
            ('Charges financières (66)', ['66'], 1),
            ('Éléments extraordinaires (77 - 67)', ['77'], -1),
            ('Charges extraordinaires (67)', ['67'], 1),
            ('Impôts sur les bénéfices (69)', ['69'], 1),
        ]
        lines = []
        total = 0.0
        for label, prefixes, sign in rows:
            amount = self._sum_balance(options, prefixes, sign=sign)
            total += amount
            lines.append({'name': label, 'level': 1, 'debit': 0.0, 'credit': 0.0, 'balance': amount})
        lines.append({'name': _('Résultat net'), 'level': 0, 'debit': 0.0, 'credit': 0.0, 'balance': total, 'is_total': True})
        return lines

    def _get_vat_statement_data(self, options):
        sales_base = self._sum_balance(options, ['70'], sign=-1)
        vat_collected = self._sum_balance(options, ['4451'], sign=-1)
        vat_deductible_goods = self._sum_balance(options, ['4452'], sign=1)
        vat_deductible_assets = self._sum_balance(options, ['4453'], sign=1)
        vat_credit = self._sum_balance(options, ['4456'], sign=1)
        deductible_total = vat_deductible_goods + vat_deductible_assets + vat_credit
        return [
            {'name': 'A. Chiffre d’affaires taxable estimé', 'level': 0, 'debit': 0.0, 'credit': 0.0, 'balance': sales_base},
            {'name': 'B. TVA collectée (4451)', 'level': 0, 'debit': 0.0, 'credit': 0.0, 'balance': vat_collected},
            {'name': 'C1. TVA déductible biens et services (4452)', 'level': 1, 'debit': 0.0, 'credit': 0.0, 'balance': vat_deductible_goods},
            {'name': 'C2. TVA déductible immobilisations (4453)', 'level': 1, 'debit': 0.0, 'credit': 0.0, 'balance': vat_deductible_assets},
            {'name': 'C3. Crédit de TVA à reporter (4456)', 'level': 1, 'debit': 0.0, 'credit': 0.0, 'balance': vat_credit},
            {'name': 'C. Total TVA déductible', 'level': 0, 'debit': 0.0, 'credit': 0.0, 'balance': deductible_total, 'is_total': True},
            {'name': 'D. TVA à décaisser', 'level': 0, 'debit': 0.0, 'credit': 0.0, 'balance': vat_collected - deductible_total, 'is_total': True},
        ]

    def _get_general_balance_data(self, options):
        return self._account_totals(options)

    def _get_partner_balance_data(self, options):
        return self._account_totals(options, [('partner_id', '!=', False)], partner=True)

    def _get_general_ledger_data(self, options):
        lines = self.env['account.move.line'].search(self._base_line_domain(options), order='account_id, date, move_name, id')
        return [{
            'name': '{} - {} - {}'.format(line.date, line.account_id.code, line.name or line.move_name),
            'partner': line.partner_id.display_name or '',
            'debit': line.debit,
            'credit': line.credit,
            'balance': line.balance,
            'level': 1,
        } for line in lines[:2000]]

    def _get_journals_data(self, options):
        rows = self.env['account.move.line'].read_group(
            self._base_line_domain(options),
            ['debit:sum', 'credit:sum', 'balance:sum'],
            ['journal_id'],
            lazy=False,
        )
        return [{
            'name': row['journal_id'] and row['journal_id'][1] or _('Sans journal'),
            'debit': row.get('debit', 0.0),
            'credit': row.get('credit', 0.0),
            'balance': row.get('balance', 0.0),
            'level': 1,
        } for row in rows]

    def _get_account_analysis_data(self, options):
        return self._account_totals(options)

    def _prepare_xlsx_data(self, options):
        return self.get_report_data(options)
