# -*- coding: utf-8 -*-
from odoo import fields

from .common import MicrofinanceCommon


class GuichetBackendListsCommon(MicrofinanceCommon):
    """Lot 1.2 (guichet caisse) : méthodes de liste
    microfinance.loan.get_pending_disbursements(company_id) et
    microfinance.loan.installment.get_pending_or_late(company_id)."""

    def _neutralize_funds(self):
        # SEFOR (et toute base réelle) a un microfinance.fond.credit actif : sans
        # fond_credit_id, action_disburse() lève « Un fonds de crédit rotatif actif existe
        # pour cette agence ». TransactionCase => rollback, aucune donnée réelle touchée.
        self.env['microfinance.fond.credit'].sudo().search([('active', '=', True)]).write({'active': False})

    def _approve_loan(self, **kwargs):
        """Crédit mené jusqu'à state == 'approved' (sans décaissement)."""
        loan = self._create_loan(**kwargs)
        loan.action_generate_schedule()
        loan.action_start_enquete()
        loan.action_ca_review()
        loan.action_cdag_review()
        loan.action_view_applications()
        loan.application_ids.write({'committee_first_decision': 'accepted'})
        loan.action_approve()
        return loan


class TestGetPendingDisbursements(GuichetBackendListsCommon):
    # Assertions par appartenance (assertIn / assertNotIn) et non par égalité stricte de
    # liste : la base peut déjà contenir des crédits réels (cas SEFOR).
    #
    # Depuis le découplage activation / décaissement (docs_dev/guichet_caisse/
    # AUDIT_decaissement.md, sous-lot F), la file cible state == 'active' ET disbursement_date
    # vide (crédit activé sur la fiche, pas encore décaissé au guichet), plus state ==
    # 'approved'.

    def _rows(self, company=None):
        return self.env['microfinance.loan'].get_pending_disbursements(
            (company or self.env.company).id)

    def test_nominal_returns_activated_loan_with_expected_payload(self):
        self._neutralize_funds()
        loan = self._activate_loan_without_disbursement(loan_amount=500.0, term=3)

        row = next((r for r in self._rows() if r['id'] == loan.id), None)
        self.assertIsNotNone(row, "Un crédit activé non décaissé doit apparaître dans les décaissements en attente.")
        self.assertEqual(row['partner_id'], loan.partner_id.id)
        self.assertEqual(row['partner_name'], loan.partner_id.name)
        self.assertEqual(row['dossier'], loan.name)
        self.assertEqual(row['product_name'], loan.product_id.name)
        self.assertAlmostEqual(row['amount'], loan.net_disbursed_amount, places=2)
        self.assertEqual(row['approval_date'], loan.approval_date)
        self.assertEqual(row['activation_date'], loan.activation_date)
        self.assertEqual(row['company_name'], self.env.company.name)

    def test_excludes_approved_not_yet_activated(self):
        self._neutralize_funds()
        loan = self._approve_loan(loan_amount=500.0, term=3)
        self.assertNotIn(loan.id, [r['id'] for r in self._rows()])

    def test_excludes_avis_ca_and_avis_cdag(self):
        loan_ca = self._create_loan(loan_amount=400.0, term=3)
        loan_ca.action_generate_schedule()
        loan_ca.action_start_enquete()
        loan_ca.action_ca_review()
        self.assertEqual(loan_ca.state, 'avis_ca')

        loan_cdag = self._create_loan(loan_amount=400.0, term=3)
        loan_cdag.action_generate_schedule()
        loan_cdag.action_start_enquete()
        loan_cdag.action_ca_review()
        loan_cdag.action_cdag_review()
        self.assertEqual(loan_cdag.state, 'avis_cdag')

        ids = [r['id'] for r in self._rows()]
        self.assertNotIn(loan_ca.id, ids)
        self.assertNotIn(loan_cdag.id, ids)

    def test_excludes_already_disbursed_loan(self):
        self._neutralize_funds()
        loan = self._activate_loan(loan_amount=600.0, term=3)  # 'active' ET décaissé
        self.assertTrue(loan.disbursement_date)
        self.assertNotIn(loan.id, [r['id'] for r in self._rows()])

    def test_scoped_by_company_no_leak(self):
        self._neutralize_funds()
        loan = self._activate_loan_without_disbursement(loan_amount=500.0, term=3)
        other_company = self.env['res.company'].create({
            'name': 'Autre agence décaissements (test)', 'agency_code': 'ZD1',
        })
        rows_other = self._rows(other_company)
        self.assertEqual(rows_other, [])
        self.assertNotIn(loan.id, [r['id'] for r in rows_other])

    def test_ordered_by_activation_date(self):
        self._neutralize_funds()
        loan_early = self._activate_loan_without_disbursement(loan_amount=500.0, term=3)
        loan_late = self._activate_loan_without_disbursement(loan_amount=500.0, term=3)
        loan_early.activation_date = fields.Date.to_date('2026-01-05')
        loan_late.activation_date = fields.Date.to_date('2026-01-10')

        ordered = [r['id'] for r in self._rows() if r['id'] in (loan_early.id, loan_late.id)]
        self.assertEqual(ordered, [loan_early.id, loan_late.id])


