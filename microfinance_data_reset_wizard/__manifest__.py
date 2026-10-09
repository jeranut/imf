# -*- coding: utf-8 -*-
{
    'name': 'RAZ Microfinance (multi-agence)',
    'version': '17.0.1.1.0',
    'category': 'Tools',
    'summary': "Assistant de remise à zéro des données transactionnelles microfinance "
               "(dossiers d'instruction, crédits, épargne, comptabilité) par agence.",
    'description': """
Assistant de RAZ des données transactionnelles microfinance, agence par agence.

Vide, pour les agences (res.company) sélectionnées : les dossiers d'instruction
et leurs sous-lignes (visites terrain, section financière, documents, garant),
les crédits et leur échéancier, les comptes crédit conteneurs (historique par
client), les remboursements, les transferts de remboursement inter-agences (si
le module microfinance_transfert_inter_agence est installé), les visites de
recouvrement, les garanties et lignes de scoring liées, l'historique de
rééchelonnement, les comptes et transactions d'épargne, ainsi que les
écritures comptables (account.move) générées par ces opérations (décaissement,
remboursement, frais, radiation, dépôt/retrait d'épargne).

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

Inclut un second wizard, indépendant, de purge des fonds de crédit rotatif
(microfinance.fond.credit) — contributions, allocations et partages
associés supprimés avec le fonds (contraintes FK ondelete='restrict'), les
écritures comptables déjà postées étant toujours conservées. Réservé au
groupe métier group_microfinance_manager (pas group_system) : DRY-RUN par
défaut, verrouillé en plus par le paramètre système
microfinance.fond_credit_purge_apply (à activer explicitement pour une
exécution réelle). Cf. docs_dev/fond_credit/AUDIT_suppression_fonds.md du
module microfinance_loan_management. Cet ancien assistant n'a plus de menu.

Purge des fonds (crédit ET exploitation) : menu « Purge des fonds », réservé à
l'administrateur technique. Remet à zéro (garde le fonds) ou supprime le fonds,
avec ses contributions, partages, allocations, répartitions et écritures
comptables LIÉES (par les champs de lien, jamais par libellé) : extourne (défaut)
ou suppression des écritures de test (si microfinance.raz_environnement_test =
True), écritures miroirs des agences, rapprochements bancaires défaits (lignes de
relevé remises à traiter), compte d'origine automatique archivé. Simulation
obligatoire de la même sélection, mot PURGER, paramètre
microfinance.fond_credit_purge_apply, transaction unique avec rollback complet,
arrêt avant toute suppression si une clé étrangère inconnue bloque, soldes de
contrôle et journal d'audit conservé (menu « Journal des purges de fonds »).
    """,
    'author': 'Micka',
    'license': 'LGPL-3',
    # Ne dépend PAS de microfinance_transfert_inter_agence, alors que le bloc
    # do_transfert_remboursement (wizard/microfinance_data_reset_wizard.py) traite
    # microfinance.transfert.remboursement : ce module est optionnel (bases EAT/MIIA
    # sans transferts inter-agences), donc dépendance dure évitée. Le wizard vérifie
    # 'microfinance.transfert.remboursement' in self.env avant de l'utiliser.
    'depends': [
        'base', 'web', 'account',
        'microfinance_loan_management',
        'microfinance_savings_management',
    ],
    'data': [
        'security/ir.model.access.csv',
        'wizard/microfinance_data_reset_wizard_views.xml',
        'wizard/microfinance_fond_credit_purge_wizard_views.xml',
        'wizard/microfinance_fond_purge_wizard_views.xml',
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
