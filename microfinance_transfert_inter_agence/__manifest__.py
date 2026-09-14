# -*- coding: utf-8 -*-
{
    'name': 'Microfinance — Transfert de fonds inter-agences',
    'version': '17.0.1.0.0',
    'category': 'Accounting/Finance',
    'summary': "Remboursement d'un crédit dans une agence autre que l'agence "
               "propriétaire : encaissement, mise en transit, rapatriement par "
               "coursier et validation du remboursement à l'agence destination.",
    'description': """
Transfert de fonds inter-agences — remboursement crédit
=======================================================================

Permet à un client de rembourser son crédit dans une agence CEFOR qui n'est pas
l'agence propriétaire du crédit. L'agence qui encaisse (source) accumule les
transferts, les regroupe en lots par agence destination, les remet à un coursier,
puis l'agence destination valide chaque ligne — ce qui déclenche la
comptabilisation réelle du remboursement sur le crédit.

Le compte PCEC 302000 « Opérations entre succursales/agences » sert de compte de
transit entre l'encaissement à la source et la remise à la destination.

Périmètre : remboursement crédit uniquement (l'extension épargne est prévue dans
la conception mais n'est pas implémentée).

Conception : docs_dev/guichet_caisse/AUDIT_transfert_inter_agence.md.
Mise en œuvre découpée en 6 sous-lots (A à F).

Sous-lot A : squelette du module + numérotation du code de transfert
(res.company._build_microfinance_transfer_code) et ses tests.

Sous-lot B : modèles microfinance.transfert.remboursement (le transfert unitaire)
et microfinance.transfert.lot (le regroupement remis au coursier), + l'ir.rule
d'exception qui les rend visibles des DEUX agences (source et destination).

Sous-lot C : comptabilisation. Journal « Transit inter-agences » (code TRANSIT,
compte 302000) créé par agence PCEC. Les 4 écritures du cycle (encaissement
source / remise au coursier / réception destination / remboursement) via des
primitives existantes (account.move de liaison, microfinance.loan.payment
inchangé sur le journal TRANSIT). Sudo comptable circonscrit à ce module. Droits
d'accès posés (caissier CRUD sans unlink, manager complet, finance/comptable/
auditeur lecture).

Sous-lot D : le guichet (patch OWL de MicrofinanceCaissePos, on ne quitte jamais
l'écran guichet). Deux points d'accroche :

1. POINT D'ENTRÉE d'un nouveau transfert = la barre de recherche principale.
   refreshOtherClients() est patché pour interroger AUSSI
   res.partner.search_other_agency_clients (sudo ciblé, retour minimal) et
   fusionner le résultat dans la section « Autres clients », avec un badge agence.
   Cliquer une ligne cross-agence -> mini-sélecteur du crédit
   (get_other_agency_client_loans) -> assistant de confirmation puis encaissement
   (register_transfert -> étape 1). search_caisse_clients et le flux des clients de
   l'agence courante sont inchangés ; register_operation reste mono-agence.

2. « Transfert » = 5e onglet de la LISTE CENTRALE (à côté de Décaissements en
   attente / Échéances du jour / Épargne en attente / Frais), UNIQUEMENT pour la
   gestion des lots : « à envoyer » = regrouper les transferts encaissés puis les
   remettre au coursier (action_create_lot / validate_lot -> étape 2) ; « à
   recevoir » = valider les transferts arrivés (validate_transfert_destination ->
   étapes 3 + 4).

Les tests du cycle complet multi-société (sous-lot F) restent à faire.
    """,
    'author': 'Micka',
    'license': 'LGPL-3',
    'depends': [
        'base', 'account',
        'microfinance_loan_management',
        'microfinance_savings_management',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/microfinance_transfert_rules.xml',
        'report/report_transfert_lot.xml',
        'wizard/microfinance_transfert_confirm_wizard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'microfinance_transfert_inter_agence/static/src/js/microfinance_caisse_pos_transfert.js',
            'microfinance_transfert_inter_agence/static/src/xml/microfinance_caisse_pos_transfert.xml',
            'microfinance_transfert_inter_agence/static/src/scss/microfinance_caisse_pos_transfert.scss',
        ],
    },
    'installable': True,
    'application': False,
    'post_init_hook': 'post_init_hook',
}
