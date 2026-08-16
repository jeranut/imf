# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError

from .common import MicrofinanceCommon


class TestSocialCategoryGrid(MicrofinanceCommon):
    """Section VI (suite) — Fiche de catégorisation sociale : grille de points, moteur
    générique de tranches (microfinance.social.score.bracket)."""

    def _create_application(self):
        return self.env['microfinance.loan.application'].create({
            'partner_id': self.partner.id,
            'company_id': self.env.company.id,
            'loan_product_id': self.product.id,
        })

    def _bracket_id(self, category, sequence):
        return self.env['microfinance.social.score.bracket'].search([
            ('category', '=', category), ('company_id', '=', self.env.company.id),
            ('sequence', '=', sequence),
        ], limit=1).id

    def test_consumption_units_formula(self):
        application = self._create_application()
        application.write({'household_size': 4, 'members_over_14': 2, 'members_under_14': 2})
        # 1 (1er adulte) + 0,5 * (2 - 1) + 0,3 * 2 = 1 + 0,5 + 0,6 = 2,1
        self.assertAlmostEqual(application.consumption_units, 2.1, places=2)

    def _bracket_1_vals(self):
        return {
            'assets_bracket_id': self._bracket_id('assets', 1),
            'activity_bracket_id': self._bracket_id('activity', 1),
            'income_bracket_id': self._bracket_id('income', 1),
            'food_bracket_id': self._bracket_id('food', 1),
            'health_bracket_id': self._bracket_id('health', 1),
            'housing_state_bracket_id': self._bracket_id('housing_state', 1),
            # housing_surface non choisi => 0
            'education_borrower_bracket_id': self._bracket_id('education_borrower', 1),
            'education_children_bracket_id': self._bracket_id('education_children', 1),
        }

    def test_total_points_without_any_option(self):
        application = self._create_application()
        application.write(self._bracket_1_vals())
        # Somme des 8 catégories obligatoires uniquement (housing_score = 1 + 0 = 1) :
        # 1+1+1+1+1+1+1+1 = 8, sans la catégorie optionnelle restante (impression).
        self.assertEqual(application.total_points, 8)

    def test_total_points_include_impression_only(self):
        application = self._create_application()
        application.write(self._bracket_1_vals())
        application.surveyor_impression_score = 4
        self.env.company.microfinance_social_grid_include_impression_in_total = True
        self.assertEqual(application.total_points, 12)  # 8 + surveyor_impression_score (4)

    def test_social_level_at_exact_boundaries(self):
        application = self._create_application()
        application.write({
            'assets_bracket_id': self._bracket_id('assets', 2), 'assets_exact_amount': 150000,
            'activity_bracket_id': self._bracket_id('activity', 2),
            'income_bracket_id': self._bracket_id('income', 2), 'income_net_benefit_amount': 80000,
            'food_bracket_id': self._bracket_id('food', 2),
            'health_bracket_id': self._bracket_id('health', 2),
            'housing_state_bracket_id': self._bracket_id('housing_state', 2),
            'housing_surface_bracket_id': self._bracket_id('housing_surface', 2),
            'education_borrower_bracket_id': self._bracket_id('education_borrower', 1),
            'education_children_bracket_id': self._bracket_id('education_children', 1),
        })
        self.assertEqual(application.total_points, 16)
        self.assertEqual(application.social_level_id.name, 'Niv 1')

        application.education_children_bracket_id = self._bracket_id('education_children', 2)
        self.assertEqual(application.total_points, 17)
        self.assertEqual(application.social_level_id.name, 'Niv 2')

    def test_social_level_out_of_bounds_returns_empty_without_error(self):
        application = self._create_application()
        # surveyor_impression_score (seul champ encore librement éditable de la grille — les 8
        # catégories obligatoires sont toutes dérivées d'une tranche et bornées à 0/1-4) sert
        # de valeur hors-limites, via l'option société qui l'inclut dans le total.
        self.env.company.microfinance_social_grid_include_impression_in_total = True
        application.write({'surveyor_impression_score': 40})
        self.assertGreater(application.total_points, 32)
        self.assertFalse(application.social_level_id)

    def test_assets_score_display_updates_with_bracket(self):
        application = self._create_application()
        application.write({
            'assets_bracket_id': self._bracket_id('assets', 2), 'assets_exact_amount': 150000,
        })
        self.assertEqual(application.assets_score, 2)
        self.assertEqual(application.assets_score_display, '2/4')

    def test_food_score_display_updates_with_bracket(self):
        application = self._create_application()
        application.write({'food_bracket_id': self._bracket_id('food', 3)})
        self.assertEqual(application.food_score, 3)
        self.assertEqual(application.food_score_display, '3/4')

    def test_housing_score_display_sums_state_and_surface_brackets(self):
        application = self._create_application()
        application.write({
            'housing_state_bracket_id': self._bracket_id('housing_state', 1),
            'housing_surface_bracket_id': self._bracket_id('housing_surface', 2),
        })
        self.assertEqual(application.housing_state_score, 1)
        self.assertEqual(application.housing_surface_score, 2)
        self.assertEqual(application.housing_score, 3)
        self.assertEqual(application.housing_score_display, '3/4')

    def test_housing_score_state_zero_is_valid(self):
        # sequence 0 ("0. Mauvais état") doit être pris en compte, pas traité comme "pas de
        # tranche choisie" — Many2one vide vs record existant, pas de piège "falsy" ici
        # (contrairement à un Selection stocké en chaîne '0').
        application = self._create_application()
        application.write({
            'housing_state_bracket_id': self._bracket_id('housing_state', 0),
            'housing_surface_bracket_id': self._bracket_id('housing_surface', 1),
        })
        self.assertEqual(application.housing_score, 1)
        self.assertEqual(application.housing_score_display, '1/4')

    def test_education_borrower_score_sequence_zero_is_valid(self):
        application = self._create_application()
        application.write({
            'education_borrower_bracket_id': self._bracket_id('education_borrower', 0),
        })
        self.assertEqual(application.education_borrower_score, 0)
        self.assertEqual(application.education_borrower_score_display, '0/4')


