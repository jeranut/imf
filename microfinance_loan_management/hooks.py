# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)

# Sous-comptes PCEC dédiés créés pour microfinance.loan.product : un compte par segment
# (Individuel/Groupe) plutôt qu'un compte "famille" PCEC partagé entre segments, et un compte
# dédié par champ quand plusieurs champs partagent la même famille PCEC (208, 325, 717, 749 —
# voir microfinance_loan_management/audit_pcg2005_mapping/mapping_comptes_pcg2005_cefor.md).
# Table figée : ne pas générer ces codes par incrémentation indépendante ailleurs dans le code,
# c'est la seule source de vérité pour éviter une collision entre deux champs différents.
# {code: (name, account_type, reconcile)}
LOAN_NEW_SUBACCOUNTS = {
    '203001': ('Crédits de trésorerie - Principal individuel', 'asset_receivable', True),
    '203002': ('Crédits de trésorerie - Principal groupe', 'asset_receivable', True),
    '641201': ('Pertes sur prêts et avances non couverts par provisions - Individuel', 'expense', False),
    '641202': ('Pertes sur prêts et avances non couverts par provisions - Groupe', 'expense', False),
    '273001': ('Créances litigieuses/douteuses crédits de trésorerie - Individuel', 'asset_current', True),
    '273002': ('Créances litigieuses/douteuses crédits de trésorerie - Groupe', 'asset_current', True),
    '293001': ('Pertes de valeur sur avances et prêts crédits de trésorerie - Individuel', 'asset_current', False),
    '293002': ('Pertes de valeur sur avances et prêts crédits de trésorerie - Groupe', 'asset_current', False),
    '682201': ('Dotations pertes de valeur opérations clientèle - Individuel', 'expense', False),
    '682202': ('Dotations pertes de valeur opérations clientèle - Groupe', 'expense', False),
    '707301': ("Produits d'intérêts crédits de trésorerie - Individuel", 'income', False),
    '707302': ("Produits d'intérêts crédits de trésorerie - Groupe", 'income', False),
    '208001': ('Produits à recevoir - Intérêts échus individuel', 'asset_current', False),
    '208002': ('Produits à recevoir - Intérêts échus groupe', 'asset_current', False),
    '208003': ('Produits à recevoir - Intérêts échus à recevoir individuel', 'asset_current', False),
    '208004': ('Produits à recevoir - Intérêts échus à recevoir groupe', 'asset_current', False),
    '325001': ("Produits reçus ou constatés d'avance - Pénalités comptabilisées d'avance individuel", 'liability_current', False),
    '325002': ("Produits reçus ou constatés d'avance - Pénalités comptabilisées d'avance groupe", 'liability_current', False),
    '326101': ('Produits réservés sur échéances de crédit non imputées - Revenu pénalités avance individuel', 'income', False),
    '326102': ('Produits réservés sur échéances de crédit non imputées - Revenu pénalités avance groupe', 'income', False),
    '325003': ("Produits reçus ou constatés d'avance - Commissions échues accumulées individuel", 'liability_current', False),
    '325004': ("Produits reçus ou constatés d'avance - Commissions échues accumulées groupe", 'liability_current', False),
    '717001': ('Commissions perçues - Commissions accumulées gagnées individuel', 'income', False),
    '717002': ('Commissions perçues - Commissions accumulées gagnées groupe', 'income', False),
    '717003': ('Commissions perçues - Commission sur crédit', 'income', False),
    '749001': ('Autres produits opérationnels divers - Papeterie crédit', 'income', False),
    '749002': ('Autres produits opérationnels divers - Pénalités crédits', 'income', False),
    # Sous-comptes de la classe 13 (Établissements de crédit) dédiés aux 3 journaux banque.
    '131001': ('Établissements de crédit - Banque opérations', 'asset_cash', False),
    '131002': ('Établissements de crédit - Banque épargne', 'asset_cash', False),
    '131003': ('Établissements de crédit - Banque crédits', 'asset_cash', False),
}

