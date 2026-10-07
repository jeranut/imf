# -*- coding: utf-8 -*-
"""Tests pour l'onglet "Clients a traiter" (decision 2026-10-05, cas bosta : un client
rattache par microfinance_officer_id mais sans pret n'apparaissait jamais dans "Mes clients").
Memes prerequis que les autres tests du module : donnees reelles de MOWGLI (copie jetable),
TransactionCase (rollback systematique)."""
import base64

from odoo.api import call_kw
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestMicrofinancePortfolioClientsATraiter(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].search([('name', '=', 'CEFOR Isotry')], limit=1)

    def setUp(self):
        super().setUp()
        if not self.company:
            self.skipTest("Societe CEFOR Isotry absente de cette base.")
        self.env['microfinance.fond.credit'].sudo().search([('active', '=', True)]).write({'active': False})

        self.agent = self.env['res.users'].create({
            'name': 'Agent Clients A Traiter', 'login': 'agent_cat_test@example.com',
            'email': 'agent_cat_test@example.com',
            'groups_id': [
                (4, self.env.ref('base.group_user').id),
                (4, self.env.ref('microfinance_loan_management.group_microfinance_user').id),
            ],
        })
        self.portfolio = self.env['microfinance.portfolio'].create({
            'agent_id': self.agent.id, 'company_id': self.company.id,
        })
        self.other_agent = self.env['res.users'].create({
            'name': 'Autre Agent CAT Test', 'login': 'other_agent_cat_test@example.com',
            'email': 'other_agent_cat_test@example.com',
            'groups_id': [
                (4, self.env.ref('base.group_user').id),
                (4, self.env.ref('microfinance_loan_management.group_microfinance_user').id),
            ],
        })
        self.env['microfinance.portfolio'].create({
            'agent_id': self.other_agent.id, 'company_id': self.company.id,
        })

        cash_account = self.env['account.account'].create({
            'name': 'Caisse test CAT', 'code': 'TCATCASH',
            'account_type': 'asset_cash', 'company_id': self.company.id,
        })
        self.loan_journal = self.env['account.journal'].create({
            'name': 'Caisse test CAT', 'code': 'TCATCRE', 'type': 'cash',
            'company_id': self.company.id, 'default_account_id': cash_account.id,
        })
        principal_account = self.env['account.account'].create({
            'name': 'Prets clients test CAT', 'code': 'TCATPRET',
            'account_type': 'asset_current', 'company_id': self.company.id,
        })
        interest_account = self.env['account.account'].create({
            'name': 'Interets test CAT', 'code': 'TCATINT',
            'account_type': 'income', 'company_id': self.company.id,
        })
        monthly = self.env.ref('microfinance_loan_management.repayment_frequency_monthly')
        self.product = self.env['microfinance.loan.product'].create({
            'name': 'Produit CAT test', 'code': 'PCATTEST',
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

    def _create_client_with_officer(self, name, officer):
        return self.env['res.partner'].create({
            'name': name, 'microfinance_partner_type': 'client',
            'microfinance_client_type': 'individual',
            'company_id': self.company.id, 'microfinance_officer_id': officer.id,
        })

    def _create_loan(self, partner, **kwargs):
        vals = {
            'partner_id': partner.id, 'product_id': self.product.id,
            'loan_amount': 600000.0, 'term': 6,
            'officer_id': self.agent.id,
            'signed_contract': base64.b64encode(b'test signed contract'),
            'signed_contract_filename': 'contrat_signe_test.pdf',
        }
        vals.update(kwargs)
        return self.env['microfinance.loan'].create(vals)

    def _tab_partner_ids(self, tab, user):
        Loan = self.env['microfinance.loan'].with_user(user)
        result = Loan.get_portfolio_tab(tab, user.id)
        return {row['id'] for row in result['rows']}, result['total']

    def test_client_without_loan_in_clients_a_traiter_not_in_my_clients(self):
        bosta_like = self._create_client_with_officer('Bosta Test', self.agent)
        my_clients_ids, _ = self._tab_partner_ids('my_clients', self.agent)
        cat_ids, cat_total = self._tab_partner_ids('clients_a_traiter', self.agent)
        self.assertNotIn(bosta_like.id, my_clients_ids)
        self.assertIn(bosta_like.id, cat_ids)
        self.assertEqual(cat_total, len(cat_ids))

    def test_client_with_active_loan_in_my_clients_not_in_clients_a_traiter(self):
        ccl1_like = self._create_client_with_officer('CCL1 Test', self.agent)
        self._create_loan(ccl1_like)
        my_clients_ids, _ = self._tab_partner_ids('my_clients', self.agent)
        cat_ids, _ = self._tab_partner_ids('clients_a_traiter', self.agent)
        self.assertIn(ccl1_like.id, my_clients_ids)
        self.assertNotIn(ccl1_like.id, cat_ids)

    def test_union_invariant_draft_loan_moves_client_between_tabs(self):
        client = self._create_client_with_officer('Invariant Test', self.agent)
        my_clients_ids, _ = self._tab_partner_ids('my_clients', self.agent)
        cat_ids, _ = self._tab_partner_ids('clients_a_traiter', self.agent)
        self.assertNotIn(client.id, my_clients_ids)
        self.assertIn(client.id, cat_ids, "Sans pret : doit etre dans clients_a_traiter.")

        loan = self._create_loan(client)
        self.assertEqual(loan.state, 'draft')
        my_clients_ids2, _ = self._tab_partner_ids('my_clients', self.agent)
        cat_ids2, _ = self._tab_partner_ids('clients_a_traiter', self.agent)
        in_my_clients = client.id in my_clients_ids2
        in_cat = client.id in cat_ids2
        self.assertTrue(
            in_my_clients ^ in_cat,
            "Un pret meme en brouillon doit faire basculer le client vers exactement un "
            "des deux onglets, jamais aucun ni les deux.")
        self.assertTrue(in_my_clients, "Un pret, meme brouillon, suffit pour 'Mes clients'.")
        self.assertFalse(in_cat)

    def test_other_agent_does_not_see_these_clients(self):
        self._create_client_with_officer('Bosta Scope Test', self.agent)
        cat_ids_other, cat_total_other = self._tab_partner_ids('clients_a_traiter', self.other_agent)
        self.assertEqual(cat_total_other, 0)
        self.assertEqual(cat_ids_other, set())

    def test_kpis_unchanged_by_clients_a_traiter_tab(self):
        Loan = self.env['microfinance.loan'].with_user(self.agent)
        kpis_before = Loan.get_agent_portfolio_kpis(self.agent.id)
        self._create_client_with_officer('Bosta KPI Test', self.agent)
        kpis_after = Loan.get_agent_portfolio_kpis(self.agent.id)
        self.assertEqual(kpis_before, kpis_after, "Un client sans pret ne doit pas bouger les KPI/PAR.")

    def test_wizard_second_run_does_not_duplicate_tab_entry(self):
        employee = self.env['hr.employee'].create({
            'name': 'Employe CAT Wizard Test', 'company_id': self.company.id,
            'identification_id': '999988887777',
        })
        contract = self.env['hr.contract'].create({
            'name': 'Contrat CAT Wizard Test', 'employee_id': employee.id,
            'company_id': self.company.id, 'wage': 500000.0, 'state': 'open',
        })
        employee.contract_id = contract.id
        wizard1 = self.env['microfinance.payroll.advance.wizard'].create({
            'employee_id': employee.id, 'officer_id': self.agent.id,
        })
        wizard1.action_validate()
        cat_ids1, cat_total1 = self._tab_partner_ids('clients_a_traiter', self.agent)
        self.assertIn(employee.microfinance_partner_id.id, cat_ids1)

        wizard2 = self.env['microfinance.payroll.advance.wizard'].create({
            'employee_id': employee.id, 'officer_id': self.agent.id,
        })
        wizard2.action_validate()
        cat_ids2, cat_total2 = self._tab_partner_ids('clients_a_traiter', self.agent)
        self.assertEqual(cat_total1, cat_total2, "Le 2e passage du wizard ne doit pas dupliquer l'entree.")
        self.assertEqual(cat_ids1, cat_ids2)

    def test_get_portfolio_tab_dispatches_correctly_via_rpc(self):
        # Regression : get_portfolio_tab (override de ce module) doit porter @api.model.
        # odoo.api.call_kw est le point d'entree REELLEMENT utilise par le JS (orm.call ->
        # /web/dataset/call_kw -> call_kw) : un appel Python direct (env[...].get_portfolio_tab(...))
        # ne passe PAS par ce dispatch et ne peut donc pas detecter l'absence de @api.model -
        # seul ce test, qui appelle call_kw explicitement, le peut.
        client = self._create_client_with_officer('RPC Dispatch Test', self.agent)
        Loan = self.env['microfinance.loan'].with_user(self.agent)
        result = call_kw(Loan, 'get_portfolio_tab', ['clients_a_traiter', self.agent.id, 0, 20], {})
        self.assertIn(client.id, {row['id'] for row in result['rows']})

    def test_matcher_excludes_work_contact_id(self):
        # F : le work_contact_id auto-cree par hr.employee.create() ne doit jamais
        # ressortir comme candidat (ni avertissement, ni rapprochement).
        employee = self.env['hr.employee'].create({
            'name': 'Employe Exclusion Test', 'company_id': self.company.id,
        })
        result = self.env['hr.employee'].microfinance_match_candidates(employee=employee)
        self.assertIsNone(result['match_type'])
        self.assertFalse(result['candidates'])
