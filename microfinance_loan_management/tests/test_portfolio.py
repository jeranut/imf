# -*- coding: utf-8 -*-
"""R1/R2 (AUDIT_portefeuille_agent.md) : unicité du portefeuille, isolation entre agents d'une
même agence, plafond de répartition agence -> portefeuilles, blocage du décaissement au-delà du
fonds disponible du portefeuille de l'agent."""
from psycopg2 import IntegrityError

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import mute_logger

from .common import MicrofinanceCommon, MicrofinanceNoFundMixin
from .test_fond_bailleur import TestFondBailleurCommon

ALLOCATION_TECHNICAL_CONTEXT = 'fond_partage_technique'
PORTFOLIO_ALLOCATION_TECHNICAL_CONTEXT = 'portfolio_allocation_technique'


class TestPortfolioUnique(MicrofinanceCommon):

    @mute_logger('odoo.sql_db')
    def test_portfolio_unique_per_agent_and_company(self):
        # R1 : un seul portefeuille par couple (agent, agence) - contrainte SQL, même idiome que
        # tests/test_agency_code.py::test_agency_code_unique (res.company.agency_code_unique).
        self.env['microfinance.portfolio'].create({
            'agent_id': self.env.user.id, 'company_id': self.env.company.id,
        })
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.env['microfinance.portfolio'].create({
                'agent_id': self.env.user.id, 'company_id': self.env.company.id,
            })


class TestPortfolioIsolation(MicrofinanceCommon):

    def _agent_user(self, login):
        return self.env['res.users'].create({
            'name': login, 'login': login,
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('microfinance_loan_management.group_microfinance_user').id,
            ])],
        })

    def _gestionnaire_user(self, login):
        return self.env['res.users'].create({
            'name': login, 'login': login,
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('microfinance_loan_management.group_microfinance_gestionnaire').id,
            ])],
        })

    def test_agent_only_sees_own_portfolio(self):
        agent_a = self._agent_user('portfolio_agent_a_test')
        agent_b = self._agent_user('portfolio_agent_b_test')
        portfolio_a = self.env['microfinance.portfolio'].create({
            'agent_id': agent_a.id, 'company_id': self.env.company.id,
        })
        portfolio_b = self.env['microfinance.portfolio'].create({
            'agent_id': agent_b.id, 'company_id': self.env.company.id,
        })
        # Agent A (group_microfinance_user, aucun groupe manager/gestionnaire) : ne voit que son
        # propre portefeuille dans la même agence, cf. security/microfinance_portfolio_rules.xml.
        visible_to_a = self.env['microfinance.portfolio'].with_user(agent_a).search([])
        self.assertEqual(visible_to_a, portfolio_a)
        self.assertNotIn(portfolio_b, visible_to_a)
        # Lecture directe d'un portefeuille d'un collègue : invisible (ir.rule), pas seulement
        # absent d'une recherche large.
        self.assertFalse(
            self.env['microfinance.portfolio'].with_user(agent_a).search(
                [('id', '=', portfolio_b.id)]))

    def test_agent_cannot_open_colleague_dashboard_via_portfolio_id(self):
        # Menu "Portefeuille" -> microfinance.portfolio.action_open_dashboard : le contexte ne
        # transmet qu'un portfolio_id, jamais un agent_id (consigne explicite) ; get_dashboard_data
        # le relit par ORM avec les droits réels de l'appelant - même règle d'isolation que ci-dessus.
        agent_a = self._agent_user('portfolio_dash_agent_a_test')
        agent_b = self._agent_user('portfolio_dash_agent_b_test')
        portfolio_b = self.env['microfinance.portfolio'].create({
            'agent_id': agent_b.id, 'company_id': self.env.company.id,
        })
        with self.assertRaises(AccessError):
            self.env['microfinance.loan'].with_user(agent_a).get_dashboard_data(portfolio_b.id)

    def test_gestionnaire_can_open_either_agent_dashboard_via_portfolio_id(self):
        agent_a = self._agent_user('portfolio_dash_agent_a2_test')
        agent_b = self._agent_user('portfolio_dash_agent_b2_test')
        gestionnaire = self._gestionnaire_user('portfolio_dash_gestionnaire_test')
        portfolio_a = self.env['microfinance.portfolio'].create({
            'agent_id': agent_a.id, 'company_id': self.env.company.id,
        })
        portfolio_b = self.env['microfinance.portfolio'].create({
            'agent_id': agent_b.id, 'company_id': self.env.company.id,
        })
        visible = self.env['microfinance.portfolio'].with_user(gestionnaire).search([])
        self.assertIn(portfolio_a, visible)
        self.assertIn(portfolio_b, visible)
        Loan = self.env['microfinance.loan'].with_user(gestionnaire)
        self.assertEqual(Loan.get_dashboard_data(portfolio_a.id)['portfolio_officer_id'], agent_a.id)
        self.assertEqual(Loan.get_dashboard_data(portfolio_b.id)['portfolio_officer_id'], agent_b.id)


