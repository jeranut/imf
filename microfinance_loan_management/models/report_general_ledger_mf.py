# -*- coding: utf-8 -*-
from odoo import api, models


class ReportGeneralLedgerMf(models.AbstractModel):
    _name = 'report.microfinance_loan_management.report_general_ledger_mf'
    _description = 'Grand livre interactif (PDF)'

    @api.model
    def _get_report_values(self, docids, data=None):
        data = data or {}
        company = data.get('company')
        return dict(data, doc_ids=docids, doc_model='res.company',
                    docs=self.env['res.company'].browse([company.id]) if company else self.env['res.company'])
