# -*- coding: utf-8 -*-
import csv
import logging
import os

_logger = logging.getLogger(__name__)

GEO_DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
GEO_MODULE = 'microfinance_loan_management'

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
# CRE et EPG doivent rester de type 'cash' (jamais 'general') : ce sont les journaux retournés
# par _journal_default('CRE')/_journal_default('EPG') (microfinance_loan_product.py,
# microfinance_savings_product.py), utilisés comme valeur par défaut de champs dont le domaine
# de vue exige ('type', 'in', ('bank', 'cash')) — disbursement_journal_id, payment_journal_id,
# fee_journal_id côté crédit, deposit_journal_id, withdrawal_journal_id côté épargne. Un journal
# 'general' ne satisfait pas ce domaine (cf. docs_dev/gestion_caisse/AUDIT.md §1.3). OD reste
# 'general' : jamais utilisé comme défaut de ces champs, réservé aux écritures diverses
# (radiation, provision — cf. _prepare_writeoff_move/_prepare_provision_move dans
# microfinance_loan.py, qui recherchent dynamiquement le journal 'general' de la société).
JOURNALS = [
    ('BQOP', 'Banque - Opérations', 'bank', '131001'),
    ('BQEP', 'Banque - Épargne', 'bank', '131002'),
    ('BQCR', 'Banque - Crédits', 'bank', '131003'),
    ('CAI', 'Caisse', 'cash', '101000'),
    ('CRE', 'Crédits', 'cash', None),
    ('EPG', 'Épargne', 'cash', None),
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


def _seed_agency_partner_type(env):
    """Backfill microfinance_partner_type='agence' sur les partners des sociétés déjà en base
    (create()/write() ne couvrent que les sociétés créées/modifiées après ce chantier). Non
    destructif : ne touche que les sociétés ayant déjà un agency_code, écrit uniquement si la
    valeur diffère."""
    companies = env['res.company'].search([('agency_code', '!=', False)])
    companies.mapped('partner_id').filtered(
        lambda p: p.microfinance_partner_type != 'agence'
    ).write({'microfinance_partner_type': 'agence'})


def _backfill_existing_client_partner_type(env):
    """Backfill microfinance_partner_type='client' pour les partners déjà créés via l'ancien
    menu Clients (sans domaine) avant l'introduction de ce champ : sinon le menu Clients tombe à
    zéro résultat juste après la migration.

    Candidat = partner avec company_id renseigné sur une agence CEFOR (agency_code non vide) ET
    pas encore typé. La seule condition "company_id sur une agence" ne suffit pas : les partners
    techniques (OdooBot, l'utilisateur admin, tout compte res.users) portent eux aussi un
    company_id d'agence par défaut sans être des clients — on les exclut explicitement en
    vérifiant qu'aucun res.users ne pointe vers ce partner."""
    Partner = env['res.partner']
    agency_ids = env['res.company'].search([('agency_code', '!=', False)]).ids
    user_partner_ids = env['res.users'].search([]).mapped('partner_id').ids
    candidates = Partner.search([
        ('company_id', 'in', agency_ids),
        ('microfinance_partner_type', '=', False),
        ('id', 'not in', user_partner_ids),
    ])
    candidates.write({'microfinance_partner_type': 'client'})


def _backfill_bailleur_partner_ids(env):
    """Rattache un res.partner (créé à la volée) à tout microfinance.bailleur.fonds existant
    sans partner_id — nécessaire dès qu'au moins un enregistrement a été créé avant l'ajout de ce
    champ required, sinon la fiche reste bloquée en écriture (champ requis vide)."""
    Bailleur = env['microfinance.bailleur.fonds'].with_context(active_test=False)
    orphans = Bailleur.search([('partner_id', '=', False)])
    for bailleur in orphans:
        partner = env['res.partner'].create({
            'name': bailleur.name,
            'microfinance_partner_type': 'bailleur',
            'company_id': False,
        })
        bailleur.partner_id = partner.id


def _read_geo_csv(filename):
    path = os.path.join(GEO_DATA_DIR, filename)
    with open(path, encoding='utf-8') as f:
        return list(csv.DictReader(f))


def _force_geo_noupdate(env, xml_ids):
    """_load_records(noupdate=True) ne pose ce flag que sur les ir.model.data nouvellement
    créés : la requête ON CONFLICT sous-jacente (_update_xmlids) ne touche jamais la colonne
    noupdate d'une ligne déjà existante. Sans ce correctif, les xml_ids déjà chargés une première
    fois (via l'ancien mécanisme CSV de la clé 'data', qui les avait créés en noupdate=False)
    resteraient réécrasables indéfiniment par un futur appel de ce hook."""
    if not xml_ids:
        return
    env.cr.execute(
        "UPDATE ir_model_data SET noupdate = TRUE "
        "WHERE module = %s AND name = ANY(%s) AND NOT noupdate",
        (GEO_MODULE, list(xml_ids)),
    )


def _load_geo_communes(env):
    """Charge le référentiel des communes BCM depuis data/microfinance.geo.commune.csv, sous
    forme de xml_ids noupdate=True gérés programmatiquement (et non plus via la clé 'data' du
    manifeste) : un futur -u ne doit pas écraser une correction manuelle faite en base sur une
    commune déjà chargée. _load_records(update=True) est l'API moderne équivalente à l'ancien
    ir.model.data._update() (retiré des versions récentes d'Odoo) — elle détecte les xml_ids déjà
    présents et, pour ceux marqués noupdate, ne réapplique pas les valeurs du CSV dessus.

    Deux passes nécessaires car parent_city_id référence une autre ligne du même fichier,
    potentiellement pas encore créée au moment où sa ligne est lue (ex: Antananarivo I peut
    précéder ou suivre ANTANANARIVO selon l'ordre du CSV)."""
    Commune = env['microfinance.geo.commune']
    rows = _read_geo_csv('microfinance.geo.commune.csv')

    # Passe 1 : créer/synchroniser toutes les communes sans parent_city_id.
    data_list = [{
        'xml_id': f'{GEO_MODULE}.{row["id"]}',
        'values': {'code': row['code'] or False, 'name': row['name']},
        'noupdate': True,
    } for row in rows]
    Commune._load_records(data_list, update=True)
    _force_geo_noupdate(env, [row['id'] for row in rows])

    # Passe 2 : poser parent_city_id maintenant que toutes les communes existent.
    linked = 0
    for row in rows:
        parent_xml_id = row.get('parent_city_id/id')
        if not parent_xml_id:
            continue
        commune = env.ref(f'{GEO_MODULE}.{row["id"]}', raise_if_not_found=False)
        parent = env.ref(f'{GEO_MODULE}.{parent_xml_id}', raise_if_not_found=False)
        if not commune or not parent:
            _logger.warning(
                "Référentiel géo : commune %s ou ville mère %s introuvable, lien ignoré.",
                row['id'], parent_xml_id)
            continue
        if commune.parent_city_id != parent:
            commune.write({'parent_city_id': parent.id})
        linked += 1

    _logger.info(
        "Référentiel géo : %d communes synchronisées (%d rattachées à une ville mère).",
        len(rows), linked)


def _load_geo_fokontany(env):
    """Charge les fokontany depuis data/microfinance.geo.fokontany-antananarivo.csv, en
    résolvant commune_id par xml_id (la commune doit avoir été chargée par
    _load_geo_communes avant cet appel)."""
    Fokontany = env['microfinance.geo.fokontany']
    rows = _read_geo_csv('microfinance.geo.fokontany-antananarivo.csv')

    data_list = []
    skipped = 0
    for row in rows:
        commune_xml_id = row.get('commune_id/id')
        commune = env.ref(f'{GEO_MODULE}.{commune_xml_id}', raise_if_not_found=False) \
            if commune_xml_id else False
        if not commune:
            skipped += 1
            _logger.warning(
                "Référentiel géo : fokontany %s ignoré, commune %s introuvable.",
                row['id'], commune_xml_id)
            continue
        data_list.append({
            'xml_id': f'{GEO_MODULE}.{row["id"]}',
            'values': {
                'name': row['name'],
                'postal_code': row.get('postal_code') or False,
                'commune_id': commune.id,
            },
            'noupdate': True,
        })
    Fokontany._load_records(data_list, update=True)
    _force_geo_noupdate(env, [data['xml_id'].split('.', 1)[1] for data in data_list])

    _logger.info(
        "Référentiel géo : %d fokontany synchronisés (%d ignorés).",
        len(data_list), skipped)


def _load_geo_commune_postal_codes(env):
    """Charge data/microfinance_geo_commune_postal_code.csv (colonnes commune_xmlid,postal_code
    — format volontairement non standard Odoo, destiné uniquement à ce hook, jamais à la clé
    'data' du manifeste). write() conditionnel : ne renseigne postal_code que s'il est encore
    vide sur la commune, pour ne jamais écraser une correction manuelle faite en base."""
    rows = _read_geo_csv('microfinance_geo_commune_postal_code.csv')
    updated = 0
    kept = 0
    missing = 0
    for row in rows:
        commune = env.ref(f'{GEO_MODULE}.{row["commune_xmlid"]}', raise_if_not_found=False)
        if not commune:
            missing += 1
            _logger.warning(
                "Référentiel géo : commune %s introuvable, code postal ignoré.",
                row['commune_xmlid'])
            continue
        if commune.postal_code:
            kept += 1
            continue
        commune.write({'postal_code': row['postal_code']})
        updated += 1

    _logger.info(
        "Référentiel géo : %d codes postaux de commune appliqués (%d déjà renseignés "
        "conservés, %d communes introuvables).",
        updated, kept, missing)


def _load_geo_regions(env):
    """Charge data/microfinance.geo.region.csv (référentiel administratif Loi n°2018-011,
    21 régions sur les 23 que compte Madagascar — les 2 manquantes n'apparaissent pas dans le
    fichier source fourni)."""
    Region = env['microfinance.geo.region']
    rows = _read_geo_csv('microfinance.geo.region.csv')
    data_list = [{
        'xml_id': f'{GEO_MODULE}.{row["id"]}',
        'values': {'name': row['name']},
        'noupdate': True,
    } for row in rows]
    Region._load_records(data_list, update=True)
    _force_geo_noupdate(env, [row['id'] for row in rows])
    _logger.info("Référentiel géo : %d régions synchronisées.", len(rows))


def _load_geo_districts(env):
    """Charge data/microfinance.geo.district.csv (112 districts), en résolvant region_id par
    xml_id (la région doit avoir été chargée par _load_geo_regions avant cet appel)."""
    District = env['microfinance.geo.district']
    rows = _read_geo_csv('microfinance.geo.district.csv')
    data_list = []
    skipped = 0
    for row in rows:
        region_xml_id = row.get('region_id/id')
        region = env.ref(f'{GEO_MODULE}.{region_xml_id}', raise_if_not_found=False) \
            if region_xml_id else False
        if not region:
            skipped += 1
            _logger.warning(
                "Référentiel géo : district %s ignoré, région %s introuvable.",
                row['id'], region_xml_id)
            continue
        data_list.append({
            'xml_id': f'{GEO_MODULE}.{row["id"]}',
            'values': {'name': row['name'], 'region_id': region.id},
            'noupdate': True,
        })
    District._load_records(data_list, update=True)
    _force_geo_noupdate(env, [data['xml_id'].split('.', 1)[1] for data in data_list])
    _logger.info(
        "Référentiel géo : %d districts synchronisés (%d ignorés).",
        len(data_list), skipped)


def _link_geo_commune_districts(env):
    """Charge data/microfinance_geo_commune_district_link.csv (colonnes
    commune_xmlid,district_xmlid — format volontairement non standard Odoo, destiné uniquement
    à ce hook, jamais à la clé 'data' du manifeste). write() conditionnel : ne renseigne
    district_id que s'il est encore vide sur la commune, pour ne jamais écraser une correction
    manuelle. Les communes non couvertes par ce fichier (noms ambigus ou introuvables lors du
    rapprochement automatique, cf. docs/unmatched_ambiguous_report.csv) restent à None, à traiter
    manuellement dans un lot séparé."""
    rows = _read_geo_csv('microfinance_geo_commune_district_link.csv')
    updated = 0
    kept = 0
    missing = 0
    for row in rows:
        commune = env.ref(f'{GEO_MODULE}.{row["commune_xmlid"]}', raise_if_not_found=False)
        district = env.ref(f'{GEO_MODULE}.{row["district_xmlid"]}', raise_if_not_found=False)
        if not commune or not district:
            missing += 1
            _logger.warning(
                "Référentiel géo : lien commune %s -> district %s ignoré (introuvable).",
                row['commune_xmlid'], row['district_xmlid'])
            continue
        if commune.district_id:
            kept += 1
            continue
        commune.write({'district_id': district.id})
        updated += 1

    _logger.info(
        "Référentiel géo : %d communes liées à un district (%d déjà liées conservées, "
        "%d liens introuvables).",
        updated, kept, missing)


def _load_geo_reference_data(env):
    _load_geo_communes(env)
    _load_geo_fokontany(env)
    _load_geo_commune_postal_codes(env)
    _load_geo_regions(env)
    _load_geo_districts(env)
    _link_geo_commune_districts(env)


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
    _seed_agency_partner_type(env)
    _backfill_existing_client_partner_type(env)
    _backfill_bailleur_partner_ids(env)
    _load_geo_reference_data(env)
