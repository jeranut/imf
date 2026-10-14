# -*- coding: utf-8 -*-
from odoo import models

from .payroll_param import PARAM_CODES

PAYSLIP_REQUIRED_PARAMS = [code for code, __ in PARAM_CODES]

# hr_payroll_community._prepare_account_move_line_vals() ne retient que
# BASIC/ALW/DED/COMP : la catégorie NET en est exclue, donc le Net à payer
# ne peut jamais être crédité et l'écriture de paie ne peut jamais être
# équilibrée. On surcharge ici (sans toucher au fichier d'origine) pour
# ajouter NET à la liste des catégories éligibles. GROSS reste exclu
# volontairement pour ne pas comptabiliser le brut une deuxième fois.
# 'Travel' : catégorie propre de l'indemnité de transport (distincte de ALW),
# sinon son montant n'est jamais débité et l'écriture est déséquilibrée.
ELIGIBLE_CATEGORY_CODES = ('BASIC', 'ALW', 'Travel', 'DED', 'COMP', 'NET')


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    def _create_account_move(self):
        """Écriture de paie créée dans le contexte de la société DE LA
        FICHE (et non celle du navigateur) : plusieurs sociétés cochées
        n'ont ainsi aucun effet."""
        self.ensure_one()
        return super(HrPayslip, self.with_company(self.company_id)
                     )._create_account_move()

    def _prepare_account_move_line_vals(self):
        self.ensure_one()
        slip = self.with_company(self.company_id)
        company = slip.company_id
        amounts = {}
        for line in slip.line_ids:
            if not line.total or line.category_id.code not in ELIGIBLE_CATEGORY_CODES:
                continue
            rule = line.salary_rule_id
            debit = rule._mowgli_account_for_company(
                'debit_account_id', company)
            if debit:
                key = (debit, 'debit')
                amounts[key] = amounts.get(key, 0.0) + abs(line.total)
            credit = rule._mowgli_account_for_company(
                'credit_account_id', company)
            if credit:
                key = (credit, 'credit')
                amounts[key] = amounts.get(key, 0.0) + abs(line.total)
        move_lines = []
        for (account, direction), amount in amounts.items():
            move_lines.append((0, 0, {
                'account_id': account.id,
                'name': slip.name,
                'debit': amount if direction == 'debit' else 0.0,
                'credit': amount if direction == 'credit' else 0.0,
            }))
        return move_lines

    # ------------------------------------------------------------------
    # Paramètres de cotisations (lus à la date_to et pour la société du bulletin)
    # ------------------------------------------------------------------
    def _mowgli_param(self, code):
        self.ensure_one()
        return self.env['mowgli.payroll.param']._get_value(
            code, self.date_to, self.company_id)

    def _mowgli_contribution_base(self, brut):
        """Base cotisable : min(plafond, max(plancher, brut)), plancher = SME
        si PLANCHER = 1 sinon 0."""
        self.ensure_one()
        sme = self._mowgli_param('SME')
        plafond = self._mowgli_param('FACTEUR_PLAFOND') * sme
        plancher = sme if self._mowgli_param('PLANCHER') else 0.0
        return min(plafond, max(plancher, brut))

    def action_compute_sheet(self):
        # Les erreurs levées dans le code python d'une règle sont masquées par
        # le moteur (« Wrong python code ») : on vérifie donc les paramètres
        # AVANT le calcul pour donner un message clair (ex. SME non défini).
        for payslip in self:
            for code in PAYSLIP_REQUIRED_PARAMS:
                payslip._mowgli_param(code)
        return super().action_compute_sheet()
