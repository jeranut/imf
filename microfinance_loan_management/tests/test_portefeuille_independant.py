# -*- coding: utf-8 -*-
"""Chantier groupé Ampaly, bloc A : un agent présent dans deux agences a deux portefeuilles
totalement indépendants. « Fonds utilisé » = principal restant des crédits approved/active
rattachés à un fonds (fond_credit_id), dans la société du portefeuille ; la tuile du dashboard,
la liste Portefeuilles et le journal « Tous les fonds » lisent la même définition."""
from odoo.exceptions import UserError

from .test_fond_bailleur import TestFondBailleurCommon

G = 'microfinance_loan_management.group_microfinance_'


class TestPortefeuilleIndependant(TestFondBailleurCommon):

    def setUp(self):
        super().setUp()
        self.company_a = self.env.company
        self.company_b = self.env['res.company'].create({'name': 'Agence B portefeuille (test)', 'agency_code': 'PIB'})
        self.agent = self.env['res.users'].create({
            'name': 'Agent deux agences', 'login': 'agent_deux_agences_test',
            'company_id': self.company_a.id, 'company_ids': [(6, 0, [self.company_a.id, self.company_b.id])],
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id, self.env.ref(G + 'user').id])],
        })
        Portfolio = self.env['microfinance.portfolio']
        self.portfolio_a = Portfolio.create({'agent_id': self.agent.id, 'company_id': self.company_a.id})
        self.portfolio_b = Portfolio.create({'agent_id': self.agent.id, 'company_id': self.company_b.id})
        self.fond = self._create_fond(name='Fonds indépendance', verification_disponibilite='never')
        self.Loan = self.env['microfinance.loan']
        repartition = self.env['microfinance.portfolio.allocation'].create({
            'fond_id': self.fond.id, 'company_id': self.company_a.id, 'base_amount': 50000.0,
            'line_ids': [(0, 0, {'portfolio_id': self.portfolio_a.id, 'percent': 100.0, 'amount': 50000.0})],
        })
        # Validation posée directement : ces tests portent sur l'agrégation par société, pas sur
        # le plafond d'agence ni le « reçu en banque » (testés dans test_fond_recu_banque).
        repartition.state = 'validated'
        self.portfolio_a.with_context(portfolio_allocation_technique=True).amount_allocated = 50000.0
        # Société A : un crédit au fonds (10 000) + un crédit de reprise sans fonds (4 000).
        self.loan_fund_a = self._activate_loan(
            officer_id=self.agent.id, fond_credit_id=self.fond.id, loan_amount=10000.0)
        self.loan_reprise_a = self._activate_loan(
            officer_id=self.agent.id, fond_credit_id=self.fond.id, loan_amount=4000.0)
        self._detach(self.loan_reprise_a, self.company_a)
        # Société B : deux crédits de reprise sans fonds (3 000 + 2 000), dont un en retard de 100 j.
        self.loan_b1 = self._activate_loan(officer_id=self.agent.id, fond_credit_id=self.fond.id, loan_amount=3000.0)
        self.loan_b2 = self._activate_loan(officer_id=self.agent.id, fond_credit_id=self.fond.id, loan_amount=2000.0)
        self._detach(self.loan_b1, self.company_b)
        self._detach(self.loan_b2, self.company_b)
        self.loan_b2.max_days_overdue = 100
        self.expected_used = self.loan_fund_a._get_principal_outstanding()

    def _detach(self, loan, company):
        """Place un crédit déjà activé (chemin réel) dans `company` et retire son fonds : cas
        d'une reprise d'historique. SQL direct car fond_credit_id est verrouillé après décaissement."""
        self.env.cr.execute(
            "UPDATE microfinance_loan SET company_id = %s, fond_credit_id = NULL WHERE id = %s",
            (company.id, loan.id))
        loan.invalidate_recordset()
        self.env['microfinance.portfolio'].invalidate_model()

    def _as_agent(self, company):
        return self.Loan.with_user(self.agent).with_company(company)

    def test_fonds_utilise_counts_only_fund_loans_of_the_portfolio_company(self):
        self.assertEqual(self.portfolio_a.montant_utilise, self.expected_used)
        self.assertEqual(self.portfolio_b.montant_utilise, 0.0)

    def test_tile_list_and_funds_tab_agree(self):
        kpis = self._as_agent(self.company_a).get_agent_portfolio_kpis()
        self.assertEqual(kpis['fonds_utilise'], self.expected_used)
        self.assertEqual(kpis['fonds_utilise'], self.portfolio_a.montant_utilise)
        tab = self._as_agent(self.company_a).get_portfolio_tab('fonds', self.agent.id, 0, 20)
        self.assertEqual(tab['aggregate']['used'], self.expected_used)
        self.assertEqual(sum(f['used'] for f in tab['funds']), self.expected_used)
        self.assertAlmostEqual(kpis['fonds_disponible'], 50000.0 - self.expected_used, places=2)

    def test_each_dashboard_sees_only_its_company(self):
        kpis_a = self._as_agent(self.company_a).get_agent_portfolio_kpis()
        kpis_b = self._as_agent(self.company_b).get_agent_portfolio_kpis()
        self.assertEqual(kpis_a['nb_dossiers_actifs'], 2)
        self.assertEqual(kpis_b['nb_dossiers_actifs'], 2)
        self.assertEqual(kpis_a['fonds_utilise'], self.expected_used)
        self.assertEqual(kpis_b['fonds_utilise'], 0.0)
        self.assertEqual(kpis_b['fonds_alloue'], 0.0)
        table_b = self._as_agent(self.company_b).get_agent_portfolio_table()
        self.assertEqual({row['id'] for row in table_b['rows']}, {self.loan_b1.id, self.loan_b2.id})

    def test_two_companies_ticked_only_the_active_one_counts(self):
        ticked = self.Loan.with_user(self.agent).with_context(
            allowed_company_ids=[self.company_a.id, self.company_b.id])
        self.assertEqual(ticked.env.company, self.company_a)
        kpis = ticked.get_agent_portfolio_kpis()
        self.assertEqual(kpis['nb_dossiers_actifs'], 2)
        self.assertEqual(kpis['fonds_utilise'], self.expected_used)
        ticked_b = self.Loan.with_user(self.agent).with_context(
            allowed_company_ids=[self.company_b.id, self.company_a.id])
        self.assertEqual(ticked_b.get_agent_portfolio_kpis()['nb_dossiers_actifs'], 2)
        self.assertEqual(ticked_b.get_agent_portfolio_kpis()['fonds_utilise'], 0.0)

    def test_par_is_independent_per_company(self):
        par_a = self._as_agent(self.company_a).get_par_data_by_agent()['cumulative']
        par_b = self._as_agent(self.company_b).get_par_data_by_agent()['cumulative']
        self.assertTrue(all(v == 0.0 for row in par_a for v in row['values']))
        self.assertAlmostEqual(
            par_a[0]['outstanding_total'], self.loan_fund_a.balance_total + self.loan_reprise_a.balance_total, places=2)
        self.assertAlmostEqual(
            par_b[0]['outstanding_total'], self.loan_b1.balance_total + self.loan_b2.balance_total, places=2)
        # Le crédit de 2 000 est en retard de 100 j dans B seulement : PAR30 = sa part de l'encours B, 0 dans A.
        expected = self.loan_b2.balance_total / par_b[0]['outstanding_total'] * 100.0
        self.assertAlmostEqual(par_b[0]['values'][0], expected, places=2)
        self.assertGreater(par_b[0]['values'][0], 0.0)

    def test_open_dashboard_of_another_company_is_refused(self):
        with self.assertRaises(UserError):
            self.portfolio_b.with_company(self.company_a).action_open_dashboard()
        with self.assertRaises(UserError):
            self.Loan.with_company(self.company_a).get_dashboard_data(portfolio_id=self.portfolio_b.id)
        action = self.portfolio_a.with_company(self.company_a).action_open_dashboard()
        self.assertEqual(action['context']['portfolio_id'], self.portfolio_a.id)
