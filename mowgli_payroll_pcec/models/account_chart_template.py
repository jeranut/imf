# -*- coding: utf-8 -*-
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class AccountChartTemplate(models.AbstractModel):
    _inherit = 'account.chart.template'

    def _load(self, template_code, company, install_demo):
        """Après l'installation d'un plan comptable sur une société,
        renseigne automatiquement les comptes de paie de cette société
        (les codes sont dans le template PCEC : résolution, pas création)."""
        result = super()._load(template_code, company, install_demo)
        if 'hr.salary.rule' in self.env and company.chart_template:
            rows = self.env['hr.salary.rule'].sudo(
            )._mowgli_complete_new_company(company)
            _logger.info(
                "mowgli_payroll_pcec: comptes de paie complétés pour %s "
                "(%d valeur(s) examinée(s)).", company.name, len(rows))
        return result