class TestPortfolioAllocationCeiling(TestFondBailleurCommon):
    """Plafond non contournable (Phase 2 §3) : la somme des répartitions agence ->
    portefeuilles ne peut jamais dépasser le fonds reçu par l'agence (mère -> agence)."""

    def setUp(self):
        super().setUp()
        self.fond = self._create_fond(verification_disponibilite='at_disbursement')
        self.portfolio_1 = self.env['microfinance.portfolio'].create({
            'agent_id': self.env.user.id, 'company_id': self.env.company.id,
        })
        # Allocation d'agence créée en direct (sudo + contexte technique), sans passer par
        # microfinance.fond.partage (gabarit mère -> agences, lecture seule, hors périmètre de ce
        # test) : l'agence a reçu 1000 sur ce fonds.
        self.allocation = self.env['microfinance.fond.allocation'].sudo().with_context(**{
            ALLOCATION_TECHNICAL_CONTEXT: True,
        }).create({
            'fond_id': self.fond.id, 'company_id': self.env.company.id, 'amount_allocated': 1000.0,
        })

    def test_repartition_cannot_exceed_agency_allocation(self):
        repartition = self.env['microfinance.portfolio.allocation'].create({
            'fond_id': self.fond.id,
            'company_id': self.env.company.id,
            'base_amount': 1500.0,
            'line_ids': [(0, 0, {'portfolio_id': self.portfolio_1.id, 'percent': 100.0, 'amount': 1500.0})],
        })
        with self.assertRaises(UserError):
            repartition.action_validate()

    def test_repartition_within_agency_allocation_succeeds(self):
        repartition = self.env['microfinance.portfolio.allocation'].create({
            'fond_id': self.fond.id,
            'company_id': self.env.company.id,
            'base_amount': 1000.0,
            'line_ids': [(0, 0, {'portfolio_id': self.portfolio_1.id, 'percent': 100.0, 'amount': 1000.0})],
        })
        repartition.action_validate()
        self.assertEqual(repartition.state, 'validated')
        self.assertEqual(self.portfolio_1.amount_allocated, 1000.0)


