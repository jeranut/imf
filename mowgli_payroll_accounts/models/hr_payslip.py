# -*- coding: utf-8 -*-
from odoo import models

EMPLOYER_CODES = ('CNAPS_ER', 'OSTIE_ER')


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    def _mowgli_post_csoc(self):
        """Quand les règles patronales portent leurs comptes, la part patronale
        est déjà dans l'écriture du bulletin : l'écriture du journal CSOC la
        compterait une seconde fois. Le registre reste alimenté."""
        self.ensure_one()
        rules = self.line_ids.filtered(
            lambda line: line.code in EMPLOYER_CODES).mapped('salary_rule_id')
        rules = rules.sudo().with_company(self.company_id)
        if rules and all(rule.debit_account_id and rule.credit_account_id
                         for rule in rules):
            rows = self.mowgli_contribution_ids.filtered(
                lambda row: row.nature == 'patronal')
            if self.move_id:
                rows.sudo().write({'move_id': self.move_id.id})
            return
        return super()._mowgli_post_csoc()
