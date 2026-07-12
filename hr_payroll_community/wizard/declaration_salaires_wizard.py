# -*- coding: utf-8 -*-
import base64
import io

import xlsxwriter

from odoo import fields, models


class DeclarationSalairesWizard(models.TransientModel):
    """Assistant de génération de la Déclaration des Salaires (DS)"""
    _name = 'hr.declaration.salaires.wizard'
    _description = 'Assistant Déclaration des Salaires'

    date_from = fields.Date(string='Du', required=True,
                            default=lambda self: fields.Date.today().replace(
                                day=1))
    date_to = fields.Date(string='Au', required=True,
                          default=fields.Date.today)
    company_id = fields.Many2one('res.company', string='Société',
                                 required=True,
                                 default=lambda self: self.env.company)

    def _get_payslips(self):
        """Retourne les bulletins validés de la période pour la société"""
        self.ensure_one()
        return self.env['hr.payslip'].search([
            ('state', 'in', ('done', 'paid')),
            ('date_from', '>=', self.date_from),
            ('date_to', '<=', self.date_to),
            ('company_id', '=', self.company_id.id),
        ])

    @staticmethod
    def _sum_codes(payslip, codes):
        """Somme les lignes du bulletin dont le code de règle est dans codes"""
        lines = payslip.line_ids.filtered(lambda line: line.code in codes)
        return sum(lines.mapped('total'))

    @staticmethod
    def _sum_category(payslip, category_code):
        """Somme les lignes du bulletin appartenant à une catégorie donnée"""
        lines = payslip.line_ids.filtered(
            lambda line: line.category_id.code == category_code)
        return sum(lines.mapped('total'))

    def _get_declaration_lines(self):
        """Agrège, par employé, les montants nécessaires à la DS"""
        self.ensure_one()
        payslips = self._get_payslips()
        result = {}
        for payslip in payslips:
            employee = payslip.employee_id
            row = result.setdefault(employee, {
                'brut': 0.0,
                'irsa': 0.0,
                'cnaps_ostie_sal': 0.0,
                'cnaps_ostie_pat': 0.0,
                'fmfp': 0.0,
            })
            row['brut'] += self._sum_category(payslip, 'GROSS')
            row['irsa'] += self._sum_codes(payslip, ('IRSA',))
            row['cnaps_ostie_sal'] += self._sum_codes(
                payslip, ('CNAPS_SAL', 'OSTIE_SAL'))
            row['cnaps_ostie_pat'] += self._sum_codes(
                payslip, ('CNAPS_PAT', 'OSTIE_PAT'))
            row['fmfp'] += self._sum_codes(payslip, ('FMFP',))
        return result

    def action_generate_xlsx(self):
        """Génère le fichier XLSX de la Déclaration des Salaires"""
        self.ensure_one()
        declaration_lines = self._get_declaration_lines()

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('DS')
        bold = workbook.add_format({'bold': True})
        amount_format = workbook.add_format({'num_format': '#,##0.00'})

        headers = ['Employé', 'Salaire Brut', 'IRSA', 'CNAPS+OSTIE Salarial',
                   'CNAPS+OSTIE Patronal', 'FMFP']
        for col, header in enumerate(headers):
            sheet.write(0, col, header, bold)

        row_index = 1
        for employee, amounts in declaration_lines.items():
            sheet.write(row_index, 0, employee.name)
            sheet.write(row_index, 1, amounts['brut'], amount_format)
            sheet.write(row_index, 2, amounts['irsa'], amount_format)
            sheet.write(row_index, 3, amounts['cnaps_ostie_sal'],
                       amount_format)
            sheet.write(row_index, 4, amounts['cnaps_ostie_pat'],
                       amount_format)
            sheet.write(row_index, 5, amounts['fmfp'], amount_format)
            row_index += 1
        workbook.close()
        output.seek(0)

        attachment = self.env['ir.attachment'].create({
            'name': 'Declaration_Salaires_%s_%s.xlsx' % (
                self.date_from, self.date_to),
            'type': 'binary',
            'datas': base64.b64encode(output.read()),
            'res_model': self._name,
            'res_id': self.id,
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % attachment.id,
            'target': 'self',
        }
