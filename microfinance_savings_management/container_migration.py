# -*- coding: utf-8 -*-
"""OBSOLÈTE depuis la scission compte / produit (17.0.1.7.0, docs_dev/epargne_split/) : conservé
uniquement pour les migrations 17.0.1.4.0 / 17.0.1.5.0 d'une base en retard de version.

Migration du correctif du 2026-09-24 (abroge l'« Option A » du 21/09, docs_dev/epargne_auto/
AUDIT_doublons_creation_client.md §11-13) : le conteneur épargne reprend la règle AGENCE/I/N (N =
numéro de compte permanent du client, PLUS AGENCE/IC/<numéro du compte crédit>), et il n'y a plus
de « compte principal » créé séparément à l'enregistrement du client.

Deux opérations indépendantes, toutes deux en lecture/écriture contrôlée :

1. ``rename_misnumbered_containers`` : renomme les conteneurs existants dont le nom ne suit pas
   la nouvelle règle (essentiellement ceux nommés AGENCE/IC/... par le correctif du 21/09) vers
   AGENCE/I/N. Respecte le paramètre système ``microfinance_savings.migration_dry_run`` (True par
   défaut, créé s'il est absent) : en dry-run, rien n'est renommé, seul un CSV liste ce qui serait
   fait. Idempotent : un conteneur déjà conforme est ignoré.

2. ``list_savings_duplicates`` : liste (sans jamais rien modifier ni fusionner) les clients ayant
   PLUSIEURS comptes épargne pour une même société (typiquement : l'ancien « compte principal »,
   réel, coexistant avec le conteneur). Écrit un CSV avec une colonne ``decision`` vide, à remplir
   par Micka avant tout traitement (aucune fusion automatique dans ce correctif).

3. ``align_savings_number_sequences`` : Option B (docs_dev/epargne_auto/
   AUDIT_doublons_creation_client.md §15) - le dry-run du 2026-09-24 a montré que la séquence des
   comptes réels de type I (``microfinance.savings.account.I``) et celle du numéro de compte
   permanent (``microfinance.partner.account``) avaient dérivé l'une de l'autre (écart de 105 sur
   l'agence IS), au point de bloquer l'enregistrement de nouveaux clients (collision de nom dès
   la création du conteneur). Les deux compteurs sont fusionnés dans le code
   (microfinance_savings_account.py._get_savings_sequence_code) ; cette fonction aligne UNE FOIS
   le plancher de la séquence partagée sur le plus avancé des deux anciens compteurs, par société,
   puis neutralise (renomme, désactive - jamais supprime) l'ancienne séquence ``.I`` devenue
   inutile. Respecte le même paramètre de dry-run que (1).

4. ``activate_draft_containers`` : correctif du 2026-10-05 (docs_dev/epargne_auto/
   AUDIT_doublons_creation_client.md §16) - un conteneur épargne ne doit jamais rester en
   brouillon (``create()`` pose désormais ``state='active'`` directement, cf.
   microfinance_savings_account.py). Régularise (ou, en dry-run, liste seulement) les conteneurs
   déjà en base et encore en ``draft`` avant ce correctif, en les passant à ``active`` - jamais
   via ``action_activate()`` (qui refuse explicitement un conteneur), directement par ``write()``.
   Aucun autre champ touché (pas de ``opening_date``, pour ne pas rendre le conteneur éligible à
   la dormance - cf. cron_detect_dormant_accounts, désormais filtré sur is_container en défense
   en profondeur). Respecte le même paramètre de dry-run que (1) et (3).

Points communs : aucun montant, journal, écriture ni solde n'est modifié - seul le champ `name`
du conteneur est écrit par (1), seul `state` par (4) ; (2) n'écrit jamais aucun compte. Avant
tout renommage, (1) vérifie les références en texte libre (écritures comptables, chatter
d'autres documents, séquences, transactions) : si l'ancien nom y figure, le conteneur n'est PAS
renommé, le cas est consigné dans le CSV.

Relance après bascule du paramètre à False (le script de migration ne se rejoue pas tout seul) ::

    odoo-bin shell -c odoo.conf -d <base>
    >>> from odoo.addons.microfinance_savings_management.container_migration import rename_misnumbered_containers
    >>> rename_misnumbered_containers(env)
    >>> env.cr.commit()
"""
import csv
import logging
import os
from datetime import datetime

from odoo import _, tools
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

PARAM_DRY_RUN = 'microfinance_savings.migration_dry_run'
PARAM_LOG_DIR = 'microfinance_savings.migration_log_dir'
_FALSE_VALUES = ('false', '0', 'no', 'non', 'f')

