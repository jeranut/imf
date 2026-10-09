# -*- coding: utf-8 -*-
"""Scission « compte épargne » (microfinance.savings.holder.account) / « produit d'épargne »
(microfinance.savings.account) — docs_dev/epargne_split/.

Passage 1 (`run_split_pass1`) : comptes créés depuis les anciens conteneurs et les comptes crédit,
produits rattachés et rangés, crédits pointant un conteneur repointés ou vidés, vérifications.
Passage 2 (`run_split_pass2`) : retrait des anciens conteneurs du modèle produit, uniquement si le
paramètre `microfinance_savings.split_remove_containers` vaut True et que le passage 1 est vert.

Dry-run par défaut (`microfinance_savings.split_dry_run`, absent => créé à True) : le traitement
réel tourne dans un savepoint annulé à la fin, le CSV et les vérifications décrivent donc
exactement ce que ferait le run réel. Rien n'est jamais deviné : les cas ambigus sont listés.

Run réel (odoo-bin shell) :
    from odoo.addons.microfinance_savings_management import savings_split_migration as m
    env['ir.config_parameter'].sudo().set_param(m.PARAM_DRY_RUN, 'False')
    m.run_split_pass1(env); env.cr.commit()
"""
import csv
import logging
import os
from datetime import datetime

from odoo import _, tools
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

PARAM_DRY_RUN = 'microfinance_savings.split_dry_run'
PARAM_REMOVE_CONTAINERS = 'microfinance_savings.split_remove_containers'
_FALSE_VALUES = ('false', '0', 'no', 'non', 'f')
CSV_HEADER = ['passage', 'etape', 'objet', 'id', 'reference', 'client', 'agence', 'statut', 'detail']
MIGRATION_CONTEXT = {'savings_split_migration': True, 'active_test': False, 'tracking_disable': True}


class _Rollback(Exception):
    pass


def is_dry_run(env):
    params = env['ir.config_parameter'].sudo()
    raw = params.get_param(PARAM_DRY_RUN)
    if raw is False or raw is None:
        params.set_param(PARAM_DRY_RUN, 'True')
        return True
    return str(raw).strip().lower() not in _FALSE_VALUES


def _remove_containers_allowed(env):
    raw = env['ir.config_parameter'].sudo().get_param(PARAM_REMOVE_CONTAINERS)
    return bool(raw) and str(raw).strip().lower() not in _FALSE_VALUES


def _default_log_dir():
    logfile = tools.config['logfile']
    base = os.path.dirname(logfile) if logfile else tools.config['data_dir']
    return os.path.join(base, 'microfinance_migrations')


def _write_csv(env, rows, dry_run, log_dir, passage):
    directory = log_dir or _default_log_dir()
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    base = 'scission_epargne_%s_%s_p%s_%s' % (env.cr.dbname, stamp, passage, 'dryrun' if dry_run else 'reel')
    try:
        os.makedirs(directory, exist_ok=True)
        counter = 0
        while True:
            path = os.path.join(directory, '%s%s.csv' % (base, '_%d' % counter if counter else ''))
            try:
                with open(path, 'x', encoding='utf-8', newline='') as handle:
                    writer = csv.DictWriter(handle, fieldnames=CSV_HEADER, delimiter=';')
                    writer.writeheader()
                    writer.writerows(rows)
                return path
            except FileExistsError:
                counter += 1
    except OSError as exc:
        if not dry_run:
            raise UserError(_("Scission épargne : trace CSV impossible à écrire dans %(dir)s (%(err)s).")
                            % {'dir': directory, 'err': exc})
        _logger.warning("Scission épargne : CSV non écrit (%s) : %s", directory, exc)
        return None


def _row(passage, etape, record, statut, detail='', reference=None):
    partner = getattr(record, 'partner_id', None)
    company = getattr(record, 'company_id', None)
    return {
        'passage': passage, 'etape': etape, 'objet': record._name, 'id': record.id,
        'reference': reference or record.display_name, 'client': partner.display_name if partner else '',
        'agence': company.display_name if company else '', 'statut': statut, 'detail': detail,
    }


