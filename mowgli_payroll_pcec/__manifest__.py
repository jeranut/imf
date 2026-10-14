# -*- coding: utf-8 -*-
{
    'name': 'MOWGLI - Paie CEFOR (PCEC)',
    'version': '17.0.4.0.0',
    'category': 'Human Resources',
    'summary': "Structure et règles de paie partagées entre agences, "
               "comptes débit/crédit résolus par société (création "
               "automatique en filet), règle Net imposable, alignement "
               "PCEC (CEFOR)",
    'author': 'MOWGLI',
    'depends': ['hr_payroll_community', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'security/hr_payroll_security.xml',
        'data/mowgli_payroll_param_data.xml',
        'data/hr_payroll_rules_data.xml',
        'views/mowgli_payroll_param_views.xml',
        'views/hr_payroll_structure_views.xml',
        'views/hr_salary_rule_views.xml',
        'views/account_account_views.xml',
        'views/report_payslip_templates.xml',
        'views/report_paperformat.xml',
        'wizard/mowgli_payroll_sync_wizard_views.xml',
    ],
    'installable': True,
    'application': False,
}
