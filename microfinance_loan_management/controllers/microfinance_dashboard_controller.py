# -*- coding: utf-8 -*-
from collections import defaultdict

from dateutil.relativedelta import relativedelta

from odoo import fields, http
from odoo.http import request


class MicrofinanceDashboardController(http.Controller):

    @http.route('/microfinance/dashboard/data', type='json', auth='user')
    def dashboard_data(self):
        env = request.env
        company = env.company
        today = fields.Date.context_today(env.user)
        month_start = today.replace(day=1)
        months = [month_start - relativedelta(months=index) for index in range(11, -1, -1)]
        month_keys = [month.strftime('%Y-%m') for month in months]
        month_labels = [month.strftime('%b %Y') for month in months]

        Loan = env['microfinance.loan']
        Installment = env['microfinance.loan.installment']
        Payment = env['microfinance.loan.payment']

        company_domain = [('company_id', '=', company.id)]
        active_domain = company_domain + [('state', '=', 'active')]
        defaulted_domain = company_domain + [('state', '=', 'defaulted')]
        disbursed_domain = company_domain + [('state', 'in', ('active', 'closed', 'defaulted'))]
        portfolio_domain = company_domain + [('state', 'in', ('active', 'defaulted'))]

        active_loans = Loan.search(active_domain)
        defaulted_count = Loan.search_count(defaulted_domain)
        disbursed_loans = Loan.search(disbursed_domain)
        portfolio_loans = Loan.search(portfolio_domain)

        active_loan_count = len(active_loans)
        disbursed_amount = sum(disbursed_loans.mapped('loan_amount'))
        outstanding_amount = sum(portfolio_loans.mapped('balance_total'))
        overdue_amount = sum(portfolio_loans.mapped('overdue_amount'))
        default_rate = active_loan_count and (defaulted_count / active_loan_count * 100.0) or 0.0

        state_rows = Loan.read_group(company_domain, ['state'], ['state'], lazy=False)
        state_selection = dict(Loan._fields['state'].selection)
        loans_by_state = {
            'labels': [state_selection.get(row['state'], row['state'] or '') for row in state_rows],
            'values': [row.get('__count', row.get('state_count', 0)) for row in state_rows],
        }

        monthly_disbursement = dict.fromkeys(month_keys, 0.0)
        for loan in Loan.search(disbursed_domain + [('disbursement_date', '>=', months[0])]):
            key = loan.disbursement_date and loan.disbursement_date.strftime('%Y-%m')
            if key in monthly_disbursement:
                monthly_disbursement[key] += loan.loan_amount

        monthly_repayment = dict.fromkeys(month_keys, 0.0)
        for payment in Payment.search(company_domain + [('state', '=', 'posted'), ('payment_date', '>=', months[0])]):
            key = payment.payment_date and payment.payment_date.strftime('%Y-%m')
            if key in monthly_repayment:
                monthly_repayment[key] += payment.amount

        monthly_overdue = dict.fromkeys(month_keys, 0.0)
        overdue_installments = Installment.search(company_domain + [
            ('state', '=', 'overdue'),
            ('due_date', '>=', months[0]),
        ])
        for installment in overdue_installments:
            key = installment.due_date and installment.due_date.strftime('%Y-%m')
            if key in monthly_overdue:
                monthly_overdue[key] += installment.residual_amount

        risk_distribution = {'low': 0, 'medium': 0, 'high': 0}
        for loan in portfolio_loans:
            if loan.risk_score < 35:
                risk_distribution['low'] += 1
            elif loan.risk_score < 70:
                risk_distribution['medium'] += 1
            else:
                risk_distribution['high'] += 1

        overdue_by_loan = defaultdict(lambda: {'amount_due': 0.0, 'days_overdue': 0})
        top_lines = Installment.search(company_domain + [('state', '=', 'overdue'), ('residual_amount', '>', 0)])
        for line in top_lines:
            bucket = overdue_by_loan[line.loan_id]
            bucket['amount_due'] += line.residual_amount
            if line.due_date:
                bucket['days_overdue'] = max(bucket['days_overdue'], (today - line.due_date).days)

        top_overdue_loans = []
        for loan, values in overdue_by_loan.items():
            top_overdue_loans.append({
                'partner': loan.partner_id.display_name,
                'loan': loan.name,
                'amount_due': values['amount_due'],
                'days_overdue': values['days_overdue'],
            })
        top_overdue_loans = sorted(
            top_overdue_loans,
            key=lambda item: (item['days_overdue'], item['amount_due']),
            reverse=True,
        )[:10]

        return {
            'currency': company.currency_id.symbol or '',
            'kpis': {
                'active_loan_count': active_loan_count,
                'disbursed_amount': disbursed_amount,
                'outstanding_amount': outstanding_amount,
                'overdue_amount': overdue_amount,
                'default_rate': default_rate,
            },
            'loans_by_state': loans_by_state,
            'monthly': {
                'labels': month_labels,
                'disbursement': [monthly_disbursement[key] for key in month_keys],
                'repayment': [monthly_repayment[key] for key in month_keys],
                'overdue': [monthly_overdue[key] for key in month_keys],
            },
            'risk_distribution': risk_distribution,
            'top_overdue_loans': top_overdue_loans,
        }
