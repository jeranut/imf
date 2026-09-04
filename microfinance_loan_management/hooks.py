# -*- coding: utf-8 -*-
import csv
import logging
import os

from odoo import fields

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
    # Créance "frais de dossier à recevoir" (flux Option A : engagement à l'approbation, soldé
    # à l'encaissement) - docs_dev/frais_dossier_creance_pcec/. reconcile=True (lettrage
    # engagement <-> règlement), contrairement aux 208001-004 (intérêts, jamais lettrés).
    '208005': ('Produits à recevoir - Frais de dossier sur crédit', 'asset_current', True),
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


# Référentiel Catégorie d'activité / Activité (Bloc IV), fourni par Micka le 2026-07-19 :
# (code_categorie, categorie, code_activite, activite). Ne pas retrier ni "nettoyer" l'ordre de
# cette liste : c'est cet ordre qui détermine, pour les 2 codes d'activité en double (27 et 30),
# laquelle des deux occurrences est conservée à l'import (décision confirmée avec Micka, Option
# A : on garde la première occurrence dans l'ordre ci-dessous, on ignore la suivante — cf.
# docs_dev/programme_progressif/STATUS.md).
ACTIVITY_REFERENCE_DATA = [
    ('G4711', 'Commerce de détail en magasins non spécialisés, avec vente prédominante de produits alimentaires, boissons et tabacs', '0', 'Épicerie'),
    ('G4721', 'Commerce de détail de produits alimentaires en magasins spécialisés', '2', 'Vente viande, poisson'),
    ('G4752', 'Commerce de détail de quincaillerie, peintures et verrerie en magasins spécialisés', '18', 'Quincaillerie'),
    ('G4764', 'Commerce de détail de jeux et jouets en magasin spécialisé', '6', 'Vente jouets, cadeaux'),
    ('G4771', "Commerce de détail de vêtements, de chaussures et d'articles de cuir en magasins spécialisés", '5', 'Vente vêtements, chaussures'),
    ('G4772', "Commerce de détail de produits pharmaceutiques et médicaux, de produits de beauté et d'articles de toilette", '7', 'Plantes médicinales, médicaments'),
    ('G4774', "Commerce de détail d'articles d'occasion", '15', 'Brocante'),
    ('G4789', "Commerce de détail sur éventaires et marchés d'autres articles", '1', 'Fruits & légumes'),
    ('G4789', "Commerce de détail sur éventaires et marchés d'autres articles", '4', 'Volaille, lapin vivant'),
    ('G4799', "Autres commerces de détail autres qu'en magasins, sur éventaires ou marchés", '8', 'Marchand ambulant'),
    ('G4799', "Autres commerces de détail autres qu'en magasins, sur éventaires ou marchés", '9', 'Autre achat ou revente'),
    ('H4922', 'Transports routiers de marchandises', '26', 'Transporteurs'),
    ('I5629', 'Autres activités de services de restauration', '11', 'Petite gargote extérieure'),
    ('I5629', 'Autres activités de services de restauration', '20', 'Hôtely, gargote intérieure'),
    ('S9602', 'Coiffure et autres soins esthétiques', '21', 'Coiffure et beauté'),
    ('N7722', 'Location de vidéocassettes et de vidéodisques', '23', 'Location vidéo'),
    ('Q8892', 'Autres activités de services aux particuliers et aux familles', '22', 'Lavanderie'),
    ('Q8892', 'Autres activités de services aux particuliers et aux familles', '25', 'Photos'),
    ('Q8892', 'Autres activités de services aux particuliers et aux familles', '29', 'Tailleur'),
    ('Q8892', 'Autres activités de services aux particuliers et aux familles', '30', 'Autres services'),
    ('S9512', 'Réparation de matériel de communication', '24', 'Réparateur TV, radio'),
    ('S9523', "Réparation de chaussures et d'articles de cuir", '30', 'Autres services'),
    ('S9529', "Réparation d'autres articles personnels et ménagers", '27', 'Réparateur à domicile'),
    ('A0112', 'Culture du riz (y compris biologique et génétiquement modifié)', '43', 'Riziculture'),
    ('A0113', 'Culture de légumes, de melons, de racines et de tubercules', '44', 'Produits maraîchers'),
    ('A0119', 'Autres cultures temporaires', '45', 'Pépinière'),
    ('A0125', "Culture d'autres fruits sur arbres et arbustes, et de fruits à coque", '46', 'Arbre fruitier'),
    ('A0141', 'Élevage de bovins et de buffles', '39', 'Zébus'),
    ('A0145', 'Élevage de porcins', '38', 'Porc'),
    ('A0146', 'Élevage de volailles', '32', 'Poulet de chair'),
    ('A0146', 'Élevage de volailles', '33', 'Poule pondeuse'),
    ('A0146', 'Élevage de volailles', '34', 'Poulet gasy'),
    ('A0146', 'Élevage de volailles', '35', 'Canard'),
    ('A0146', 'Élevage de volailles', '36', 'Oie'),
    ('A0146', 'Élevage de volailles', '37', 'Dinde'),
    ('A0149', "Élevage d'autres animaux", '40', 'Apiculture'),
    ('A0149', "Élevage d'autres animaux", '41', 'Pisciculture'),
    ('A0149', "Élevage d'autres animaux", '42', 'Lapin'),
    ('C1071', 'Boulangerie, pâtisserie, biscuiterie', '3', 'Boulangerie, pâtisserie'),
    ('C1312', 'Tissage des fibres textiles', '49', '(non résolu)'),
    ('C1399', "Fabrication d'autres textiles nca", '47', '(non résolu)'),
    ('C1410', "Fabrication de vêtements autres qu'en fourrure", '13', 'Confection'),
    ('C2392', 'Fabrication de matériaux de construction non réfractaires en argile et céramique', '50', '(non résolu)'),
    ('C2393', "Fabrication d'autres articles en porcelaine et en céramique", '48', '(non résolu)'),
    ('C2396', 'Taille, façonnage et finissage de la pierre', '28', 'Lapidaire'),
    ('C3100', 'Fabrication de meubles de bureau et autres', '14', 'Menuiserie'),
    ('C3240', 'Fabrication de jeux et jouets', '16', 'Fabrication de jouets'),
    ('C3290', 'Autres activités de fabrication, nca', '12', 'Artisanat'),
    ('C3290', 'Autres activités de fabrication, nca', '19', 'Autre fabrication'),
    ('C3290', 'Autres activités de fabrication, nca', '17', 'Forgeron, ferrailleur'),
    ('C3319', "Réparation d'autres matériels", '27', 'Réparateur à domicile'),
    ('F4100', 'Construction de bâtiments', '31', 'Habitat'),
]


