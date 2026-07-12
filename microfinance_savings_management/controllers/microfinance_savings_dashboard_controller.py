# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request

from odoo.addons.microfinance_loan_management.controllers.microfinance_dashboard_controller import (
    MicrofinanceDashboardController,
)


class MicrofinanceSavingsDashboardController(MicrofinanceDashboardController):

    @http.route('/microfinance/dashboard/data', type='json', auth='user')
    def dashboard_data(self):
        data = super().dashboard_data()
        env = request.env
        company = env.company
        Account = env['microfinance.savings.account']
        active_accounts = Account.search([('company_id', '=', company.id), ('state', '=', 'active')])
        data['kpis']['savings_outstanding_total'] = sum(active_accounts.mapped('balance'))
        data['kpis']['active_savings_account_count'] = len(active_accounts)
        return data
