# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)

# Sous-comptes PCEC dédiés créés pour microfinance.savings.product, même logique que
# microfinance_loan_management/hooks.py::LOAN_NEW_SUBACCOUNTS (voir ce fichier pour le détail
# de la règle de génération). Familles partagées avec le module crédit (325, 717, 749) :
# suffixes choisis pour ne jamais collisionner avec ceux déjà utilisés côté crédit — voir
# audit_pcg2005_mapping/mapping_comptes_pcg2005_cefor.md pour la table complète.
# {code: (name, account_type, reconcile)}
SAVINGS_NEW_SUBACCOUNTS = {
    '213001': ("Compte d'épargne à régime spécial - Individuel", 'liability_current', True),
    '213002': ("Compte d'épargne à régime spécial - Groupe", 'liability_current', True),
    '213003': ("Compte d'épargne à régime spécial - Entreprise", 'liability_current', True),
    '607301': ("Charges d'intérêts comptes d'épargne à régime spécial - Individuel", 'expense', False),
    '607302': ("Charges d'intérêts comptes d'épargne à régime spécial - Groupe", 'expense', False),
    '607303': ("Charges d'intérêts comptes d'épargne à régime spécial - Entreprise", 'expense', False),
    '218001': ('Charges à payer comptes de la clientèle - Coût intérêt à payer individuel', 'liability_current', False),
    '218002': ('Charges à payer comptes de la clientèle - Coût intérêt à payer groupe', 'liability_current', False),
    '218003': ('Charges à payer comptes de la clientèle - Coût intérêt à payer entreprise', 'liability_current', False),
    # TODO valider avec CEFOR : remplace les anciens 325005/6/7 ("Produits reçus ou constatés
    # d'avance", retirés de cette table). Bascule vers 218 car ce sont des charges d'intérêt
    # épargne dues au client, pas un revenu différé — suffixes 004/005/006 choisis pour ne pas
    # collisionner avec 218001/2/3 ci-dessus (voir synthese_audit_pcec.md §2.1).
    '218004': ("Charges à payer comptes de la clientèle - Intérêts épargne comptabilisés d'avance individuel", 'liability_current', False),
    '218005': ("Charges à payer comptes de la clientèle - Intérêts épargne comptabilisés d'avance groupe", 'liability_current', False),
    '218006': ("Charges à payer comptes de la clientèle - Intérêts épargne comptabilisés d'avance entreprise", 'liability_current', False),
    '749003': ('Autres produits opérationnels divers - Pénalités épargne', 'income', False),
    '749004': ('Autres produits opérationnels divers - Papeterie épargne', 'income', False),
    '717004': ('Commissions perçues - Commission sur épargne', 'income', False),
    # 467000 n'appartient pas à la nomenclature PCEC classes 1-7 : aucun poste officiel ne
    # correspond à une retenue fiscale sur épargne. Compte technique ajouté par ce module,
    # documenté comme tel plutôt que rattaché silencieusement à une ligne PCEC existante.
    '467000': ('Autres comptes débiteurs/créditeurs - Retenues fiscales (compte technique, hors nomenclature PCEC)', 'liability_current', False),
}

# Champs dont la famille PCEC n'est utilisée que par ce seul champ : réutilisation directe.
SAVINGS_DIRECT_REUSE_CODES = {
    'account_commission_cheques_rejetes_id': '719000',
    # TODO valider avec CEFOR. Corrigé : 511200 n'est PAS un compte réel du plan PCEC (la classe 5
    # ne comporte aucune sous-classe bancaire — erreur de report depuis le PCG générique, où 511
    # désigne les valeurs à l'encaissement). Remplacé par 331120, poste 33112 "Chèques à
    # l'encaissement non disponibles" (classe 3, comptes d'encaissement), déjà présent dans le
    # plan PCEC de base chargé par plan_compta_pcec (pcec_33112) — pas besoin de sous-compte dédié
    # ici. Utilisé comme compte d'attente pour les dépôts par chèque (account_cheques_attente_id).
    'account_cheques_attente_id': '331120',
}


def _get_account(env, company, code):
    return env['account.account'].search([
        ('code', '=', code), ('company_id', '=', company.id),
    ], limit=1)


def _get_or_create_account(env, company, code, name, account_type, reconcile):
    account = _get_account(env, company, code)
    if account:
        return account
    return env['account.account'].create({
        'code': code,
        'name': name,
        'account_type': account_type,
        'reconcile': reconcile,
        'company_id': company.id,
    })


def provision_company_savings_accounts(env, company):
    """Crée idempotemment, pour une société sur le plan PCEC (chart_template == 'mg_pcec'),
    les sous-comptes épargne dédiés par segment (SAVINGS_NEW_SUBACCOUNTS : 213001/2/3 Épargne,
    607301/2/3 Intérêt payé, 218001/2/3 Coût intérêt à payer, 218004/5/6 Intérêts comptabilisés
    d'avance, 749003/4, 717004, 467000). Ne fait rien pour les sociétés sur un autre plan
    comptable.

    Source unique appelée par post_init_hook (installation neuve), par
    AccountChartTemplate._load() (chargement du plan PCEC sur une agence créée après
    l'installation du module — cf. models/account_chart_template.py) et par le script de
    migration post-migrate. Les journaux (dont EPG, utilisé par les défauts des champs
    journal_id dépôt/retrait) sont créés côté microfinance_loan_management, dont ce module
    dépend."""
    if not company or company.chart_template != 'mg_pcec':
        return
    for code, (name, account_type, reconcile) in SAVINGS_NEW_SUBACCOUNTS.items():
        _get_or_create_account(env, company, code, name, account_type, reconcile)


def post_init_hook(env):
    """Sur chaque société utilisant le plan PCEC (chart_template == 'mg_pcec'), crée les
    sous-comptes épargne dédiés par segment. Les journaux (dont EPG, utilisé par les défauts
    des champs journal_id dépôt/retrait) sont créés par microfinance_loan_management, dont ce
    module dépend."""
    for company in env['res.company'].search([]):
        provision_company_savings_accounts(env, company)
