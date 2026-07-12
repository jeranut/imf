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
    '325005': ("Produits reçus ou constatés d'avance - Intérêts comptabilisés d'avance individuel", 'liability_current', False),
    '325006': ("Produits reçus ou constatés d'avance - Intérêts comptabilisés d'avance groupe", 'liability_current', False),
    '325007': ("Produits reçus ou constatés d'avance - Intérêts comptabilisés d'avance entreprise", 'liability_current', False),
    '218001': ('Charges à payer comptes de la clientèle - Coût intérêt à payer individuel', 'liability_current', False),
    '218002': ('Charges à payer comptes de la clientèle - Coût intérêt à payer groupe', 'liability_current', False),
    '218003': ('Charges à payer comptes de la clientèle - Coût intérêt à payer entreprise', 'liability_current', False),
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


def post_init_hook(env):
    """Sur chaque société utilisant le plan PCEC (chart_template == 'mg_pcec'), crée les
    sous-comptes épargne dédiés par segment. Les journaux (dont EPG, utilisé par les défauts
    des champs journal_id dépôt/retrait) sont créés par microfinance_loan_management, dont ce
    module dépend."""
    for company in env['res.company'].search([]):
        if company.chart_template != 'mg_pcec':
            continue
        for code, (name, account_type, reconcile) in SAVINGS_NEW_SUBACCOUNTS.items():
            _get_or_create_account(env, company, code, name, account_type, reconcile)
