# -*- coding: utf-8 -*-
import random

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.microfinance_loan_management.tests.common import MicrofinanceCommon


@tagged('post_install', '-at_install')
class TestMicrofinancePayrollAdvanceWizard(MicrofinanceCommon):

    @classmethod
    def _unique_test_cin(cls):
        """MOWGLI est une copie de données réelles (clients existants) : un CIN de test en
        dur peut par coïncidence correspondre à un vrai client. On génère donc un CIN à 12
        chiffres et on vérifie son absence avant de l'utiliser."""
        Partner = cls.env['res.partner']
        while True:
            candidate = ''.join(str(random.randint(0, 9)) for _ in range(12))
            if not Partner.search_count([
                ('microfinance_id_type', '=', 'cin'), ('microfinance_id_number', '=', candidate),
            ]):
                return candidate

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent = cls.env['res.users'].create({
            'name': 'Agent CCL Test',
            'login': 'agent_ccl_test@example.com',
            'email': 'agent_ccl_test@example.com',
            'groups_id': [(4, cls.env.ref('microfinance_loan_management.group_microfinance_user').id)],
        })
        cls.portfolio = cls.env['microfinance.portfolio'].create({
            'agent_id': cls.agent.id,
            'company_id': cls.env.company.id,
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Employé Test',
            'company_id': cls.env.company.id,
            'identification_id': cls._unique_test_cin(),
            'work_email': 'employe.test@example.com',
            'work_phone': '0340000000',
        })
        cls.contract = cls.env['hr.contract'].create({
            'name': 'Contrat Employé Test',
            'employee_id': cls.employee.id,
            'company_id': cls.env.company.id,
            'wage': 500000.0,
            'state': 'open',
        })
        cls.employee.contract_id = cls.contract.id

    def _open_wizard(self, employee=None):
        return self.env['microfinance.payroll.advance.wizard'].create({
            'employee_id': (employee or self.employee).id,
            'officer_id': self.agent.id,
        })

    def test_wizard_creates_client_standard_path(self):
        wizard = self._open_wizard()
        wizard.action_validate()
        partner = self.employee.microfinance_partner_id
        self.assertTrue(partner, "Le wizard doit rattacher un client microfinance à l'employé.")
        self.assertEqual(partner.microfinance_partner_type, 'client')
        self.assertEqual(partner.company_id, self.env.company)
        self.assertTrue(partner.microfinance_account_number, "Le client doit recevoir un numéro de compte permanent (chemin standard).")
        self.assertEqual(partner.microfinance_officer_id, self.agent)
        container = self.env['microfinance.loan.account'].search([('partner_id', '=', partner.id)])
        self.assertEqual(len(container), 1, "Un seul conteneur crédit doit être créé.")
        applications = self.env['microfinance.loan.application'].search([('partner_id', '=', partner.id)])
        self.assertFalse(applications, "Le wizard ne doit jamais créer de demande de crédit.")

    def test_wizard_second_call_no_duplicate(self):
        wizard1 = self._open_wizard()
        wizard1.action_validate()
        partner_first = self.employee.microfinance_partner_id

        wizard2 = self._open_wizard()
        wizard2.action_validate()
        partner_second = self.employee.microfinance_partner_id

        self.assertEqual(partner_first, partner_second, "Un second appel ne doit pas créer un second client.")
        container = self.env['microfinance.loan.account'].search([('partner_id', '=', partner_first.id)])
        self.assertEqual(len(container), 1, "Un second appel ne doit pas créer un second conteneur.")

    def test_wizard_blocks_other_agent_client(self):
        other_agent = self.env['res.users'].create({
            'name': 'Autre Agent Test',
            'login': 'autre_agent_test@example.com',
            'email': 'autre_agent_test@example.com',
            'groups_id': [(4, self.env.ref('microfinance_loan_management.group_microfinance_user').id)],
        })
        self.env['microfinance.portfolio'].create({
            'agent_id': other_agent.id,
            'company_id': self.env.company.id,
        })
        wizard1 = self._open_wizard()
        wizard1.action_validate()

        other_employee = self.env['hr.employee'].create({
            'name': 'Autre Employé (même CIN pour le test)',
            'company_id': self.env.company.id,
            'identification_id': self.employee.identification_id,
        })
        wizard2 = self.env['microfinance.payroll.advance.wizard'].create({
            'employee_id': other_employee.id,
            'officer_id': other_agent.id,
        })
        with self.assertRaises(UserError):
            wizard2.action_validate()

    def test_wizard_second_call_idempotent_no_duplicate_activity(self):
        # Audit 2026-10-05 (cas bosta) : un 2e passage du wizard (ex. reparation d'un lien
        # deja pose) ne doit recreer ni chatter ni activite "Traiter l'avance speciale".
        wizard1 = self._open_wizard()
        wizard1.action_validate()
        partner = self.employee.microfinance_partner_id

        activities_after_first = self.env['mail.activity'].search([
            ('res_model', '=', 'res.partner'), ('res_id', '=', partner.id),
        ])
        self.assertEqual(len(activities_after_first), 1)

        wizard2 = self._open_wizard()
        wizard2.action_validate()

        self.assertEqual(self.employee.microfinance_partner_id, partner)
        activities_after_second = self.env['mail.activity'].search([
            ('res_model', '=', 'res.partner'), ('res_id', '=', partner.id),
        ])
        self.assertEqual(
            len(activities_after_second), 1,
            "Un 2e passage du wizard ne doit pas dupliquer l'activite.")
        partner_count = self.env['res.partner'].search_count([
            ('name', '=', self.employee.name), ('company_id', '=', self.env.company.id),
            ('microfinance_partner_type', '=', 'client'),
        ])
        self.assertEqual(partner_count, 1, "Un 2e passage ne doit pas creer de client doublon.")

    def test_wizard_requires_active_contract(self):
        self.contract.state = 'draft'
        wizard = self._open_wizard()
        with self.assertRaises(UserError):
            wizard.action_validate()
