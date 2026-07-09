# -*- coding: utf-8 -*-
{
    'name': 'Microfinance Savings Management',
    'version': '17.0.1.0.0',
    'summary': "Comptes et produits d'épargne, prélèvement automatique sur crédit",
    'description': "Produits d'épargne, comptes, transactions, capitalisation des intérêts, "
                   "prélèvement automatique sur échéance de crédit impayée, éligibilité progressive "
                   "au crédit basée sur l'épargne.",
    'category': 'Accounting/Finance',
    'author': 'SysAdaptPro',
    'website': 'https://sysadaptpro.com',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'account', 'microfinance_loan_management', 'base_accounting_kit'],
    'data': [
        'security/savings_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/ir_cron_data.xml',
        'report/savings_receipt_report.xml',
        'views/microfinance_savings_product_views.xml',
        'views/microfinance_savings_account_views.xml',
        'views/microfinance_savings_transaction_views.xml',
        'views/microfinance_loan_product_views_inherit.xml',
        'views/microfinance_loan_views_inherit.xml',
        'views/microfinance_loan_payment_views_inherit.xml',
        'views/res_partner_views_inherit.xml',
        'views/microfinance_savings_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'microfinance_savings_management/static/src/xml/microfinance_savings_dashboard.xml',
            'microfinance_savings_management/static/src/scss/microfinance_savings_dashboard.scss',
        ],
    },
    'application': False,
    'installable': True,
}
