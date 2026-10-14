# -*- coding: utf-8 -*-
"""Reprise de portefeuille, volet épargne (extension de microfinance_loan_management, jamais l'inverse) : feuille « Épargne »
du gabarit, soldes d'ouverture posés par une transaction de dépôt déjà « comptabilisée » mais SANS écriture ni mouvement de
caisse, et concordance avec les comptes 213xxx."""
from collections import defaultdict

from odoo import _, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.microfinance_loan_management.models.microfinance_opening_import import _amount, _clean
from odoo.addons.microfinance_loan_management.models.microfinance_opening_reprise_balance import (
    SAVINGS_CODES_DEFAULT, SAVINGS_CODES_PARAM)

SAVINGS_SHEET = 'Épargne'
SAVINGS_HEADERS = ['Référence client', "Produit d'épargne", "Solde d'ouverture"]
ACCOUNT_BY_CLIENT_TYPE = {'individual': 'account_epargne_individuel_id', 'company': 'account_epargne_entreprise_id'}


class MicrofinanceSavingsTransaction(models.Model):
    _inherit = 'microfinance.savings.transaction'

    opening_balance_id = fields.Many2one(
        'microfinance.opening.balance', string="Balance d'ouverture (reprise)", readonly=True, copy=False, index=True,
        ondelete='set null',
        help="Renseigné pour le solde d'ouverture posé par « Reprise de portefeuille » : transaction sans écriture "
             "comptable ni mouvement de caisse (le solde est déjà dans la balance d'ouverture).")

    def write(self, vals):
        if 'amount' in vals and self.filtered('opening_balance_id'):
            raise ValidationError(_("Le solde d'ouverture repris ne peut plus être modifié."))
        return super().write(vals)


