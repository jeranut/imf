# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo.exceptions import UserError, ValidationError

from .common import MicrofinanceCommon


class TestPeriodicities(MicrofinanceCommon):

    def _schedule_for(self, frequency, **kwargs):
        self.product.repayment_frequency_id = self.env.ref(
            'microfinance_loan_management.repayment_frequency_%s' % frequency
        ).id
        # Arrondi de la cible (installment_rounding_unit) désactivé : ces tests portent sur les
        # dates/l'interest-first par périodicité, pas sur l'arrondi (couvert séparément par
        # test_interest_first_schedule.py), pour ne pas coupler les deux comportements.
        self.product.installment_rounding_unit = 0
        loan = self._create_loan(**kwargs)
        loan.action_generate_schedule()
        return loan.installment_ids.sorted('sequence')

    def test_biweekly_schedule_dates(self):
        installments = self._schedule_for('biweekly', term=3)
        start = installments[0].loan_id.application_date
        for idx, inst in enumerate(installments, start=1):
            self.assertEqual(inst.due_date, start + relativedelta(days=15 * idx))

    def test_four_weekly_schedule_dates(self):
        installments = self._schedule_for('four_weekly', term=3)
        start = installments[0].loan_id.application_date
        for idx, inst in enumerate(installments, start=1):
            self.assertEqual(inst.due_date, start + relativedelta(days=28 * idx))

    def test_bimonthly_schedule_dates(self):
        installments = self._schedule_for('bimonthly', term=3)
        start = installments[0].loan_id.application_date
        for idx, inst in enumerate(installments, start=1):
            self.assertEqual(inst.due_date, start + relativedelta(months=2 * idx))

    def test_four_monthly_schedule_dates(self):
        installments = self._schedule_for('four_monthly', term=3)
        start = installments[0].loan_id.application_date
        for idx, inst in enumerate(installments, start=1):
            self.assertEqual(inst.due_date, start + relativedelta(months=4 * idx))

    def test_quarterly_schedule_dates_and_interest(self):
        installments = self._schedule_for('quarterly', term=4, loan_amount=1200.0)
        start = installments[0].loan_id.application_date
        for idx, inst in enumerate(installments, start=1):
            self.assertEqual(inst.due_date, start + relativedelta(months=3 * idx))
        # Interest-first (politique CEFOR) : intérêt total (taux uniforme, prorata trimestriel)
        # consommé en priorité - ici il tient entièrement dans la 1ère tranche (144 < cible 336),
        # les tranches suivantes n'ont donc plus d'intérêt du tout (à l'opposé de l'ancien partage
        # linéaire identique sur les 4 tranches).
        total_interest = 1200.0 * 0.12 * (3 / 12.0) * 4
        installment_target = (1200.0 + total_interest) / 4
        self.assertAlmostEqual(installments[0].interest_amount, total_interest, places=2)
        self.assertAlmostEqual(installments[0].principal_amount, installment_target - total_interest, places=2)
        for inst in installments[1:]:
            self.assertAlmostEqual(inst.interest_amount, 0.0, places=2)

    def test_semiannual_schedule_dates_and_interest(self):
        installments = self._schedule_for('semiannual', term=2, loan_amount=1200.0)
        start = installments[0].loan_id.application_date
        for idx, inst in enumerate(installments, start=1):
            self.assertEqual(inst.due_date, start + relativedelta(months=6 * idx))
        # Idem : l'intérêt total (144) tient dans la cible de la 1ère tranche (672), donc
        # entièrement absorbé dès la 1ère échéance.
        total_interest = 1200.0 * 0.12 * (6 / 12.0) * 2
        installment_target = (1200.0 + total_interest) / 2
        self.assertAlmostEqual(installments[0].interest_amount, total_interest, places=2)
        self.assertAlmostEqual(installments[0].principal_amount, installment_target - total_interest, places=2)
        self.assertAlmostEqual(installments[1].interest_amount, 0.0, places=2)

    def test_annual_schedule_dates_and_interest(self):
        installments = self._schedule_for('annual', term=2, loan_amount=1000.0)
        start = installments[0].loan_id.application_date
        for idx, inst in enumerate(installments, start=1):
            self.assertEqual(inst.due_date, start + relativedelta(years=idx))
        # A full year at the 12% annual rate: no proration needed. Intérêt total (240) absorbé
        # entièrement par la 1ère tranche (cible 620) - interest-first, pas de partage linéaire.
        total_interest = 1000.0 * 0.12 * 2
        installment_target = (1000.0 + total_interest) / 2
        self.assertAlmostEqual(installments[0].interest_amount, total_interest, places=2)
        self.assertAlmostEqual(installments[0].principal_amount, installment_target - total_interest, places=2)
        self.assertAlmostEqual(installments[1].interest_amount, 0.0, places=2)

    def test_reducing_balance_quarterly_declines(self):
        self.product.interest_method = 'reducing'
        installments = self._schedule_for('quarterly', term=3, loan_amount=900.0)
        # Reducing balance: interest computed on the declining principal, strictly decreasing.
        amounts = installments.mapped('interest_amount')
        self.assertGreater(amounts[0], amounts[1])
        self.assertGreater(amounts[1], amounts[2])

    def test_fixed_product_generates_schedule_without_agent_choice(self):
        # Produit en mode 'fixed' (comportement par défaut du produit commun de test) : le crédit
        # reprend automatiquement la périodicité du produit, aucune saisie de l'agent nécessaire.
        loan = self._create_loan()
        self.assertEqual(loan.repayment_frequency_id, self.env.ref('microfinance_loan_management.repayment_frequency_monthly'))
        loan.action_generate_schedule()
        self.assertTrue(loan.installment_ids)

    def test_client_choice_product_requires_explicit_frequency(self):
        weekly = self.env.ref('microfinance_loan_management.repayment_frequency_weekly')
        monthly = self.env.ref('microfinance_loan_management.repayment_frequency_monthly')
        self.product.write({
            'repayment_frequency_mode': 'client_choice',
            'allowed_repayment_frequency_ids': [(6, 0, (weekly | monthly).ids)],
        })
        loan = self._create_loan()
        self.assertFalse(loan.repayment_frequency_id)
        with self.assertRaises(UserError):
            loan.action_generate_schedule()

        loan.repayment_frequency_id = weekly.id
        loan.action_generate_schedule()
        self.assertTrue(loan.installment_ids)

    def test_client_choice_rejects_frequency_outside_allowed_list(self):
        weekly = self.env.ref('microfinance_loan_management.repayment_frequency_weekly')
        monthly = self.env.ref('microfinance_loan_management.repayment_frequency_monthly')
        annual = self.env.ref('microfinance_loan_management.repayment_frequency_annual')
        self.product.write({
            'repayment_frequency_mode': 'client_choice',
            'allowed_repayment_frequency_ids': [(6, 0, (weekly | monthly).ids)],
        })
        loan = self._create_loan()
        with self.assertRaises(ValidationError):
            loan.repayment_frequency_id = annual.id

    def test_product_fixed_mode_requires_frequency(self):
        with self.assertRaises(ValidationError):
            self.product.write({'repayment_frequency_mode': 'fixed', 'repayment_frequency_id': False})

    def test_product_client_choice_requires_at_least_one_allowed(self):
        with self.assertRaises(ValidationError):
            self.product.write({
                'repayment_frequency_mode': 'client_choice',
                'allowed_repayment_frequency_ids': [(5, 0, 0)],
            })
