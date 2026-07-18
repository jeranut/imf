# -*- coding: utf-8 -*-
from odoo.exceptions import UserError

from .common import MicrofinanceCommon


class TestApplicationWorkflow(MicrofinanceCommon):
    """Workflow global du dossier d'instruction (microfinance.loan.application) :
    transitions d'état, contrôle de rôle, numérotation, éligibilité de rang > 1."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        surveyor_group = cls.env.ref('microfinance_loan_management.group_application_surveyor')
        manager_group = cls.env.ref('microfinance_loan_management.group_microfinance_manager')
        cls.surveyor_user = cls.env['res.users'].create({
            'name': 'Enquêteur Test Workflow', 'login': 'test_wf_surveyor',
            'groups_id': [(6, 0, [surveyor_group.id])],
        })
        cls.manager_user = cls.env['res.users'].create({
            'name': 'Manager Test Workflow', 'login': 'test_wf_manager',
            'groups_id': [(6, 0, [manager_group.id])],
        })

    def _create_application(self, **kwargs):
        vals = {'partner_id': self.partner.id, 'loan_product_id': self.product.id}
        vals.update(kwargs)
        return self.env['microfinance.loan.application'].create(vals)

    def test_full_workflow_to_loan_created(self):
        application = self._create_application()
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
        self.assertEqual(application.loan_id.product_id, self.product)

    def test_wrong_group_cannot_advance(self):
        application = self._create_application()
        application.action_start_field_survey()
        application.action_start_analysis()
        application.action_submit_committee()
        # committee -> ca_review exige group_application_ca ; l'enquêteur seul ne l'a pas.
        with self.assertRaises(UserError):
            application.with_user(self.surveyor_user).action_ca_review()

    def test_manager_bypasses_group_check(self):
        application = self._create_application()
        application.action_start_field_survey()
        application.action_start_analysis()
        application.action_submit_committee()
        # Le manager crédit n'a ni group_application_ca ni cdag, mais passe outre le contrôle
        # de rôle (jamais celui de l'ordre des transitions).
        application.with_user(self.manager_user).action_ca_review()
        self.assertEqual(application.state, 'ca_review')

    def test_automatic_numbering(self):
        app1 = self._create_application()
        app2 = self._create_application()
        self.assertNotEqual(app1.name, 'Nouveau')
        self.assertTrue(app1.name.startswith('%s/' % self.env.company.agency_code))
        self.assertNotEqual(app1.name, app2.name)

    def test_previous_loan_requirement_triggered_on_rank_greater_than_one(self):
        company = self.env.company
        # Crédit de rang 1 déjà décaissé et clôturé, pour que le nouveau dossier calcule un
        # loan_sequence_number de 2 (cf. _compute_loan_sequence_number / PRIOR_LOAN_STATES).
        loan1 = self._create_loan()
        loan1.write({'state': 'closed'})

        application1 = self._create_application()
        application1.action_start_field_survey()
        application1.action_start_analysis()
        application1.action_submit_committee()
        application1.action_ca_review()
        application1.action_cdag_review()
        application1.action_accept()
        application1.surveyor_impression_score = 0
        application1.with_context(application_create_loan=True).write({'state': 'loan_created'})

        company.microfinance_social_grid_include_impression_next_loan = True
        company.microfinance_social_grid_impression_next_loan_min_score = 1

        application2 = self._create_application()
        self.assertEqual(application2.loan_sequence_number, 2)
        application2.action_start_field_survey()
        application2.action_start_analysis()
        # analysis -> committee déclenche _check_committee_eligibility ->
        # _check_previous_loan_requirements : impression du dossier précédent (0) < seuil (1).
        with self.assertRaises(UserError):
            application2.action_submit_committee()

        # Relever l'impression du dossier précédent au-dessus du seuil débloque la soumission.
        application1.surveyor_impression_score = 2
        application2.action_submit_committee()
        self.assertEqual(application2.state, 'committee')
