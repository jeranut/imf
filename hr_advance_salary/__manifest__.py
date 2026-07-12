{
    'name': 'HR Advance Salary',
    'version': '1.0',
    'summary': 'Gestion des avances sur salaire',
    'category': 'Human Resources',
    'author': 'SYSADAPTPRO',
    'depends': ['hr', 'payroll'],
    'data': [
        'security/ir.model.access.csv',
        'views/hr_advance_view.xml',
        'views/hr_payslip_view.xml',
    ],
    'installable': True,
    'application': True,
}