def _load_activity_reference_data(env):
    """Charge le référentiel Catégorie d'activité / Activité (Bloc IV) depuis
    ACTIVITY_REFERENCE_DATA, avec le même mécanisme que le référentiel géo (xml_ids
    noupdate=True via _load_records, cf. _force_geo_noupdate). Dédoublonne les catégories (un
    code_categorie = une seule catégorie créée) et applique l'Option A confirmée avec Micka sur
    les codes d'activité en double : garde la première occurrence dans l'ordre de
    ACTIVITY_REFERENCE_DATA, ignore les suivantes (rapport détaillé en log)."""
    Category = env['microfinance.loan.application.activity.category']
    Activity = env['microfinance.loan.application.activity']

    category_xml_ids = {}  # code_categorie -> xml_id (première occurrence)
    category_data_list = []
    for code_categ, categorie, _code_act, _act in ACTIVITY_REFERENCE_DATA:
        if code_categ in category_xml_ids:
            continue
        xml_id = f'activity_category_{code_categ}'
        category_xml_ids[code_categ] = xml_id
        category_data_list.append({
            'xml_id': f'{GEO_MODULE}.{xml_id}',
            'values': {'code': code_categ, 'name': categorie},
            'noupdate': True,
        })
    Category._load_records(category_data_list, update=True)
    _force_geo_noupdate(env, [xml_id for xml_id in category_xml_ids.values()])

    activity_first_seen = {}  # code_activite -> (code_categorie, activite) première occurrence
    skipped = []
    activity_data_list = []
    for code_categ, categorie, code_act, act in ACTIVITY_REFERENCE_DATA:
        if code_act in activity_first_seen:
            skipped.append((code_act, act, code_categ, categorie))
            continue
        activity_first_seen[code_act] = (code_categ, act)
        category = env.ref(f'{GEO_MODULE}.{category_xml_ids[code_categ]}')
        xml_id = f'activity_{code_act}'
        activity_data_list.append({
            'xml_id': f'{GEO_MODULE}.{xml_id}',
            'values': {'code': code_act, 'name': act, 'category_id': category.id},
            'noupdate': True,
        })
    Activity._load_records(activity_data_list, update=True)
    _force_geo_noupdate(env, [f'activity_{code}' for code in activity_first_seen])

    _logger.info(
        "Référentiel activités (Bloc IV) : %d catégorie(s), %d activité(s) chargées, "
        "%d doublon(s) de code d'activité ignoré(s) (première occurrence conservée) : %s",
        len(category_data_list), len(activity_data_list), len(skipped),
        '; '.join(
            f"code {code} ({act!r}) sous {categ_code} ignoré (déjà utilisé par "
            f"{activity_first_seen[code][0]}/{activity_first_seen[code][1]!r})"
            for code, act, categ_code, _categ_name in skipped
        ) or 'aucun',
    )


