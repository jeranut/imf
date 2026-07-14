# -*- coding: utf-8 -*-
from .common import MicrofinanceCommon


class TestRepaymentAllocation(MicrofinanceCommon):
    """Ventilation CEFOR d'un remboursement (Décision 2, _allocate_to_installments) : ordre fixe
    intérêt dû -> principal dû -> pénalités, sur la tranche courante ; débordement sur la ou les
    tranches suivantes (même ordre) si le montant payé dépasse le total dû de la tranche
    courante ; couverture partielle (intérêt en premier) si le montant est insuffisant."""

    def _make_payment(self, loan, amount):
        payment = self.env['microfinance.loan.payment'].create({
            'loan_id': loan.id,
            'amount': amount,
            'journal_id': self.payment_journal.id,
        })
        payment.action_post()
        return payment

    def test_exact_payment_clears_installment(self):
        loan = self._activate_loan(loan_amount=900.0, term=3)
        first = loan.installment_ids.sorted('sequence')[0]
        first.write({'principal_amount': 100.0, 'interest_amount': 20.0, 'penalty_amount': 10.0})
        payment = self._make_payment(loan, first.total_amount)

        self.assertAlmostEqual(first.paid_interest, 20.0, places=2)
        self.assertAlmostEqual(first.paid_principal, 100.0, places=2)
        self.assertAlmostEqual(first.paid_penalty, 10.0, places=2)
        self.assertEqual(first.state, 'paid')
        self.assertAlmostEqual(payment.allocated_interest, 20.0, places=2)
        self.assertAlmostEqual(payment.allocated_principal, 100.0, places=2)
        self.assertAlmostEqual(payment.allocated_penalty, 10.0, places=2)

    def test_partial_payment_covers_interest_then_principal_before_penalty(self):
        loan = self._activate_loan(loan_amount=900.0, term=3)
        first = loan.installment_ids.sorted('sequence')[0]
        first.write({'principal_amount': 100.0, 'interest_amount': 30.0, 'penalty_amount': 20.0})
        # 40 = intérêt (30) intégralement + 10 de principal ; rien pour la pénalité.
        payment = self._make_payment(loan, 40.0)

        self.assertAlmostEqual(first.paid_interest, 30.0, places=2)
        self.assertAlmostEqual(first.paid_principal, 10.0, places=2)
        self.assertAlmostEqual(first.paid_penalty, 0.0, places=2)
        self.assertEqual(first.state, 'partial')
        self.assertAlmostEqual(payment.allocated_interest, 30.0, places=2)
        self.assertAlmostEqual(payment.allocated_principal, 10.0, places=2)
        self.assertAlmostEqual(payment.allocated_penalty, 0.0, places=2)

    def test_insufficient_payment_covers_interest_only(self):
        loan = self._activate_loan(loan_amount=900.0, term=3)
        first = loan.installment_ids.sorted('sequence')[0]
        first.write({'principal_amount': 100.0, 'interest_amount': 30.0, 'penalty_amount': 20.0})
        # 25 < intérêt dû (30) : rien ne doit atteindre le principal ni la pénalité.
        payment = self._make_payment(loan, 25.0)

        self.assertAlmostEqual(first.paid_interest, 25.0, places=2)
        self.assertAlmostEqual(first.paid_principal, 0.0, places=2)
        self.assertAlmostEqual(first.paid_penalty, 0.0, places=2)

    def test_surplus_payment_overflows_to_next_installment_same_priority(self):
        loan = self._activate_loan(loan_amount=900.0, term=3)
        first, second = loan.installment_ids.sorted('sequence')[:2]
        first.write({'principal_amount': 100.0, 'interest_amount': 20.0, 'penalty_amount': 0.0})
        second.write({'principal_amount': 200.0, 'interest_amount': 30.0, 'penalty_amount': 0.0})
        # 150 = tranche 1 intégrale (120) + 30 de surplus, qui doit s'imputer sur l'intérêt de la
        # tranche 2 en premier (30 = exactement son intérêt dû), rien sur son principal.
        payment = self._make_payment(loan, 150.0)

        self.assertEqual(first.state, 'paid')
        self.assertAlmostEqual(first.paid_interest, 20.0, places=2)
        self.assertAlmostEqual(first.paid_principal, 100.0, places=2)

        self.assertAlmostEqual(second.paid_interest, 30.0, places=2)
        self.assertAlmostEqual(second.paid_principal, 0.0, places=2)
        self.assertEqual(second.state, 'partial')

        self.assertAlmostEqual(payment.allocated_interest, 50.0, places=2)
        self.assertAlmostEqual(payment.allocated_principal, 100.0, places=2)
        self.assertAlmostEqual(payment.allocated_penalty, 0.0, places=2)
