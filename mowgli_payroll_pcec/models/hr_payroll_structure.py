# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import AccessError

MANAGER_GROUP = 'hr_payroll_community.group_hr_payroll_community_manager'

# Champs de hr.salary.rule copiés tels quels de la source vers la cible.
# category_id reste partagé (même id) : cf. décision du 2026-10-04, les
# catégories ont toutes company_id=1 mais ne sont protégées par aucun
# ir.rule, donc réutilisables sans modification.
RULE_FIELDS = (
    'name', 'code', 'sequence', 'condition_select', 'condition_range',
    'condition_range_min', 'condition_range_max', 'condition_python',
    'amount_select', 'amount_fix', 'amount_percentage',
    'amount_percentage_base', 'amount_python_compute', 'appears_on_payslip',
)
RULE_RELATIONAL_FIELDS = ('category_id', 'company_id', 'debit_account_id',
                          'credit_account_id')


class HrPayrollStructure(models.Model):
    # hr.payroll.structure n'hérite pas de mail.thread dans
    # hr_payroll_community : ajouté ici pour permettre message_post()
    # (rapport de synchro dans le chatter), sans toucher au module d'origine.
    # _name explicite requis en plus de _inherit (liste) : sans lui, Odoo
    # ne reconnaît pas qu'il s'agit d'étendre le modèle existant + y
    # ajouter un mixin, et redéclare rule_ids en double (TypeError au
    # démarrage : « use the same table and columns »).
    _name = 'hr.payroll.structure'
    _inherit = ['hr.payroll.structure', 'mail.thread']

    # Structure PARTAGÉE entre agences : société facultative et vide.
    company_id = fields.Many2one(
        'res.company', string='Société', required=False, default=False,
        help="Laisser vide : la structure est partagée par toutes les "
             "agences.")
    mowgli_source_id = fields.Many2one(
        'hr.payroll.structure', string='Structure source (OBSOLÈTE)',
        index=True, copy=False, readonly=True,
        help="OBSOLÈTE : ancienne copie de structure par agence, plus "
             "utilisée (la structure est désormais partagée).")

    def action_open_mowgli_sync_wizard(self):
        self.ensure_one()
        self._mowgli_check_manager()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Compléter les comptes de paie par société"),
            'res_model': 'mowgli.payroll.sync.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_structure_id': self.id},
        }

    def _mowgli_check_manager(self):
        if not self.env.user.has_group(MANAGER_GROUP):
            raise AccessError(_(
                "Seuls les utilisateurs du groupe Paie / Manager peuvent "
                "compléter les comptes de paie par société."))

    def _mowgli_find_account_for_company(self, account, target_company):
        """Retrouve, chez la société cible, le compte de même code que
        `account` (comparaison sur le code, jamais sur l'id). Ne crée et ne
        renomme jamais de compte : si rien ne correspond, renvoie (False,
        message d'avertissement).

        OBSOLÈTE : approche « une copie par agence », conservée mais plus
        appelée."""
        if not account:
            return False, None
        target_account = self.env['account.account'].sudo().search([
            ('code', '=', account.code),
            ('company_id', '=', target_company.id),
        ], limit=1)
        if target_account:
            return target_account.id, None
        return False, _(
            "Compte %(code)s (%(name)s) introuvable chez %(company)s : "
            "champ laissé vide.") % {
                'code': account.code, 'name': account.name,
                'company': target_company.name}

    def _mowgli_find_or_create_payroll_journal(self, target_company):
        """Étape D : si la société cible n'a pas de journal de paie, en
        crée un (nom « Salaires », type general, code SAL) seulement s'il
        manque vraiment. Ne modifie jamais un journal existant. Si le code
        SAL est déjà pris par un autre journal, ne l'écrase pas : le
        signale et laisse payroll_journal_id vide.

        OBSOLÈTE : conservée mais plus appelée."""
        if target_company.payroll_journal_id:
            return {'status': 'already_configured'}

        Journal = self.env['account.journal'].sudo()
        existing_sal = Journal.search([
            ('code', '=', 'SAL'), ('company_id', '=', target_company.id),
        ], limit=1)
        if existing_sal:
            return {
                'status': 'code_taken',
                'message': _(
                    "Le code journal SAL existe déjà chez %(company)s "
                    "(« %(name)s ») : journal non créé, "
                    "payroll_journal_id laissé vide.") % {
                        'company': target_company.name,
                        'name': existing_sal.name},
            }

        journal = Journal.create({
            'name': 'Salaires',
            'code': 'SAL',
            'type': 'general',
            'company_id': target_company.id,
        })
        target_company.sudo().write({'payroll_journal_id': journal.id})
        return {'status': 'created', 'id': journal.id}

    def _mowgli_sync_to_company(self, target_company, create_journal=False):
        """Propage cette structure (et ses règles) vers `target_company`.
        Idempotent : recherche par mowgli_source_id puis par (code,
        company_id) avant de créer. Ne supprime et ne désactive jamais rien
        chez la cible ; les règles en trop y sont seulement listées.

        OBSOLÈTE : approche « une copie par agence » remplacée par une
        structure partagée et des comptes par société ; conservée, plus
        appelée."""
        self.ensure_one()
        self._mowgli_check_manager()
        source = self
        report = {
            'company_id': target_company.id,
            'company_name': target_company.name,
            'structure': {},
            'rules': [],
            'accounts_missing': [],
            'extra_rules': [],
            'journal_missing': False,
            'journal_action': None,
            'other_structure_contracts': [],
        }

        Structure = self.env['hr.payroll.structure'].sudo()
        target_structure = Structure.search([
            ('mowgli_source_id', '=', source.id),
            ('company_id', '=', target_company.id),
        ], limit=1)
        if not target_structure:
            target_structure = Structure.search([
                ('code', '=', source.code),
                ('company_id', '=', target_company.id),
            ], limit=1)

        parent_id = False
        if source.parent_id:
            parent_target = Structure.search([
                ('mowgli_source_id', '=', source.parent_id.id),
                ('company_id', '=', target_company.id),
            ], limit=1)
            if parent_target:
                parent_id = parent_target.id
            else:
                report['structure']['parent_warning'] = _(
                    "Structure parente non synchronisée pour cette "
                    "société : lien parent non reporté.")

        struct_vals = {
            'name': source.name,
            'code': source.code,
            'company_id': target_company.id,
            'parent_id': parent_id,
            'note': source.note,
            'mowgli_source_id': source.id,
        }
        diff_fields = ('name', 'code', 'company_id', 'parent_id', 'note')
        if target_structure:
            before = {
                f: (target_structure[f].id if f in ('company_id', 'parent_id')
                    else target_structure[f])
                for f in diff_fields
            }
            target_structure.write(struct_vals)
            changed = any(before[f] != struct_vals[f] for f in diff_fields)
            report['structure'].update({
                'status': 'updated' if changed else 'unchanged',
                'id': target_structure.id,
            })
        else:
            target_structure = Structure.create(struct_vals)
            report['structure'].update(
                {'status': 'created', 'id': target_structure.id})

        source_rule_codes = set()
        SalaryRule = self.env['hr.salary.rule'].sudo()
        for rule in source.rule_ids.sorted('sequence'):
            source_rule_codes.add(rule.code)
            target_rule = target_structure.rule_ids.filtered(
                lambda r: r.mowgli_source_id.id == rule.id)
            if not target_rule:
                target_rule = target_structure.rule_ids.filtered(
                    lambda r: r.code == rule.code)
            target_rule = target_rule[:1]

            debit_id, debit_warning = self._mowgli_find_account_for_company(
                rule.debit_account_id, target_company)
            credit_id, credit_warning = self._mowgli_find_account_for_company(
                rule.credit_account_id, target_company)
            for warning in (debit_warning, credit_warning):
                if warning:
                    report['accounts_missing'].append(
                        {'rule_code': rule.code, 'message': warning})

            rule_vals = {f: rule[f] for f in RULE_FIELDS}
            rule_vals.update({
                'category_id': rule.category_id.id,
                'company_id': target_company.id,
                'debit_account_id': debit_id,
                'credit_account_id': credit_id,
                'mowgli_source_id': rule.id,
            })

            if target_rule:
                before = {
                    f: (target_rule[f].id if f in RULE_RELATIONAL_FIELDS
                        else target_rule[f])
                    for f in rule_vals if f != 'mowgli_source_id'
                }
                target_rule.write(rule_vals)
                changed = any(
                    before[f] != rule_vals[f] for f in before)
                status = 'updated' if changed else 'unchanged'
                rule_id = target_rule.id
            else:
                new_rule = SalaryRule.create(rule_vals)
                target_structure.write({'rule_ids': [(4, new_rule.id)]})
                status = 'created'
                rule_id = new_rule.id

            report['rules'].append(
                {'code': rule.code, 'status': status, 'id': rule_id})

        for rule in target_structure.rule_ids:
            if rule.code not in source_rule_codes:
                report['extra_rules'].append(rule.code)

        if create_journal:
            report['journal_action'] = (
                self._mowgli_find_or_create_payroll_journal(target_company))
        report['journal_missing'] = not target_company.payroll_journal_id

        other_contracts = self.env['hr.contract'].sudo().search([
            ('company_id', '=', target_company.id),
            ('struct_id', '!=', False),
            ('struct_id', '!=', target_structure.id),
        ])
        for contract in other_contracts:
            report['other_structure_contracts'].append({
                'contract': contract.name,
                'employee': contract.employee_id.name,
                'structure': contract.struct_id.name,
            })

        return report
