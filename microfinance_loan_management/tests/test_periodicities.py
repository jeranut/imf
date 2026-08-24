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


class TestProductDurationLimits(MicrofinanceCommon):
    """_check_product_limits compare la durée réelle en mois (_actual_duration_months),
    pas le nombre brut d'échéances - un produit multi-périodicité (type PRET RURAL) doit
    accepter un term élevé si la périodicité choisie donne une durée réelle dans les bornes
    min_term/max_term du produit (exprimées en mois, quelle que soit la périodicité)."""

    def setUp(self):
        super().setUp()
        self.weekly = self.env.ref('microfinance_loan_management.repayment_frequency_weekly')
        self.monthly = self.env.ref('microfinance_loan_management.repayment_frequency_monthly')
        self.product.max_term = 12
        self.product.write({
            'repayment_frequency_mode': 'client_choice',
            'allowed_repayment_frequency_ids': [(6, 0, (self.weekly | self.monthly).ids)],
        })

    def test_monthly_term_within_bounds_still_passes(self):
        loan = self._create_loan(term=6, repayment_frequency_id=self.monthly.id)
        self.assertEqual(loan.term, 6)

    def test_weekly_term_24_within_real_duration_no_longer_raises(self):
        # 24 échéances hebdomadaires ~= 5,6 mois réels (24 x 7 / 30), dans les bornes [1, 12]
        # du produit - ne doit plus lever d'erreur (bug d'origine : 24 > 12 comparé brut à
        # tort, sans conversion de périodicité).
        loan = self._create_loan(term=24, repayment_frequency_id=self.weekly.id)
        self.assertEqual(loan.term, 24)
        self.assertAlmostEqual(loan._actual_duration_months(), 5.6, places=2)

    def test_weekly_term_60_exceeds_real_duration_still_raises(self):
        # 60 échéances hebdomadaires ~= 14 mois réels, dépasse max_term=12 - la borne max doit
        # continuer à fonctionner une fois convertie correctement.
        with self.assertRaises(ValidationError):
            self._create_loan(term=60, repayment_frequency_id=self.weekly.id)

    def test_no_frequency_chosen_does_not_block(self):
        # Produit client_choice, périodicité pas encore choisie : ne pas bloquer sur la durée
        # tant qu'on ne peut pas la convertir - le contrôle se refait automatiquement dès que
        # la périodicité est choisie (repayment_frequency_id dans @api.constrains).
        loan = self._create_loan(term=999)
        self.assertFalse(loan.repayment_frequency_id)
        self.assertEqual(loan.term, 999)

    def test_constraint_retriggers_when_frequency_changed_afterwards(self):
        # repayment_frequency_id doit bien être surveillé par @api.constrains : choisir une
        # périodicité sur un crédit existant (pas seulement à la création) doit redéclencher
        # la vérification.
        loan = self._create_loan(term=60)
        self.assertFalse(loan.repayment_frequency_id)
        with self.assertRaises(ValidationError):
            loan.repayment_frequency_id = self.weekly.id

    def test_term_update_respects_actual_duration_not_raw_count(self):
        """Reproduit le scénario exact du bug IS/000289 : un produit multi-périodicité
        (min_term=1, max_term=12 mois) doit accepter un changement de term vers 24 échéances
        hebdomadaires (~5,6 mois réels), alors que 24 > 12 en brut aurait échoué avec
        l'ancienne contrainte - et l'échéancier regénéré doit bien refléter la nouvelle
        valeur (24 lignes), pas l'ancienne (8 lignes) restée en base suite à un write()
        silencieusement rejeté."""
        loan = self._create_loan(term=8, repayment_frequency_id=self.weekly.id)
        loan.action_generate_schedule()
        self.assertEqual(len(loan.installment_ids), 8)

        loan.write({'term': 24})  # ne doit PAS lever de ValidationError
        self.assertEqual(loan.term, 24)

        loan.action_generate_schedule()
        self.assertEqual(len(loan.installment_ids), 24)