class TestGetPendingOrLate(GuichetBackendListsCommon):

    def _get(self, company=None):
        return self.env['microfinance.loan.installment'].get_pending_or_late(
            (company or self.env.company).id)

    def test_due_today_included_future_excluded(self):
        self._neutralize_funds()
        loan = self._activate_loan(term=3)
        today = fields.Date.context_today(loan)
        first, second, third = loan.installment_ids.sorted('sequence')[:3]
        first.due_date = today
        second.due_date = today
        third.due_date = fields.Date.add(today, days=30)

        ids = [r['id'] for r in self._get()]
        self.assertIn(first.id, ids)
        self.assertIn(second.id, ids)
        self.assertNotIn(third.id, ids)

    def test_late_installment_included_and_flagged(self):
        self._neutralize_funds()
        loan = self._activate_loan(term=3)
        today = fields.Date.context_today(loan)
        first = loan.installment_ids.sorted('sequence')[0]
        first.due_date = fields.Date.add(today, days=-10)
        self.assertEqual(first.state, 'overdue')

        rows = self._get()
        row = next(r for r in rows if r['id'] == first.id)
        self.assertTrue(row['is_late'])
        self.assertEqual(row['state'], 'overdue')
        self.assertAlmostEqual(row['amount'], first.residual_amount, places=2)

    def test_partial_and_late_installment_included(self):
        self._neutralize_funds()
        loan = self._activate_loan(term=3)
        today = fields.Date.context_today(loan)
        first = loan.installment_ids.sorted('sequence')[0]
        first.due_date = fields.Date.add(today, days=-5)

        payment = self.env['microfinance.loan.payment'].create({
            'loan_id': loan.id,
            'amount': round(first.total_amount / 2.0, 2),
            'payment_date': today,
            'journal_id': self.payment_journal.id,
        })
        payment.action_post()
        self.assertEqual(first.state, 'partial')

        row = next((r for r in self._get() if r['id'] == first.id), None)
        self.assertIsNotNone(row, "Une échéance 'partial' en retard doit apparaître.")
        self.assertTrue(row['is_late'])
        self.assertEqual(row['state'], 'partial')

    def test_paid_installment_excluded(self):
        self._neutralize_funds()
        loan = self._activate_loan(term=3)
        today = fields.Date.context_today(loan)
        first = loan.installment_ids.sorted('sequence')[0]
        first.due_date = today

        payment = self.env['microfinance.loan.payment'].create({
            'loan_id': loan.id,
            'amount': first.total_amount,
            'payment_date': today,
            'journal_id': self.payment_journal.id,
        })
        payment.action_post()
        self.assertEqual(first.state, 'paid')

        self.assertNotIn(first.id, [r['id'] for r in self._get()])

    def test_excludes_installments_of_non_active_loan(self):
        # Échéancier généré en phase 'approved' avec des dates passées : ne doit PAS remonter
        # (loan_id.state not in ('active','defaulted')). Cf. AUDIT §3.3 / anomalie A1.
        loan = self._approve_loan(loan_amount=500.0, term=3)
        today = fields.Date.context_today(loan)
        for inst in loan.installment_ids:
            inst.due_date = fields.Date.add(today, days=-15)
        self.assertTrue(loan.installment_ids)
        self.assertEqual(loan.state, 'approved')

        ids = [r['id'] for r in self._get()]
        self.assertFalse(set(loan.installment_ids.ids) & set(ids))

    def test_scoped_by_company_no_leak(self):
        self._neutralize_funds()
        loan = self._activate_loan(term=3)
        loan.installment_ids.sorted('sequence')[0].due_date = fields.Date.context_today(loan)

        other_company = self.env['res.company'].create({
            'name': 'Autre agence échéances (test)', 'agency_code': 'ZE1',
        })
        self.assertEqual(self._get(other_company), [])

    def test_excludes_installments_of_active_but_not_disbursed_loan(self):
        # Découplage activation / décaissement (AUDIT_decaissement.md §2) : un crédit 'active'
        # sans disbursement_date a un échéancier mais aucun fonds sorti — ses échéances
        # échues ne doivent pas remonter au guichet.
        self._neutralize_funds()
        loan = self._activate_loan_without_disbursement(loan_amount=500.0, term=3)
        today = fields.Date.context_today(loan)
        for inst in loan.installment_ids:
            inst.due_date = fields.Date.add(today, days=-15)
        self.assertEqual(loan.state, 'active')
        self.assertFalse(loan.disbursement_date)

        ids = [r['id'] for r in self._get()]
        self.assertFalse(set(loan.installment_ids.ids) & set(ids))

        # Une fois décaissé, les mêmes échéances (recalées sur disbursement_date) redeviennent
        # visibles dès qu'elles sont échues.
        loan.action_process_disbursement()
        for inst in loan.installment_ids:
            inst.due_date = fields.Date.add(today, days=-15)
        ids_after = [r['id'] for r in self._get()]
        self.assertTrue(set(loan.installment_ids.ids) & set(ids_after))


