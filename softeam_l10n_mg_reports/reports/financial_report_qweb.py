# -*- coding: utf-8 -*-
from odoo import api, models


class SofteamMgFinancialReportQweb(models.AbstractModel):
    _name = 'report.softeam_l10n_mg_reports.report_mg_financial_pdf'
    _description = 'Madagascar financial report PDF'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['softeam.l10n.mg.financial.report.wizard'].browse(docids)
        for wizard in docs:
            if not wizard.html_content:
                report_data = wizard._get_report_data()
                wizard.html_content = wizard._render_html(report_data)
        return {
            'doc_ids': docids,
            'doc_model': 'softeam.l10n.mg.financial.report.wizard',
            'docs': docs,
        }
