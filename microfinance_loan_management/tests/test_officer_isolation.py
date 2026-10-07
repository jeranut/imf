# -*- coding: utf-8 -*-
"""R1, résidu A4 (AUDIT_portefeuille_agent.md) : isolation par agent au niveau ORM sur
microfinance.loan/.loan.payment/.loan.installment/.collection.visit (security/
microfinance_officer_isolation_rules.xml), pas seulement via le filtrage applicatif du
dashboard. Fixtures réutilisées depuis tests/test_portfolio.py::TestPortfolioIsolation
(utilisateur agent minimal, group_microfinance_user seul)."""
from odoo.exceptions import AccessError

from .common import MicrofinanceCommon, MicrofinanceNoFundMixin


class TestOfficerIsolationCommon(MicrofinanceNoFundMixin, MicrofinanceCommon):

    def _user(self, login, group_xmlid):
        return self.env['res.users'].create({
            'name': login, 'login': login,
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id, self.env.ref(group_xmlid).id,
            ])],
        })

    def setUp(self):
        super().setUp()
        self.agent_a = self._user('officer_iso_agent_a', 'microfinance_loan_management.group_microfinance_user')
        self.agent_b = self._user('officer_iso_agent_b', 'microfinance_loan_management.group_microfinance_user')
        self.gestionnaire = self._user('officer_iso_gestionnaire', 'microfinance_loan_management.group_microfinance_gestionnaire')
        self.cashier = self._user('officer_iso_cashier', 'microfinance_loan_management.group_microfinance_cashier')
        self.loan_a = self._activate_loan(loan_amount=900.0, term=3, officer_id=self.agent_a.id)
        self.loan_b = self._activate_loan(loan_amount=900.0, term=3, officer_id=self.agent_b.id)
        self.payment_b = self.env['microfinance.loan.payment'].create({
            'loan_id': self.loan_b.id, 'amount': 50.0, 'journal_id': self.payment_journal.id,
        })
        self.payment_b.action_post()


class TestOfficerIsolation(TestOfficerIsolationCommon):

    def test_agent_does_not_see_colleague_records(self):
        self.assertIn(self.loan_a, self.env['microfinance.loan'].with_user(self.agent_a).search([]))
        self.assertNotIn(self.loan_b, self.env['microfinance.loan'].with_user(self.agent_a).search([]))
        self.assertTrue(self.env['microfinance.loan.installment'].with_user(self.agent_a).search(
            [('loan_id', '=', self.loan_a.id)]))
        self.assertFalse(self.env['microfinance.loan.installment'].with_user(self.agent_a).search(
            [('loan_id', '=', self.loan_b.id)]))
        self.assertFalse(self.env['microfinance.loan.payment'].with_user(self.agent_a).search(
            [('id', '=', self.payment_b.id)]))
        visit_b = self.env['microfinance.collection.visit'].create({
            'loan_id': self.loan_b.id, 'agent_id': self.agent_b.id,
        })
        self.assertFalse(self.env['microfinance.collection.visit'].with_user(self.agent_a).search(
            [('id', '=', visit_b.id)]))

    def test_gestionnaire_sees_both_agents_everywhere(self):
        Gest = self.env['microfinance.loan'].with_user(self.gestionnaire)
        self.assertIn(self.loan_a, Gest.search([]))
        self.assertIn(self.loan_b, Gest.search([]))
        self.assertTrue(self.env['microfinance.loan.payment'].with_user(self.gestionnaire).search(
            [('id', '=', self.payment_b.id)]))

    def test_cashier_can_read_any_agent_loan_and_payment_for_guichet(self):
        # Le guichet (microfinance_caisse_mouvement, module microfinance_savings_management, hors
        # périmètre de ce module) poste les remboursements EN SUDO (Phase 1 B3) - mécanisme
        # inchangé. Ce que la règle d'échappement caissier garantit ici, testable dans ce module :
        # la LECTURE de n'importe quel crédit/paiement de l'agence, nécessaire aux listes du
        # guichet (ex. get_pending_disbursements) quel que soit l'agent propriétaire.
        Cashier = self.env['microfinance.loan'].with_user(self.cashier)
        self.assertIn(self.loan_a, Cashier.search([]))
        self.assertIn(self.loan_b, Cashier.search([]))
        self.assertTrue(self.env['microfinance.loan.payment'].with_user(self.cashier).search(
            [('id', '=', self.payment_b.id)]))

    def test_agent_cannot_write_colleague_loan(self):
        with self.assertRaises(AccessError):
            self.loan_b.with_user(self.agent_a).write({'note': 'tentative hors portefeuille'})
