# -*- coding: utf-8 -*-
{
    'name': 'MOWGLI - Paie CEFOR (PCEC)',
    'version': '17.0.3.1.0',
    'category': 'Human Resources',
    'summary': "Corrections, règle Net imposable, synchronisation "
               "multi-agences et alignement des comptes PCEC pour la "
               "structure de paie BASE (CEFOR), sans modifier "
               "hr_payroll_community",
    'author': 'MOWGLI',
    'depends': ['hr_payroll_community', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'data/hr_payroll_rules_data.xml',
        'views/hr_payroll_structure_views.xml',
        'views/report_payslip_templates.xml',
        'views/report_paperformat.xml',
        'wizard/mowgli_payroll_sync_wizard_views.xml',
    ],
    'installable': True,
    'application': False,
}
