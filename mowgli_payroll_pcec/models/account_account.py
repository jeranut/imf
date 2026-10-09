# -*- coding: utf-8 -*-
from odoo import _, api, fields, models

# Comptes PCEC "sûrs" à aligner sur le libellé officiel (code déjà correct,
# seul le libellé Odoo diverge). Rien d'autre dans la classe 65 n'est
# touché : cf. rapport d'audit, écarts 651100/652900 laissés en l'état.
PCEC_RELABEL = {
    '652100': 'Rémunérations du personnel',
    '316000': 'Dividendes à distribuer',
}
# Compte PCEC absent du plan Odoo actuel, à créer s'il manque et que le
# code est libre. Aucune règle patronale n'est créée ici.
PCEC_NEW_ACCOUNT_CODE = '652500'
PCEC_NEW_ACCOUNT_NAME = 'Cotisations aux organismes sociaux'


class AccountAccount(models.Model):
    _inherit = 'account.account'

    mowgli_auto_created = fields.Boolean(
        string="Créé automatiquement", readonly=True, copy=False,
        help="Compte de paie recréé automatiquement par "
             "mowgli_payroll_pcec parce qu'il manquait dans cette société.")

    def _mowgli_references(self):
        """Liste des références qui interdisent de renommer ce compte :
        lignes d'écriture, règles salariales, journaux (compte par
        défaut), positions fiscales, modèles de réconciliation,
        paramètres société pointant vers ce compte. Liste vide = sûr."""
        self.ensure_one()
        refs = []

        move_line_count = self.env['account.move.line'].sudo().search_count(
            [('account_id', '=', self.id)])
        if move_line_count:
            refs.append(_("%d ligne(s) d'écriture") % move_line_count)

        # debit/credit_account_id sont company_dependent : valeurs dans
        # ir_property, pas dans une colonne de hr_salary_rule.
        properties = self.env['ir.property'].sudo().search([
            ('fields_id.model', '=', 'hr.salary.rule'),
            ('fields_id.name', 'in', ['debit_account_id', 'credit_account_id']),
            ('value_reference', '=', 'account.account,%d' % self.id)])
        rule_count = len(set(properties.mapped('res_id')))
        if rule_count:
            refs.append(_("%d règle(s) salariale(s)") % rule_count)

        journal_count = self.env['account.journal'].sudo().search_count(
            [('default_account_id', '=', self.id)])
        if journal_count:
            refs.append(
                _("%d journal/journaux (compte par défaut)") % journal_count)

        fiscal_count = self.env[
            'account.fiscal.position.account'].sudo().search_count([
                '|', ('account_src_id', '=', self.id),
                ('account_dest_id', '=', self.id)])
        if fiscal_count:
            refs.append(_("%d position(s) fiscale(s)") % fiscal_count)

        reconcile_count = self.env[
            'account.reconcile.model.line'].sudo().search_count(
                [('account_id', '=', self.id)])
        if reconcile_count:
            refs.append(
                _("%d modèle(s) de réconciliation") % reconcile_count)

        company_account_fields = [
            fname for fname, field in self.env['res.company']._fields.items()
            if field.type == 'many2one'
            and field.comodel_name == 'account.account'
        ]
        if company_account_fields:
            domain = ['|'] * (len(company_account_fields) - 1) + [
                (fname, '=', self.id) for fname in company_account_fields]
            company_count = self.env['res.company'].sudo().search_count(
                domain)
            if company_count:
                refs.append(_("%d paramètre(s) société") % company_count)

        return refs

    def _mowgli_is_safe_to_relabel(self):
        return not self._mowgli_references()

    @api.model
    def _mowgli_setup_pcec_accounts(self):
        """Aligne les libellés PCEC sûrs et crée 652500 s'il manque, pour
        la société source CEFOR Isotry puis les agences. Idempotent : ne
        renomme jamais un compte référencé (écritures, règles, journal,
        position fiscale, modèle de réconciliation, paramètre société) et
        ne crée jamais de compte si le code est déjà pris. Retourne un
        rapport détaillé (liste de dicts), un changement à la fois."""
        Account = self.env['account.account'].sudo()
        Company = self.env['res.company'].sudo()

        source = Company.search([('name', '=', 'CEFOR Isotry')], limit=1)
        others = Company.search(
            [('id', '!=', source.id)]) if source else Company.search([])
        companies = (source + others) if source else others

        report = []
        for company in companies:
            for code, pcec_label in PCEC_RELABEL.items():
                account = Account.search(
                    [('code', '=', code), ('company_id', '=', company.id)],
                    limit=1)
                entry = {'company': company.name, 'code': code}
                if not account:
                    entry['status'] = 'absent'
                    report.append(entry)
                    continue
                entry['old_name'] = account.name
                if account.name == pcec_label:
                    # Déjà au libellé PCEC : rien à écrire, donc aucune
                    # référence (même une règle salariale qui pointe déjà
                    # vers ce compte) ne doit être signalée comme blocage.
                    entry['status'] = 'already_ok'
                    report.append(entry)
                    continue
                refs = account._mowgli_references()
                if refs:
                    entry.update({'status': 'blocked', 'references': refs})
                    report.append(entry)
                    continue
                account.write({'name': pcec_label})
                entry.update({'status': 'renamed', 'new_name': pcec_label})
                report.append(entry)

            new_entry = {'company': company.name, 'code': PCEC_NEW_ACCOUNT_CODE}
            existing_new = Account.search([
                ('code', '=', PCEC_NEW_ACCOUNT_CODE),
                ('company_id', '=', company.id),
            ], limit=1)
            if existing_new:
                new_entry['status'] = 'already_exists'
            else:
                reference_account = Account.search([
                    ('code', '=', '652100'), ('company_id', '=', company.id),
                ], limit=1)
                if not reference_account:
                    new_entry['status'] = 'skipped_no_coa'
                else:
                    new_account = Account.create({
                        'code': PCEC_NEW_ACCOUNT_CODE,
                        'name': PCEC_NEW_ACCOUNT_NAME,
                        'account_type': reference_account.account_type,
                        'reconcile': reference_account.reconcile,
                        'company_id': company.id,
                    })
                    new_entry.update(
                        {'status': 'created', 'id': new_account.id})
            report.append(new_entry)

        return report
