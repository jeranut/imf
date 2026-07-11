# -*- coding: utf-8 -*-
{
    'name': 'MOWGLI - Assistant microfinance CEFOR',
    'version': '17.0.1.0.0',
    'summary': 'MOWGLI (Microfinance Operations With Generative Learning Intelligence) — centre d’aide métier CEFOR par workflows et datasets validés',
    'description': """
MOWGLI (Microfinance Operations With Generative Learning Intelligence) est le
centre d'aide métier CEFOR pour microfinance_loan_management et
microfinance_savings_management.

Le module fournit une base de connaissance synchronisée depuis des datasets YAML
externes, des suggestions adaptées dans Discuss et une conversation temporaire avec
nettoyage de l'historique MOWGLI utilisateur.
    """,
    'category': 'Productivity',
    'author': 'SystAdaptpro',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'web', 'web_responsive'],
    'data': [
        'security/groups.xml',
        'security/ir.model.access.csv',
        'views/knowledge_views.xml',
        'views/dev_status_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'microfinance_mowgli_assistant/static/src/js/mowgli_discuss_integration.js',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': True,
}
