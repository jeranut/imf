# -*- coding: utf-8 -*-
from .common import MicrofinanceCommon


class TestApplicationSurveyPagination(MicrofinanceCommon):
    """Pagination à 3 pages de la fiche d'enquête : survey_page est indépendant de state,
    navigable librement même sur un dossier déjà avancé dans le workflow. Page 1 = Section I,
    Page 2 = Sections II/III/IV, Page 3 = Sections V/VI/VII/VIII (cf. repagination
    2026-07-19, docs_dev/programme_progressif/STATUS.md)."""

    def _create_application(self, **kwargs):
        vals = {'partner_id': self.partner.id, 'loan_product_id': self.product.id}
        vals.update(kwargs)
        return self.env['microfinance.loan.application'].create(vals)

    def test_default_page_is_page_one(self):
        application = self._create_application()
        self.assertEqual(application.survey_page, 'partner_identification')

    def test_next_page_navigation_through_all_three_pages(self):
        application = self._create_application()
        application.action_survey_next_page()
        self.assertEqual(application.survey_page, 'guarantor_documents_activity')
        application.action_survey_next_page()
        self.assertEqual(application.survey_page, 'financial_visits_ca_cdag')

    def test_next_page_stays_on_page_three_at_the_end(self):
        application = self._create_application()
        application.action_survey_next_page()
        application.action_survey_next_page()
        application.action_survey_next_page()
        self.assertEqual(application.survey_page, 'financial_visits_ca_cdag')

    def test_previous_page_navigation_through_all_three_pages(self):
        application = self._create_application()
        application.survey_page = 'financial_visits_ca_cdag'
        application.action_survey_previous_page()
        self.assertEqual(application.survey_page, 'guarantor_documents_activity')
        application.action_survey_previous_page()
        self.assertEqual(application.survey_page, 'partner_identification')

    def test_previous_page_stays_on_page_one_at_the_start(self):
        application = self._create_application()
        application.action_survey_previous_page()
        self.assertEqual(application.survey_page, 'partner_identification')

    def test_navigation_never_changes_state(self):
        application = self._create_application()
        application.action_start_visite()
        self.assertEqual(application.state, 'visite')
        application.action_survey_next_page()
        application.action_survey_next_page()
        self.assertEqual(application.state, 'visite')
        application.action_survey_previous_page()
        application.action_survey_previous_page()
        self.assertEqual(application.state, 'visite')

    def test_navigation_available_regardless_of_workflow_state(self):
        # Navigable librement même sur un dossier avancé dans le workflow (indépendant de state).
        application = self._create_application()
        application.action_start_visite()
        application.action_start_contre_visite()
        application.action_survey_next_page()
        self.assertEqual(application.survey_page, 'guarantor_documents_activity')
        self.assertEqual(application.state, 'contre_visite')

    def test_page_two_guarantor_fields_still_save_and_update_summary(self):
        # Aucune section de la Page 2 n'a été modifiée par la pagination (uniquement la vue) :
        # simple contrôle de non-régression sur le garant (champs directs sur le dossier, un
        # seul garant par dossier — cf. abandon de l'architecture wizard).
        application = self._create_application()
        guarantor_contact = self.env['res.partner'].create({'name': 'Garant Test Pagination'})
        application.write({
            'guarantor_partner_id': guarantor_contact.id,
            'guarantor_id_card_number': '123456789012',
        })
        self.assertEqual(application.guarantor_count, 1)
        self.assertEqual(application.primary_guarantor_name, 'Garant Test Pagination')
