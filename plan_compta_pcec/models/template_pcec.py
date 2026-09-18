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
                # TODO valider avec CEFOR : bascule de pcec_335 vers pcec_301, comme
                # account_journal_suspense_account_id ci-dessous (voir synthese_audit_pcec.md
                # §1.2). 301 "Opérations entre siège et succursales/agences" est retenu comme
                # compte de liaison générique pour les virements internes CEFOR, malgré le
                # libellé "Virements internes" de 335 — à confirmer avec CEFOR.
                'transfer_account_code_prefix': '301',
                'income_currency_exchange_account_id': 'pcec_731',
                'expense_currency_exchange_account_id': 'pcec_631',
                # Pas de poste PCEC dédié à l'escompte de règlement ni aux écarts de caisse :
                # repli sur les comptes génériques "autres charges/produits opérationnels divers"
                # (649/749), à affiner si CEFOR utilise réellement ces mécanismes.
                'account_journal_early_pay_discount_loss_account_id': 'pcec_649',
                'account_journal_early_pay_discount_gain_account_id': 'pcec_749',
                # TODO valider avec CEFOR : bascule de pcec_335 vers pcec_301, comme
                # transfer_account_code_prefix ci-dessus. 335 "Virements internes" n'est pas un
                # compte de suspens de journal générique. 301 "Opérations entre siège et
                # succursales/agences" est retenu comme équivalent PCEC (voir
                # synthese_audit_pcec.md §1.2).
                'account_journal_suspense_account_id': 'pcec_301',
                'default_cash_difference_income_account_id': 'pcec_749',
                'default_cash_difference_expense_account_id': 'pcec_649',
                'account_sale_tax_id': 'tva_collectee_20',
                'account_purchase_tax_id': 'tva_deductible_bs_20',
            }
        }