class TestHouseholdSizeConsistency(MicrofinanceCommon):
    """Garde-fou bloquant : household_size doit toujours égaler members_over_14 +
    members_under_14."""

    def _create_application(self):
        return self.env['microfinance.loan.application'].create({
            'partner_id': self.partner.id,
            'company_id': self.env.company.id,
            'loan_product_id': self.product.id,
        })

    def test_inconsistent_sum_raises(self):
        application = self._create_application()
        with self.assertRaises(ValidationError):
            application.write({'household_size': 5, 'members_over_14': 3, 'members_under_14': 4})

    def test_consistent_sum_does_not_raise(self):
        application = self._create_application()
        application.write({'household_size': 5, 'members_over_14': 3, 'members_under_14': 2})
        self.assertEqual(application.household_size, 5)

    def test_default_values_are_consistent(self):
        application = self._create_application()
        self.assertEqual(application.household_size, 0)
        self.assertEqual(application.members_over_14, 0)
        self.assertEqual(application.members_under_14, 0)


class TestAssetsBracketConsistency(MicrofinanceCommon):
    """Garde-fou bloquant : assets_exact_amount doit correspondre à la tranche
    assets_bracket_id sélectionnée, seuils configurables par tranche (microfinance.social.
    score.bracket), pas des champs res.company fixes."""

    def _create_application(self):
        return self.env['microfinance.loan.application'].create({
            'partner_id': self.partner.id,
            'company_id': self.env.company.id,
            'loan_product_id': self.product.id,
        })

    def _bracket_id(self, category, sequence):
        return self.env['microfinance.social.score.bracket'].search([
            ('category', '=', category), ('company_id', '=', self.env.company.id),
            ('sequence', '=', sequence),
        ], limit=1).id

    def test_amount_within_bracket_1_does_not_raise(self):
        application = self._create_application()
        application.write({
            'assets_bracket_id': self._bracket_id('assets', 1), 'assets_exact_amount': 80000,
        })
        self.assertEqual(application.assets_bracket_id.sequence, 1)

    def test_amount_above_bracket_1_raises(self):
        application = self._create_application()
        with self.assertRaises(ValidationError):
            application.write({
                'assets_bracket_id': self._bracket_id('assets', 1), 'assets_exact_amount': 250000,
            })

    def test_amount_within_bracket_3_default_thresholds_does_not_raise(self):
        # Seuils par défaut 100 000 / 200 000 / 300 000 : 250 000 est bien en tranche 3.
        application = self._create_application()
        application.write({
            'assets_bracket_id': self._bracket_id('assets', 3), 'assets_exact_amount': 250000,
        })
        self.assertEqual(application.assets_bracket_id.sequence, 3)

    def test_no_bracket_selected_does_not_raise(self):
        application = self._create_application()
        application.write({'assets_exact_amount': 999999})
        self.assertFalse(application.assets_bracket_id)

    def test_respects_custom_bracket_thresholds(self):
        # Modifier le seuil DE LA TRANCHE elle-même (pas un champ res.company) fait suivre le
        # garde-fou — preuve que la source de vérité est bien la tranche configurable.
        bracket_1 = self.env['microfinance.social.score.bracket'].browse(
            self._bracket_id('assets', 1))
        bracket_1.threshold_amount = 500000
        application = self._create_application()
        application.write({'assets_bracket_id': bracket_1.id, 'assets_exact_amount': 250000})
        self.assertEqual(application.assets_bracket_id.sequence, 1)