# Désignations par défaut Section V (revenus familiaux, dépenses d'activité, dépenses
# familiales) et fréquences de montant avec leur multiplicateur — configurables librement
# ensuite par Micka (Configuration > Financement), ces valeurs ne sont qu'un point de départ,
# pas une liste figée.
FINANCIAL_DESIGNATION_INCOME_DATA = [
    'Bénéfices activité financée', 'Bénéfices autre activité', 'Salaire', 'Pension',
    'Loyers perçus', 'Contribution autres membres', 'Autres revenus',
]
FINANCIAL_DESIGNATION_ACTIVITY_EXPENSE_DATA = [
    'Ticket', 'Transport', 'Location table/parasol', 'Loyer lieu de vente',
    'Employés (activités)', 'Patente', 'Autres',
]
FINANCIAL_DESIGNATION_FAMILY_EXPENSE_DATA = [
    'Nourriture', 'Charbon', 'Goûter', 'Bougie', 'Eau (@ pompy)', 'Jirama', 'Pétrole', 'Savon',
    'Kojakoja madinika', 'Transport (frais)', 'Paraky (tabac)', 'Sigara (cigarettes)', 'Loyer',
    'Ecolage', 'Téléphone', 'Employés (domestiques)', 'Santé', 'Charges financières',
    'Participation familiale', 'Cotisation', 'Autres',
]
# (code xml_id, nom, multiplicateur)
FINANCIAL_FREQUENCY_DATA = [
    ('daily', 'Quotidien', 30.0),
    ('weekly', 'Hebdomadaire', 4.0),
    ('monthly', 'Mensuel', 1.0),
]


def _load_financial_designation_list(env, model_name, xml_id_prefix, names):
    Model = env[model_name]
    data_list = [{
        'xml_id': f'{GEO_MODULE}.{xml_id_prefix}_{index}',
        'values': {'name': name, 'sequence': (index + 1) * 10},
        'noupdate': True,
    } for index, name in enumerate(names)]
    Model._load_records(data_list, update=True)
    _force_geo_noupdate(env, [data['xml_id'].split('.', 1)[1] for data in data_list])
    return len(data_list)


def _load_financial_reference_data(env):
    """Charge les désignations par défaut des 3 catalogues Section V et les fréquences de
    montant (avec multiplicateur), même mécanisme que le référentiel géo/activités (xml_ids
    noupdate=True via _load_records, cf. _force_geo_noupdate) — modifiable ensuite librement
    par Micka dans Configuration > Financement, ce n'est qu'un jeu de valeurs de départ."""
    count_income = _load_financial_designation_list(
        env, 'microfinance.financial.designation.income',
        'financial_designation_income', FINANCIAL_DESIGNATION_INCOME_DATA)
    count_activity_expense = _load_financial_designation_list(
        env, 'microfinance.financial.designation.activity.expense',
        'financial_designation_activity_expense', FINANCIAL_DESIGNATION_ACTIVITY_EXPENSE_DATA)
    count_family_expense = _load_financial_designation_list(
        env, 'microfinance.financial.designation.family.expense',
        'financial_designation_family_expense', FINANCIAL_DESIGNATION_FAMILY_EXPENSE_DATA)

    Frequency = env['microfinance.financial.frequency']
    frequency_data_list = [{
        'xml_id': f'{GEO_MODULE}.financial_frequency_{code}',
        'values': {'name': name, 'multiplier': multiplier, 'sequence': (index + 1) * 10},
        'noupdate': True,
    } for index, (code, name, multiplier) in enumerate(FINANCIAL_FREQUENCY_DATA)]
    Frequency._load_records(frequency_data_list, update=True)
    _force_geo_noupdate(env, [data['xml_id'].split('.', 1)[1] for data in frequency_data_list])

    _logger.info(
        "Référentiel financier (Section V) : %d désignation(s) revenu, %d désignation(s) "
        "dépense d'activité, %d désignation(s) dépense familiale, %d fréquence(s) chargée(s).",
        count_income, count_activity_expense, count_family_expense, len(frequency_data_list),
    )


