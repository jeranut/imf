# -*- coding: utf-8 -*-
from .common import MicrofinanceCommon


class TestApplicationSurveyPagination(MicrofinanceCommon):
    """Pagination à 7 pages de la fiche d'enquête : survey_page est indépendant de state,
    navigable librement même sur un dossier déjà avancé dans le workflow. Page 1 = Section I,
    Page 2 = Sections II/III/IV, Page 3 = Section V jusqu'à la capacité de remboursement
    (situation actuelle), Page 4 = accroissement du revenu + situation prévisionnelle, Page 5 =
    plan de financement + Section VI (catégorisation sociale), Page 6 = impression de
    l'enquêteur + visite à domicile (VAD), Page 7 = visite au lieu de vente (VAV) + Sections
    VII/VIII (cf. repagination fine 2026-08-18)."""

    def _create_application(self, **kwargs):
        vals = {'partner_id': self.partner.id, 'loan_product_id': self.product.id}
        vals.update(kwargs)
        return self.env['microfinance.loan.application'].create(vals)

    def test_default_page_is_page_one(self):
        application = self._create_application()
        self.assertEqual(application.survey_page, 'partner_identification')

    def test_next_page_navigation_through_all_seven_pages(self):
        application = self._create_application()
        expected = [
            'guarantor_documents_activity', 'financial_visits_ca_cdag', 'income_growth_forecast',
            'financing_plan_social_grid', 'surveyor_impression_field_visits', 'ca_cdag_committee',
        ]
        for expected_page in expected:
            application.action_survey_next_page()
            self.assertEqual(application.survey_page, expected_page)

    def test_next_page_stays_on_page_seven_at_the_end(self):
        application = self._create_application()
        for _ in range(8):
            application.action_survey_next_page()
        self.assertEqual(application.survey_page, 'ca_cdag_committee')

    def test_previous_page_navigation_through_all_seven_pages(self):
        application = self._create_application()
        application.survey_page = 'ca_cdag_committee'
        expected = [
            'surveyor_impression_field_visits', 'financing_plan_social_grid',
            'income_growth_forecast', 'financial_visits_ca_cdag',
            'guarantor_documents_activity', 'partner_identification',
        ]
        for expected_page in expected:
            application.action_survey_previous_page()
            self.assertEqual(application.survey_page, expected_page)

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
