# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError, UserError, ValidationError

from .common import MicrofinanceCommon


class TestCreditCommitteeReview(MicrofinanceCommon):
    """Section VIII — Comité d'octroi (fiche d'enquête). Cf. docs_dev/comite_octroi/."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # base.group_user (Utilisateur interne) requis en plus des groupes microfinance :
        # group_microfinance_user/group_microfinance_credit_committee n'impliquent pas ce groupe
        # de base (aucun implied_ids vers lui dans security/groups.xml), sans quoi l'utilisateur
        # n'a même pas accès en lecture à res.partner - sans rapport avec la fonctionnalité
        # testée ici, juste un prérequis de fixture.
        internal_user_group = cls.env.ref('base.group_user').id
        cls.committee_user = cls.env['res.users'].create({
            'name': 'Membre comité octroi test',
            'login': 'test_committee_user',
            'groups_id': [(6, 0, [internal_user_group, cls.env.ref(
                'microfinance_loan_management.group_microfinance_credit_committee').id])],
        })
        cls.plain_user = cls.env['res.users'].create({
            'name': 'Enquêteur test (hors comité)',
            'login': 'test_plain_user',
            'groups_id': [(6, 0, [internal_user_group, cls.env.ref(
                'microfinance_loan_management.group_microfinance_user').id])],
        })
        cls.application = cls.env['microfinance.loan.application'].create({
            'partner_id': cls.partner.id,
            'loan_product_id': cls.product.id,
        })

    def test_first_slot_created_at_application_creation_by_any_user(self):
        # L'enquêteur qui crée le dossier n'est pas forcément membre du comité d'octroi - la
        # création du 1er emplacement (vide, aucune décision) ne doit pas l'en empêcher.
        application = self.env['microfinance.loan.application'].with_user(self.plain_user).create({
            'partner_id': self.partner.id, 'loan_product_id': self.product.id,
        })
        self.assertTrue(application.first_committee_review_id)
        self.assertEqual(application.first_committee_review_id.committee_number, 'first')
        self.assertFalse(application.first_committee_review_id.decision)
        self.assertFalse(application.second_committee_review_id)

    def test_committee_member_can_set_first_decision(self):
        application = self.application.with_user(self.committee_user)
        application.write({'committee_first_decision': 'accepted', 'committee_first_comment': False})
        self.assertEqual(application.committee_first_decision, 'accepted')

    def test_comment_required_when_refused(self):
        review = self.application.first_committee_review_id.with_user(self.committee_user)
        with self.assertRaises(ValidationError):
            review.write({'decision': 'refused', 'comment': False})

    def test_comment_present_when_refused_ok(self):
        review = self.application.first_committee_review_id.with_user(self.committee_user)
        review.write({'decision': 'refused', 'comment': 'Dossier incomplet, à revoir.'})
        self.assertEqual(review.decision, 'refused')

    def test_second_committee_hidden_until_first_refused(self):
        self.assertFalse(self.application.second_committee_review_id)
        review = self.application.first_committee_review_id.with_user(self.committee_user)
        review.write({'decision': 'accepted'})
        with self.assertRaises(UserError):
            self.application.with_user(self.committee_user).action_add_second_committee_review()

    def test_second_committee_available_after_first_refused(self):
        review = self.application.first_committee_review_id.with_user(self.committee_user)
        review.write({'decision': 'refused', 'comment': 'Analyse activité insuffisante.'})
        self.application.with_user(self.committee_user).action_add_second_committee_review()
        self.assertTrue(self.application.second_committee_review_id)
        self.assertEqual(self.application.second_committee_review_id.committee_number, 'second')

    def test_second_committee_cannot_be_postponed(self):
        review = self.application.first_committee_review_id.with_user(self.committee_user)
        review.write({'decision': 'refused', 'comment': 'Motif.'})
        self.application.with_user(self.committee_user).action_add_second_committee_review()
        second = self.application.second_committee_review_id.with_user(self.committee_user)
        with self.assertRaises(ValidationError):
            second.write({'decision': 'postponed'})

    def test_second_committee_requires_first_refused_at_orm_level(self):
        # Contournement du bouton (create() direct) : la contrainte doit bloquer quand même.
        with self.assertRaises(ValidationError):
            self.env['microfinance.credit.committee.review'].with_user(self.committee_user).create({
                'application_id': self.application.id, 'committee_number': 'second',
            })

    def test_cannot_change_first_decision_while_second_exists(self):
        review = self.application.first_committee_review_id.with_user(self.committee_user)
        review.write({'decision': 'refused', 'comment': 'Motif.'})
        self.application.with_user(self.committee_user).action_add_second_committee_review()
        with self.assertRaises(ValidationError):
            review.write({'decision': 'accepted'})

    def test_non_committee_member_write_blocked_at_orm_level(self):
        # Contournement de la vue (groups= masque le bloc, mais un write() direct doit être
        # bloqué indépendamment - c'est le point central de la double protection demandée).
        review = self.application.first_committee_review_id.with_user(self.plain_user)
        with self.assertRaises(AccessError):
            review.write({'decision': 'accepted'})

    def test_non_committee_member_create_blocked_at_orm_level(self):
        with self.assertRaises(AccessError):
            self.env['microfinance.credit.committee.review'].with_user(self.plain_user).create({
                'application_id': self.application.id, 'committee_number': 'first',
            })

    def test_non_committee_member_unlink_blocked_at_orm_level(self):
        review = self.application.first_committee_review_id
        with self.assertRaises(AccessError):
            review.with_user(self.plain_user).unlink()
