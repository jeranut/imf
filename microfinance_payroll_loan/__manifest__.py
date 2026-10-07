# -*- coding: utf-8 -*-
{
    'name': 'Microfinance - Avances sur salaire (passerelle paie)',
    'version': '17.0.1.0.0',
    'category': 'Human Resources',
    'summary': "Passerelle entre la paie (MOWGLI) et le circuit crédit microfinance : "
               "avance spéciale employé, retenue sur bulletin.",
    'description': (
        "Addon passerelle : ne modifie ni hr_payroll_community, ni mowgli_payroll_pcec. "
        "Dans microfinance_loan_management, se limite à 2 ajouts génériques et non cassants "
        "dans le dashboard (static/src/js/microfinance_loan_dashboard.js : méthode "
        "formatPortfolioTabLabel ; XML : son appel à la place de tab.label) — nécessaires "
        "pour qu'un onglet ajouté PAR PATCH depuis ce module (clients_a_traiter, cf. "
        "static/src/js/microfinance_loan_dashboard_patch.js) puisse afficher un compteur. "
        "Ajoute :\n"
        "- un bouton « Avance spéciale » sur la fiche employé, qui crée/rattache le client "
        "microfinance au portefeuille d'un agent de crédit choisi (le wizard ne crée jamais "
        "de demande de crédit) ;\n"
        "- un flag « Autorisé pour les employés » sur le produit de prêt (strictement "
        "mensuel) ;\n"
        "- un flag « Retenue sur salaire » sur la demande et le prêt ;\n"
        "- (Lot 2) la retenue automatique sur bulletin de paie et la comptabilisation du "
        "remboursement microfinance correspondant ;\n"
        "- l'onglet « Clients à traiter » du portefeuille agent (clients rattachés sans "
        "prêt, complément exact de « Mes clients »)."
    ),
    'author': 'Mickael',
    'depends': ['hr', 'hr_payroll_community', 'mowgli_payroll_pcec', 'microfinance_loan_management'],
    'assets': {
        'web.assets_backend': [
            'microfinance_payroll_loan/static/src/js/microfinance_loan_dashboard_patch.js',
        ],
    },
    'data': [
        'security/ir.model.access.csv',
        'views/hr_employee_views.xml',
        'views/microfinance_payroll_advance_wizard_views.xml',
        'views/microfinance_loan_product_views.xml',
        'views/microfinance_loan_views.xml',
        'views/microfinance_loan_application_views.xml',
        'views/microfinance_loan_regularization_views.xml',
        'views/hr_payslip_views.xml',
        'data/hr_payroll_rules_data.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
}
