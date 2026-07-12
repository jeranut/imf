# -*- coding: utf-8 -*-
from odoo import fields

from .common import MicrofinanceCommon


class TestDashboardPar(MicrofinanceCommon):

    def test_par_buckets_present_and_excludes_written_off(self):
        loan = self._activate_loan(loan_amount=1000.0, term=4)
        first = loan.installment_ids.sorted('sequence')[0]
        first.due_date = fields.Date.subtract(fields.Date.context_today(loan), days=45)

        writeoff_account = self.env['account.account'].create({
            'name': 'Pertes test PAR', 'code': 'TWOFPAR', 'account_type': 'expense', 'company_id': self.env.company.id,
        })
        self.product.account_credits_perte_individuel_id = writeoff_account.id
        other_partner = self.env['res.partner'].create({'name': 'Client PAR radié'})
        written_off_loan = self._activate_loan(loan_amount=2000.0, term=2, partner_id=other_partner.id)
        written_off_installment = written_off_loan.installment_ids.sorted('sequence')[0]
        written_off_installment.due_date = fields.Date.subtract(fields.Date.context_today(loan), days=200)
        written_off_loan.action_confirm_write_off('Radiation test PAR', fields.Date.context_today(loan))

        par_buckets = self.env['microfinance.loan'].get_par_buckets(self.env.company.id)

        self.assertEqual(par_buckets['labels'], ['PAR 1-30', 'PAR 31-60', 'PAR 61-90', 'PAR 90+'])
        self.assertEqual(len(par_buckets['values']), 4)
        # The 45-day-overdue active loan falls in the 31-60 bucket.
        self.assertGreater(par_buckets['values'][1], 0.0)
        # The written-off loan (200 days overdue) must not inflate the 90+ bucket: it is
        # excluded from the active/defaulted portfolio entirely.
        self.assertEqual(par_buckets['values'][3], 0.0)

    def test_par_buckets_zero_when_no_portfolio(self):
        empty_company = self.env['res.company'].create({'name': 'Société sans crédit'})
        par_buckets = self.env['microfinance.loan'].get_par_buckets(empty_company.id)
        self.assertEqual(par_buckets['values'], [0.0, 0.0, 0.0, 0.0])
