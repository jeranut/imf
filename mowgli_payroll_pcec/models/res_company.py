# -*- coding: utf-8 -*-
import logging
import re

from psycopg2 import errorcodes
from psycopg2.errors import OperationalError

from odoo import _, api, models
from odoo.tools import config
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

MODEL_COMPANY_PARAM = 'mowgli_payroll_pcec.model_company_id'
DEFAULT_MODEL_COMPANY_NAME = 'CEFOR Isotry'


class _RetryableConcurrency(OperationalError):
    """Faux échec de sérialisation : le contrôleur HTTP d'Odoo rejoue alors
    la requête dans une nouvelle transaction (qui voit le compte créé par
    la transaction concurrente)."""
    pgcode = errorcodes.SERIALIZATION_FAILURE


class ResCompany(models.Model):
    _inherit = 'res.company'

    @api.model
    def _mowgli_model_company(self):
        """Société modèle des comptes de paie (paramètre système
        mowgli_payroll_pcec.model_company_id, défaut CEFOR Isotry)."""
        Company = self.env['res.company'].sudo()
        param = self.env['ir.config_parameter'].sudo().get_param(
            MODEL_COMPANY_PARAM)
        company = Company.browse(int(param)).exists() if (
            param and param.isdigit()) else Company
        if not company:
            company = Company.search(
                [('name', '=', DEFAULT_MODEL_COMPANY_NAME)], limit=1)
        return company

    def _mowgli_find_account(self, code):
        """Compte de ce code dans CETTE société (lecture seule, sans
        création). Recordset vide si absent."""
        self.ensure_one()
        return self.env['account.account'].sudo().search(
            [('code', '=', code), ('company_id', '=', self.id)], limit=1)

    def _mowgli_check_has_chart(self):
        self.ensure_one()
        if not self.chart_template:
            raise UserError(_(
                "Installez d'abord le plan comptable PCEC pour %s "
                "(Paramètres > Comptabilité).") % self.name)

    def _mowgli_reference_account(self, code, source_company=None):
        """Compte de référence pour `code` : société modèle, sinon société
        de plus petit id qui possède le code. Recordset vide si inconnu."""
        Account = self.env['account.account'].sudo()
        source_company = source_company or self._mowgli_model_company()
        reference = Account.search([
            ('code', '=', code), ('company_id', '=', source_company.id),
        ], limit=1) if source_company else Account
        if not reference:
            reference = Account.search(
                [('code', '=', code)], order='company_id, id', limit=1)
        return reference

    def _mowgli_get_or_create_account(self, code, source_company=None):
        """Renvoie le compte `code` de cette société, en le créant s'il a
        été supprimé alors que la société a un plan comptable.

        - recherche d'abord par code (jamais de doublon) ;
        - société sans plan comptable : UserError, rien n'est créé ;
        - code hors liste blanche (codes des règles de la structure BASE) :
          UserError ;
        - création sous sudo() limité à cette seule opération, à partir de
          la société modèle (ou, à défaut, la société de plus petit id) ;
        - verrou advisory sur (code, société) : Odoo 17 n'a aucune
          contrainte SQL d'unicité du code de compte."""
        self.ensure_one()
        found = self._mowgli_find_account(code)
        if found:
            return found
        self._mowgli_check_has_chart()
        if code not in self.env['hr.salary.rule']._mowgli_payroll_account_codes():
            raise UserError(_(
                "Création automatique refusée : le code %s n'est utilisé "
                "par aucune règle de la structure de paie BASE.") % code)
        reference = self._mowgli_reference_account(code, source_company)
        if not reference:
            raise UserError(_(
                "Code %s inconnu du plan comptable de référence.") % code)

        self._mowgli_lock_account(code)
        found = self._mowgli_find_account(code)
        if found:
            return found
        return self._mowgli_create_account_from(reference)

    def _mowgli_lock_account(self, code):
        """Verrou de transaction sur (code, société). Odoo travaille en
        REPEATABLE READ : après avoir attendu le verrou, cette transaction
        ne voit pas un compte validé entre-temps par une autre. On le
        détecte avec un curseur indépendant et on force un rejeu."""
        cr = self.env.cr
        cr.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            ('mowgli_account_%s_%s' % (code, self.id),))
        query = ("SELECT count(*) FROM account_account "
                 "WHERE code = %s AND company_id = %s")
        cr.execute(query, (code, self.id))
        visible = cr.fetchone()[0]
        with self.pool.cursor() as other_cr:
            other_cr.execute(query, (code, self.id))
            committed = other_cr.fetchone()[0]
        # Les tests (TransactionCase) suppriment parfois le compte dans leur
        # propre transaction, ce qui ressemblerait à un compte « concurrent » ;
        # le verrou est testé à part, avec de vraies transactions parallèles.
        if committed > visible and not config['test_enable']:
            raise _RetryableConcurrency(
                "Compte %s créé par une transaction concurrente." % code)

    def _mowgli_create_account_from(self, reference):
        """Crée, dans cette société, la copie de `reference` (champs de
        l'audit : pas de group_id, recalculé ; pas de allowed_journal_ids)."""
        self.ensure_one()
        Account = self.env['account.account'].sudo().with_company(self)
        self.env.cr.execute(
            "SELECT name FROM account_account WHERE id = %s", (reference.id,))
        name_by_lang = self.env.cr.fetchone()[0] or {}
        base_lang = 'en_US'
        base_name = name_by_lang.get(base_lang) or next(
            iter(name_by_lang.values()), reference.code)

        vals = {
            'code': reference.code,
            'name': base_name,
            'account_type': reference.account_type,
            'reconcile': reference.reconcile,
            'deprecated': reference.deprecated,
            'non_trade': reference.non_trade,
            'note': reference.note,
            'company_id': self.id,
            'mowgli_auto_created': True,
        }
        if reference.currency_id:
            vals['currency_id'] = reference.currency_id.id
        if reference.tag_ids:
            vals['tag_ids'] = [(6, 0, reference.tag_ids.ids)]
        if reference.tax_ids:
            Tax = self.env['account.tax'].sudo()
            taxes = Tax
            for tax in reference.tax_ids:
                taxes |= Tax.search([
                    ('name', '=', tax.name), ('company_id', '=', self.id),
                    ('type_tax_use', '=', tax.type_tax_use)], limit=1)
            vals['tax_ids'] = [(6, 0, taxes.ids)]
        if 'cash_flow_type' in Account._fields and reference.cash_flow_type:
            vals['cash_flow_type'] = reference.cash_flow_type.id

        account = Account.with_context(
            lang=base_lang, tracking_disable=True).create(vals)
        for lang, text in name_by_lang.items():
            if lang != base_lang:
                account.update_field_translations('name', {lang: text})
        self._mowgli_copy_xmlid(reference, account)

        source = reference.company_id
        message = _(
            "Compte %(code)s créé automatiquement pour %(company)s depuis "
            "%(source)s.") % {'code': account.code, 'company': self.name,
                              'source': source.name}
        _logger.info(message)
        if hasattr(account, 'message_post'):
            account.message_post(body=message)
        return account

    def _mowgli_copy_xmlid(self, reference, account):
        """Pose account.<cid>_<suffixe> identique à celui de la société
        modèle (ex. 1_pcec_6521 -> 7_pcec_6521)."""
        data = self.env['ir.model.data'].sudo().search([
            ('model', '=', 'account.account'), ('res_id', '=', reference.id),
            ('module', '=', 'account')], limit=1)
        match = re.match(r'^%d_(.+)$' % reference.company_id.id, data.name or '')
        if not match:
            return
        xml_id = 'account.%d_%s' % (self.id, match.group(1))
        self.env['ir.model.data']._update_xmlids([{
            'xml_id': xml_id, 'record': account, 'noupdate': True}])
