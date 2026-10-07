# -*- coding: utf-8 -*-
from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import Form

from .common import SavingsCommon


class TestSavingsTransactionCreationLock(SavingsCommon):
    """Verrouillage de la création directe hors guichet de microfinance.savings.transaction :
    seuls register_operation() (guichet, sudo scopé) et action_close() (clôture de compte, sudo
    scopé) peuvent encore créer une transaction pour un agent/caissier/manager standard - toute
    autre tentative de création directe (formulaire, ORM sans sudo) doit être refusée par
    ir.model.access.csv."""

    def _agent_user(self):
        return self.env['res.users'].create({
            'name': 'Agent épargne accès test', 'login': 'savings_agent_access_test',
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('microfinance_savings_management.group_savings_agent').id,
            ])],
        })

    def _manager_user(self):
        return self.env['res.users'].create({
            'name': 'Manager épargne accès test', 'login': 'savings_manager_access_test',
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('microfinance_savings_management.group_savings_manager').id,
            ])],
        })

    def _cashier_user(self):
        return self.env['res.users'].create({
            'name': 'Caissier accès test', 'login': 'savings_cashier_access_test',
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('microfinance_loan_management.group_microfinance_cashier').id,
            ])],
        })

    def _open_session(self):
        session = self.env['microfinance.caisse.session'].create({
            'journal_id': self.disbursement_journal.id, 'date': fields.Date.today(),
        })
        session.action_open_session()
        return session

    # --- Verrouillage ACL : création directe refusée hors guichet/clôture ---

    def test_agent_cannot_create_transaction_directly(self):
        account = self._create_active_account(opening_amount=100.0)
        agent = self._agent_user()
        with self.assertRaises(AccessError):
            self.env['microfinance.savings.transaction'].with_user(agent).create({
                'account_id': account.id, 'transaction_type': 'deposit', 'amount': 50.0,
            })

    def test_manager_cannot_create_transaction_directly(self):
        account = self._create_active_account(opening_amount=100.0)
        manager = self._manager_user()
        with self.assertRaises(AccessError):
            self.env['microfinance.savings.transaction'].with_user(manager).create({
                'account_id': account.id, 'transaction_type': 'deposit', 'amount': 50.0,
            })

    def test_cashier_cannot_create_transaction_form_directly(self):
        account = self._create_active_account(opening_amount=100.0)
        cashier = self._cashier_user()
        with self.assertRaises(AccessError):
            with Form(self.env['microfinance.savings.transaction'].with_user(cashier)) as txn_form:
                txn_form.account_id = account
                txn_form.transaction_type = 'deposit'
                txn_form.amount = 50.0
            txn_form.save()

    # --- Verrouillage UI : create="0" sur les vues génériques (action 712 et smart button "Transactions") ---

    def test_tree_and_form_views_have_create_locked(self):
        tree_view = self.env.ref('microfinance_savings_management.view_microfinance_savings_transaction_tree')
        form_view = self.env.ref('microfinance_savings_management.view_microfinance_savings_transaction_form')
        self.assertIn('create="0"', tree_view.arch)
        self.assertIn('create="0"', form_view.arch)

    # --- Non-régression : les deux flux légitimes (sudo scopé) continuent de fonctionner ---

    def test_guichet_deposit_still_works_for_cashier(self):
        account = self._create_active_account(opening_amount=100.0)
        cashier = self._cashier_user()
        session = self._open_session()
        mouvement = self.env['microfinance.caisse.mouvement'].with_user(cashier).register_operation(
            session.id, 'depot_epargne', self.partner.id, 50.0, account.id, False,
        )
        self.assertEqual(mouvement.savings_transaction_id.transaction_type, 'deposit')
        self.assertEqual(mouvement.savings_transaction_id.state, 'posted')
        self.assertAlmostEqual(account.balance, 150.0, places=2)

    def test_guichet_withdrawal_still_works_for_cashier(self):
        account = self._create_active_account(opening_amount=200.0)
        cashier = self._cashier_user()
        session = self._open_session()
        mouvement = self.env['microfinance.caisse.mouvement'].with_user(cashier).register_operation(
            session.id, 'retrait_epargne', self.partner.id, 50.0, account.id, False,
        )
        self.assertEqual(mouvement.savings_transaction_id.transaction_type, 'withdrawal')
        self.assertAlmostEqual(account.balance, 150.0, places=2)

    def test_account_closure_still_works_for_agent(self):
        account = self._create_active_account(opening_amount=120.0)
        agent = self._agent_user()
        account.with_user(agent).action_close()
        self.assertEqual(account.state, 'closed')
        self.assertAlmostEqual(account.balance, 0.0, places=2)
