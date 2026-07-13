# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import fields

from .common import MicrofinanceCommon


class TestDashboardOverdueFlux(MicrofinanceCommon):

    def _month_start(self, months_ago):
        today = fields.Date.context_today(self.env.user)
        return today.replace(day=1) - relativedelta(months=months_ago)

    def _month_key(self, months_ago):
        return self._month_start(months_ago).strftime('%Y-%m')

    def test_overlapping_arrears_count_as_a_single_new_impaye(self):
        # Un prêt en retard sur plusieurs échéances qui se chevauchent dans le temps (aucune
        # n'est soldée) ne doit générer qu'un seul "nouvel impayé", au mois de la toute première.
        loan = self._activate_loan(term=6)
        first, second, third = loan.installment_ids.sorted('sequence')[:3]
        first.write({'arrears_onset_date': self._month_start(3) + relativedelta(days=5), 'arrears_cured_date': False})
        second.write({'arrears_onset_date': self._month_start(2) + relativedelta(days=5), 'arrears_cured_date': False})
        third.write({'arrears_onset_date': self._month_start(1) + relativedelta(days=5), 'arrears_cured_date': False})

        month_keys = [self._month_key(m) for m in (3, 2, 1, 0)]
        flux = self.env['microfinance.loan'].get_overdue_monthly_flux(self.env.company.id, month_keys)

        self.assertEqual(sum(flux.values()), 1)
        self.assertEqual(flux[self._month_key(3)], 1)
        self.assertEqual(flux[self._month_key(2)], 0)
        self.assertEqual(flux[self._month_key(1)], 0)

    def test_regularization_then_relapse_counts_twice(self):
        # Une première échéance en retard, soldée (retour à jour), suivie plus tard d'une autre
        # échéance en retard : deux épisodes distincts, donc deux "nouveaux impayés".
        loan = self._activate_loan(term=6)
        first, second = loan.installment_ids.sorted('sequence')[:2]
        first.write({
            'arrears_onset_date': self._month_start(5) + relativedelta(days=5),
            'arrears_cured_date': self._month_start(4) + relativedelta(days=5),
        })
        second.write({
            'arrears_onset_date': self._month_start(2) + relativedelta(days=5),
            'arrears_cured_date': False,
        })

        month_keys = [self._month_key(m) for m in (5, 4, 3, 2, 1, 0)]
        flux = self.env['microfinance.loan'].get_overdue_monthly_flux(self.env.company.id, month_keys)

        self.assertEqual(sum(flux.values()), 2)
        self.assertEqual(flux[self._month_key(5)], 1)
        self.assertEqual(flux[self._month_key(2)], 1)

    def test_flux_isolated_per_company(self):
        loan = self._activate_loan(term=6)
        first = loan.installment_ids.sorted('sequence')[0]
        first.write({'arrears_onset_date': self._month_start(1) + relativedelta(days=5), 'arrears_cured_date': False})

        other_company = self.env['res.company'].create({'name': 'Société sans impayés (test)', 'agency_code': 'Z6'})
        month_keys = [self._month_key(m) for m in (1, 0)]
        flux_other = self.env['microfinance.loan'].get_overdue_monthly_flux(other_company.id, month_keys)

        self.assertEqual(sum(flux_other.values()), 0)

    def test_sync_arrears_state_sets_onset_once_and_cures_on_full_payment(self):
        loan = self._activate_loan(term=6)
        inst = loan.installment_ids.sorted('sequence')[0]
        inst.due_date = fields.Date.subtract(fields.Date.context_today(loan), days=5)
        inst._sync_arrears_state()

        self.assertEqual(inst.state, 'overdue')
        self.assertEqual(inst.arrears_onset_date, inst.due_date)
        self.assertFalse(inst.arrears_cured_date)

        onset_before = inst.arrears_onset_date
        inst._sync_arrears_state()
        self.assertEqual(inst.arrears_onset_date, onset_before)

        payment = self.env['microfinance.loan.payment'].create({
            'loan_id': loan.id,
            'amount': inst.total_amount,
            'payment_date': fields.Date.context_today(loan),
            'journal_id': self.payment_journal.id,
        })
        payment.action_post()
        inst._sync_arrears_state()

        self.assertEqual(inst.state, 'paid')
        self.assertEqual(inst.arrears_cured_date, fields.Date.context_today(loan))
