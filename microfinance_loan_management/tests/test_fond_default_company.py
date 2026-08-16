# -*- coding: utf-8 -*-
from odoo.tests import Form

from .test_fond_bailleur import TestFondBailleurCommon


class TestFondCreditDefaultPerCompany(TestFondBailleurCommon):
    """Configuration res.company.microfinance_fond_credit_default_id : pré-remplissage à la
    création d'un crédit, absence totale de verrouillage/effet rétroactif (à l'opposé du
    verrouillage de fond_credit_id après décaissement), et restriction de visibilité côté vue."""

    def test_new_loan_prefills_fond_from_company_default(self):
        fond = self._create_fond()
        self.env.company.microfinance_fond_credit_default_id = fond.id
        with Form(self.env['microfinance.loan']) as loan_form:
            loan_form.partner_id = self.partner
            loan_form.product_id = self.product
            loan_form.loan_amount = 1000.0
            loan_form.term = 3
        loan = loan_form.save()
        self.assertEqual(loan.fond_credit_id, fond)

    def test_manual_choice_not_overridden_by_default(self):
        default_fond = self._create_fond(name='Fonds par defaut')
        other_fond = self._create_fond(name='Fonds choisi manuellement')
        self.env.company.microfinance_fond_credit_default_id = default_fond.id
        with Form(self.env['microfinance.loan']) as loan_form:
            loan_form.partner_id = self.partner
            loan_form.product_id = self.product
            loan_form.loan_amount = 1000.0
            loan_form.term = 3
            loan_form.fond_credit_id = other_fond
        loan = loan_form.save()
        self.assertEqual(loan.fond_credit_id, other_fond)

    def test_no_default_configured_leaves_fond_empty(self):
        with Form(self.env['microfinance.loan']) as loan_form:
            loan_form.partner_id = self.partner
            loan_form.product_id = self.product
            loan_form.loan_amount = 1000.0
            loan_form.term = 3
        loan = loan_form.save()
        self.assertFalse(loan.fond_credit_id)

    def test_changing_company_default_repeatedly_is_never_blocked(self):
        fond_1 = self._create_fond(name='Fonds 1')
        fond_2 = self._create_fond(name='Fonds 2')
        company = self.env.company
        company.microfinance_fond_credit_default_id = fond_1.id
        company.microfinance_fond_credit_default_id = fond_2.id
        company.microfinance_fond_credit_default_id = False
        company.microfinance_fond_credit_default_id = fond_1.id
        self.assertEqual(company.microfinance_fond_credit_default_id, fond_1)

    def test_changing_company_default_has_no_retroactive_effect_on_existing_loans(self):
        fond_1 = self._create_fond(name='Fonds 1')
        fond_2 = self._create_fond(name='Fonds 2')
        self.env.company.microfinance_fond_credit_default_id = fond_1.id
        with Form(self.env['microfinance.loan']) as loan_form:
            loan_form.partner_id = self.partner
            loan_form.product_id = self.product
            loan_form.loan_amount = 1000.0
            loan_form.term = 3
        loan = loan_form.save()
        self.assertEqual(loan.fond_credit_id, fond_1)

        self.env.company.microfinance_fond_credit_default_id = fond_2.id
        self.assertEqual(loan.fond_credit_id, fond_1)

    def test_manager_agent_view_restriction(self):
        manager = self.env['res.users'].create({
            'name': 'Manager Test Fonds Defaut',
            'login': 'manager_fonds_defaut_test',
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('microfinance_loan_management.group_microfinance_manager').id,
            ])],
        })
        agent = self.env['res.users'].create({
            'name': 'Agent Test Fonds Defaut',
            'login': 'agent_fonds_defaut_test',
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('microfinance_loan_management.group_microfinance_user').id,
            ])],
        })
        Company = self.env['res.company'].with_user(manager)
        view = Company.get_view(view_id=self.env.ref('base.view_company_form').id, view_type='form')
        self.assertIn('microfinance_fond_credit_default_id', view['arch'])

        Company_as_agent = self.env['res.company'].with_user(agent)
        view_as_agent = Company_as_agent.get_view(view_id=self.env.ref('base.view_company_form').id, view_type='form')
        self.assertNotIn('microfinance_fond_credit_default_id', view_as_agent['arch'])
