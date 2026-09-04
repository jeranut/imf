# -*- coding: utf-8 -*-
from odoo.exceptions import UserError

from .common import MicrofinanceCommon


class TestCommitteeReviewLazySlot(MicrofinanceCommon):
    """Création à la volée du slot comité d'octroi lors de l'écriture d'une décision, pour un
    dossier qui n'en a pas (cas des dossiers legacy créés avant le déploiement du Comité
    d'Octroi, ex. IS/000289 et IS/001076 sur SEFOR). Corrige l'échec silencieux diagnostiqué
    dans docs_dev/blocage_approbation_comite_octroi/DIAGNOSTIC_refus_silencieux.md : écrire sur
    un champ related dont le Many2one intermédiaire est vide ne fait rien, sans erreur
    (Field._inverse_related, odoo/fields.py:713). Chaque scénario est vérifié par une requête SQL
    directe (pas seulement via l'ORM/le cache), pour ne pas reproduire l'angle mort qui a caché
    le bug d'origine (l'écran laissait croire à une sauvegarde qui n'avait jamais eu lieu)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        internal_user_group = cls.env.ref('base.group_user').id
        cls.committee_user = cls.env['res.users'].create({
            'name': 'Membre comité octroi test (lazy slot)',
            'login': 'test_committee_user_lazy_slot',
            'groups_id': [(6, 0, [internal_user_group, cls.env.ref(
                'microfinance_loan_management.group_microfinance_credit_committee').id])],
        })

    def _application_without_committee_slot(self):
        """Simule un dossier legacy : création normale (bootstrap crée un slot vide), puis
        suppression de ce slot pour retomber dans l'état réel constaté sur SEFOR
        (first_committee_review_id NULL) - l'ondelete par défaut (Many2one non required) remet
        bien le pointeur à NULL en base au moment de l'unlink."""
        application = self.env['microfinance.loan.application'].create({
            'partner_id': self.partner.id, 'loan_product_id': self.product.id,
        })
        application.first_committee_review_id.sudo().unlink()
        application.invalidate_recordset(['first_committee_review_id'])
        self.assertFalse(application.first_committee_review_id)
        return application

    def test_first_decision_write_creates_slot_and_persists_in_db(self):
        application = self._application_without_committee_slot()
        application.with_user(self.committee_user).write({
            'committee_first_decision': 'refused', 'committee_first_comment': 'Motif test.',
        })
        self.env.flush_all()
        self.env.cr.execute(
            "SELECT first_committee_review_id FROM microfinance_loan_application WHERE id = %s",
            (application.id,),
        )
        slot_id = self.env.cr.fetchone()[0]
        self.assertIsNotNone(slot_id, "first_committee_review_id doit être renseigné en base après écriture")
        self.env.cr.execute(
            "SELECT decision, comment, committee_number FROM microfinance_credit_committee_review "
            "WHERE id = %s", (slot_id,),
        )
        decision, comment, committee_number = self.env.cr.fetchone()
        self.assertEqual(decision, 'refused')
        self.assertEqual(comment, 'Motif test.')
        self.assertEqual(committee_number, 'first')

    def test_ensure_committee_review_slot_idempotent(self):
        application = self._application_without_committee_slot()
        application._ensure_committee_review_slot()
        first_slot_id = application.first_committee_review_id.id
        application._ensure_committee_review_slot()
        self.assertEqual(application.first_committee_review_id.id, first_slot_id)
        self.env.cr.execute(
            "SELECT count(*) FROM microfinance_credit_committee_review WHERE application_id = %s",
            (application.id,),
        )
        self.assertEqual(self.env.cr.fetchone()[0], 1)

    def test_second_decision_write_creates_slot_when_first_refused(self):
        application = self._application_without_committee_slot()
        application.with_user(self.committee_user).write({
            'committee_first_decision': 'refused', 'committee_first_comment': 'Motif.',
        })
        self.assertFalse(application.second_committee_review_id)
        application.with_user(self.committee_user).write({'committee_second_decision': 'accepted'})
        self.env.flush_all()
        self.env.cr.execute(
            "SELECT second_committee_review_id FROM microfinance_loan_application WHERE id = %s",
            (application.id,),
        )
        slot_id = self.env.cr.fetchone()[0]
        self.assertIsNotNone(slot_id)
        self.env.cr.execute(
            "SELECT decision, committee_number FROM microfinance_credit_committee_review WHERE id = %s",
            (slot_id,),
        )
        decision, committee_number = self.env.cr.fetchone()
        self.assertEqual(decision, 'accepted')
        self.assertEqual(committee_number, 'second')

    def test_second_decision_write_raises_explicit_error_when_first_not_refused(self):
        # Erreur explicite exigée par le Lot 1.1 : jamais un nouvel échec silencieux, même dans
        # ce cas où le 2ème comité n'a pas de sens (1er comité pas refusé).
        application = self._application_without_committee_slot()
        with self.assertRaises(UserError):
            application.with_user(self.committee_user).write({'committee_second_decision': 'accepted'})

    def test_committee_fields_are_not_readonly(self):
        # Régression réelle constatée après le Lot 1.1 (docs_dev/blocage_approbation_comite_
        # octroi/AUDIT_readonly_1er_comite.md) : un compute= sans inverse= ET sans readonly=
        # explicite devient readonly=True par défaut côté framework (odoo/fields.py::
        # Field._get_attrs) - le client web ne renvoie alors jamais ces champs à la sauvegarde,
        # rendant l'interception dans write() inatteignable depuis un vrai formulaire, bien
        # qu'invisible à un test qui appelle write() directement en Python (tous les autres
        # tests de ce fichier). Seule une assertion explicite sur .readonly révèle ce cas.
        application = self.env['microfinance.loan.application']
        for field_name in (
            'committee_first_review_date', 'committee_first_decision',
            'committee_first_postpone_reason', 'committee_first_complement',
            'committee_first_comment', 'committee_second_review_date',
            'committee_second_decision', 'committee_second_comment',
        ):
            self.assertFalse(
                application._fields[field_name].readonly,
                '%s ne doit pas être readonly (sinon inatteignable depuis le formulaire)' % field_name,
            )