# Champs dont la famille PCEC n'est utilisée que par ce seul champ : réutilisation directe du
# compte déjà chargé par plan_compta_pcec, sans création de sous-compte dédié.
LOAN_DIRECT_REUSE_CODES = {
    'account_recouvrement_id': '741000',
    'account_surpaiement_id': '315000',
}

# Journaux créés pour chaque société utilisant le plan PCEC (chart_template == 'mg_pcec').
# (code, name, type, compte par défaut ou None)
JOURNALS = [
    ('BQOP', 'Banque - Opérations', 'bank', '131001'),
    ('BQEP', 'Banque - Épargne', 'bank', '131002'),
    ('BQCR', 'Banque - Crédits', 'bank', '131003'),
    ('CAI', 'Caisse', 'cash', '101000'),
    ('CRE', 'Crédits', 'general', None),
    ('EPG', 'Épargne', 'general', None),
    ('OD', 'Opérations diverses', 'general', None),
]


def _get_account(env, company, code):
    return env['account.account'].search([
        ('code', '=', code), ('company_id', '=', company.id),
    ], limit=1)


def _get_account_or_warn(env, company, code):
    account = _get_account(env, company, code)
    if not account:
        _logger.warning(
            "Microfinance PCEC : compte %s introuvable pour la société %s (id=%s) — "
            "le journal ou le champ correspondant restera sans compte par défaut. "
            "Le plan PCEC (plan_compta_pcec) est-il bien chargé sur cette société ?",
            code, company.name, company.id,
        )
    return account


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


def _create_subaccounts(env, company, subaccounts):
    for code, (name, account_type, reconcile) in subaccounts.items():
        _get_or_create_account(env, company, code, name, account_type, reconcile)


def _create_journals(env, company):
    Journal = env['account.journal']
    for code, name, journal_type, account_code in JOURNALS:
        if Journal.search_count([('code', '=', code), ('company_id', '=', company.id)]):
            continue
        vals = {'name': name, 'code': code, 'type': journal_type, 'company_id': company.id}
        if account_code:
            account = _get_account_or_warn(env, company, account_code)
            if account:
                vals['default_account_id'] = account.id
        Journal.create(vals)


# Agences CEFOR déjà identifiées au moment de l'introduction du champ agency_code (liste non
# exhaustive, 25 agences prévues au total — les suivantes sont ajoutées manuellement par
# l'utilisateur via le formulaire société). Matching par nom exact, jamais par ID statique (ces
# sociétés existaient déjà en base avant ce module).
KNOWN_AGENCY_CODES = {
    'CEFOR Isotry': 'IS',
    'CEFOR Ambanidia': 'BD',
    'CEFOR Ampitatafika': 'SY',
    'CEFOR Andranonahoatra': 'TA',
    'CEFOR Sabotsy Namehana': 'SB',
    'CEFOR Mahitsy': 'MA',
    'CEFOR Tsaramasay': 'TS',
    'CEFOR Ambohitrimanjaka': 'KA',
    'CEFOR Andoharanofotsy': 'AD',
    'CEFOR Ambohimanarina': 'BM',
    'CEFOR Andravoahangy': 'GY',
}


def _seed_known_agency_codes(env):
    for name, code in KNOWN_AGENCY_CODES.items():
        company = env['res.company'].search([('name', '=', name), ('agency_code', '=', False)], limit=1)
        if company:
            company.agency_code = code


def post_init_hook(env):
    """Sur chaque société utilisant le plan PCEC (plan_compta_pcec, chart_template ==
    'mg_pcec'), crée les sous-comptes dédiés par segment et les 7 journaux standards. Les
    sociétés utilisant un autre plan comptable ne sont pas modifiées (aucun compte au format
    PCEC n'a de sens en dehors de ce plan)."""
    for company in env['res.company'].search([]):
        if company.chart_template != 'mg_pcec':
            continue
        _create_subaccounts(env, company, LOAN_NEW_SUBACCOUNTS)
        _create_journals(env, company)
    _seed_known_agency_codes(env)
