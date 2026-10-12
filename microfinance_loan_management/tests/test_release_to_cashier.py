# -*- coding: utf-8 -*-
"""Libération d'un crédit actif vers le guichet : méthode unique _release_to_cashier() appelée par
l'activation, le cron et le bouton « Envoyer à la caisse »."""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.addons.microfinance_loan_management.models.res_company import ResCompany

from .common import MicrofinanceCommon, MicrofinanceNoFundMixin


class TestReleaseToCashier(MicrofinanceNoFundMixin, MicrofinanceCommon):

    def setUp(self):
        # MOWGLI a une société mère réelle qui bloque la neutralisation des fonds du mixin.
        self.patch(ResCompany, '_get_microfinance_parent', lambda rec: rec.browse())
        super().setUp()

    def _user(self, login, group_xmlid):
        return self.env['res.users'].create({
            'name': login, 'login': login, 'email': '%s@example.com' % login,
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id, self.env.ref(group_xmlid).id])],
        })

    def _activate(self, planned, confirmed=True):
        """Active via l'assistant de confirmation (chemin réel du bouton « Activer »)."""
        loan = self._approve_loan(loan_amount=900.0, term=3)
        if confirmed:
            self.env['microfinance.loan.activation.confirm.wizard'].create({
                'loan_id': loan.id, 'disbursement_date_planned': planned,
            }).action_confirm()
        else:
            loan.disbursement_date_planned = planned
            loan._do_activate()
        return loan

    def _pending_ids(self, loan):
        return [r['id'] for r in self.env['microfinance.loan'].get_pending_disbursements(loan.company_id.id)]

    def _upcoming_ids(self, loan):
        return self.env['microfinance.loan'].search(
            self.env['microfinance.loan']._agent_portfolio_upcoming_domain([loan.company_id.id])).ids

    def _released_messages(self, loan):
        return loan.message_ids.filtered(lambda m: 'Libéré vers la caisse' in (m.body or ''))

    def test_activation_with_reached_date_releases_immediately(self):
        loan = self._activate(fields.Date.context_today(self.env.user))
        self.assertTrue(loan.disbursement_release_ready)
        self.assertIn(loan.id, self._pending_ids(loan))
        self.assertNotIn(loan.id, self._upcoming_ids(loan))
        self.assertEqual(len(self._released_messages(loan)), 1)
        self.assertIn("à l'activation", self._released_messages(loan).body)

    def test_activation_with_future_date_waits_then_button_with_motif(self):
        future = fields.Date.context_today(self.env.user) + timedelta(days=10)
        loan = self._activate(future)
        self.assertFalse(loan.disbursement_release_ready)
        self.assertNotIn(loan.id, self._pending_ids(loan))
        self.assertIn(loan.id, self._upcoming_ids(loan))
        manager = self._user('release_manager', 'microfinance_loan_management.group_microfinance_manager')
        action = loan.with_user(manager).action_release_to_cashier()
        self.assertEqual(action['res_model'], 'microfinance.loan.release.wizard')
        self.assertFalse(loan.disbursement_release_ready)
        wizard = self.env['microfinance.loan.release.wizard'].with_user(manager).create(
            {'loan_id': loan.id, 'reason': ' '})
        with self.assertRaises(UserError):
            wizard.action_confirm()
        wizard.reason = 'Client pressé, fonds disponibles'
        wizard.action_confirm()
        self.assertTrue(loan.disbursement_release_ready)
        self.assertIn(loan.id, self._pending_ids(loan))
        self.assertNotIn(loan.id, self._upcoming_ids(loan))
        body = self._released_messages(loan).body
        self.assertIn('release_manager', body)
        self.assertIn('Client pressé', body)
        # Le cron suivant (même après la date) ne libère pas une seconde fois.
        loan.disbursement_date_planned = False
        self.env['microfinance.loan'].cron_release_ready_disbursements()
        self.assertEqual(len(self._released_messages(loan)), 1)

    def test_unconfirmed_date_not_released_automatically_but_button_usable(self):
        today = fields.Date.context_today(self.env.user)
        loan = self._activate(today, confirmed=False)
        self.assertFalse(loan.disbursement_date_confirmed)
        self.env['microfinance.loan'].cron_release_ready_disbursements()
        self.assertFalse(loan.disbursement_release_ready)
        gest = self._user('release_gest', 'microfinance_loan_management.group_microfinance_gestionnaire')
        action = loan.with_user(gest).action_release_to_cashier()
        self.assertEqual(action['res_model'], 'microfinance.loan.release.wizard')
        loan.with_user(gest).action_release_to_cashier_confirmed('Date non confirmée mais urgente')
        self.assertTrue(loan.disbursement_release_ready)

    def test_cron_releases_once_and_is_idempotent(self):
        today = fields.Date.context_today(self.env.user)
        loan = self._activate(today + timedelta(days=3))
        loan.disbursement_date_planned = today
        self.assertFalse(loan.disbursement_release_ready)
        Loan = self.env['microfinance.loan']
        Loan.cron_release_ready_disbursements()
        Loan.cron_release_ready_disbursements()
        self.assertTrue(loan.disbursement_release_ready)
        self.assertEqual(len(self._released_messages(loan)), 1)
        self.assertIn('par le cron', self._released_messages(loan).body)

    def test_repeated_calls_release_once(self):
        today = fields.Date.context_today(self.env.user)
        loan = self._activate(today + timedelta(days=3))
        manager = self._user('release_manager2', 'microfinance_loan_management.group_microfinance_manager')
        loan.with_user(manager).action_release_to_cashier_confirmed('Premier clic')
        loan.with_user(manager).action_release_to_cashier_confirmed('Second clic')
        loan.with_user(manager).action_release_to_cashier()
        self.assertEqual(len(self._released_messages(loan)), 1)

    def test_cashier_and_plain_agent_cannot_release(self):
        loan = self._activate(fields.Date.context_today(self.env.user) + timedelta(days=3))
        for login, group in (('release_cashier', 'microfinance_loan_management.group_microfinance_cashier'),
                             ('release_agent', 'microfinance_loan_management.group_microfinance_user')):
            user = self._user(login, group)
            with self.assertRaises(AccessError):
                loan.with_user(user).action_release_to_cashier()
            with self.assertRaises(AccessError):
                loan.with_user(user).action_release_to_cashier_confirmed('motif')
        self.assertFalse(loan.disbursement_release_ready)
        cashier = self.env['res.users'].search([('login', '=', 'release_cashier')])
        form_arch = self.env['microfinance.loan'].with_user(cashier).get_view(
            self.env.ref('microfinance_loan_management.view_microfinance_loan_form').id, 'form')['arch']
        self.assertNotIn('name="action_release_to_cashier"', form_arch)
        manager = self._user('release_manager3', 'microfinance_loan_management.group_microfinance_manager')
        form_arch = self.env['microfinance.loan'].with_user(manager).get_view(
            self.env.ref('microfinance_loan_management.view_microfinance_loan_form').id, 'form')['arch']
        self.assertIn('name="action_release_to_cashier"', form_arch)

    def test_other_company_user_does_not_see_loan(self):
        loan = self._activate(fields.Date.context_today(self.env.user))
        other_company = self.env['res.company'].create({'name': 'Autre agence test release', 'agency_code': 'ZR1'})
        user = self._user('release_other_co', 'microfinance_loan_management.group_microfinance_manager')
        user.write({'company_ids': [(6, 0, [other_company.id])], 'company_id': other_company.id})
        self.assertFalse(self.env['microfinance.loan'].with_user(user).search([('id', '=', loan.id)]))
        with self.assertRaises(AccessError):
            loan.with_user(user).action_release_to_cashier()

    def test_pending_list_ignores_older_open_session(self):
        session = self.env['microfinance.caisse.session'].create({
            'journal_id': self.disbursement_journal.id,
            'date': fields.Date.context_today(self.env.user) - timedelta(days=15),
        })
        session.action_open_session()
        loan = self._activate(fields.Date.context_today(self.env.user))
        self.assertIn(loan.id, self._pending_ids(loan))

    def test_disbursement_after_release_is_unchanged(self):
        loan = self._activate(fields.Date.context_today(self.env.user))
        self.assertFalse(loan.disbursement_date)
        loan.action_process_disbursement()
        self.assertTrue(loan.disbursement_date)
        self.assertTrue(loan.disbursement_move_id)
        self.assertNotIn(loan.id, self._pending_ids(loan))
        # Un crédit décaissé n'est plus libérable.
        loan._release_to_cashier('manual', reason='x')
        self.assertEqual(len(self._released_messages(loan)), 1)