class TestLpfInterestFactorAlignment(MicrofinanceCommon):
    """Alignement LPF (décision 2026-08-18) : _period_interest_factor utilise
    periods_per_year (fraction fixe conventionnelle), pas period_value / 365 (jours
    calendaires réels), pour les périodicités infra-mensuelles."""

    def test_period_interest_factor_weekly_uses_fixed_52_not_calendar_days(self):
        """Aligné sur LPF (décision 2026-08-18) : 1/52, pas 7/365."""
        loan = self._create_loan(
            term=24,
            repayment_frequency_id=self.env.ref('microfinance_loan_management.repayment_frequency_weekly').id,
        )
        self.assertAlmostEqual(loan._period_interest_factor(), 1.0 / 52.0, places=6)

    def test_period_interest_factor_daily_uses_fixed_365(self):
        # term=35 (pas 10) : le produit de test par défaut a min_term=1 mois -
        # _actual_duration_months() exige donc au moins ~30 jours (cf. correctif précédent
        # sur _check_product_limits, sujet distinct de celui-ci).
        loan = self._create_loan(
            term=35,
            repayment_frequency_id=self.env.ref('microfinance_loan_management.repayment_frequency_daily').id,
        )
        self.assertAlmostEqual(loan._period_interest_factor(), 1.0 / 365.0, places=6)

    def test_period_interest_factor_biweekly_uses_fixed_26_not_calendar_days(self):
        # period_value = 15 jours (quinzaine) -> calendaire aurait donné 15/365 ≈ 0,04110,
        # LPF impose 1/26 ≈ 0,03846 (convention 26 quinzaines/an, pas 365/15 ≈ 24,3).
        loan = self._create_loan(
            term=10,
            repayment_frequency_id=self.env.ref('microfinance_loan_management.repayment_frequency_biweekly').id,
        )
        self.assertAlmostEqual(loan._period_interest_factor(), 1.0 / 26.0, places=6)

    def test_period_interest_factor_monthly_unchanged(self):
        """Les périodicités mensuelles et au-delà ne doivent pas changer de comportement
        (12/period_value == periods_per_year pour ces fréquences, cf. Étape 2 du prompt)."""
        loan = self._create_loan(
            term=12,
            repayment_frequency_id=self.env.ref('microfinance_loan_management.repayment_frequency_monthly').id,
        )
        self.assertAlmostEqual(loan._period_interest_factor(), 1.0 / 12.0, places=6)

    def test_period_interest_factor_quarterly_unchanged(self):
        loan = self._create_loan(
            term=4,
            repayment_frequency_id=self.env.ref('microfinance_loan_management.repayment_frequency_quarterly').id,
        )
        self.assertAlmostEqual(loan._period_interest_factor(), 1.0 / 4.0, places=6)

    def test_total_interest_matches_lpf_convention_on_reference_example(self):
        """Reproduit l'exemple comparatif réel : 500.000 Ar, 36%/an, 24 échéances hebdo.
        Vérifie que l'intérêt total généré correspond à la formule LPF (taux x term/52),
        pas à l'ancienne formule calendaire (taux x term x 7/365)."""
        self.product.interest_rate = 36.0
        self.product.max_amount = 1000000.0
        loan = self._create_loan(
            loan_amount=500000.0, term=24,
            repayment_frequency_id=self.env.ref('microfinance_loan_management.repayment_frequency_weekly').id,
        )
        loan.action_generate_schedule()
        total_interest = sum(loan.installment_ids.mapped('interest_amount'))
        expected_interest_lpf = 500000.0 * 0.36 * (24 / 52.0)
        old_calendar_interest = 500000.0 * 0.36 * (24 * 7 / 365.0)
        self.assertAlmostEqual(total_interest, expected_interest_lpf, delta=1.0)
        self.assertNotAlmostEqual(total_interest, old_calendar_interest, delta=1.0)
