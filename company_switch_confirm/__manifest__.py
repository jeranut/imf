{
    'name': "Company Switch Confirm",
    'version': '17.0.1.0.0',
    'summary': "Ajoute un bouton Confirmer/Réinitialiser au sélecteur multi-société",
    'description': """
Le sélecteur multi-société du systray applique chaque coche de société
immédiatement (avec un court debounce natif). Ce module bufferise les
clics et n'applique le changement qu'au clic sur "Confirmer", avec un
bouton "Réinitialiser" pour revenir à la sélection active.
""",
    'category': 'Extra Tools',
    'depends': ['web'],
    'assets': {
        'web.assets_backend': [
            'company_switch_confirm/static/src/switch_company_menu_patch.js',
            'company_switch_confirm/static/src/switch_company_menu_patch.xml',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
