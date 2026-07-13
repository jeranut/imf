# -*- coding: utf-8 -*-
{
    'name': 'RAZ Microfinance (multi-agence)',
    'version': '17.0.1.0.0',
    'category': 'Tools',
    'summary': "Assistant de remise à zéro des données transactionnelles microfinance "
               "(crédits, épargne, comptabilité) par agence.",
    'description': """
Assistant de RAZ des données transactionnelles microfinance, agence par agence.

Vide, pour les agences (res.company) sélectionnées : les crédits et leur
échéancier, les remboursements, les visites de recouvrement, les garanties et
lignes de scoring liées, l'historique de rééchelonnement, les comptes et
transactions d'épargne, ainsi que les écritures comptables (account.move)
générées par ces opérations (décaissement, remboursement, frais, radiation,
dépôt/retrait d'épargne).

Ne touche JAMAIS : les clients (res.partner, territoire partagé avec les
autres activités de cette instance), les produits de crédit/épargne, les
profils/règles de scoring et de valorisation des garanties (configuration,
pas des instances), le plan comptable PCEC, les journaux, les séquences,
les groupes de sécurité, la configuration des sociétés, ni les liens
d'adhésion aux groupes de clients (microfinance.client.group.member).

Fonctionne en deux temps. Le mode simulation (dry-run) exécute tout dans une
transaction annulée automatiquement (savepoint puis rollback), afin de voir
les volumes concernés et détecter d'éventuels blocages sans rien modifier.
Le mode exécution réelle nécessite de cocher une case de confirmation et de
retaper le mot "SUPPRIMER" ; il effectue alors les suppressions et valide
(commit) par lot, de façon reprenable en cas d'interruption.

Un verrou anti-concurrence (advisory lock PostgreSQL) dédié à ce wizard
empêche deux exécutions de tourner en même temps. Il utilise une clé propre,
différente de celle du RAZ générique existant (data_reset_wizard, module EAT)
car les deux tournent sur des bases Postgres distinctes bien que partageant
le même cluster : réutiliser la même clé créerait un blocage croisé sans
rapport avec un vrai conflit de données.

Réservé aux administrateurs techniques (base.group_system) — outil
d'administration technique, pas un outil métier accessible aux gestionnaires
microfinance. Toujours faire un backup complet avant toute exécution réelle :
action irréversible.
    """,
    'author': 'Micka',
    'license': 'LGPL-3',
    'depends': [
        'base', 'web', 'account',
        'microfinance_loan_management',
        'microfinance_savings_management',
    ],
    'data': [
        'security/ir.model.access.csv',
        'wizard/microfinance_data_reset_wizard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'microfinance_data_reset_wizard/static/src/js/auto_runner.js',
            'microfinance_data_reset_wizard/static/src/xml/auto_runner.xml',
        ],
    },
    'installable': True,
    'application': False,
}
