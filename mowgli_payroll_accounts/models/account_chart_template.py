# -*- coding: utf-8 -*-
from odoo import models


class AccountChartTemplate(models.AbstractModel):
    _inherit = 'account.chart.template'

    def _load(self, template_code, company, install_demo):
        """Après le chargement du plan sur une société (agence créée plus
        tard, même déclencheur que le provisionnement PCEC), crée ses comptes
        de paie et configure les comptes des règles."""
        result = super()._load(template_code, company, install_demo)
        if company.chart_template:
            self.env['hr.salary.rule']._mf_ensure_payroll_accounts(company)
        return result
