# -*- coding: utf-8 -*-
from odoo import http, fields
from odoo.http import request


class FinancialReportController(http.Controller):
    """Contrôleur JSON pour afficher le Bilan en vue HTML OWL."""

    @http.route('/base_accounting_kit/financial_report/data', type='json', auth='user')
    def financial_report_data(self, report_name='Balance Sheet', date_to=None,
                              target_move='posted', **kwargs):
        company = request.env.company
        date_to = date_to or fields.Date.context_today(request.env.user)

        # Récupération directe du rapport Bilan par ID XML.
        # Plus fiable qu'une recherche par nom, car le nom peut être traduit.
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

        # Création temporaire du wizard existant pour réutiliser sa logique.
        wizard = request.env['financial.report'].sudo().create({
            'account_report_id': account_report.id,
            'date_to': date_to,
            'target_move': target_move,
            'debit_credit': False,
            'company_id': company.id,
            'view_format': 'vertical',
        })

        # Données attendues par les méthodes du wizard financial.report.
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

        # Contexte comptable : société, dates et type de pièces.
        used_context = wizard._build_contexts({'form': data})
        data['used_context'] = dict(
            used_context,
            lang=request.env.context.get('lang') or 'fr_FR',
        )

        # Génération des lignes avec la logique native du module.
        lines = wizard.get_account_lines(data)

        def get_level(line):
            """Retourne le niveau d'indentation de la ligne."""
            try:
                return int(line.get('level') or 1)
            except Exception:
                return 1

        def translate_name(name):
            """Traduit les grands libellés comptables anglais."""
            if not name:
                return name

            translations = {
                'Asset': 'Actif',
                'Assets': 'Actifs',
                'Liability': 'Passif',
                'Liabilities': 'Passifs',
                'Equity': 'Capitaux propres',
                'Income': 'Produits',
                'Expense': 'Charges',
                'Expenses': 'Charges',
            }

            return translations.get(str(name).strip(), name)

        clean_lines = []
        for line in lines:
            clean_lines.append({
                'id': line.get('id') or line.get('a_id') or str(line.get('name')),
                'parent': line.get('parent'),
                'name': translate_name(line.get('name')),
                'balance': round(line.get('balance') or 0.0, 2),
                'type': line.get('type'),
                'level': get_level(line),
                'account_type': line.get('account_type'),
            })

        return {
            'success': True,
            'report_name': translate_name(account_report.name),
            'date_to': str(date_to),
            'currency': company.currency_id.symbol or '',
            'company_name': company.name,
            'lines': clean_lines,
        }