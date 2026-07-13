# -*- coding: utf-8 -*-
from odoo.exceptions import UserError

from .common import MicrofinanceCommon


class TestDisbursementLimit(MicrofinanceCommon):
    """Plafond de décaissement en espèces : blocage par décaissement individuel uniquement (pas
    de cumul sur une période), même principe que withdrawal_limit_amount côté épargne. Ne
    s'applique que si le journal de décaissement est de type 'cash'."""

    def _approve_loan(self, **kwargs):
        loan = self._create_loan(**kwargs)
        loan.action_generate_schedule()
        loan.action_submit()
        loan.action_manager_validate()
        loan.action_finance_validate()
        loan.action_approve()
        return loan

    def test_disbursement_limit_blocked(self):
        self.product.write({'disbursement_limit_amount': 1000.0})
        loan = self._approve_loan(loan_amount=1200.0)
        with self.assertRaises(UserError):
            loan.action_disburse()

    def test_disbursement_limit_allowed_at_limit(self):
        self.product.write({'disbursement_limit_amount': 1200.0})
        loan = self._approve_loan(loan_amount=1200.0)
        loan.action_disburse()
        self.assertEqual(loan.state, 'active')

    def test_disbursement_limit_zero_means_no_limit(self):
        # 0.0 (valeur par défaut) : aucun plafond, comportement inchangé.
        loan = self._approve_loan(loan_amount=1200.0)
        loan.action_disburse()
        self.assertEqual(loan.state, 'active')

    def test_disbursement_limit_not_applied_when_journal_is_bank(self):
        bank_journal = self.env['account.journal'].create({
            'name': 'Banque décaissement test', 'code': 'TBQD', 'type': 'bank',
            'company_id': self.env.company.id, 'default_account_id': self.bank_account.id,
        })
        self.product.write({
            'disbursement_limit_amount': 1000.0,
            'disbursement_journal_id': bank_journal.id,
        })
        loan = self._approve_loan(loan_amount=1200.0)
        loan.action_disburse()
        self.assertEqual(loan.state, 'active')
