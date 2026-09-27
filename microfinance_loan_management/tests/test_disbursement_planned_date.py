# -*- coding: utf-8 -*-
from datetime import date
from unittest.mock import patch

from dateutil.relativedelta import relativedelta

from odoo import fields

from .common import MicrofinanceCommon


class TestDisbursementPlannedDate(MicrofinanceCommon):
    """Chantier décaissement provisoire (docs_dev/decaissement_provisoire/) : disbursement_
    date_planned est calculée à l'activation à partir de repayment_frequency_id, ajustée hors
    weekend, et ne doit JAMAIS modifier la logique de calcul des montants/arrondis de
    _build_installment_commands() (ligne 2005) ni de _period_delta() (ligne 1696) - seule la
    date de départ passée à ces méthodes change."""

    def setUp(self):
        super().setUp()
        # Même neutralisation que test_disbursement_schedule_recalc.py : une base réelle
        # (SEFOR) a un microfinance.fond.credit actif, ce qui ferait échouer
        # _check_activation_eligibility() (_check_fond_disponibilite) sans fond_credit_id sur
        # le crédit - hors sujet pour ces tests, qui ne portent que sur le calcul de date.
        self.env['microfinance.fond.credit'].sudo().search([('active', '=', True)]).write({'active': False})

    def test_weekly_planned_date_is_activation_wednesday_plus_one_week(self):
        """Crédit hebdomadaire activé un mercredi : disbursement_date_planned tombe au
        mercredi + 7 jours (mercredi + une semaine reste un mercredi, jamais un weekend -
        aucun report nécessaire dans ce cas précis)."""
        wednesday = date(2026, 1, 7)
        self.assertEqual(wednesday.weekday(), 2)  # 0=lundi ... 2=mercredi (garde-fou du test)
        loan = self._approve_loan(
            loan_amount=1200.0, term=6,
            repayment_frequency_id=self.env.ref(
                'microfinance_loan_management.repayment_frequency_weekly').id,
        )
        with patch.object(fields.Date, 'context_today', return_value=wednesday):
            # action_activate() ouvre désormais un wizard de confirmation - le calcul de la
            # date par défaut est testé ici via _activate_with_auto_confirm() (chemin direct),
            # qui l'invoque exactement de la même façon qu'action_activate().
            loan._activate_with_auto_confirm()
        self.assertEqual(loan.disbursement_date_planned, date(2026, 1, 14))
        self.assertEqual(loan.disbursement_date_planned.weekday(), 2)

    def test_planned_date_pushed_to_monday_when_falling_on_saturday(self):
        """Périodicité quotidienne (period_kind=days, period_value=1) activée un vendredi :
        vendredi + 1 jour tombe un samedi, reporté au lundi suivant (+2 jours) - vérifie
        l'ajustement week-end indépendamment du calcul d'échéancier lui-même."""
        friday = date(2026, 1, 2)
        self.assertEqual(friday.weekday(), 4)  # vendredi
        # term=35 (>= 30 jours) : le produit de test exige une durée d'au moins 1 mois
        # (min_term=1, cf. common.py) - _actual_duration_months() approxime le mois à 30 jours.
        loan = self._approve_loan(
            loan_amount=1200.0, term=35,
            repayment_frequency_id=self.env.ref(
                'microfinance_loan_management.repayment_frequency_daily').id,
        )
        with patch.object(fields.Date, 'context_today', return_value=friday):
            loan._activate_with_auto_confirm()
        self.assertEqual(loan.disbursement_date_planned, date(2026, 1, 5))
        self.assertEqual(loan.disbursement_date_planned.weekday(), 0)  # lundi

    def test_planned_date_pushed_to_monday_when_falling_on_sunday(self):
        """Périodicité de 2 jours (produit ad hoc, non exposée en data démo) activée un
        vendredi : vendredi + 2 jours tombe un dimanche, reporté au lundi suivant (+1 jour)."""
        friday = date(2026, 1, 2)
        two_days_freq = self.env['microfinance.repayment.frequency'].create({
            'name': 'Test 2 jours', 'code': 'test_two_days',
            'period_kind': 'days', 'period_value': 2, 'periods_per_year': 182,
        })
        # term=20 (>= 15 x 2 jours = 30 jours) : même contrainte min_term=1 que ci-dessus.
        loan = self._approve_loan(
            loan_amount=1200.0, term=20, repayment_frequency_id=two_days_freq.id)
        with patch.object(fields.Date, 'context_today', return_value=friday):
            loan._activate_with_auto_confirm()
        self.assertEqual(loan.disbursement_date_planned, date(2026, 1, 5))
        self.assertEqual(loan.disbursement_date_planned.weekday(), 0)  # lundi

    def test_action_activate_does_not_overwrite_already_confirmed_planned_date(self):
        """_compute_disbursement_date_planned_default() ne doit jamais écraser une date déjà
        confirmée (disbursement_date_confirmed == True) - action_activate() (bouton fiche,
        appelable plusieurs fois avant confirmation effective du wizard) ne doit pas non plus
        y toucher une fois la confirmation actée."""
        loan = self._approve_loan(loan_amount=1200.0, term=6)
        custom_date = fields.Date.context_today(loan) + relativedelta(days=3)
        loan.write({
            'disbursement_date_planned': custom_date,
            'disbursement_date_confirmed': True,
        })
        loan.action_activate()
        self.assertEqual(loan.disbursement_date_planned, custom_date)

    def test_build_installment_commands_amounts_unaffected_by_planned_date(self):
        """Non-régression stricte (avertissement critique du chantier décaissement
        provisoire) : _build_installment_commands() doit produire EXACTEMENT les mêmes
        principal_amount/interest_amount, que disbursement_date_planned soit vide (ancien
        comportement, ancré sur approval_date) ou renseignée (nouveau maillon de la chaîne de
        repli) - seule due_date doit changer. Preuve que l'insertion de ce maillon n'a touché
        ni _build_installment_commands() ni _period_delta() dans leur logique de calcul."""
        loan = self._approve_loan(loan_amount=1200.0, term=6)
        commands_without_planned = loan._build_installment_commands(raise_on_negative_reliquat=True)
        self.assertTrue(commands_without_planned)

        other_date = fields.Date.context_today(loan) + relativedelta(days=17)
        loan.disbursement_date_planned = other_date
        commands_with_planned = loan._build_installment_commands(raise_on_negative_reliquat=True)

        self.assertEqual(len(commands_without_planned), len(commands_with_planned))
        for (_op1, _id1, vals1), (_op2, _id2, vals2) in zip(
                commands_without_planned, commands_with_planned):
            self.assertAlmostEqual(vals1['principal_amount'], vals2['principal_amount'], places=6)
            self.assertAlmostEqual(vals1['interest_amount'], vals2['interest_amount'], places=6)
            self.assertNotEqual(vals1['due_date'], vals2['due_date'])
