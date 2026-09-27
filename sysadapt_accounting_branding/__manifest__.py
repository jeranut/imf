{
    'name': 'SysAdaptPro - Branding Comptabilité',
    'version': '17.0.1.0.0',
    'category': 'Accounting/Accounting',
    'summary': "Affiche l'application account comme « Comptabilité » avec l'icône comptabilité",
    'description': """
Branding Comptabilité
=====================
Renomme le menu racine ``account.menu_finance`` (« Facturation » / « Invoicing »)
en « Comptabilité » et lui donne une icône dédiée, sans modifier les modules
``account`` ni ``base_accounting_kit``.

Maintenance
-----------
Le menu ``account.menu_finance`` est un enregistrement du module ``account``
(``noupdate="0"``) : un ``-u account`` ou ``-u base_accounting_kit`` remet le
nom et l'icône d'origine. Après chaque mise à jour de l'un de ces modules :

    ./odoo-bin -d <base> -u sysadapt_accounting_branding --stop-after-init
""",
    'author': 'SysAdaptPro',
    'license': 'LGPL-3',
    'depends': ['account', 'base_accounting_kit'],
    'data': ['data/menu_data.xml'],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
}