def _totals(env):
    Product = env['microfinance.savings.account']
    products = Product.search([('is_container', '=', False)])
    return {
        'produits': len(products),
        'solde_produits': round(sum(products.mapped('balance')), 2),
        'transactions': env['microfinance.savings.transaction'].search_count([]),
        'mouvements_caisse': env['microfinance.caisse.mouvement'].search_count([('savings_account_id', '!=', False)]),
        'ecritures': env['account.move'].search_count([('microfinance_savings_account_id', '!=', False)]),
    }


def _holder_name(env, partner, company, loan_account):
    Holder = env['microfinance.savings.holder.account']
    if loan_account:
        return Holder._name_from_loan_account(loan_account)
    return '%s/%s' % (Holder._get_name_prefix(company), partner.microfinance_account_number)


def _blocked_containers(env):
    containers = env['microfinance.savings.account'].search([('is_container', '=', True)], order='id')
    return containers.filtered(lambda c: c.partner_id.company_id and c.partner_id.company_id != c.company_id)


def check_split(env):
    """Vérifications de fin de passage 1 : dict {nom: (ok, détail)}."""
    Holder = env['microfinance.savings.holder.account']
    Product = env['microfinance.savings.account']
    LoanAccount = env['microfinance.loan.account']
    orphans = Product.search([('is_container', '=', False), ('account_id', '=', False)])
    env.cr.execute("""SELECT account_id, rank, count(*) FROM microfinance_savings_account
                       WHERE account_id IS NOT NULL GROUP BY 1, 2 HAVING count(*) > 1""")
    duplicates = env.cr.fetchall()
    mismatches = Holder.search([('loan_account_id', '!=', False)]).filtered(
        lambda h: h.name != Holder._name_from_loan_account(h.loan_account_id))
    loans_on_container = env['microfinance.loan'].search([('savings_account_id.is_container', '=', True)])
    holder_keys = {(h.partner_id.id, h.company_id.id) for h in Holder.search([])}
    loan_without_holder = LoanAccount.search([]).filtered(
        lambda la: (la.partner_id.id, la.company_id.id) not in holder_keys)
    return {
        'aucun_produit_sans_compte': (not orphans, ', '.join(orphans.mapped('name'))),
        'aucun_rang_en_double': (not duplicates, str(duplicates)),
        'meme_numero_credit_epargne': (not mismatches, ', '.join(mismatches.mapped('name'))),
        'aucun_credit_sur_conteneur': (not loans_on_container, ', '.join(loans_on_container.mapped('name'))),
        'chaque_compte_credit_a_son_compte_epargne': (
            not loan_without_holder, ', '.join(loan_without_holder.mapped('name'))),
    }


def run_split_pass1(env, dry_run=None, log_dir=None):
    """Retourne (rows, checks, totals_before, totals_after)."""
    if dry_run is None:
        dry_run = is_dry_run(env)
    env = env(su=True, context=dict(env.context, **MIGRATION_CONTEXT))
    rows, result = [], {}
    blocked = _blocked_containers(env)
    for container in blocked:
        rows.append(_row(1, 'a_garde', container, 'A_CORRIGER_MANUELLEMENT',
                         "société du conteneur (%s) différente de celle du titulaire (%s) : à corriger "
                         "manuellement avant migration" % (container.company_id.display_name,
                                                           container.partner_id.company_id.display_name)))
    if blocked and not dry_run:
        _write_csv(env, rows, dry_run, log_dir, 1)
        raise UserError(_(
            "Scission épargne refusée : %s conteneur(s) ont une société différente de celle de leur "
            "titulaire. À corriger manuellement avant migration (voir le CSV)."
        ) % len(blocked))
    try:
        with env.cr.savepoint():
            result = _pass1(env, rows, blocked)
            if dry_run:
                raise _Rollback()
    except _Rollback:
        pass
    path = _write_csv(env, rows, dry_run, log_dir, 1)
    checks = result.get('checks', {})
    _logger.info("Scission épargne passage 1 (%s) : %s ligne(s), vérifications %s, avant %s, après %s, trace %s",
                 'DRY-RUN' if dry_run else 'RÉEL', len(rows),
                 {k: v[0] for k, v in checks.items()}, result.get('before'), result.get('after'), path)
    return rows, checks, result.get('before'), result.get('after')


