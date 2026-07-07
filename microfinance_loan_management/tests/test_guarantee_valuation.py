# -*- coding: utf-8 -*-
from odoo.exceptions import UserError, ValidationError

from .common import MicrofinanceCommon


class TestGuaranteeValuation(MicrofinanceCommon):

    def test_valuation_ratio_over_cap_raises(self):
        with self.assertRaises(ValidationError):
            self.env['microfinance.guarantee.valuation.rule'].create({
                'guarantee_type': 'land',
                'valuation_ratio': 200.0,
                'max_ratio': 150.0,
            })

    def test_recognized_value_uses_configured_ratio_by_type(self):
        self.env['microfinance.guarantee.valuation.rule'].create({
            'guarantee_type': 'vehicle',
            'valuation_ratio': 60.0,
            'max_ratio': 100.0,
        })
        loan = self._create_loan()
        guarantee = self.env['microfinance.loan.guarantee'].create({
            'loan_id': loan.id,
            'guarantee_type': 'vehicle',
            'description': 'Véhicule',
            'estimated_value': 1000.0,
        })
        self.assertAlmostEqual(guarantee.recognized_value, 600.0, places=2)

    def test_recognized_value_defaults_to_full_value_without_rule(self):
        loan = self._create_loan()
        guarantee = self.env['microfinance.loan.guarantee'].create({
            'loan_id': loan.id,
            'guarantee_type': 'furniture',
            'description': 'Mobilier sans règle configurée',
            'estimated_value': 500.0,
        })
        self.assertAlmostEqual(guarantee.recognized_value, 500.0, places=2)

    def test_guarantee_total_and_eligibility_use_recognized_value_not_raw(self):
        # Raw estimated_value (1000) alone would (wrongly) clear the 50% ratio requirement on a
        # 1000 loan, but the recognized value (40% of it, i.e. 400) must not.
        self.env['microfinance.guarantee.valuation.rule'].create({
            'guarantee_type': 'land',
            'valuation_ratio': 40.0,
            'max_ratio': 100.0,
        })
        self.product.min_guarantee_ratio = 50.0
        loan = self._create_loan(loan_amount=1000.0)
        self.env['microfinance.loan.guarantee'].create({
            'loan_id': loan.id,
            'guarantee_type': 'land',
            'description': 'Terrain décoté à 40%',
            'estimated_value': 1000.0,
            'state': 'validated',
        })
        self.assertAlmostEqual(loan.guarantee_total, 400.0, places=2)
        with self.assertRaises(UserError):
            loan.action_submit()