# (modèle, champs texte) inspectés pour retrouver l'ancien nom en texte libre. Un modèle ou un
# champ absent de l'instance est simplement ignoré.
_TEXT_REFERENCE_FIELDS = (
    ('account.move', ('name', 'ref', 'payment_reference', 'narration')),
    ('account.move.line', ('name', 'ref')),
    ('mail.message', ('body', 'subject')),
    ('ir.sequence', ('name', 'prefix', 'suffix')),
    ('microfinance.savings.transaction', ('name', 'note')),
)

RENAME_CSV_HEADER = ['id', 'ancien_nom', 'nouveau_nom', 'credit_lie', 'societe', 'statut', 'detail']
DUPLICATES_CSV_HEADER = [
    'partner_id', 'client', 'societe', 'conteneur_id', 'conteneur_nom',
    'compte_id', 'compte_nom', 'produit', 'etat', 'solde', 'candidat_ancien_principal', 'decision',
]
ALIGN_CSV_HEADER = [
    'societe', 'ancien_prochain_type_I', 'ancien_prochain_compte_permanent',
    'nouveau_prochain_compte_permanent', 'statut',
]
ACTIVATE_CSV_HEADER = ['id', 'nom', 'client', 'societe', 'etat_avant', 'statut']
# Séquence dont le rôle est désormais tenu par microfinance.partner.account (microfinance_loan_
# management) - cf. microfinance_savings_account.py._get_savings_sequence_code. Dupliquée ici en
# constante plutôt qu'importée pour ne pas faire dépendre ce fichier utilitaire du modèle ORM au
# chargement (même prudence que le reste de ce module, qui n'importe que des types Odoo génériques).
OLD_TYPE_I_SEQUENCE_CODE = 'microfinance.savings.account.I'
SHARED_ACCOUNT_NUMBER_SEQUENCE_CODE = 'microfinance.partner.account'


def _container_target_name(company, partner):
    """Ancien nom de conteneur AGENCE/I/N (N = suffixe du numéro permanent du client). Copie locale
    de l'ancienne méthode du modèle, retirée par la scission compte / produit (17.0.1.7.0)."""
    number = partner.microfinance_account_number
    if not number or '/' not in number:
        return False
    return '%s/I/%s' % (company.agency_code, number.rsplit('/', 1)[1])


def is_dry_run(env):
    """Lit le paramètre système ; le crée à « True » s'il est absent (dry-run par défaut).
    Toute valeur autre qu'un « faux » explicite reste en dry-run."""
    params = env['ir.config_parameter'].sudo()
    raw = params.get_param(PARAM_DRY_RUN)
    if raw is False or raw is None:
        params.set_param(PARAM_DRY_RUN, 'True')
        return True
    return str(raw).strip().lower() not in _FALSE_VALUES


def _log_directory(env):
    params = env['ir.config_parameter'].sudo()
    base = params.get_param(PARAM_LOG_DIR)
    if not base:
        logfile = tools.config['logfile']
        base = os.path.dirname(logfile) if logfile else tools.config['data_dir']
    return os.path.join(base, 'microfinance_migrations')


def _prepare_csv(env, name_prefix, dry_run, log_dir):
    """Crée le fichier CSV dès le départ : en mode réel, pas de renommage si la trace ne peut pas
    être écrite. Création EXCLUSIVE (mode 'x') : deux exécutions dans la même seconde ne doivent
    jamais s'écraser l'une l'autre."""
    directory = log_dir or _log_directory(env)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    base = '%s_%s_%s_%s' % (name_prefix, env.cr.dbname, stamp, 'dryrun' if dry_run else 'reel')
    try:
        os.makedirs(directory, exist_ok=True)
        counter = 0
        while True:
            path = os.path.join(directory, '%s%s.csv' % (base, '_%d' % counter if counter else ''))
            try:
                with open(path, 'x', encoding='utf-8', newline=''):
                    break
            except FileExistsError:
                counter += 1
    except OSError as exc:
        if not dry_run:
            raise UserError(_(
                "Renommage réel annulé : impossible d'écrire le fichier de traçabilité dans "
                "%(path)s (%(error)s). Corrigez les droits du dossier ou renseignez le paramètre "
                "système « %(param)s ».") % {'path': directory, 'error': exc, 'param': PARAM_LOG_DIR})
        _logger.warning("Dry-run : fichier CSV non écrit (%s) : %s", directory, exc)
        return None
    return path