def _pass1(env, rows, blocked):
    Holder = env['microfinance.savings.holder.account']
    Product = env['microfinance.savings.account']
    LoanAccount = env['microfinance.loan.account']
    before = _totals(env)
    holders = {(h.partner_id.id, h.company_id.id): h for h in Holder.search([])}

    def get_holder(partner, company, etape, source, legacy=False):
        key = (partner.id, company.id)
        if key in holders:
            holder = holders[key]
            if legacy and not holder.legacy_number:
                holder.legacy_number = legacy
            rows.append(_row(1, etape, source, 'EXISTANT', 'compte %s' % holder.name))
            return holder
        loan_account = LoanAccount.search([('partner_id', '=', partner.id), ('company_id', '=', company.id)], limit=1)
        if not loan_account and not partner.microfinance_account_number:
            rows.append(_row(1, etape, source, 'AMBIGU', "ni compte crédit ni numéro permanent : compte non créé"))
            return Holder
        try:
            with env.cr.savepoint():
                holder = Holder.create({
                    'partner_id': partner.id, 'company_id': company.id, 'loan_account_id': loan_account.id,
                    'name': _holder_name(env, partner, company, loan_account), 'legacy_number': legacy,
                })
        except Exception as exc:  # contrainte de cohérence, nom déjà pris : listé, jamais deviné
            rows.append(_row(1, etape, source, 'AMBIGU', 'création du compte impossible : %s' % exc))
            return Holder
        holders[key] = holder
        detail = 'compte %s' % holder.name + ('' if loan_account else ' (SANS_COMPTE_CREDIT)')
        rows.append(_row(1, etape, source, 'COMPTE_CREE', detail))
        return holder

    # b. anciens conteneurs -> comptes (vides inclus)
    for container in Product.search([('is_container', '=', True)], order='id') - blocked:
        get_holder(container.partner_id, container.company_id, 'b_conteneur', container, legacy=container.name)

    # c. rattrapage : compte crédit sans compte épargne
    for loan_account in LoanAccount.search([], order='id'):
        if (loan_account.partner_id.id, loan_account.company_id.id) not in holders:
            get_holder(loan_account.partner_id, loan_account.company_id, 'c_rattrapage', loan_account)

    # d. produits -> compte, rang par ordre d'ouverture, ancien numéro conservé
    products = Product.search([('is_container', '=', False), ('account_id', '=', False)])
    for product in products.sorted(lambda p: (p.opening_date or p.create_date.date(), p.id)):
        holder = get_holder(product.partner_id, product.company_id, 'd_produit_compte', product)
        if not holder:
            rows.append(_row(1, 'd_produit', product, 'AMBIGU', 'aucun compte : produit non rattaché'))
            continue
        rank = holder._reserve_rank()
        product.write({'account_id': holder.id, 'rank': rank, 'legacy_number': product.legacy_number or product.name})
        rows.append(_row(1, 'd_produit', product, 'RATTACHE', 'compte %s, rang %02d' % (holder.name, rank)))

    # e. crédits pointant un conteneur
    for loan in env['microfinance.loan'].search([('savings_account_id.is_container', '=', True)], order='id'):
        old = loan.savings_account_id.name
        candidates = Product.search([
            ('partner_id', '=', loan.partner_id.id), ('company_id', '=', loan.company_id.id),
            ('state', '=', 'active'), ('account_id', '!=', False),
        ])
        if len(candidates) == 1:
            loan.savings_account_id = candidates
            rows.append(_row(1, 'e_credit', loan, 'REPOINTE', '%s -> %s' % (old, candidates.name)))
        else:
            loan.savings_account_id = False
            rows.append(_row(1, 'e_credit', loan, 'VIDE',
                             '%s : %s produit(s) actif(s) dans l\'agence, rien deviné' % (old, len(candidates))))

    env.flush_all()
    after = _totals(env)
    checks = check_split(env)
    checks['totaux_identiques'] = (before == after, 'avant %s / après %s' % (before, after))
    for name, (ok, detail) in checks.items():
        rows.append({'passage': 1, 'etape': 'f_verification', 'objet': name, 'id': '', 'reference': '',
                     'client': '', 'agence': '', 'statut': 'OK' if ok else 'ECHEC', 'detail': detail})
    return {'before': before, 'after': after, 'checks': checks}