class TestPortfolioAllocationMode(TestFondBailleurCommon):
    """Mode allocation (M2) : attribution directe par portefeuille (montant ou %), distincte du
    mode partage (M1, inchangé) - base du % = reste à répartir de l'agence, pas d'exigence de
    total 100%, nouveaux agents/fonds vides éligibles sans condition (M3)."""

    def setUp(self):
        super().setUp()
        self.fond = self._create_fond(verification_disponibilite='at_disbursement')
        self.agent_a = self.env.user
        self.agent_b = self.env['res.users'].create({
            'name': 'portfolio_alloc_agent_b_test', 'login': 'portfolio_alloc_agent_b_test',
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('microfinance_loan_management.group_microfinance_user').id,
            ])],
        })
        self.portfolio_a = self.env['microfinance.portfolio'].create({
            'agent_id': self.agent_a.id, 'company_id': self.env.company.id,
        })
        self.portfolio_b = self.env['microfinance.portfolio'].create({
            'agent_id': self.agent_b.id, 'company_id': self.env.company.id,
        })
        self.env['microfinance.fond.allocation'].sudo().with_context(**{
            ALLOCATION_TECHNICAL_CONTEXT: True,
        }).create({
            'fond_id': self.fond.id, 'company_id': self.env.company.id, 'amount_allocated': 1000.0,
        })

    def test_base_amount_not_required_in_any_scenario(self):
        # Non-régression : base_amount était required=True sans valeur garantie en mode allocation
        # (le recalcul _sync_header_base_amount n'intervient qu'au create/write des LIGNES, donc
        # après l'insertion de l'en-tête) - "Un champ obligatoire n'est pas défini" au create().
        Allocation = self.env['microfinance.portfolio.allocation']
        empty = Allocation.create({
            'fond_id': self.fond.id, 'company_id': self.env.company.id,
            'allocation_mode': 'allocation', 'input_type': 'montant',
        })
        self.assertEqual(empty.base_amount, 0.0)

        with_lines = Allocation.create({
            'fond_id': self.fond.id, 'company_id': self.env.company.id,
            'allocation_mode': 'allocation', 'input_type': 'montant',
            'line_ids': [
                (0, 0, {'portfolio_id': self.portfolio_a.id, 'amount': 100.0}),
                (0, 0, {'portfolio_id': self.portfolio_b.id, 'amount': 50.0}),
            ],
        })
        self.assertEqual(with_lines.base_amount, 150.0)

        partage = Allocation.create({
            'fond_id': self.fond.id, 'company_id': self.env.company.id,
            'base_amount': 200.0,
            'line_ids': [(0, 0, {'portfolio_id': self.portfolio_a.id, 'percent': 100.0, 'amount': 200.0})],
        })
        self.assertEqual(partage.allocation_mode, 'partage')
        self.assertEqual(partage.base_amount, 200.0)

    def test_allocation_mode_amount_input(self):
        repartition = self.env['microfinance.portfolio.allocation'].create({
            'fond_id': self.fond.id, 'company_id': self.env.company.id,
            'allocation_mode': 'allocation', 'input_type': 'montant', 'base_amount': 0.0,
            'line_ids': [
                (0, 0, {'portfolio_id': self.portfolio_a.id, 'amount': 300.0}),
                (0, 0, {'portfolio_id': self.portfolio_b.id, 'amount': 400.0}),
            ],
        })
        self.assertEqual(repartition.base_amount, 700.0)
        repartition.action_validate()
        self.assertEqual(self.portfolio_a.amount_allocated, 300.0)
        self.assertEqual(self.portfolio_b.amount_allocated, 400.0)

        # Reste agence = 1000 - 700 = 300 : une seconde allocation de 450 (deux lignes <= 300
        # chacune, donc <= 100% chacune) le dépasse au total.
        repartition2 = self.env['microfinance.portfolio.allocation'].create({
            'fond_id': self.fond.id, 'company_id': self.env.company.id,
            'allocation_mode': 'allocation', 'input_type': 'montant', 'base_amount': 0.0,
            'line_ids': [
                (0, 0, {'portfolio_id': self.portfolio_a.id, 'amount': 250.0}),
                (0, 0, {'portfolio_id': self.portfolio_b.id, 'amount': 200.0}),
            ],
        })
        with self.assertRaises(UserError):
            repartition2.action_validate()

    def test_allocation_mode_percent_input(self):
        repartition = self.env['microfinance.portfolio.allocation'].create({
            'fond_id': self.fond.id, 'company_id': self.env.company.id,
            'allocation_mode': 'allocation', 'input_type': 'pourcentage', 'base_amount': 0.0,
            'line_ids': [
                (0, 0, {'portfolio_id': self.portfolio_a.id, 'percent': 60.0}),
                (0, 0, {'portfolio_id': self.portfolio_b.id, 'percent': 25.0}),
            ],
        })
        line_a = repartition.line_ids.filtered(lambda l: l.portfolio_id == self.portfolio_a)
        line_b = repartition.line_ids.filtered(lambda l: l.portfolio_id == self.portfolio_b)
        self.assertEqual(line_a.amount, 600.0)
        self.assertEqual(line_b.amount, 250.0)
        self.assertEqual(repartition.base_amount, 850.0)
        repartition.action_validate()

        other_company = self.env['res.company'].create({
            'name': 'Autre agence allocation test', 'agency_code': 'ALLOC-TEST',
        })
        other_portfolio = self.env['microfinance.portfolio'].create({
            'agent_id': self.agent_a.id, 'company_id': other_company.id,
        })
        with self.assertRaises(ValidationError):
            self.env['microfinance.portfolio.allocation'].create({
                'fond_id': self.fond.id, 'company_id': self.env.company.id,
                'allocation_mode': 'allocation', 'input_type': 'pourcentage', 'base_amount': 0.0,
                'line_ids': [(0, 0, {'portfolio_id': other_portfolio.id, 'percent': 10.0})],
            })

    def test_new_agent_after_validated_partage(self):
        partage = self.env['microfinance.portfolio.allocation'].create({
            'fond_id': self.fond.id, 'company_id': self.env.company.id,
            'base_amount': 400.0,
            'line_ids': [(0, 0, {'portfolio_id': self.portfolio_a.id, 'percent': 100.0, 'amount': 400.0})],
        })
        partage.action_validate()
        self.assertEqual(self.portfolio_a.amount_allocated, 400.0)

        agent_c = self.env['res.users'].create({
            'name': 'portfolio_alloc_agent_c_test', 'login': 'portfolio_alloc_agent_c_test',
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('microfinance_loan_management.group_microfinance_user').id,
            ])],
        })
        portfolio_c = self.env['microfinance.portfolio'].create({
            'agent_id': agent_c.id, 'company_id': self.env.company.id,
        })
        new_allocation = self.env['microfinance.portfolio.allocation'].new({
            'fond_id': self.fond.id, 'company_id': self.env.company.id,
        })
        new_allocation._onchange_fond_id()
        line_c = new_allocation.line_ids.filtered(lambda l: l.portfolio_id.id == portfolio_c.id)
        self.assertTrue(line_c, "Le nouvel agent doit apparaître pré-rempli à l'ouverture du formulaire.")
        self.assertEqual(line_c.amount, 0.0)

        repartition = self.env['microfinance.portfolio.allocation'].create({
            'fond_id': self.fond.id, 'company_id': self.env.company.id,
            'allocation_mode': 'allocation', 'input_type': 'montant', 'base_amount': 0.0,
            'line_ids': [(0, 0, {'portfolio_id': portfolio_c.id, 'amount': 150.0})],
        })
        repartition.action_validate()
        self.assertEqual(portfolio_c.amount_allocated, 150.0)
        self.assertEqual(self.portfolio_a.amount_allocated, 400.0)

        Line = self.env['microfinance.portfolio.allocation.line']
        history_c = Line.search([('portfolio_id', '=', portfolio_c.id), ('state', '=', 'validated')])
        self.assertEqual(len(history_c), 1)
        self.assertEqual(history_c.amount, 150.0)
        history_fond = Line.search([('fond_id', '=', self.fond.id), ('state', '=', 'validated')])
        self.assertIn(history_c, history_fond)