def _find_text_references(env, old_name, container):
    """Références textuelles à `old_name` hors du conteneur lui-même. Renvoie une liste de
    « modèle.champ:n ». Lecture seule ; sudo() limité à ces recherches (les règles d'accès ne
    doivent pas masquer une référence)."""
    found = []
    for model_name, field_names in _TEXT_REFERENCE_FIELDS:
        if model_name not in env:
            continue
        Model = env[model_name].sudo().with_context(active_test=False)
        for field_name in field_names:
            if field_name not in Model._fields or not Model._fields[field_name].store:
                continue
            domain = [(field_name, 'ilike', old_name)]
            if model_name == 'mail.message':
                # Les messages du conteneur lui-même (suivi du champ Référence) contiennent
                # légitimement l'ancien nom.
                domain += ['!', '&', ('model', '=', container._name), ('res_id', '=', container.id)]
            count = Model.search_count(domain)
            if count:
                found.append('%s.%s:%d' % (model_name, field_name, count))
    return found


def rename_misnumbered_containers(env, dry_run=None, log_dir=None):
    """Renomme (ou, en dry-run, liste seulement) les conteneurs épargne dont le nom n'est pas
    AGENCE/I/<numéro de compte permanent du client>. Toutes sociétés. Renvoie la liste des lignes
    du CSV.

    N'appelle jamais commit() : l'appelant décide (le framework de migration commit à la fin,
    en shell il faut `env.cr.commit()`)."""
    if not (env.is_superuser() or env.user.has_group('base.group_system')):
        raise AccessError(_("Seul un administrateur peut renommer les conteneurs épargne."))
    if dry_run is None:
        dry_run = is_dry_run(env)
    Account = env['microfinance.savings.account'].with_context(active_test=False)
    csv_path = _prepare_csv(env, 'renommage_conteneurs_epargne', dry_run, log_dir)

    rows = []
    claimed = {}  # nom cible -> id du conteneur qui l'a déjà réservé dans cette exécution
    containers = Account.search([('is_container', '=', True)], order='id')
    for container in containers:
        company = container.company_id
        partner = container.partner_id
        target = _container_target_name(company, partner)
        row = {
            'id': container.id, 'ancien_nom': container.name, 'nouveau_nom': target or '',
            'credit_lie': partner.microfinance_account_number or '', 'societe': company.name,
            'statut': '', 'detail': '',
        }
        if not target:
            row.update(statut='IGNORE_SOURCE_INTROUVABLE',
                       detail="pas de numéro de compte permanent pour ce client/société")
        elif container.name == target:
            continue  # déjà conforme : hors périmètre, aucune ligne
        elif Account.sudo().search_count([('name', '=', target), ('id', '!=', container.id)]):
            row.update(statut='IGNORE_NOM_EXISTANT',
                       detail="le nom cible est déjà porté par un autre compte épargne")
        elif target in claimed:
            row.update(statut='IGNORE_CIBLE_EN_DOUBLE',
                       detail="même cible que le conteneur %s (client/société en double)" % claimed[target])
        else:
            references = _find_text_references(env, container.name, container)
            if references:
                row.update(statut='IGNORE_REFERENCES_TEXTE',
                           detail="ancien nom cité en texte libre : %s" % ', '.join(references))
            else:
                claimed[target] = container.id
                row['statut'] = 'A_RENOMMER' if dry_run else 'RENOMME'
                if not dry_run:
                    # Seul champ écrit. Le suivi (tracking) du champ Référence laisse une trace
                    # dans le chatter du conteneur.
                    container.write({'name': target})
        rows.append(row)

    if csv_path:
        with open(csv_path, 'a', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=RENAME_CSV_HEADER, delimiter=';')
            writer.writeheader()
            writer.writerows(rows)
    counts = {}
    for row in rows:
        counts[row['statut']] = counts.get(row['statut'], 0) + 1
    _logger.info(
        "Conteneurs épargne — renommage %s : %d conteneur(s) non conformes sur %d, détail %s, "
        "trace : %s", 'DRY-RUN (rien modifié)' if dry_run else 'RÉEL', len(rows), len(containers),
        counts or '{}', csv_path or 'non écrite')
    return rows


