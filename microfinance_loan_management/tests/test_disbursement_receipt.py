# -*- coding: utf-8 -*-
from .common import MicrofinanceCommon


class TestDisbursementReceipt(MicrofinanceCommon):

    def test_receipt_renders_for_active_loan(self):
        loan = self._activate_loan(loan_amount=500.0, term=3)
        html, _report_type = self.env['ir.actions.report']._render_qweb_html(
            'microfinance_loan_management.report_microfinance_loan_disbursement_receipt_document', loan.ids
        )
        self.assertIn(loan.name.encode(), html)
        self.assertIn(loan.partner_id.name.encode(), html)
