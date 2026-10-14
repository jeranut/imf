# -*- coding: utf-8 -*-
{
    'name': 'MOWGLI - Cotisations et charges sociales de paie',
    'version': '17.0.1.0.0',
    'category': 'Human Resources',
    'summary': "Journal Charges sociales (CSOC), écriture patronale à la "
               "validation du bulletin et registre des cotisations par "
               "organisme (CNaPS, OSTIE, IRSA)",
    'author': 'MOWGLI',
    'license': 'LGPL-3',
    'depends': ['mowgli_payroll_pcec', 'account'],
    'data': [
        'security/ir.model.access.csv',
        'security/mowgli_payroll_contributions_security.xml',
        'data/mowgli_payroll_contributions_data.xml',
        'views/mowgli_payroll_contribution_views.xml',
        'wizard/mowgli_payroll_contribution_wizard_views.xml',
    ],
    'installable': True,
    'application': False,
}