def list_savings_duplicates(env, log_dir=None):
    """Liste, SANS RIEN MODIFIER (aucune fusion automatique), les clients ayant un conteneur
    épargne ET au moins un compte épargne réel (is_container=False) pour la même société -
    typiquement l'ancien « compte principal » de l'« Option A » du 21/09, mais aussi tout compte
    épargne réel légitimement créé à la main (bouton « Épargne », 2e produit).

    Une ligne par compte réel concerné, avec une colonne ``decision`` vide : c'est Micka qui
    tranche (garder comme 2e produit, fusionner dans le conteneur, clôturer...) - aucune
    consommation automatique de cette colonne dans ce correctif. ``candidat_ancien_principal``
    est une SIMPLE INDICATION (pas une certitude) : 'OUI' si le compte a été créé le même jour
    que la fiche client (signature de l'ancienne création automatique).

    Toujours en lecture seule sur les comptes : n'accepte pas de paramètre dry_run. Renvoie la
    liste des lignes du CSV."""
    if not (env.is_superuser() or env.user.has_group('base.group_system')):
        raise AccessError(_("Seul un administrateur peut lister les doublons de comptes épargne."))
    Account = env['microfinance.savings.account'].with_context(active_test=False)
    csv_path = _prepare_csv(env, 'doublons_comptes_epargne', True, log_dir)

    rows = []
    containers = Account.search([('is_container', '=', True)], order='partner_id, company_id')
    for container in containers:
        partner = container.partner_id
        real_accounts = Account.search([
            ('partner_id', '=', partner.id), ('company_id', '=', container.company_id.id),
            ('is_container', '=', False),
        ], order='id')
        if not real_accounts:
            continue
        for account in real_accounts:
            same_day = (
                partner.create_date and account.create_date
                and partner.create_date.date() == account.create_date.date()
            )
            rows.append({
                'partner_id': partner.id, 'client': partner.display_name,
                'societe': container.company_id.name,
                'conteneur_id': container.id, 'conteneur_nom': container.name,
                'compte_id': account.id, 'compte_nom': account.name,
                'produit': account.product_id.display_name or '', 'etat': account.state,
                'solde': account.balance, 'candidat_ancien_principal': 'OUI' if same_day else '',
                'decision': '',
            })

    if csv_path:
        with open(csv_path, 'a', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=DUPLICATES_CSV_HEADER, delimiter=';')
            writer.writeheader()
            writer.writerows(rows)
    partners_concerned = len({row['partner_id'] for row in rows})
    _logger.info(
        "Comptes épargne en doublon d'un conteneur — %d compte(s) réel(s) sur %d client(s)/"
        "société(s) à examiner (AUCUNE fusion automatique), trace : %s",
        len(rows), partners_concerned, csv_path or 'non écrite')
    return rows


