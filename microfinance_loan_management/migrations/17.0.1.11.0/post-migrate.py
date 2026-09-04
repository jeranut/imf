# -*- coding: utf-8 -*-
"""Flux « frais de dossier à recevoir » (Option A, docs_dev/frais_dossier_creance_pcec/).

1) Création du sous-compte PCEC `208005` « Produits à recevoir - Frais de dossier sur crédit »
   (asset_current, reconcile=True) pour chaque société sur plan PCEC : post_init_hook ne
   s'exécute pas sur un -u d'un module déjà installé (cf. migrations/17.0.1.5.0 et
   17.0.1.7.0 de ce module). Aujourd'hui une seule société concernée (CEFOR Isotry), mais on
   boucle sur toutes les sociétés `mg_pcec` comme le hook.

2) Rattrapage de l'écriture d'ENGAGEMENT pour les dossiers déjà approuvés dont les frais ne
   sont pas encore encaissés (décision Micka, AUDIT.md Q6) : state == 'approved',
   fee_paid = False, fee_amount_due > 0, produit en mode « frais exigés avant décaissement »,
   comptes/journal configurés. Les dossiers déjà `fee_paid` ne sont PAS repris (frais déjà
   constatés en 717003 via l'ancienne écriture unique). Le produit doit avoir été configuré
   (account_fee_receivable_id + fee_engagement_journal_id) — sinon le dossier est listé et
   ignoré, à rattraper manuellement une fois le produit paramétré.
"""
import logging

from odoo import api, SUPERUSER_ID

from odoo.addons.microfinance_loan_management.hooks import LOAN_NEW_SUBACCOUNTS, _create_subaccounts

_logger = logging.getLogger(__name__)

_FEE_RECEIVABLE_CODE = '208005'


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    # 1) Sous-compte 208005 par société PCEC ----------------------------------------------------
    subaccount = {_FEE_RECEIVABLE_CODE: LOAN_NEW_SUBACCOUNTS[_FEE_RECEIVABLE_CODE]}
    created = 0
    for company in env['res.company'].search([]):
        if company.chart_template != 'mg_pcec':
            continue
        before = env['account.account'].search_count([
            ('code', '=', _FEE_RECEIVABLE_CODE), ('company_id', '=', company.id)])
        _create_subaccounts(env, company, subaccount)
        if not before:
            created += 1
    _logger.info("Microfinance frais/créance : compte %s créé pour %d société(s) PCEC.",
                 _FEE_RECEIVABLE_CODE, created)

    # 2) Rattrapage engagement des dossiers approuvés non soldés -------------------------------
    Loan = env['microfinance.loan']
    candidates = Loan.search([
        ('state', '=', 'approved'),
        ('fee_paid', '=', False),
        ('fee_amount_due', '>', 0),
        ('fee_receivable_move_id', '=', False),
        ('product_id.fee_charged_before_disbursement', '=', True),
    ])
    done, skipped = [], []
    for loan in candidates:
        product = loan.product_id
        if not (product.fee_engagement_journal_id and product.account_fee_receivable_id
                and product.account_commission_credit_id):
            skipped.append(loan.name)
            continue
        move = env['account.move'].with_context(
            default_loan_id=False, default_loan_line_id=False,
        ).create(loan._prepare_fee_receivable_move())
        move.action_post()
        loan.fee_receivable_move_id = move.id
        loan.message_post(body=(
            "Engagement frais de dossier (rattrapage migration 17.0.1.11.0) : %s" % move.name))
        done.append(loan.name)

    _logger.info(
        "Microfinance frais/créance : engagement rétroactif créé pour %s ; ignoré (produit non "
        "configuré, à rattraper manuellement) pour %s.", done or '—', skipped or '—')