def _financial_line_keep_key(line):
    """Préserve en priorité une saisie existante quand un doublon porte déjà un montant.
    Dernier critère de départage (line.id, pas -line.id) : au sein d'une même transaction,
    write_date/create_date peuvent être identiques à la microseconde près (valeur mise en
    cache par le curseur) — dans ce cas, on garde la ligne la plus récemment créée (id le
    plus grand) plutôt que la plus ancienne."""
    return (
        bool(line.amount),
        bool(line.frequency_id),
        line.write_date or line.create_date or fields.Datetime.now(),
        line.id,
    )


def _cleanup_existing_financial_lines(env):
    """Nettoie les lignes financières historiques créées en double par l'ancien hook de lecture.

    Pour chaque dossier, catégorie et situation : supprime les lignes sans désignation, les
    lignes liées à une désignation inactive et les doublons, puis recrée les désignations actives
    manquantes. Idempotent : un second passage ne modifie plus rien.
    """
    Line = env['microfinance.loan.application.income.line'].with_context(active_test=False)
    Application = env['microfinance.loan.application'].with_context(active_test=False)
    Frequency = env['microfinance.financial.frequency'].with_context(active_test=False)
    monthly_frequency = env.ref(
        'microfinance_loan_management.financial_frequency_monthly',
        raise_if_not_found=False,
    )
    if not monthly_frequency or not monthly_frequency.active:
        monthly_frequency = Frequency.search([('active', '=', True)], order='sequence, id', limit=1)

    category_designations = {
        'family_income': (
            env['microfinance.financial.designation.income'].search([('active', '=', True)]),
            'income_designation_id',
        ),
        'activity_expense': (
            env['microfinance.financial.designation.activity.expense'].search([('active', '=', True)]),
            'activity_expense_designation_id',
        ),
        'family_expense': (
            env['microfinance.financial.designation.family.expense'].search([('active', '=', True)]),
            'family_expense_designation_id',
        ),
    }

    deleted_empty = deleted_duplicate = deleted_inactive = created_missing = 0
    for application in Application.search([]):
        for category, (designations, field_name) in category_designations.items():
            active_designation_ids = set(designations.ids)
            for situation in ('current', 'forecast'):
                lines = Line.search([
                    ('application_id', '=', application.id),
                    ('category', '=', category),
                    ('situation', '=', situation),
                ])
                to_delete = Line.browse()
                by_designation = {}
                for line in lines:
                    designation = line[field_name]
                    if not designation:
                        to_delete |= line
                        deleted_empty += 1
                    elif designation.id not in active_designation_ids:
                        to_delete |= line
                        deleted_inactive += 1
                    else:
                        by_designation.setdefault(designation.id, Line.browse())
                        by_designation[designation.id] |= line

                kept_designation_ids = set()
                for designation_id, duplicate_lines in by_designation.items():
                    kept = max(duplicate_lines, key=_financial_line_keep_key)
                    kept_designation_ids.add(designation_id)
                    duplicates = duplicate_lines - kept
                    if duplicates:
                        to_delete |= duplicates
                        deleted_duplicate += len(duplicates)

                if to_delete:
                    to_delete.unlink()

                missing_designations = designations.filtered(
                    lambda designation: designation.id not in kept_designation_ids)
                for designation in missing_designations:
                    vals = {
                        'application_id': application.id,
                        'category': category,
                        'situation': situation,
                        field_name: designation.id,
                    }
                    if monthly_frequency:
                        vals['frequency_id'] = monthly_frequency.id
                    Line.create(vals)
                    created_missing += 1

    _logger.info(
        "Nettoyage lignes financières : %d vide(s), %d doublon(s), %d inactive(s) supprimé(s), "
        "%d ligne(s) manquante(s) recréée(s).",
        deleted_empty, deleted_duplicate, deleted_inactive, created_missing,
    )


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
    _load_activity_reference_data(env)
    _load_financial_reference_data(env)
    _cleanup_existing_financial_lines(env)
    _seed_social_score_brackets(env)


