# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import UserError

from .common import MicrofinanceCommon


class TestDisbursementScheduleRecalc(MicrofinanceCommon):
    """Sous-lot B du découplage activation / décaissement (docs_dev/guichet_caisse/
    AUDIT_decaissement.md), mis à jour pour le chantier décaissement provisoire
    (docs_dev/decaissement_provisoire/) : à l'activation l'échéancier est désormais recalé sur
    disbursement_date_planned (plus sur l'ancienne approval_date, potentiellement obsolète) ;
    au décaissement effectif il est de nouveau recalé, cette fois sur disbursement_date."""

    def setUp(self):
        super().setUp()
        # Une base réelle (SEFOR) a un microfinance.fond.credit actif : sans fond_credit_id
        # sur le crédit, action_activate() lève via _check_fond_disponibilite. On neutralise
        # les fonds le temps du test (TransactionCase => rollback), comme test_guichet_backend_lists.
        self.env['microfinance.fond.credit'].sudo().search([('active', '=', True)]).write({'active': False})

    def test_schedule_recalced_on_disbursement_date(self):
        loan = self._approve_loan(loan_amount=1200.0, term=6)

        # Simule un crédit approuvé il y a 40 jours dont l'échéancier a été généré à l'époque
        # (ancré sur l'ancienne approval_date).
        past = fields.Date.today() - relativedelta(days=40)
        loan.approval_date = past
        loan.action_generate_schedule()
        delta = loan._period_delta()  # même relativedelta que _build_installment_commands
        old = loan.installment_ids.sorted('sequence')
        old_first_due = old[0].due_date
        old_total = sum(old.mapped('total_amount'))
        old_principal = sum(old.mapped('principal_amount'))
        self.assertEqual(old_first_due, past + delta)

        # Date provisoire attendue, calculée AVANT activation (pure fonction de
        # repayment_frequency_id + date du jour, cf. _compute_disbursement_date_planned_default) :
        # sert de référence pour vérifier que l'activation recale bien dessus, plus sur
        # l'ancienne approval_date figée dans le passé.
        expected_planned = loan._compute_disbursement_date_planned_default()
        # action_activate() ouvre désormais un wizard de confirmation (chantier décaissement
        # provisoire) - _activate_with_auto_confirm() reste le chemin direct pour les tests.
        loan._activate_with_auto_confirm()
        # Après activation : échéancier recalé sur disbursement_date_planned (chantier
        # décaissement provisoire), plus sur l'ancienne approval_date figée dans le passé.
        self.assertEqual(loan.disbursement_date_planned, expected_planned)
        self.assertEqual(loan.installment_ids.sorted('sequence')[0].due_date, expected_planned + delta)
        self.assertNotEqual(loan.installment_ids.sorted('sequence')[0].due_date, old_first_due)
        self.assertFalse(loan.disbursement_date)

        loan.action_process_disbursement()

        new = loan.installment_ids.sorted('sequence')
        self.assertEqual(loan.disbursement_date, fields.Date.today())
        self.assertEqual(len(new), 6)
        # Recalé sur la date de décaissement, plus sur l'ancienne approval_date.
        self.assertEqual(new[0].due_date, fields.Date.today() + delta)
        self.assertNotEqual(new[0].due_date, old_first_due)
        # Montants inchangés : le total dû et le capital ne dépendent pas de la date de départ.
        self.assertAlmostEqual(sum(new.mapped('principal_amount')), old_principal, places=2)
        self.assertAlmostEqual(sum(new.mapped('principal_amount')), 1200.0, places=2)
        self.assertAlmostEqual(sum(new.mapped('total_amount')), old_total, places=2)

    def test_schedule_stable_when_disbursed_same_day_as_activation(self):
        loan = self._approve_loan(loan_amount=1200.0, term=6)
        before = [
            (i.sequence, i.due_date, round(i.principal_amount, 2), round(i.interest_amount, 2))
            for i in loan.installment_ids.sorted('sequence')
        ]

        # action_activate() ouvre désormais un wizard de confirmation (chantier décaissement
        # provisoire) - _activate_with_auto_confirm() reste le chemin direct pour les tests.
        loan._activate_with_auto_confirm()
        loan.action_process_disbursement()

        after = [
            (i.sequence, i.due_date, round(i.principal_amount, 2), round(i.interest_amount, 2))
            for i in loan.installment_ids.sorted('sequence')
        ]
        # disbursement_date == approval_date == aujourd'hui : régénération = no-op fonctionnel,
        # aucune ligne perdue ni dupliquée.
        self.assertEqual(len(after), 6)
        self.assertEqual(before, after)

    def test_recalc_blocked_when_repayment_already_imputed(self):
        loan = self._activate_loan_without_disbursement(loan_amount=1200.0, term=6)
        loan.installment_ids.sorted('sequence')[0].paid_principal = 10.0
        with self.assertRaises(UserError):
            loan._regenerate_schedule_from_disbursement()