class TestPortfolioDisbursementBlocked(MicrofinanceNoFundMixin, TestFondBailleurCommon):
    """Correction Phase 2 §4 : l'octroi/décaissement d'un crédit est bloqué si son montant
    dépasse le fonds disponible du portefeuille de l'agent, dès que le fonds utilisé est géré par
    allocation (même condition de déclenchement que le plafond d'agence existant)."""

    def test_disbursement_blocked_when_portfolio_insufficient(self):
        fond = self._create_fond(verification_disponibilite='at_disbursement')
        fond.allocation_required = True
        portfolio = self.env['microfinance.portfolio'].create({
            'agent_id': self.env.user.id, 'company_id': self.env.company.id,
        })
        self.env['microfinance.fond.allocation'].sudo().with_context(**{
            ALLOCATION_TECHNICAL_CONTEXT: True,
        }).create({
            'fond_id': fond.id, 'company_id': self.env.company.id, 'amount_allocated': 500.0,
        })
        portfolio.sudo().with_context(**{PORTFOLIO_ALLOCATION_TECHNICAL_CONTEXT: True}).write({
            'amount_allocated': 500.0,
        })
        with self.assertRaises(UserError):
            self._activate_loan_without_disbursement(
                loan_amount=900.0, term=3, officer_id=self.env.user.id, fond_credit_id=fond.id)

    def test_disbursement_allowed_within_portfolio_balance(self):
        fond = self._create_fond(verification_disponibilite='at_disbursement')
        fond.allocation_required = True
        portfolio = self.env['microfinance.portfolio'].create({
            'agent_id': self.env.user.id, 'company_id': self.env.company.id,
        })
        self.env['microfinance.fond.allocation'].sudo().with_context(**{
            ALLOCATION_TECHNICAL_CONTEXT: True,
        }).create({
            'fond_id': fond.id, 'company_id': self.env.company.id, 'amount_allocated': 2000.0,
        })
        portfolio.sudo().with_context(**{PORTFOLIO_ALLOCATION_TECHNICAL_CONTEXT: True}).write({
            'amount_allocated': 2000.0,
        })
        loan = self._activate_loan_without_disbursement(
            loan_amount=900.0, term=3, officer_id=self.env.user.id, fond_credit_id=fond.id)
        self.assertEqual(loan.state, 'active')


