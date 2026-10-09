# -*- coding: utf-8 -*-
from odoo.addons.base_accounting_kit.controllers.financial_report_controller import FinancialReportController


class MfFinancialReportController(FinancialReportController):

    def _get_balance_sheet_check(self, lines, report_config):
        """PASSIF et CAPITAUX PROPRES s'affichent en positif (voir account_financial_report_mf.py) : l'équation du
        bilan est ACTIF − PASSIF − CAPITAUX PROPRES = 0."""
        section_rank = report_config.get('section_rank') or {}
        if not {'ACTIF', 'PASSIF', 'CAPITAUX PROPRES'} <= set(section_rank):
            return False
        totals = {}
        for line in lines:
            if not line.get('parent') and line.get('name') in section_rank:
                totals[line['name']] = totals.get(line['name'], 0.0) + (line.get('balance') or 0.0)
        total_actif = totals.get('ACTIF', 0.0)
        total_passif = totals.get('PASSIF', 0.0)
        total_capitaux_propres = totals.get('CAPITAUX PROPRES', 0.0)
        diff = round(total_actif - total_passif - total_capitaux_propres, 2)
        return {
            'ok': abs(diff) < 0.01,
            'total_actif': total_actif,
            'total_passif': total_passif,
            'total_capitaux_propres': total_capitaux_propres,
            'diff': diff,
        }