class TestGetLoanSchedule(GuichetBackendListsCommon):
    """microfinance.loan.installment.get_loan_schedule(loan_id, company_id) — calendrier
    d'échéance affiché au clic d'une ligne « Décaissements en attente » du guichet."""

    def test_returns_ordered_schedule_with_expected_payload(self):
        self._neutralize_funds()
        loan = self._activate_loan_without_disbursement(loan_amount=900.0, term=3)
        rows = self.env['microfinance.loan.installment'].get_loan_schedule(
            loan.id, self.env.company.id)

        self.assertEqual(len(rows), 3)
        self.assertEqual([r['sequence'] for r in rows], sorted(r['sequence'] for r in rows))
        first = rows[0]
        inst = loan.installment_ids.sorted(lambda i: (i.sequence, i.due_date))[0]
        self.assertEqual(first['id'], inst.id)
        self.assertEqual(first['due_date'], inst.due_date)
        self.assertAlmostEqual(first['total_amount'], inst.total_amount, places=2)
        self.assertAlmostEqual(first['residual_amount'], inst.residual_amount, places=2)
        self.assertEqual(first['state'], inst.state)
        self.assertTrue(first['state_label'])

    def test_company_mismatch_returns_empty(self):
        self._neutralize_funds()
        loan = self._activate_loan_without_disbursement(loan_amount=900.0, term=3)
        other_company = self.env['res.company'].create({
            'name': 'Autre agence calendrier (test)', 'agency_code': 'ZC1',
        })
        self.assertEqual(
            self.env['microfinance.loan.installment'].get_loan_schedule(loan.id, other_company.id),
            [],
        )

    def test_unknown_loan_returns_empty(self):
        self.assertEqual(
            self.env['microfinance.loan.installment'].get_loan_schedule(0, self.env.company.id),
            [],
        )
