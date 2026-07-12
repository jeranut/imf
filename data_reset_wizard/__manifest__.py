# -*- coding: utf-8 -*-
{
    'name': 'Data Reset Wizard (RAZ multi-société)',
    'version': '17.0.1.0.0',
    'category': 'Tools',
    'summary': "Assistant de remise à zéro des transactions (commandes, factures, "
               "paiements, stock) par société, en conservant produits/UdM/config.",
    'description': """
Assistant de RAZ (remise a zero) des donnees transactionnelles.

Permet de vider, societe par societe, sans toucher aux produits, unites de
mesure, ni a la configuration. Sont concernes : les paiements (account.payment),
les liens de facturation inter-societe (auto_invoice_id), les factures et
avoirs (account.move), les commandes fournisseurs (purchase.order), les
commandes clients (sale.order), les mouvements et transferts de stock
(stock.picking, stock.move, stock.move.line) ainsi que les quantites en
stock (stock.quant).

Fonctionne en deux temps. Le mode simulation (dry-run) execute tout dans
une transaction annulee automatiquement (savepoint puis rollback), afin de
voir les volumes concernes et detecter d'eventuels blocages, sans rien
modifier. Le mode execution reelle necessite de cocher une case de
confirmation et de retaper un mot de confirmation ; il effectue alors les
suppressions et valide (commit).

Attention : module reserve aux administrateurs techniques. Toujours faire
un backup complet de la base avant toute execution reelle, cette action
etant irreversible.

Un verrou anti-concurrence (advisory lock PostgreSQL) empeche deux
executions du wizard de tourner en meme temps, que ce soit dans deux
onglets du meme utilisateur ou par deux utilisateurs differents. Si une
operation est deja en cours, toute tentative de demarrer ou de faire
avancer une autre operation affiche un message d'erreur clair au lieu de
provoquer un blocage de lignes en base de donnees.
    """,
    'author': 'Micka',
    'license': 'LGPL-3',
    'depends': ['base', 'web', 'account', 'sale', 'purchase', 'stock',
                'hr_expense', 'custom_paid_totals'],
    'data': [
        'security/ir.model.access.csv',
        'wizard/data_reset_wizard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'data_reset_wizard/static/src/js/auto_runner.js',
            'data_reset_wizard/static/src/xml/auto_runner.xml',
        ],
    },
    'installable': True,
    'application': False,
}
