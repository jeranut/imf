from odoo import models, fields, api

class HrAdvanceSalary(models.Model):
    _name = 'hr.advance.salary'
    _description = 'Advance Salary'
    _rec_name = 'employee_id'

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        domain=lambda self: [('company_id', '=', self.env.company.id)]
    )
    date = fields.Date(string='Advance Date', required=True, default=fields.Date.today)
    amount = fields.Float(string='Amount', required=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('approved', 'Approved'),
    ], default='draft', string='Status')
    company_id = fields.Many2one(
        'res.company', string='Company', default=lambda self: self.env.company.id, required=True
    )

    def action_approve(self):
        self.state = 'approved'


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    advance_amount = fields.Float(string="Avance sur salaire")

    def action_add_advance(self):
        for payslip in self:
            if payslip.advance_amount > 0 and payslip.contract_id:
                # Crée l'avance pour l'employé
                advance = self.env['hr.advance.salary'].create({
                    'employee_id': payslip.employee_id.id,
                    'date': fields.Date.today(),
                    'amount': payslip.advance_amount,
                    'state': 'approved',
                    'company_id': payslip.company_id.id,
                })

                # Ajoute une ligne input sur le bulletin sans company_id
                payslip.input_line_ids = [(0, 0, {
                    'name': 'Avance sur Salaire',
                    'code': 'ADVANCE',
                    'amount': advance.amount,
                    'contract_id': payslip.contract_id.id,  # c’est suffisant pour le lien entreprise
                })]

                # Réinitialise le champ pour éviter les doublons
                payslip.advance_amount = 0

