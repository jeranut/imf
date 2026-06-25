from odoo import models
from odoo.addons.account.models.chart_template import template


class AccountChartTemplate(models.AbstractModel):
    _inherit = 'account.chart.template'

    @template('mg')
    def _get_mg_template_data(self):
        return {
            'name': 'Madagascar - PCG 2005',
            'parent': None,
            'code_digits': '6',
            'use_anglo_saxon': False,
            'property_account_receivable_id': 'pcg_4111',
            'property_account_payable_id': 'pcg_4011',
            'property_account_expense_categ_id': 'pcg_607',
            'property_account_income_categ_id': 'pcg_707',
            'property_stock_account_input_categ_id': 'pcg_408',
            'property_stock_account_output_categ_id': 'pcg_418',
            'property_stock_valuation_account_id': 'pcg_370',
        }

    @template('mg', 'res.company')
    def _get_mg_res_company(self):
        return {
            self.env.company.id: {
                'account_fiscal_country_id': 'base.mg',
                'bank_account_code_prefix': '512',
                'cash_account_code_prefix': '53',
                'transfer_account_code_prefix': '58',
                'income_currency_exchange_account_id': 'pcg_766',
                'expense_currency_exchange_account_id': 'pcg_666',
                'account_journal_early_pay_discount_loss_account_id': 'pcg_665',
                'account_journal_early_pay_discount_gain_account_id': 'pcg_765',
                'account_journal_suspense_account_id': 'pcg_511',
                'default_cash_difference_income_account_id': 'pcg_758',
                'default_cash_difference_expense_account_id': 'pcg_658',
                'account_sale_tax_id': 'tva_collectee_20',
                'account_purchase_tax_id': 'tva_deductible_bs_20',
            }
        }