# Valeurs par défaut des tranches de notation sociale (microfinance.social.score.bracket) :
# (sequence, is_amount_based, threshold_amount, label). threshold_amount vaut 0 sur la
# dernière tranche amount-based = pas de plafond ; label vaut None pour une tranche
# amount-based (généré automatiquement par le modèle) et inversement.
SOCIAL_SCORE_BRACKET_DEFAULTS = {
    'assets': [
        (1, True, 100000, None),
        (2, True, 200000, None),
        (3, True, 300000, None),
        (4, True, 0, None),
    ],
    'food': [
        (1, False, None, '1. 0 à 1 repas par jour'),
        (2, False, None, '2. 2 repas par jour'),
        (3, False, None, '3. 3 repas par jour'),
        (4, False, None, '4. > 3 repas par jour (avec confort)'),
    ],
    'activity': [
        (1, False, None, '1. Aucune'),
        (2, False, None, '2. Informelle et irrégulière'),
        (3, False, None, '3. Informelle et régulière'),
        (4, False, None, '4. Formelle et régulière'),
    ],
    'health': [
        (1, False, None, '1. Maladies chroniques et non traitées'),
        (2, False, None, '2. Maladies non chroniques et non traitées'),
        (3, False, None, '3. Maladies mal traitées ou irrégulièrement'),
        (4, False, None, '4. Toutes maladies traitées'),
    ],
    'income': [
        (1, True, 50000, None),
        (2, True, 80000, None),
        (3, True, 110000, None),
        (4, True, 0, None),
    ],
    'housing_state': [
        (0, False, None, '0. Mauvais état'),
        (1, False, None, '1. Moyen état'),
        (2, False, None, '2. Bon état'),
    ],
    'housing_surface': [
        (1, False, None, '1. < 4 m² par membre du ménage'),
        (2, False, None, '2. > 4 m² par membre du ménage'),
    ],
    'education_borrower': [
        (0, False, None, '0. Sans éducation'),
        (1, False, None, "1. Primaire (jusqu'au CEPE)"),
        (2, False, None, '2. Secondaire (6ème au BEPC)'),
        (3, False, None, '3. Seconde au Terminale'),
        (4, False, None, '4. BAC et plus'),
    ],
    'education_children': [
        (1, False, None, '1. Aucune'),
        (2, False, None, '2. Certains enfants scolarisés'),
        (3, False, None, '3. Tous les enfants scolarisés'),
        (4, False, None,
         '4. Tous les enfants scolarisés et dans le cycle correspondant à leur âge'),
    ],
}


def _seed_social_score_brackets(env):
    """Crée les tranches de notation sociale par défaut pour chaque société n'en ayant pas
    encore (idempotent, vérifié par catégorie/société avant création — jamais de doublon).
    Appelée depuis post_init_hook (installation neuve) ET depuis le script de migration
    17.0.1.7.0 (mise à jour d'une instance déjà installée, où post_init_hook ne se
    redéclenche pas — cf. odoo/modules/loading.py, post_init ne s'exécute que si
    new_install)."""
    Bracket = env['microfinance.social.score.bracket']
    for company in env['res.company'].search([]):
        for category, tranches in SOCIAL_SCORE_BRACKET_DEFAULTS.items():
            if Bracket.search_count([('category', '=', category), ('company_id', '=', company.id)]):
                continue
            vals_list = []
            for seq, is_amount, threshold, label in tranches:
                vals = {
                    'company_id': company.id, 'category': category, 'sequence': seq,
                    'is_amount_based': is_amount,
                }
                if is_amount:
                    vals['threshold_amount'] = threshold
                else:
                    vals['label'] = label
                vals_list.append(vals)
            Bracket.create(vals_list)
