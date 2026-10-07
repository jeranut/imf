# -*- coding: utf-8 -*-
"""Tests Etape 2 (audit 2026-10-05, bulletin ccl1 LOAN=0 : lien employe-client manquant).
Memes prerequis que test_payroll_salary_deduction.py : donnees reelles de MOWGLI (societe
CEFOR Isotry, structure BASE) - a executer sur une copie jetable, jamais en production.
TransactionCase : rollback systematique en fin de test."""
import base64

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestMicrofinanceEmployeePartnerMatch(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].search([('name', '=', 'CEFOR Isotry')], limit=1)
        cls.structure = cls.env['hr.payroll.structure'].search([('code', '=', 'BASE')], limit=1)

    def setUp(self):
        super().setUp()
        if not self.company or not self.structure or not self.structure.rule_ids.filtered(
            lambda r: r.code == 'LOAN'
        ):
            self.skipTest(
                "Societe CEFOR Isotry, structure BASE ou regle LOAN absente de cette base : "
                "ces tests necessitent les donnees reelles de MOWGLI (ou une copie jetable).")
        self.env['microfinance.fond.credit'].sudo().search([('active', '=', True)]).write({'active': False})

        general_journal = self.env['account.journal'].search([
            ('company_id', '=', self.company.id), ('type', '=', 'general'), ('code', '=', 'OD'),
        ], limit=1)
        self.company.write({'payroll_journal_id': general_journal.id})

        cash_account = self.env['account.account'].create({
            'name': 'Caisse test match', 'code': 'TMATCASH',
            'account_type': 'asset_cash', 'company_id': self.company.id,
        })
        self.loan_journal = self.env['account.journal'].create({
            'name': 'Caisse test match', 'code': 'TMATCRE', 'type': 'cash',
            'company_id': self.company.id, 'default_account_id': cash_account.id,
        })
        principal_account = self.env['account.account'].create({
            'name': 'Prets clients test match', 'code': 'TMATPRET',
            'account_type': 'asset_current', 'company_id': self.company.id,
        })
        interest_account = self.env['account.account'].create({
            'name': 'Interets test match', 'code': 'TMATINT',
            'account_type': 'income', 'company_id': self.company.id,
        })
        monthly = self.env.ref('microfinance_loan_management.repayment_frequency_monthly')
        self.product = self.env['microfinance.loan.product'].create({
            'name': 'Produit match test', 'code': 'PMATTEST',
            'min_amount': 100.0, 'max_amount': 10000000.0,
            'min_term': 1, 'max_term': 36,
            'interest_rate': 0.0, 'interest_method': 'flat',
            'installment_rounding_unit': 0,
            'repayment_frequency_mode': 'fixed', 'repayment_frequency_id': monthly.id,
            'disbursement_journal_id': self.loan_journal.id,
            'payment_journal_id': self.loan_journal.id,
            'account_principal_individuel_id': principal_account.id,
            'account_principal_groupe_id': principal_account.id,
            'account_interets_recus_individuel_id': interest_account.id,
            'account_interets_recus_groupe_id': interest_account.id,
            'company_id': self.company.id,
            'employee_authorized': True,
        })
        self.agent = self.env['res.users'].create({
            'name': 'Agent Match Test', 'login': 'agent_match_test@example.com',
            'email': 'agent_match_test@example.com',
            'groups_id': [(4, self.env.ref('microfinance_loan_management.group_microfinance_user').id)],
        })
        self.portfolio = self.env['microfinance.portfolio'].create({
            'agent_id': self.agent.id, 'company_id': self.company.id,
        })
        self.employee = self.env['hr.employee'].create({
            'name': 'Rakoto Employe Match Test', 'company_id': self.company.id,
            'identification_id': '111122223333',
        })
        self.contract = self.env['hr.contract'].create({
            'name': 'Contrat Match Test', 'employee_id': self.employee.id,
            'company_id': self.company.id, 'wage': 1000000.0, 'state': 'open',
            'struct_id': self.structure.id, 'date_start': '2026-01-01',
        })
        self.employee.contract_id = self.contract.id

    # -- Helpers ----------------------------------------------------------

    def _create_loan(self, partner, **kwargs):
        vals = {
            'partner_id': partner.id,
            'product_id': self.product.id,
            'loan_amount': 600000.0,
            'term': 6,
            'signed_contract': base64.b64encode(b'test signed contract'),
            'signed_contract_filename': 'contrat_signe_test.pdf',
        }
        vals.update(kwargs)
        return self.env['microfinance.loan'].create(vals)

    def _approve_loan(self, loan):
        loan.action_generate_schedule()
        loan.action_start_enquete()
        loan.action_ca_review()
        loan.action_cdag_review()
        loan.action_view_applications()
        loan.application_ids.write({'committee_first_decision': 'accepted'})
        loan.action_approve()
        return loan

    def _make_payslip(self, date_from, date_to):
        return self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'contract_id': self.contract.id,
            'struct_id': self.structure.id,
            'date_from': date_from,
            'date_to': date_to,
        })

    def _line_total(self, payslip, code):
        line = payslip.line_ids.filtered(lambda l: l.code == code)
        return line.total if line else 0.0

    # -- A : evaluation tardive de salary_deduction ------------------------

    def test_flag_posed_at_activation_once_link_exists(self):
        partner = self.env['res.partner'].create({
            'name': 'Client Match A', 'microfinance_partner_type': 'client',
            'company_id': self.company.id,
        })
        loan = self._create_loan(partner)
        self._approve_loan(loan)
        self.assertFalse(loan.salary_deduction, "Pas de lien employe encore : rien a poser.")

        self.employee.microfinance_partner_id = partner.id
        loan._activate_with_auto_confirm()
        self.assertTrue(
            loan.salary_deduction,
            "Le lien a ete pose avant l'activation : salary_deduction doit etre reevalue a "
            "True a l'activation (A), sans attendre le decaissement.")

    def test_flag_never_auto_modified_after_disbursement(self):
        partner = self.env['res.partner'].create({
            'name': 'Client Match A2', 'microfinance_partner_type': 'client',
            'company_id': self.company.id,
        })
        loan = self._create_loan(partner)
        self._approve_loan(loan)
        loan._activate_with_auto_confirm()
        loan.action_process_disbursement()
        self.assertFalse(loan.salary_deduction)
        self.assertTrue(loan.disbursement_date)

        # Lien pose APRES decaissement : ne doit jamais etre recalcule automatiquement.
        self.employee.microfinance_partner_id = partner.id
        loan.invalidate_recordset(['salary_deduction'])
        self.assertFalse(
            loan.salary_deduction,
            "Un pret deja decaisse ne doit JAMAIS etre recalcule automatiquement - seule "
            "l'action F (regularisation) peut encore le poser.")
        with self.assertRaises(UserError):
            loan.write({'salary_deduction': True})

    # -- B/C/D : rapprochement CIN exact vs homonymie seule -----------------

    def test_cin_exact_match_links_automatically_on_application_create(self):
        partner = self.env['res.partner'].create({
            'name': 'Nom Totalement Different', 'microfinance_partner_type': 'client',
            'company_id': self.company.id,
            'microfinance_id_type': 'cin', 'microfinance_id_number_display': '111122223333',
        })
        application = self.env['microfinance.loan.application'].create({
            'partner_id': partner.id, 'loan_product_id': self.product.id,
            'company_id': self.company.id,
        })
        self.assertEqual(
            self.employee.microfinance_partner_id, partner,
            "CIN exact (meme si le nom differe) : lien automatique attendu.")
        self.assertFalse(application.microfinance_employee_match_pending)

    def test_name_only_match_warns_without_linking(self):
        partner = self.env['res.partner'].create({
            'name': self.employee.name, 'microfinance_partner_type': 'client',
            'company_id': self.company.id,
        })
        application = self.env['microfinance.loan.application'].create({
            'partner_id': partner.id, 'loan_product_id': self.product.id,
            'company_id': self.company.id,
        })
        self.assertFalse(
            self.employee.microfinance_partner_id,
            "Homonymie seule (sans CIN identique) : jamais de lien automatique.")
        self.assertTrue(application.microfinance_employee_match_pending)
        self.assertIn(self.employee, application.microfinance_employee_match_candidate_ids)

        with self.assertRaises(UserError):
            application.write({'state': 'visite'})

        application.action_microfinance_dismiss_employee_match()
        self.assertFalse(application.microfinance_employee_match_pending)
        application.write({'state': 'visite'})  # ne leve plus

        dismissal = self.env['microfinance.employee.partner.match.dismissal'].search([
            ('employee_id', '=', self.employee.id), ('partner_id', '=', partner.id),
        ])
        self.assertTrue(dismissal, "Le rejet doit etre trace pour ne plus jamais re-proposer cette paire.")

        result = self.env['hr.employee'].microfinance_match_candidates(employee=self.employee)
        self.assertNotIn(partner, result['candidates'])

    # -- C : wizard avance speciale -----------------------------------------

    def test_wizard_refuses_without_cin(self):
        self.employee.identification_id = False
        wizard = self.env['microfinance.payroll.advance.wizard'].create({
            'employee_id': self.employee.id, 'officer_id': self.portfolio.agent_id.id,
        })
        with self.assertRaises(UserError):
            wizard.action_validate()

    def test_wizard_multiple_candidates_requires_explicit_choice(self):
        partner_a = self.env['res.partner'].create({
            'name': self.employee.name, 'microfinance_partner_type': 'client',
            'company_id': self.company.id,
        })
        partner_b = self.env['res.partner'].create({
            'name': self.employee.name, 'microfinance_partner_type': 'client',
            'company_id': self.company.id,
        })
        wizard = self.env['microfinance.payroll.advance.wizard'].create({
            'employee_id': self.employee.id, 'officer_id': self.portfolio.agent_id.id,
        })
        self.assertEqual(len(wizard.candidate_partner_ids), 2)
        with self.assertRaises(UserError):
            wizard.action_validate()

        no_new_partner_count = self.env['res.partner'].search_count([
            ('name', '=', self.employee.name), ('company_id', '=', self.company.id),
            ('microfinance_partner_type', '=', 'client'),
        ])
        self.assertEqual(
            no_new_partner_count, 2,
            "Aucune creation silencieuse de 3e client en cas d'ambiguite.")

        wizard.selected_partner_id = partner_b
        wizard.action_validate()
        self.assertEqual(self.employee.microfinance_partner_id, partner_b)

    # -- D : visibilite paie --------------------------------------------------

    def test_no_loan_line_without_any_loan(self):
        payslip = self._make_payslip('2026-02-01', '2026-02-28')
        payslip.action_compute_sheet()
        self.assertAlmostEqual(self._line_total(payslip, 'LOAN'), 0.0)
        self.assertFalse(payslip.line_ids.filtered(lambda l: l.code == 'LOAN'))
        self.assertFalse(payslip.microfinance_loan_warning)

    def test_warning_shown_when_disbursed_loan_not_retained_due_to_missing_link(self):
        partner = self.env['res.partner'].create({
            'name': self.employee.name, 'microfinance_partner_type': 'client',
            'company_id': self.company.id,
        })
        loan = self._create_loan(partner, loan_amount=100000.0, term=1)
        self._approve_loan(loan)
        loan._activate_with_auto_confirm()
        loan.action_process_disbursement()
        self.assertFalse(self.employee.microfinance_partner_id)

        payslip = self._make_payslip('2026-02-01', '2026-02-28')
        payslip.action_compute_sheet()
        self.assertFalse(payslip.line_ids.filtered(lambda l: l.code == 'LOAN'))
        self.assertTrue(payslip.microfinance_loan_warning)
        self.assertIn(loan.name, payslip.microfinance_loan_warning)

    # -- F : regularisation ---------------------------------------------------

    def test_regularization_requires_both_groups_and_reason(self):
        partner = self.env['res.partner'].create({
            'name': 'Client Regularisation', 'microfinance_partner_type': 'client',
            'company_id': self.company.id,
        })
        loan = self._create_loan(partner, loan_amount=100000.0, term=1)
        self._approve_loan(loan)
        loan._activate_with_auto_confirm()
        loan.action_process_disbursement()
        self.employee.microfinance_partner_id = partner.id
        self.assertFalse(loan.salary_deduction)

        gestionnaire_only = self.env['res.users'].create({
            'name': 'Gestionnaire Seul', 'login': 'gestionnaire_seul_test@example.com',
            'email': 'gestionnaire_seul_test@example.com',
            'company_id': self.company.id, 'company_ids': [(4, self.company.id)],
            'groups_id': [(4, self.env.ref(
                'microfinance_loan_management.group_microfinance_gestionnaire').id)],
        })
        wizard = self.env['microfinance.loan.salary.deduction.regularization.wizard'].with_user(
            gestionnaire_only).create({'loan_id': loan.id, 'reason': 'Lien pose tardivement.'})
        with self.assertRaises(UserError):
            wizard.action_confirm()
        self.assertFalse(loan.salary_deduction)

        both_groups = self.env['res.users'].create({
            'name': 'Responsable Paie + Gestionnaire', 'login': 'both_groups_test@example.com',
            'email': 'both_groups_test@example.com',
            'company_id': self.company.id, 'company_ids': [(4, self.company.id)],
            'groups_id': [
                (4, self.env.ref(
                    'microfinance_loan_management.group_microfinance_gestionnaire').id),
                (4, self.env.ref(
                    'hr_payroll_community.group_hr_payroll_community_manager').id),
            ],
        })
        wizard_empty_reason = self.env['microfinance.loan.salary.deduction.regularization.wizard'].with_user(
            both_groups).create({'loan_id': loan.id, 'reason': ''})
        with self.assertRaises(UserError):
            wizard_empty_reason.action_confirm()
        self.assertFalse(loan.salary_deduction)

        wizard3 = self.env['microfinance.loan.salary.deduction.regularization.wizard'].with_user(
            both_groups).create({'loan_id': loan.id, 'reason': 'Lien pose tardivement, motif reel.'})
        wizard3.action_confirm()
        self.assertTrue(loan.salary_deduction)

        # Le verrou normal de write() reste intact pour tout le reste.
        with self.assertRaises(UserError):
            loan.write({'salary_deduction': False})

    def test_regularization_links_employee_when_missing(self):
        partner = self.env['res.partner'].create({
            'name': 'Client Regularisation Lien', 'microfinance_partner_type': 'client',
            'company_id': self.company.id,
        })
        loan = self._create_loan(partner, loan_amount=100000.0, term=1)
        self._approve_loan(loan)
        loan._activate_with_auto_confirm()
        loan.action_process_disbursement()
        self.assertFalse(self.employee.microfinance_partner_id)

        both_groups = self.env['res.users'].create({
            'name': 'Responsable Paie + Gestionnaire 2', 'login': 'both_groups_test2@example.com',
            'email': 'both_groups_test2@example.com',
            'company_id': self.company.id, 'company_ids': [(4, self.company.id)],
            'groups_id': [
                (4, self.env.ref(
                    'microfinance_loan_management.group_microfinance_gestionnaire').id),
                (4, self.env.ref(
                    'hr_payroll_community.group_hr_payroll_community_manager').id),
            ],
        })
        wizard = self.env['microfinance.loan.salary.deduction.regularization.wizard'].with_user(
            both_groups).create({
                'loan_id': loan.id, 'employee_id': self.employee.id,
                'reason': 'Lien employe-client oublie a la creation du pret.',
            })
        wizard.action_confirm()
        self.assertEqual(self.employee.microfinance_partner_id, partner)
        self.assertTrue(loan.salary_deduction)
