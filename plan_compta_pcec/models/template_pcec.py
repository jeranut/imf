from odoo import models
from odoo.addons.account.models.chart_template import template


class AccountChartTemplate(models.AbstractModel):
    _inherit = 'account.chart.template'

    @template('mg_pcec')
    def _get_mg_pcec_template_data(self):
        return {
            'name': 'PCEC 2005',
            'parent': None,
            'code_digits': '6',
            'use_anglo_saxon': False,
            # Pas de propriétés property_stock_account_* : établissement de crédit, pas de
            # stock physique dans le plan PCEC (contrairement au PCG générique).
            'property_account_receivable_id': 'pcec_201',
            'property_account_payable_id': 'pcec_315',
            'property_account_expense_categ_id': 'pcec_649',
            'property_account_income_categ_id': 'pcec_749',
        }

    @template('mg_pcec', 'res.company')
    def _get_mg_pcec_res_company(self):
        return {
            self.env.company.id: {
                'account_fiscal_country_id': 'base.mg',
                # PCEC inverse trésorerie/capitaux propres par rapport au PCG générique : la
                # trésorerie (caisse, Banque Centrale, établissements de crédit) est en classe 1,
                # pas en classe 5. bank_account_code_prefix pointe donc vers 13 (comptes ordinaires
                # auprès des établissements de crédit correspondants) et cash_account_code_prefix
                # vers 10 (valeurs en caisse), au lieu de 51/53 dans le PCG.
                'bank_account_code_prefix': '13',
                'cash_account_code_prefix': '10',
                # 335 "Virements internes" (classe 3, comptes d'encaissement) : pas d'équivalent
                # direct du "58 Virements internes" du PCG générique dans la nomenclature PCEC
                # classes 1-7 fournie ; compte le plus proche fonctionnellement.
                'transfer_account_code_prefix': '335',
                'income_currency_exchange_account_id': 'pcec_731',
                'expense_currency_exchange_account_id': 'pcec_631',
                # Pas de poste PCEC dédié à l'escompte de règlement ni aux écarts de caisse :
                # repli sur les comptes génériques "autres charges/produits opérationnels divers"
                # (649/749), à affiner si CEFOR utilise réellement ces mécanismes.
                'account_journal_early_pay_discount_loss_account_id': 'pcec_649',
                'account_journal_early_pay_discount_gain_account_id': 'pcec_749',
                'account_journal_suspense_account_id': 'pcec_335',
                'default_cash_difference_income_account_id': 'pcec_749',
                'default_cash_difference_expense_account_id': 'pcec_649',
                'account_sale_tax_id': 'tva_collectee_20',
                'account_purchase_tax_id': 'tva_deductible_bs_20',
            }
        }
