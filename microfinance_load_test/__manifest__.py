# -*- coding: utf-8 -*-
# NE JAMAIS INSTALLER EN PRODUCTION — génère des clients et crédits factices qui
# polluent la base et les statistiques métier. Module de dev/staging uniquement,
# jamais une dépendance d'un module de production, à installer/désinstaller
# manuellement sur une instance de dev.
{
    'name': 'Microfinance Load Test',
    'version': '17.0.1.0.0',
    'summary': 'Génération en un clic de clients/crédits factices pour tests manuels (dev/staging uniquement)',
    'description': (
        "NE JAMAIS INSTALLER EN PRODUCTION.\n\n"
        "Ajoute un wizard 'Load test' qui crée un client factice et un crédit factice, "
        "poussé automatiquement jusqu'à l'état 'avis_ca', pour éviter de ressaisir "
        "manuellement les données à chaque test du workflow crédit."
    ),
    'category': 'Accounting/Finance',
    'author': 'SysAdaptPro',
    'website': 'https://sysadaptpro.com',
    'license': 'LGPL-3',
    'depends': ['microfinance_loan_management'],
    'data': [
        'security/groups.xml',
        'security/ir.model.access.csv',
        'views/microfinance_load_test_wizard_views.xml',
    ],
    'application': False,
    'installable': True,
    'auto_install': False,
}