class TestIncomeBracketConsistency(MicrofinanceCommon):
    """Garde-fou bloquant : income_net_benefit_amount / consumption_units (par mois et par
    UC, pas le montant BN brut) doit correspondre à la tranche income_bracket_id."""

    def _create_application(self):
        return self.env['microfinance.loan.application'].create({
            'partner_id': self.partner.id,
            'company_id': self.env.company.id,
            'loan_product_id': self.product.id,
        })

    def _bracket_id(self, category, sequence):
        return self.env['microfinance.social.score.bracket'].search([
            ('category', '=', category), ('company_id', '=', self.env.company.id),
            ('sequence', '=', sequence),
        ], limit=1).id

    def test_amount_within_bracket_1_does_not_raise(self):
        application = self._create_application()
        application.write({
            'income_bracket_id': self._bracket_id('income', 1), 'income_net_benefit_amount': 30000,
        })
        self.assertEqual(application.income_bracket_id.sequence, 1)

    def test_amount_above_bracket_1_raises(self):
        application = self._create_application()
        with self.assertRaises(ValidationError):
            application.write({
                'income_bracket_id': self._bracket_id('income', 1),
                'income_net_benefit_amount': 90000,
            })

    def test_no_bracket_selected_does_not_raise(self):
        application = self._create_application()
        application.write({'income_net_benefit_amount': 999999})
        self.assertFalse(application.income_bracket_id)

    def test_amount_per_uc_divides_by_consumption_units(self):
        # members_over_14=2, members_under_14=2 => UC = 1 + 0,5*1 + 0,3*2 = 2,1 ;
        # 168 000 / 2,1 = 80 000 pile (seuil tranche 2 par défaut) : tranche 2 valide,
        # tranche 3 invalide (80 000 n'est pas strictement > 80 000).
        application = self._create_application()
        application.write({
            'household_size': 4, 'members_over_14': 2, 'members_under_14': 2,
            'income_net_benefit_amount': 168000,
        })
        application.write({'income_bracket_id': self._bracket_id('income', 2)})
        self.assertEqual(application.income_bracket_id.sequence, 2)
        with self.assertRaises(ValidationError):
            application.write({'income_bracket_id': self._bracket_id('income', 3)})
