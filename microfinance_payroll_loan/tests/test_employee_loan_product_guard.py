# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from odoo.addons.microfinance_loan_management.tests.common import MicrofinanceCommon


@tagged('post_install', '-at_install')
class TestMicrofinanceEmployeeLoanProductGuard(MicrofinanceCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.monthly = cls.env.ref('microfinance_loan_management.repayment_frequency_monthly')
        cls.weekly = cls.env.ref('microfinance_loan_management.repayment_frequency_weekly')
        # Le produit générique de MicrofinanceCommon est déjà mensuel (fixed + monthly) :
        # réutilisé tel quel comme produit "sain" pour les cas de succès.
        cls.agent = cls.env['res.users'].create({
            'name': 'Agent CCL Test 2',
            'login': 'agent_ccl_test2@example.com',
            'email': 'agent_ccl_test2@example.com',
            'groups_id': [(4, cls.env.ref('microfinance_loan_management.group_microfinance_user').id)],
        })
        cls.env['microfinance.portfolio'].create({
            'agent_id': cls.agent.id,
            'company_id': cls.env.company.id,
        })

    # --- E.a : cocher employee_authorized sur un produit non strictement mensuel ---
    def test_guard_a_check_flag_requires_monthly(self):
        weekly_product = self.product.copy({'code': 'PWEEK', 'repayment_frequency_id': self.weekly.id})
        with self.assertRaises(ValidationError):
            weekly_product.employee_authorized = True

    def test_guard_a_check_flag_on_monthly_product_passes(self):
        monthly_product = self.product.copy({'code': 'PMONTH'})
        monthly_product.employee_authorized = True
        self.assertTrue(monthly_product.employee_authorized)

    # --- E.b : changer la périodicité d'un produit déjà coché ---
    def test_guard_b_change_periodicity_while_checked_blocked(self):
        monthly_product = self.product.copy({'code': 'PMONTH2', 'employee_authorized': True})
        with self.assertRaises(ValidationError):
            monthly_product.repayment_frequency_id = self.weekly.id

    def test_guard_unchecked_product_periodicity_still_free(self):
        plain_product = self.product.copy({'code': 'PPLAIN'})
        plain_product.repayment_frequency_id = self.weekly.id
        self.assertEqual(plain_product.repayment_frequency_id, self.weekly)

    # --- E.c : périodicité mensuelle imposée sur la demande/le prêt retenue sur salaire ---
    def test_guard_c_loan_salary_deduction_requires_monthly(self):
        weekly_product = self.product.copy({'code': 'PWEEK2', 'repayment_frequency_id': self.weekly.id})
        loan = self.env['microfinance.loan'].create({
            'partner_id': self.partner.id,
            'product_id': weekly_product.id,
            'loan_amount': 600.0,
            'term': 6,
            'repayment_frequency_id': self.weekly.id,
        })
        with self.assertRaises(ValidationError):
            loan.write({'salary_deduction': True})

    # --- F : produits proposés / flag retenue sur salaire posé automatiquement ---
    def test_employee_linked_partner_sees_only_authorized_products(self):
        employee = self.env['hr.employee'].create({
            'name': 'Employé Produit Test',
            'company_id': self.env.company.id,
        })
        monthly_product = self.product.copy({'code': 'PMONTH3', 'employee_authorized': True})
        partner = self.env['res.partner'].create({
            'name': 'Client Employé Produit Test',
            'microfinance_partner_type': 'client',
            'company_id': self.env.company.id,
        })
        employee.microfinance_partner_id = partner.id

        with self.assertRaises(ValidationError):
            partner.with_context(microfinance_context=True, allow_microfinance_partner_create=True).write({
                'microfinance_selected_product_id': self.product.id,
            })
        partner.with_context(microfinance_context=True, allow_microfinance_partner_create=True).write({
            'microfinance_selected_product_id': monthly_product.id,
        })
        self.assertEqual(partner.microfinance_selected_product_id, monthly_product)

    def test_salary_deduction_flag_set_automatically_and_not_retroactive(self):
        employee = self.env['hr.employee'].create({
            'name': 'Employé Flag Test',
            'company_id': self.env.company.id,
        })
        monthly_product = self.product.copy({'code': 'PMONTH4', 'employee_authorized': True})
        partner = self.env['res.partner'].create({
            'name': 'Client Employé Flag Test',
            'microfinance_partner_type': 'client',
            'company_id': self.env.company.id,
        })
        employee.microfinance_partner_id = partner.id

        loan = self.env['microfinance.loan'].create({
            'partner_id': partner.id,
            'product_id': monthly_product.id,
            'loan_amount': 600.0,
            'term': 6,
        })
        self.assertTrue(loan.salary_deduction, "Le flag doit être posé automatiquement à la création.")

        # Non rétroactif : un prêt existant créé AVANT le lien employé<->client ne doit pas
        # voir son flag recalculé rien qu'en relisant/écrivant un autre champ.
        plain_loan = self.env['microfinance.loan'].create({
            'partner_id': self.partner.id,
            'product_id': self.product.id,
            'loan_amount': 600.0,
            'term': 6,
        })
        self.assertFalse(plain_loan.salary_deduction)
        employee.microfinance_partner_id = self.partner.id
        plain_loan.invalidate_recordset()
        self.assertFalse(plain_loan.salary_deduction, "Jamais recalculé après coup.")
