# -*- coding: utf-8 -*-
{
    'name': 'MOWGLI - Comptes de paie par société',
    'version': '17.0.1.0.0',
    'category': 'Human Resources',
    'summary': "Comptes des règles de salaire (rémunérations, CNaPS, OSTIE, "
               "IRSA, personnel) créés et configurés pour chaque société, "
               "y compris les agences créées plus tard",
    'author': 'MOWGLI',
    'license': 'LGPL-3',
    'depends': ['mowgli_payroll_pcec', 'mowgli_payroll_contributions', 'account'],
    'data': [
        'data/mowgli_payroll_accounts_data.xml',
    ],
    'installable': True,
    'application': False,
}
