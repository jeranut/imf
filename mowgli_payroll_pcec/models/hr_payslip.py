# -*- coding: utf-8 -*-
from odoo import models

# hr_payroll_community._prepare_account_move_line_vals() ne retient que
# BASIC/ALW/DED/COMP : la catégorie NET en est exclue, donc le Net à payer
# ne peut jamais être crédité et l'écriture de paie ne peut jamais être
# équilibrée. On surcharge ici (sans toucher au fichier d'origine) pour
# ajouter NET à la liste des catégories éligibles. GROSS reste exclu
# volontairement pour ne pas comptabiliser le brut une deuxième fois.
ELIGIBLE_CATEGORY_CODES = ('BASIC', 'ALW', 'DED', 'COMP', 'NET')


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    def _prepare_account_move_line_vals(self):
        self.ensure_one()
        amounts = {}
        for line in self.line_ids:
            if not line.total or line.category_id.code not in ELIGIBLE_CATEGORY_CODES:
                continue
            rule = line.salary_rule_id
            if rule.debit_account_id:
                key = (rule.debit_account_id, 'debit')
                amounts[key] = amounts.get(key, 0.0) + abs(line.total)
            if rule.credit_account_id:
                key = (rule.credit_account_id, 'credit')
                amounts[key] = amounts.get(key, 0.0) + abs(line.total)
        move_lines = []
        for (account, direction), amount in amounts.items():
            move_lines.append((0, 0, {
                'account_id': account.id,
                'name': self.name,
                'debit': amount if direction == 'debit' else 0.0,
                'credit': amount if direction == 'credit' else 0.0,
            }))
        return move_lines
