# -*- coding: utf-8 -*-
from .common import MicrofinanceCommon


class TestSocialCategoryGrid(MicrofinanceCommon):
    """Section VI (suite) — Fiche de catégorisation sociale : grille de points."""

    def _create_application(self):
        return self.env['microfinance.loan.application'].create({
            'partner_id': self.partner.id,
            'company_id': self.env.company.id,
            'loan_product_id': self.product.id,
        })

    def test_consumption_units_formula(self):
        application = self._create_application()
        application.write({'members_over_14': 2, 'members_under_14': 2})
        # 1 (1er adulte) + 0,5 * (2 - 1) + 0,3 * 2 = 1 + 0,5 + 0,6 = 2,1
        self.assertAlmostEqual(application.consumption_units, 2.1, places=2)

    def test_total_points_without_any_option(self):
        application = self._create_application()
        application.write({
            'assets_score': 1, 'activity_score': 1, 'income_score': 1, 'food_score': 1,
            'health_score': 1, 'housing_state_score': 1, 'housing_surface_score': 0,
            'education_borrower_score': 1, 'education_children_score': 1,
            'savings_score': 4, 'administrative_score': 4, 'surveyor_impression_score': 4,
        })
        # Somme des 8 catégories obligatoires uniquement (housing_score = 1 + 0 = 1) :
        # 1+1+1+1+1+1+1+1 = 8, sans les 3 catégories optionnelles.
        self.assertEqual(application.total_points, 8)

    def test_total_points_include_savings_only(self):
        application = self._create_application()
        application.write({
            'assets_score': 1, 'activity_score': 1, 'income_score': 1, 'food_score': 1,
            'health_score': 1, 'housing_state_score': 1, 'housing_surface_score': 0,
            'education_borrower_score': 1, 'education_children_score': 1,
            'savings_score': 4, 'administrative_score': 4, 'surveyor_impression_score': 4,
        })
        self.env.company.microfinance_social_grid_include_savings = True
        self.assertEqual(application.total_points, 12)  # 8 + savings_score (4)

    def test_total_points_include_administrative_only(self):
        application = self._create_application()
        application.write({
            'assets_score': 1, 'activity_score': 1, 'income_score': 1, 'food_score': 1,
            'health_score': 1, 'housing_state_score': 1, 'housing_surface_score': 0,
            'education_borrower_score': 1, 'education_children_score': 1,
            'savings_score': 4, 'administrative_score': 4, 'surveyor_impression_score': 4,
        })
        self.env.company.microfinance_social_grid_include_administrative = True
        self.assertEqual(application.total_points, 12)  # 8 + administrative_score (4)

    def test_total_points_include_impression_only(self):
        application = self._create_application()
        application.write({
            'assets_score': 1, 'activity_score': 1, 'income_score': 1, 'food_score': 1,
            'health_score': 1, 'housing_state_score': 1, 'housing_surface_score': 0,
            'education_borrower_score': 1, 'education_children_score': 1,
            'savings_score': 4, 'administrative_score': 4, 'surveyor_impression_score': 4,
        })
        self.env.company.microfinance_social_grid_include_impression_in_total = True
        self.assertEqual(application.total_points, 12)  # 8 + surveyor_impression_score (4)

    def test_total_points_options_are_independent(self):
        application = self._create_application()
        application.write({
            'assets_score': 1, 'activity_score': 1, 'income_score': 1, 'food_score': 1,
            'health_score': 1, 'housing_state_score': 1, 'housing_surface_score': 0,
            'education_borrower_score': 1, 'education_children_score': 1,
            'savings_score': 4, 'administrative_score': 4, 'surveyor_impression_score': 4,
        })
        company = self.env.company
        company.microfinance_social_grid_include_savings = True
        self.assertEqual(application.total_points, 12)
        company.microfinance_social_grid_include_administrative = True
        self.assertEqual(application.total_points, 16)
        company.microfinance_social_grid_include_impression_in_total = True
        self.assertEqual(application.total_points, 20)
        # Désactiver l'épargne seule ne doit pas toucher aux deux autres, actifs indépendamment.
        company.microfinance_social_grid_include_savings = False
        self.assertEqual(application.total_points, 16)

    def test_social_level_at_exact_boundaries(self):
        application = self._create_application()
        application.write({
            'assets_score': 2, 'activity_score': 2, 'income_score': 2, 'food_score': 2,
            'health_score': 2, 'housing_state_score': 2, 'housing_surface_score': 2,
            'education_borrower_score': 1, 'education_children_score': 1,
        })
        self.assertEqual(application.total_points, 16)
        self.assertEqual(application.social_level_id.name, 'Niv 1')

        application.education_children_score = 2
        self.assertEqual(application.total_points, 17)
        self.assertEqual(application.social_level_id.name, 'Niv 2')

    def test_social_level_out_of_bounds_returns_empty_without_error(self):
        application = self._create_application()
        # Valeur volontairement hors de la plage réaliste (1-4 par catégorie) pour dépasser
        # le maximum théorique (32) sans activer aucune option — ne doit lever aucune
        # exception, social_level_id doit simplement rester vide.
        application.write({'assets_score': 40})
        self.assertGreater(application.total_points, 32)
        self.assertFalse(application.social_level_id)
