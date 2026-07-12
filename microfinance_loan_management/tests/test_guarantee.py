# -*- coding: utf-8 -*-
from odoo.exceptions import UserError, ValidationError

from .common import MicrofinanceCommon


class TestGuarantee(MicrofinanceCommon):

    def test_guarantor_partner_required_for_guarantor_type(self):
        loan = self._create_loan()
        with self.assertRaises(ValidationError):
            self.env['microfinance.loan.guarantee'].create({
                'loan_id': loan.id,
                'guarantee_type': 'guarantor',
                'description': 'Caution sans partenaire',
                'estimated_value': 100.0,
            })

    def test_submit_blocked_when_guarantee_required_but_missing(self):
        self.product.guarantee_required = True
        loan = self._create_loan()
        with self.assertRaises(UserError):
            loan.action_submit()

    def test_submit_allowed_once_guarantee_validated(self):
        self.product.guarantee_required = True
        loan = self._create_loan()
        self.env['microfinance.loan.guarantee'].create({
            'loan_id': loan.id,
            'guarantee_type': 'land',
            'description': 'Terrain à Analamanga',
            'estimated_value': 5000.0,
            'state': 'validated',
        })
        loan.action_submit()
        self.assertEqual(loan.state, 'submitted')

    def test_submit_blocked_when_guarantee_ratio_not_met(self):
        self.product.min_guarantee_ratio = 50.0
        loan = self._create_loan(loan_amount=1000.0)
        self.env['microfinance.loan.guarantee'].create({
            'loan_id': loan.id,
            'guarantee_type': 'land',
            'description': 'Garantie insuffisante',
            'estimated_value': 100.0,
            'state': 'validated',
        })
        with self.assertRaises(UserError):
            loan.action_submit()

    def test_submit_allowed_when_guarantee_ratio_met(self):
        self.product.min_guarantee_ratio = 50.0
        loan = self._create_loan(loan_amount=1000.0)
        self.env['microfinance.loan.guarantee'].create({
            'loan_id': loan.id,
            'guarantee_type': 'land',
            'description': 'Garantie suffisante',
            'estimated_value': 600.0,
            'state': 'validated',
        })
        loan.action_submit()
        self.assertEqual(loan.state, 'submitted')

    def test_guarantees_released_on_close(self):
        loan = self._activate_loan(loan_amount=300.0, term=1)
        guarantee = self.env['microfinance.loan.guarantee'].create({
            'loan_id': loan.id,
            'guarantee_type': 'land',
            'description': 'Garantie à libérer',
            'estimated_value': 300.0,
            'state': 'validated',
        })
        installment = loan.installment_ids[0]
        payment = self.env['microfinance.loan.payment'].create({
            'loan_id': loan.id,
            'amount': installment.total_amount,
            'journal_id': self.payment_journal.id,
        })
        payment.action_post()
        self.assertEqual(loan.state, 'closed')
        self.assertEqual(guarantee.state, 'released')