def align_savings_number_sequences(env, dry_run=None, log_dir=None):
    """Option B (docs_dev/epargne_auto/AUDIT_doublons_creation_client.md §15) : fusionne, par
    société, la séquence des comptes épargne réels de type I avec celle du numéro de compte
    permanent du client - désormais la MÊME séquence dans le code
    (microfinance_savings_account.py._get_savings_sequence_code). Sans cet alignement, la fusion
    ferait REPARTIR la numérotation des comptes réels de type I depuis la valeur du compteur
    compte permanent, qui peut être EN RETARD sur l'ancienne séquence .I (constaté sur MOWGLI :
    écart de 105 sur l'agence IS) - donc recréer des collisions avec des comptes réels déjà
    existants sous l'ancien régime.

    Avance UNE SEULE FOIS le plancher (``number_next_actual``) de la séquence partagée
    (``microfinance.partner.account``) sur le plus avancé des deux anciens compteurs, pour
    chaque société qui a une séquence ``microfinance.savings.account.I``. N'avance JAMAIS un
    plancher déjà supérieur (idempotent - un second passage ne fait rien). Neutralise ensuite
    l'ancienne séquence ``.I`` (renommée, désactivée - jamais supprimée, pour ne pas perdre la
    trace de son ancienne valeur).

    Ne touche à aucun compte, aucun conteneur, aucun montant : uniquement des lignes
    ``ir.sequence``. Respecte le paramètre système ``microfinance_savings.migration_dry_run``
    comme (1) ci-dessus."""
    if not (env.is_superuser() or env.user.has_group('base.group_system')):
        raise AccessError(_("Seul un administrateur peut aligner les séquences de numérotation épargne."))
    if dry_run is None:
        dry_run = is_dry_run(env)
    # active_test=False : une exécution précédente a pu désactiver l'ancienne séquence (cf.
    # neutralisation ci-dessous) - il faut continuer à la voir pour rester idempotent (rapporter
    # DEJA_ALIGNE plutôt que de la perdre silencieusement du périmètre de la recherche).
    Sequence = env['ir.sequence'].sudo().with_context(active_test=False)
    csv_path = _prepare_csv(env, 'alignement_sequences_epargne', dry_run, log_dir)

    rows = []
    old_sequences = Sequence.search([('code', '=', OLD_TYPE_I_SEQUENCE_CODE)], order='company_id')
    for old_seq in old_sequences:
        company = old_seq.company_id
        shared_seq = Sequence.search([
            ('code', '=', SHARED_ACCOUNT_NUMBER_SEQUENCE_CODE), ('company_id', '=', company.id),
        ], limit=1)
        old_next = old_seq.number_next_actual
        shared_next_before = shared_seq.number_next_actual if shared_seq else 1
        target_next = max(old_next, shared_next_before)
        row = {
            'societe': company.name, 'ancien_prochain_type_I': old_next,
            'ancien_prochain_compte_permanent': shared_next_before,
            'nouveau_prochain_compte_permanent': target_next, 'statut': '',
        }
        if shared_next_before >= old_next:
            row['statut'] = 'DEJA_ALIGNE'
        elif dry_run:
            row['statut'] = 'A_ALIGNER'
        else:
            if not shared_seq:
                shared_seq = Sequence.create({
                    'name': '%s (%s)' % (SHARED_ACCOUNT_NUMBER_SEQUENCE_CODE, company.name),
                    'code': SHARED_ACCOUNT_NUMBER_SEQUENCE_CODE, 'company_id': company.id,
                    'padding': 6, 'number_increment': 1,
                })
            # number_next_actual (pas number_next) : c'est ce champ qui déclenche réellement
            # l'ALTER SEQUENCE Postgres sous-jacent pour une séquence en implémentation
            # 'standard' - écrire number_next seul ne modifie que la valeur stockée, sans effet
            # sur next_by_id() (piège constaté en dry-run interne, cf. tests).
            shared_seq.write({'number_next_actual': target_next})
            old_seq.write({
                'name': '[OBSOLÉTE - fusionnée avec %s le 2026-09-24] %s' % (
                    SHARED_ACCOUNT_NUMBER_SEQUENCE_CODE, old_seq.name),
                'active': False,
            })
            row['statut'] = 'ALIGNE'
        rows.append(row)

    if csv_path:
        with open(csv_path, 'a', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=ALIGN_CSV_HEADER, delimiter=';')
            writer.writeheader()
            writer.writerows(rows)
    _logger.info(
        "Alignement des séquences épargne (type I / compte permanent) %s : %d société(s) "
        "concernée(s), trace : %s", 'DRY-RUN (rien modifié)' if dry_run else 'RÉEL',
        len(rows), csv_path or 'non écrite')
    return rows


def activate_draft_containers(env, dry_run=None, log_dir=None):
    """Correctif du 2026-10-05 (docs_dev/epargne_auto/AUDIT_doublons_creation_client.md §16) :
    régularise (ou, en dry-run, liste seulement) les conteneurs épargne encore en ``draft``
    créés avant que ``microfinance.savings.account.create()`` ne pose ``state='active'``
    directement. Passe uniquement ``state`` à ``active`` par ``write()`` - jamais
    ``action_activate()`` (qui refuse explicitement un conteneur) et jamais ``opening_date``
    (poser cette date rendrait le conteneur éligible à la dormance - cf. _compute_is_dormant).

    Respecte le paramètre système ``microfinance_savings.migration_dry_run`` comme les autres
    opérations de ce fichier. N'appelle jamais commit() : l'appelant décide. Renvoie la liste des
    lignes du CSV."""
    if not (env.is_superuser() or env.user.has_group('base.group_system')):
        raise AccessError(_("Seul un administrateur peut régulariser l'état des conteneurs épargne."))
    if dry_run is None:
        dry_run = is_dry_run(env)
    Account = env['microfinance.savings.account'].with_context(active_test=False)
    csv_path = _prepare_csv(env, 'activation_conteneurs_epargne', dry_run, log_dir)

    rows = []
    draft_containers = Account.search([('is_container', '=', True), ('state', '=', 'draft')], order='id')
    for container in draft_containers:
        rows.append({
            'id': container.id, 'nom': container.name, 'client': container.partner_id.display_name,
            'societe': container.company_id.name, 'etat_avant': container.state,
            'statut': 'A_ACTIVER' if dry_run else 'ACTIVE',
        })
    if not dry_run and draft_containers:
        draft_containers.write({'state': 'active'})

    if csv_path:
        with open(csv_path, 'a', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=ACTIVATE_CSV_HEADER, delimiter=';')
            writer.writeheader()
            writer.writerows(rows)
    _logger.info(
        "Conteneurs épargne en brouillon à régulariser %s : %d conteneur(s), trace : %s",
        'DRY-RUN (rien modifié)' if dry_run else 'RÉEL', len(rows), csv_path or 'non écrite')
    return rows
