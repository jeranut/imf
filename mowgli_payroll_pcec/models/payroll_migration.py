# -*- coding: utf-8 -*-
"""Migration « paie multi-sociétés » (rejouable, dry-run par défaut).

Les scripts pre/post-migrate d'Odoo ne s'exécutent qu'une fois par version :
un dry-run les consommerait. La migration est donc une fonction appelée à
chaque -u (data/hr_payroll_rules_data.xml), no-op une fois
mowgli_payroll_pcec.migration_done = True.

a. valeurs historiques des colonnes debit/credit (757, 612...) copiées en
   ir_property pour la société PROPRIÉTAIRE du compte, comptage avant/après,
   puis colonnes vidées ;
b. structure BASE et toutes les règles : company_id = NULL ;
c. valeurs par société résolues par code (10 sociétés avec plan) ;
e. vérification, CSV des écarts.

Dry-run tant que mowgli_payroll_pcec.migration_apply n'est pas 'True' :
seul un CSV est écrit. Aucune fiche de paie ni écriture n'est touchée.
"""
import csv
import logging
import os
from datetime import datetime

from odoo import api, models

_logger = logging.getLogger(__name__)

MIGRATIONS_DIR = '/opt/odoo17_2/odoo/microfinance_migrations'
FIELDS = ('debit_account_id', 'credit_account_id')
CSV_FIELDS = ('phase', 'societe', 'regle', 'role', 'code', 'compte_id', 'statut')
PARAM_APPLY = 'mowgli_payroll_pcec.migration_apply'
PARAM_DONE = 'mowgli_payroll_pcec.migration_done'