class TestDashboardDataNoRegression(MicrofinanceCommon):
    """Non-régression dashboard (action 914, « Impossible de charger les données ») : un bug
    réel reproduit en prod venait d'une surcharge de get_dashboard_data restée sur l'ancienne
    signature (microfinance_savings_management/models/microfinance_dashboard_extension.py)
    après l'ajout du paramètre portfolio_id côté microfinance_loan_management - TypeError
    "takes 1 positional argument but 2 were given" dès le premier appel, pour N'IMPORTE QUEL
    rôle (agent, caissier, gestionnaire), avant même toute question d'accès à un portefeuille."""

    def _user(self, login, group_xmlid):
        return self.env['res.users'].create({
            'name': login, 'login': login,
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id, self.env.ref(group_xmlid).id,
            ])],
        })

    def test_get_dashboard_data_without_args_works_for_every_role(self):
        agent = self._user('dash_regress_agent_test', 'microfinance_loan_management.group_microfinance_user')
        cashier = self._user('dash_regress_cashier_test', 'microfinance_loan_management.group_microfinance_cashier')
        gestionnaire = self._user('dash_regress_gestionnaire_test', 'microfinance_loan_management.group_microfinance_gestionnaire')
        expected_keys = None
        for user in (agent, cashier, gestionnaire):
            data = self.env['microfinance.loan'].with_user(user).get_dashboard_data()
            self.assertIsInstance(data, dict)
            self.assertIn('kpis', data)
            self.assertIn('portfolio_officer_id', data)
            self.assertIn('portfolio_is_own', data)
            if expected_keys is None:
                expected_keys = set(data.keys())
            else:
                self.assertEqual(set(data.keys()), expected_keys)
