# -*- coding: utf-8 -*-
import json
import logging

from odoo import _, api, models
from odoo.exceptions import UserError
from odoo.tools import file_open

_logger = logging.getLogger(__name__)

CONFIG_FILE = 'mowgli_payroll_accounts/data/payroll_accounts.json'
ROLE_FIELDS = {'debit': 'debit_account_id', 'credit': 'credit_account_id'}


class HrSalaryRule(models.Model):
    _inherit = 'hr.salary.rule'

    @api.model
    def _mf_payroll_accounts_config(self):
        with file_open(CONFIG_FILE) as config_file:
            return json.load(config_file)

    @api.model
    def _mf_ensure_payroll_accounts(self, company):
        """Idempotent : (1) crée dans `company` les comptes de paie manquants
        (copie des valeurs d'une autre société qui a le code, sinon valeurs de
        la liste de données) ; un compte existant au même code mais de nature
        différente arrête tout (UserError), un compte existant n'est jamais
        modifié ; (2) configure les comptes de chaque règle de la structure
        BASE pour cette société (écrit seulement si la valeur diffère).
        Renvoie {'created': [codes], 'rules': [(règle, rôle, avant, après)]}."""
        company = company.sudo()
        result = {'created': [], 'rules': []}
        if not company.chart_template:
            return result
        config = self._mf_payroll_accounts_config()
        Account = self.env['account.account'].sudo()
        for spec in config['accounts']:
            account = Account.search(
                [('code', '=', spec['code']), ('company_id', '=', company.id)],
                limit=1)
            if account:
                if (account.account_type != spec['account_type']
                        or bool(account.reconcile) != spec['reconcile']):
                    raise UserError(_(
                        "Le compte %(code)s de %(company)s existe déjà avec une "
                        "nature différente (%(type)s, lettrable : %(rec)s) de "
                        "celle attendue (%(etype)s, lettrable : %(erec)s) : "
                        "arrêt, rien n'est modifié.") % {
                            'code': spec['code'], 'company': company.name,
                            'type': account.account_type, 'rec': account.reconcile,
                            'etype': spec['account_type'],
                            'erec': spec['reconcile']})
                continue
            reference = Account.search(
                [('code', '=', spec['code']), ('company_id', '!=', company.id),
                 ('account_type', '=', spec['account_type'])],
                order='company_id, id', limit=1)
            if reference:
                company._mowgli_create_account_from(reference)
            else:
                Account.with_company(company).create({
                    'code': spec['code'], 'name': spec['name'],
                    'account_type': spec['account_type'],
                    'reconcile': spec['reconcile'], 'company_id': company.id})
            result['created'].append(spec['code'])
        structure = self.env['hr.payroll.structure'].sudo().search(
            [('code', '=', 'BASE')], limit=1)
        rules = {rule.code: rule for rule in structure.rule_ids.sudo()}
        for mapping in config['rules']:
            rule = rules.get(mapping['rule'])
            account = Account.search(
                [('code', '=', mapping['account']),
                 ('company_id', '=', company.id)], limit=1)
            if not rule or not account:
                _logger.warning(
                    "mowgli_payroll_accounts: règle %s ou compte %s absent "
                    "pour %s, ignoré.", mapping['rule'], mapping['account'],
                    company.name)
                continue
            fname = ROLE_FIELDS[mapping['role']]
            scoped = rule.with_company(company)
            current = scoped[fname]
            if current == account:
                continue
            scoped.write({fname: account.id})
            result['rules'].append((
                rule.code, mapping['role'], current.code or '', account.code))
        if result['created'] or result['rules']:
            _logger.info(
                "mowgli_payroll_accounts: %s : comptes créés %s ; règles "
                "configurées %s", company.name, result['created'],
                result['rules'])
        return result

    @api.model
    def _mf_ensure_payroll_accounts_all(self):
        """Pour chaque société avec plan comptable (script de données)."""
        for company in self.env['res.company'].sudo().search(
                [('chart_template', '!=', False)]):
            self._mf_ensure_payroll_accounts(company)
