# -*- coding: utf-8 -*-
from odoo.exceptions import UserError

from .common import MicrofinanceCommon


class TestLoanCreationLock(MicrofinanceCommon):
    """Le dossier d'instruction devient le seul point d'entrée de création d'un crédit
    (microfinance.loan) : verrou sur le chemin d'appel (contexte
    microfinance_loan_creation_allowed), jamais sur le rôle/groupe de l'utilisateur —
    un manager avec accès en écriture sur le modèle ne doit pas pouvoir contourner ce
    verrou via l'ORM/API sans passer par le wizard légitime."""

    def _loan_vals(self, **kwargs):
        vals = {
            'partner_id': self.partner.id,
            'product_id': self.product.id,
            'loan_amount': 1200.0,
            'term': 6,
        }
        vals.update(kwargs)
        return vals

    def test_direct_create_without_context_blocked(self):
        with self.assertRaises(UserError):
            self.env['microfinance.loan'].create(self._loan_vals())

    def test_direct_create_as_manager_still_blocked(self):
        """Le verrou n'est pas contournable par un rôle privilégié : même un manager
        crédit (accès complet sur le modèle) est bloqué sans le contexte explicite."""
        manager_group = self.env.ref('microfinance_loan_management.group_microfinance_manager')
        manager = self.env['res.users'].create({
            'name': 'Manager Test Verrou Crédit', 'login': 'test_lock_manager',
            'groups_id': [(6, 0, [manager_group.id])],
        })
        with self.assertRaises(UserError):
            self.env['microfinance.loan'].with_user(manager).create(self._loan_vals())

    def test_simulated_import_without_context_blocked(self):
        """Simule un import CSV/API : plusieurs enregistrements en une seule création par
        lot (api.model_create_multi), sans le contexte d'autorisation."""
        with self.assertRaises(UserError):
            self.env['microfinance.loan'].create([self._loan_vals(), self._loan_vals()])

    def test_create_with_context_flag_allowed(self):
        loan = self.env['microfinance.loan'].with_context(
            microfinance_loan_creation_allowed=True
        ).create(self._loan_vals())
        self.assertTrue(loan.id)

    def test_create_via_wizard_allowed(self):
        """Chemin légitime de bout en bout : dossier accepté → wizard → crédit créé."""
        application = self.env['microfinance.loan.application'].create({
            'partner_id': self.partner.id,
            'loan_product_id': self.product.id,
        })
        application.action_start_field_survey()
        application.action_start_analysis()
        application.action_submit_committee()
        application.action_ca_review()
        application.action_cdag_review()
        application.action_accept()
        action = application.action_create_loan()
        wizard = self.env['microfinance.loan.application.create.loan.wizard'].with_context(
            action['context']
        ).create({'loan_amount': 1000.0, 'term': 6})
        wizard.action_validate()
        self.assertEqual(application.state, 'loan_created')
        self.assertTrue(application.loan_id.id)
