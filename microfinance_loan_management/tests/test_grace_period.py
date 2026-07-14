# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import fields

from .common import MicrofinanceCommon


class TestGracePeriod(MicrofinanceCommon):

    def test_schedule_without_grace_period(self):
        loan = self._create_loan(term=3)
        loan.action_generate_schedule()
        start = loan.application_date
        first = loan.installment_ids.sorted('sequence')[0]
        self.assertEqual(first.due_date, start + relativedelta(months=1))
        self.assertEqual(len(loan.installment_ids), 3)

    def test_first_installment_after_short_grace_period(self):
        self.product.grace_period_days = 10
        # Arrondi de la cible (installment_rounding_unit) désactivé : ce test porte sur la forme
        # interest-first elle-même, pas sur l'arrondi (couvert séparément par
        # test_interest_first_schedule.py), pour ne pas coupler les deux comportements.
        self.product.installment_rounding_unit = 0
        loan = self._create_loan(term=3)
        loan.action_generate_schedule()
        start = loan.application_date
        installments = loan.installment_ids.sorted('sequence')
        first = installments[0]
        self.assertGreater(first.due_date, fields.Date.add(start, days=10) - relativedelta(days=1))
        self.assertEqual(first.due_date, fields.Date.add(start, days=10) + relativedelta(months=1))
        # Grace period shorter than one repayment period: no dedicated interest bucket.
        self.assertEqual(len(installments), 3)
        # Interest-first (Lot "moteur de remboursement CEFOR") : la 1ere tranche n'a plus un
        # principal purement lineaire (loan_amount/term) - elle absorbe d'abord sa part
        # d'interet cible, le principal ne comble que le reste.
        total_interest = loan.loan_amount * (loan.interest_rate / 100.0) * (1 / 12.0) * loan.term
        installment_target = (loan.loan_amount + total_interest) / loan.term
        expected_first_interest = min(total_interest, installment_target)
        self.assertAlmostEqual(first.principal_amount, installment_target - expected_first_interest, places=2)

    def test_grace_period_longer_than_period_creates_dedicated_installment(self):
        self.product.grace_period_days = 45
        # Cf. commentaire du test précédent : arrondi désactivé, test focalisé sur la forme
        # interest-first, pas sur l'arrondi.
        self.product.installment_rounding_unit = 0
        loan = self._create_loan(term=3)
        loan.action_generate_schedule()
        start = loan.application_date
        installments = loan.installment_ids.sorted('sequence')
        # An extra installment captures the interest accrued during the grace period.
        self.assertEqual(len(installments), 4)
        grace_installment = installments[0]
        self.assertEqual(grace_installment.principal_amount, 0.0)
        self.assertGreater(grace_installment.interest_amount, 0.0)
        schedule_start = fields.Date.add(start, days=45)
        self.assertEqual(grace_installment.due_date, schedule_start)
        first_normal = installments[1]
        self.assertEqual(first_normal.due_date, schedule_start + relativedelta(months=1))
        self.assertGreater(first_normal.due_date, start + relativedelta(days=45))
        # Interest-first : la 1ere tranche "normale" (hors tranche dediee au delai de grace,
        # calculee separement) cible elle aussi le montant total (loan_amount + interet total) /
        # term, avec l'interet du credit consomme en priorite - plus un principal purement
        # lineaire loan_amount/term.
        total_interest = loan.loan_amount * (loan.interest_rate / 100.0) * (1 / 12.0) * loan.term
        installment_target = (loan.loan_amount + total_interest) / loan.term
        expected_interest = min(total_interest, installment_target)
        self.assertAlmostEqual(first_normal.principal_amount, installment_target - expected_interest, places=2)