def run_split_pass2(env, dry_run=None, log_dir=None):
    """Retrait des anciens conteneurs : seulement si le paramètre explicite est posé et que les
    vérifications du passage 1 sont toutes vertes. Retourne (rows, removed_count)."""
    if dry_run is None:
        dry_run = is_dry_run(env)
    env = env(su=True, context=dict(env.context, **MIGRATION_CONTEXT))
    rows = []
    if not _remove_containers_allowed(env):
        rows.append({'passage': 2, 'etape': 'garde', 'objet': PARAM_REMOVE_CONTAINERS, 'id': '', 'reference': '',
                     'client': '', 'agence': '', 'statut': 'NON_DEMANDE', 'detail': 'paramètre explicite absent'})
        _write_csv(env, rows, dry_run, log_dir, 2)
        return rows, 0
    checks = check_split(env)
    failed = {k: v for k, v in checks.items() if not v[0]}
    if failed:
        for name, (_ok, detail) in failed.items():
            rows.append({'passage': 2, 'etape': 'garde', 'objet': name, 'id': '', 'reference': '', 'client': '',
                         'agence': '', 'statut': 'ECHEC', 'detail': detail})
        _write_csv(env, rows, dry_run, log_dir, 2)
        raise UserError(_("Retrait des conteneurs refusé : vérifications du passage 1 non vertes (voir le CSV)."))
    Holder = env['microfinance.savings.holder.account']
    removed = 0
    try:
        with env.cr.savepoint():
            for container in env['microfinance.savings.account'].search([('is_container', '=', True)], order='id'):
                holder = Holder.search([('partner_id', '=', container.partner_id.id),
                                        ('company_id', '=', container.company_id.id)], limit=1)
                refs = {
                    'crédits': env['microfinance.loan'].search_count([('savings_account_id', '=', container.id)]),
                    'transactions': len(container.transaction_ids),
                    'caisse': env['microfinance.caisse.mouvement'].search_count([('savings_account_id', '=', container.id)]),
                    'écritures': env['account.move'].search_count([('microfinance_savings_account_id', '=', container.id)]),
                }
                if not holder or any(refs.values()):
                    detail = 'compte épargne absent' if not holder else 'références : %s' % {k: v for k, v in refs.items() if v}
                    rows.append(_row(2, 'retrait', container, 'CONSERVE', detail))
                    continue
                rows.append(_row(2, 'retrait', container, 'RETIRE', 'remplacé par %s' % holder.name))
                container.unlink()
                removed += 1
            if dry_run:
                raise _Rollback()
    except _Rollback:
        pass
    path = _write_csv(env, rows, dry_run, log_dir, 2)
    _logger.info("Scission épargne passage 2 (%s) : %s conteneur(s) retiré(s), trace %s",
                 'DRY-RUN' if dry_run else 'RÉEL', removed, path)
    return rows, removed