class MicrofinanceOpeningReprise(models.TransientModel):
    _inherit = 'microfinance.opening.reprise'

    def _template_sheets(self):
        sheets = super()._template_sheets()
        sheets.append({'name': SAVINGS_SHEET, 'headers': SAVINGS_HEADERS, 'rows': [], 'text_columns': (0, 1),
                       'money_columns': (2,)})
        return sheets

    def _validate_extra(self, sheets, plan, errors, warnings):
        super()._validate_extra(sheets, plan, errors, warnings)
        plan['savings'] = []
        balance, company = plan['balance'], plan['company']
        S = self.sudo()
        Product = S.env['microfinance.savings.product']
        done = {}
        marked = S.env['microfinance.savings.transaction'].search([('opening_balance_id', '=', balance.id)])
        for number, cells in self._sheet_rows(sheets, SAVINGS_SHEET, SAVINGS_HEADERS, errors):
            ref, product_name = _clean(cells[0]), _clean(cells[1])
            if not ref:
                errors.append((SAVINGS_SHEET, number, _("référence client manquante")))
                continue
            info = plan['client_info'](ref)
            if not info:
                errors.append((SAVINGS_SHEET, number, _("client inconnu : %s") % ref))
                continue
            problems = []
            products = Product.search([('name', '=', product_name), ('company_id', '=', company.id)])
            product = products if len(products) == 1 else Product
            if not products:
                problems.append(_("produit d'épargne inconnu dans l'agence : %s") % product_name)
            elif len(products) > 1:
                problems.append(_("plusieurs produits d'épargne portent le nom « %s »") % product_name)
            key = (ref, product.id)
            if product and key in done:
                problems.append(_("produit d'épargne en double pour ce client (ligne %s)") % done[key])
            done.setdefault(key, number)
            try:
                amount = _amount(cells[2])
                if amount != amount or amount in (float('inf'), float('-inf')):
                    raise ValueError
            except ValueError:
                problems.append(_("solde invalide : « %s »") % cells[2])
                amount = 0.0
            if amount <= 0:
                problems.append(_("le solde d'ouverture doit être positif"))
            if product:
                field = ACCOUNT_BY_CLIENT_TYPE.get(info['ctype'])
                if not field or not product[field]:
                    problems.append(_("le produit « %(product)s » n'a pas de compte d'épargne pour ce type de client")
                                    % {'product': product.name})
                if amount > 0 and amount < product.min_opening_amount:
                    problems.append(_("solde inférieur au montant minimum d'ouverture du produit (%s)")
                                    % product.min_opening_amount)
            partner, skip = info['partner'], False
            if product and partner:
                accounts = S.env['microfinance.savings.account'].search([
                    ('partner_id', '=', partner.id), ('product_id', '=', product.id), ('state', '!=', 'closed')])
                if accounts:
                    skip = bool(marked.filtered(lambda t: t.account_id in accounts))
                    if not skip:
                        problems.append(_("le client a déjà ce produit d'épargne ouvert (%s)") % accounts[:1].name)
            if problems:
                errors.append((SAVINGS_SHEET, number, '; '.join(problems)))
                continue
            plan['savings'].append({'row': number, 'ref': ref, 'product': product, 'amount': amount, 'skip': skip})

    def _apply_extra(self, plan):
        created = super()._apply_extra(plan) or {}
        balance, company = plan['balance'], plan['company']
        context = {'microfinance_context': True}
        Account = self.env['microfinance.savings.account'].sudo().with_company(company).with_context(**context)
        Transaction = self.env['microfinance.savings.transaction'].sudo().with_company(company)
        count = 0
        for item in plan.get('savings', []):
            if item['skip']:
                continue
            partner = plan['client_info'](item['ref'])['partner']
            account = Account.create({'partner_id': partner.id, 'company_id': company.id, 'product_id': item['product'].id})
            # Transaction déjà « comptabilisée » sans action_post : pas d'écriture, pas de mouvement de caisse.
            Transaction.create({
                'account_id': account.id, 'transaction_type': 'deposit', 'amount': item['amount'],
                'date': balance.date, 'state': 'posted', 'note': _("Solde d'ouverture repris (%s)") % balance.name,
                'opening_balance_id': balance.id,
            })
            account.write({'opening_date': balance.date})
            account.action_activate()
            count += 1
        created["produits d'épargne"] = count
        return created

    def _summary_extra(self, plan):
        items = [i for i in plan.get('savings', [])]
        return super()._summary_extra(plan) + [
            _("Épargne : %(new)s solde(s) à reprendre, %(old)s déjà repris (ignorés) ; total à reprendre : %(total)s.") % {
                'new': sum(1 for i in items if not i['skip']), 'old': sum(1 for i in items if i['skip']),
                'total': sum(i['amount'] for i in items if not i['skip'])}]

    def _template_instructions(self):
        return super()._template_instructions() + [
            _("9. Feuille Épargne : un solde d'ouverture par client et par produit d'épargne ; il est posé sans écriture "
              "ni mouvement de caisse (il est déjà dans la balance d'ouverture)."),
        ]


class MicrofinanceOpeningBalance(models.Model):
    _inherit = 'microfinance.opening.balance'

    def _reprise_has_data(self):
        return super()._reprise_has_data() or bool(self.env['microfinance.savings.transaction'].sudo().search_count([
            ('opening_balance_id', '=', self.id)]))

    def _reprise_groups(self):
        groups = super()._reprise_groups()
        detail = defaultdict(float)
        for txn in self.env['microfinance.savings.transaction'].sudo().search([('opening_balance_id', '=', self.id),
                                                                                ('state', '=', 'posted')]):
            account = txn.account_id.product_id._get_account('epargne', txn.account_id.partner_id)
            detail[account] += txn.amount if txn.transaction_type in ('deposit', 'interest_credit') else -txn.amount
        groups.append({'label': _("Épargne des clients"), 'detail': detail, 'sign': -1,
                       'codes': self._reprise_codes(SAVINGS_CODES_PARAM, SAVINGS_CODES_DEFAULT)})
        return groups
