# -*- coding: utf-8 -*-
from odoo import fields

from .common import MicrofinanceCommon


class TestScoring(MicrofinanceCommon):
    """The former hardcoded _compute_risk_score() has been retired: a single unified score
    (internal_score) is now produced by the configurable microfinance.scoring.profile/rule
    engine, seeded with default rules reproducing the old weights."""

    def test_default_profile_and_rules_are_loaded(self):
        profile = self.env.ref('microfinance_loan_management.scoring_profile_default')
        self.assertTrue(profile.active)
        self.assertEqual(len(profile.rule_ids), 5)
        linear_rules = profile.rule_ids.filtered(lambda rule: rule.computation == 'linear')
        self.assertEqual(len(linear_rules), 4)

    def test_editing_a_scoring_rule_changes_the_score_on_an_existing_loan(self):
        loan = self._activate_loan(loan_amount=1000.0, term=4)
        overdue_installment = loan.installment_ids.sorted('sequence')[0]
        overdue_installment.due_date = fields.Date.subtract(fields.Date.context_today(loan), days=10)

        loan.action_calculate_scoring()
        score_before = loan.internal_score
        self.assertGreater(loan.overdue_installment_count, 0)
        self.assertLess(score_before, 100.0)

        rule = self.env.ref('microfinance_loan_management.scoring_rule_default_overdue_installments')
        rule.points = rule.points * 2

        loan.action_calculate_scoring()
        score_after = loan.internal_score
        self.assertLess(score_after, score_before)

    def test_single_score_field_exposed_no_duplicate(self):
        loan = self._activate_loan()
        self.assertFalse(hasattr(type(loan), 'risk_score'))
        self.assertIn('internal_score', loan._fields)
