# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError

PAYROLL_MANAGER_GROUP = 'hr_payroll_community.group_hr_payroll_community_manager'
MICROFINANCE_GESTIONNAIRE_GROUP = 'microfinance_loan_management.group_microfinance_gestionnaire'


class MicrofinanceLoanSalaryDeductionRegularizationWizard(models.TransientModel):
    _name = 'microfinance.loan.salary.deduction.regularization.wizard'
    _description = "Régularisation de la retenue sur salaire (prêt employé déjà décaissé)"

    loan_id = fields.Many2one('microfinance.loan', required=True, readonly=True)
    partner_id = fields.Many2one(related='loan_id.partner_id', string='Client', readonly=True)
    employee_id = fields.Many2one(
        'hr.employee', string='Employé à lier',
        help="À renseigner uniquement si le lien employé-client n'existe pas encore : "
             "corrige hr.employee.microfinance_partner_id dans la même action. Laisser "
             "vide si le lien existe déjà et que seul le flag « Retenue sur salaire » doit "
             "être régularisé.",
    )
    reason = fields.Text(string='Motif', required=True)

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        loan = self.env['microfinance.loan'].browse(vals.get('loan_id'))
        if loan and not loan.partner_id.microfinance_employee_ids:
            match = self.env['hr.employee'].microfinance_match_candidates(partner=loan.partner_id)
            if match['match_type'] == 'cin' and len(match['candidates']) == 1:
                vals['employee_id'] = match['candidates'].id
        return vals

    def _check_access(self):
        user = self.env.user
        if not (user.has_group(PAYROLL_MANAGER_GROUP) and user.has_group(MICROFINANCE_GESTIONNAIRE_GROUP)):
            raise UserError(_(
                "Seul un utilisateur à la fois responsable paie ET gestionnaire microfinance "
                "peut régulariser une retenue sur salaire après décaissement."
            ))

    def action_confirm(self):
        self.ensure_one()
        self._check_access()
        if not self.reason:
            raise UserError(_(
                "Le motif de regularisation est obligatoire."
            ))
        loan = self.loan_id
        if self.employee_id:
            if self.employee_id.microfinance_partner_id and \
                    self.employee_id.microfinance_partner_id != loan.partner_id:
                raise UserError(_(
                    "%(employee)s est déjà lié à un autre client (%(partner)s) : impossible "
                    "de le relier aussi à %(new_partner)s."
                ) % {
                    'employee': self.employee_id.display_name,
                    'partner': self.employee_id.microfinance_partner_id.display_name,
                    'new_partner': loan.partner_id.display_name,
                })
            if not self.employee_id.microfinance_partner_id:
                self.employee_id.microfinance_partner_id = loan.partner_id.id
                self.employee_id.message_post(body=_(
                    "Lien employé-client corrigé par régularisation du prêt %(loan)s. "
                    "Motif : %(reason)s"
                ) % {'loan': loan.name, 'reason': self.reason})
        if not loan.salary_deduction:
            loan._microfinance_regularize_salary_deduction(self.reason)
        return {'type': 'ir.actions.act_window_close'}