class MowgliPayrollMigration(models.AbstractModel):
    _name = 'mowgli.payroll.migration'
    _description = "Migration paie multi-sociétés"

    @api.model
    def _run(self):
        params = self.env['ir.config_parameter'].sudo()
        if params.get_param(PARAM_DONE) == 'True':
            return
        apply = params.get_param(PARAM_APPLY) == 'True'
        Rule = self.env['hr.salary.rule']
        legacy = Rule._mowgli_migration_pending()
        if legacy and not apply:
            rows = self._step_a(apply=False) + self._step_b(apply=False)
            rows += self._dry_run_step_c()
            self._write_csv('DRYRUN', rows)
            _logger.info("mowgli_payroll_pcec: migration paie en DRY-RUN "
                         "(rien n'a été modifié).")
            return
        rows = self._step_a(apply=True) + self._step_b(apply=True)
        structure = self.env['hr.payroll.structure'].search(
            [('code', '=', 'BASE')], limit=1)
        companies = self.env['res.company'].search([])
        if structure:
            rows += [dict(r, phase='c') for r in
                     Rule._mowgli_complete_company_accounts(
                         structure.rule_ids, companies, apply=True)]
            for r in Rule._mowgli_complete_company_accounts(
                    structure.rule_ids, companies, apply=False):
                ok = r['statut'] == 'deja_renseigne'
                rows.append(dict(r, phase='e', statut=(
                    'OK' if ok else 'ECART:%s' % r['statut'])))
        self._write_csv('REEL', rows)
        params.set_param(PARAM_DONE, 'True')
        params.set_param(PARAM_APPLY, 'False')
        _logger.info("mowgli_payroll_pcec: migration paie multi-sociétés "
                     "APPLIQUÉE.")

    def _column_exists(self, column):
        self.env.cr.execute("""SELECT 1 FROM information_schema.columns
            WHERE table_name = 'hr_salary_rule' AND column_name = %s""",
                            (column,))
        return bool(self.env.cr.fetchone())

    def _step_a(self, apply):
        cr = self.env.cr
        rows = []
        for fname in FIELDS:
            if not self._column_exists(fname):
                continue
            field = self.env['ir.model.fields']._get('hr.salary.rule', fname)
            cr.execute("""
                SELECT r.id, r.code, r."%s", a.code, a.company_id
                  FROM hr_salary_rule r
                  JOIN account_account a ON a.id = r."%s"
                 WHERE r."%s" IS NOT NULL ORDER BY r.id""" % (fname, fname, fname))
            legacy = cr.fetchall()
            for rule_id, rule_code, account_id, account_code, company_id in legacy:
                res_id = 'hr.salary.rule,%d' % rule_id
                cr.execute("""SELECT 1 FROM ir_property WHERE fields_id = %s
                                 AND res_id = %s AND company_id = %s""",
                           (field.id, res_id, company_id))
                exists = bool(cr.fetchone())
                if apply and not exists:
                    cr.execute("""
                        INSERT INTO ir_property (name, fields_id, company_id,
                            res_id, type, value_reference, create_uid,
                            create_date, write_uid, write_date)
                        VALUES (%s, %s, %s, %s, 'many2one', %s, 1, now(), 1, now())""",
                               (fname, field.id, company_id, res_id,
                                'account.account,%d' % account_id))
                rows.append({
                    'phase': 'a', 'societe': company_id, 'regle': rule_code,
                    'role': fname, 'code': account_code,
                    'compte_id': account_id,
                    'statut': 'deja_migre' if exists else (
                        'copie_en_propriete' if apply else 'a_copier')})
            if apply and legacy:
                cr.execute("""SELECT count(*) FROM ir_property
                               WHERE fields_id = %s
                                 AND res_id LIKE 'hr.salary.rule,%%'
                                 AND value_reference LIKE 'account.account,%%'""",
                           (field.id,))
                after = cr.fetchone()[0]
                if after < len(legacy):
                    raise RuntimeError(
                        "Migration paie annulée : %s, %d valeur(s) en colonne "
                        "mais %d en propriété." % (fname, len(legacy), after))
                cr.execute('UPDATE hr_salary_rule SET "%s" = NULL' % fname)
                _logger.info("mowgli_payroll_pcec: %s migré (%d -> %d).",
                             fname, len(legacy), after)
        return rows

    def _step_b(self, apply):
        cr = self.env.cr
        rows = []
        for table, label in (('hr_payroll_structure', 'structure:'),
                             ('hr_salary_rule', '')):
            cr.execute("SELECT id, code, company_id FROM %s ORDER BY id" % table)
            for __, code, company_id in cr.fetchall():
                rows.append({
                    'phase': 'b', 'societe': company_id or '',
                    'regle': label + (code or ''),
                    'statut': ('company_id->NULL' if company_id
                               else 'deja_partagee')})
            if apply:
                cr.execute("UPDATE %s SET company_id = NULL "
                           "WHERE company_id IS NOT NULL" % table)
        if apply:
            self.env.invalidate_all()
        return rows

    def _dry_run_step_c(self):
        """Simulation SQL (valeurs encore en colonne)."""
        cr = self.env.cr
        rows = []
        cr.execute("SELECT id, name, chart_template FROM res_company ORDER BY id")
        companies = cr.fetchall()
        for role, column in (('debit', 'debit_account_id'),
                             ('credit', 'credit_account_id')):
            if not self._column_exists(column):
                continue
            cr.execute("""
                SELECT r.code, a.code FROM hr_salary_rule r
                  JOIN account_account a ON a.id = r."%s"
                  JOIN hr_structure_salary_rule_rel rel ON rel.rule_id = r.id
                 ORDER BY r.id""" % column)
            for rule_code, account_code in cr.fetchall():
                for company_id, name, chart in companies:
                    row = {'phase': 'c', 'societe': name, 'regle': rule_code,
                           'role': role, 'code': account_code, 'compte_id': ''}
                    if not chart:
                        row['statut'] = 'sans_plan_a_installer'
                    else:
                        cr.execute("""SELECT id FROM account_account
                                       WHERE code = %s AND company_id = %s""",
                                   (account_code, company_id))
                        found = cr.fetchone()
                        row.update(compte_id=found[0] if found else '',
                                   statut='resolu' if found else 'a_creer')
                    rows.append(row)
        return rows

    def _write_csv(self, mode, rows):
        os.makedirs(MIGRATIONS_DIR, exist_ok=True)
        path = os.path.join(MIGRATIONS_DIR, 'paie_multisociete_%s_%s_%s.csv' % (
            self.env.cr.dbname, mode, datetime.now().strftime('%Y%m%d_%H%M%S')))
        with open(path, 'w', newline='', encoding='utf-8') as handle:
            writer = csv.DictWriter(handle, delimiter=';', fieldnames=CSV_FIELDS,
                                    extrasaction='ignore', restval='')
            writer.writeheader()
            writer.writerows(rows)
        _logger.info("mowgli_payroll_pcec: CSV de migration %s", path)
