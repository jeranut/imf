# -*- coding: utf-8 -*-
from odoo.exceptions import UserError

from .common import MicrofinanceCommon


class TestCommitteeOctroiApprovalGuard(MicrofinanceCommon):
    """Blocage de action_approve() tant que le Comité d'Octroi (Section VIII, microfinance.loan.
    application) n'a pas rendu une décision effectivement acceptée. Cf. docs_dev/
    blocage_approbation_comite_octroi/AUDIT.md pour le tableau de cas complet."""

    def setUp(self):
        super().setUp()
        self.env['microfinance.fond.credit'].sudo().search([]).write({'active': False})

    def _loan_in_avis_cdag(self):
        loan = self._create_loan(loan_amount=1200.0, term=6)
        loan.action_generate_schedule()
        loan.action_start_enquete()
        loan.action_ca_review()
        loan.action_cdag_review()
        return loan

    def test_blocked_when_no_application_at_all(self):
        loan = self._loan_in_avis_cdag()
        self.assertFalse(loan.application_ids)
        with self.assertRaises(UserError):
            loan.action_approve()
        self.assertEqual(loan.state, 'avis_cdag')

    def test_blocked_when_first_committee_not_decided(self):
        loan = self._loan_in_avis_cdag()
        loan.action_view_applications()
        self.assertTrue(loan.application_ids.first_committee_review_id)
        self.assertFalse(loan.application_ids.committee_first_decision)
        with self.assertRaises(UserError):
            loan.action_approve()

    def test_allowed_when_first_committee_accepted(self):
        loan = self._loan_in_avis_cdag()
        loan.action_view_applications()
        loan.application_ids.write({'committee_first_decision': 'accepted'})
        loan.action_approve()
        self.assertEqual(loan.state, 'approved')

    def test_blocked_when_first_committee_postponed(self):
        loan = self._loan_in_avis_cdag()
        loan.action_view_applications()
        loan.application_ids.write({'committee_first_decision': 'postponed'})
        with self.assertRaises(UserError):
            loan.action_approve()

    def test_blocked_when_first_refused_and_no_second(self):
        # Écrit directement sur l'enregistrement enfant (pas via les champs related de
        # l'application) : decision/comment doivent être posés dans le MÊME write() pour
        # satisfaire _check_comment_required_if_refused - passer par les related écrirait
        # chaque champ séparément (un _inverse_related par champ) et lèverait prématurément.
        loan = self._loan_in_avis_cdag()
        loan.action_view_applications()
        loan.application_ids.first_committee_review_id.write({
            'decision': 'refused', 'comment': 'Motif.',
        })
        with self.assertRaises(UserError):
            loan.action_approve()

    def test_blocked_when_first_refused_and_second_refused(self):
        loan = self._loan_in_avis_cdag()
        loan.action_view_applications()
        application = loan.application_ids
        application.first_committee_review_id.write({'decision': 'refused', 'comment': 'Motif.'})
        application.action_add_second_committee_review()
        application.second_committee_review_id.write({'decision': 'refused', 'comment': 'Confirmé.'})
        with self.assertRaises(UserError):
            loan.action_approve()

    def test_allowed_when_first_refused_and_second_accepted(self):
        loan = self._loan_in_avis_cdag()
        loan.action_view_applications()
        application = loan.application_ids
        application.first_committee_review_id.write({'decision': 'refused', 'comment': 'Motif.'})
        application.action_add_second_committee_review()
        application.second_committee_review_id.write({'decision': 'accepted'})
        loan.action_approve()
        self.assertEqual(loan.state, 'approved')
