# -*- coding: utf-8 -*-
from odoo.exceptions import UserError

from .common import MicrofinanceCommon


class TestCashBalanceCheck(MicrofinanceCommon):
    """Contrôle de solde de caisse réel au décaissement : opt-in par produit
    (check_cash_balance_at_disbursement, désactivé par défaut), sinon tout décaissement serait
    bloqué dès l'installation faute d'écriture d'ouverture de caisse (cf. docs_dev/gestion_caisse)."""

    def _fund_cash_account(self, account, amount):
        journal = self.env['account.journal'].create({
            'name': 'Ouverture caisse test', 'code': 'TOUV', 'type': 'general', 'company_id': self.env.company.id,
        })
        counterpart = self.env['account.account'].create({
            'name': 'Capital caisse test', 'code': 'TCAP', 'account_type': 'equity', 'company_id': self.env.company.id,
        })
        move = self.env['account.move'].create({
            'journal_id': journal.id,
            'line_ids': [
                (0, 0, {'account_id': account.id, 'debit': amount, 'credit': 0.0}),
                (0, 0, {'account_id': counterpart.id, 'debit': 0.0, 'credit': amount}),
            ],
        })
        move.action_post()

    def _approve_loan(self, **kwargs):
        loan = self._create_loan(**kwargs)
        loan.action_generate_schedule()
        loan.action_submit()
        loan.action_manager_validate()
        loan.action_finance_validate()
        loan.action_approve()
        return loan

    def test_check_disabled_by_default_allows_disbursement_with_empty_journal(self):
        # Garde-fou : le champ check_cash_balance_at_disbursement vaut False par défaut, donc
        # aucun changement de comportement pour les produits existants (solde du journal à 0).
        self.assertFalse(self.product.check_cash_balance_at_disbursement)
        loan = self._approve_loan(loan_amount=1200.0)
        loan.action_disburse()
        self.assertEqual(loan.state, 'active')

    def test_check_enabled_blocks_disbursement_when_balance_insufficient(self):
        self.product.write({'check_cash_balance_at_disbursement': True})
        loan = self._approve_loan(loan_amount=1200.0)
        with self.assertRaises(UserError):
            loan.action_disburse()

    def test_check_enabled_allows_disbursement_when_balance_sufficient(self):
        self.product.write({'check_cash_balance_at_disbursement': True})
        self._fund_cash_account(self.bank_account, 5000.0)
        loan = self._approve_loan(loan_amount=1200.0)
        loan.action_disburse()
        self.assertEqual(loan.state, 'active')

    def test_check_enabled_bypass_allows_disbursement(self):
        self.product.write({'check_cash_balance_at_disbursement': True})
        loan = self._approve_loan(loan_amount=1200.0)
        loan.bypass_cash_balance = True
        loan.action_disburse()
        self.assertEqual(loan.state, 'active')

    def test_check_enabled_not_applied_when_journal_is_bank(self):
        bank_journal = self.env['account.journal'].create({
            'name': 'Banque décaissement test 2', 'code': 'TBQD2', 'type': 'bank',
            'company_id': self.env.company.id, 'default_account_id': self.bank_account.id,
        })
        self.product.write({
            'check_cash_balance_at_disbursement': True,
            'disbursement_journal_id': bank_journal.id,
        })
        loan = self._approve_loan(loan_amount=1200.0)
        loan.action_disburse()
        self.assertEqual(loan.state, 'active')
