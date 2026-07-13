# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError

from .common import SavingsCommon


class TestSavingsTransactionDateOrder(SavingsCommon):

    def test_transaction_date_order_blocked(self):
        account = self._create_active_account(opening_amount=200.0)
        account._create_transaction('deposit', 50.0, date=fields.Date.today())
        with self.assertRaises(ValidationError):
            account._create_transaction('withdrawal', 10.0, date=fields.Date.today() - timedelta(days=5))

    def test_transaction_date_order_allows_same_day(self):
        account = self._create_active_account(opening_amount=200.0)
        account._create_transaction('deposit', 50.0, date=fields.Date.today())
        txn = account._create_transaction('withdrawal', 10.0, date=fields.Date.today())
        self.assertEqual(txn.state, 'posted')

    def test_transaction_date_order_allows_later_date(self):
        account = self._create_account()
        account._create_transaction('deposit', 200.0, date=fields.Date.today() - timedelta(days=10))
        account.action_activate()
        txn = account._create_transaction('withdrawal', 10.0, date=fields.Date.today())
        self.assertEqual(txn.state, 'posted')

    def test_transaction_date_order_is_per_account(self):
        # Une date antérieure à la dernière transaction d'un AUTRE compte ne doit pas bloquer :
        # le contrôle est bien scopé par compte, pas global. account_a a déjà une transaction
        # datée d'aujourd'hui ; la première transaction d'account_b, datée d'il y a 30 jours,
        # doit passer car elle n'a encore aucune transaction antérieure sur SON compte.
        account_a = self._create_active_account(opening_amount=200.0)
        account_b = self._create_account()
        txn = account_b._create_transaction('deposit', 10.0, date=fields.Date.today() - timedelta(days=30))
        account_b.action_activate()
        self.assertEqual(txn.state, 'posted')
        self.assertTrue(account_a.last_transaction_date)


class TestSavingsWithdrawalLimit(SavingsCommon):
    """Plafond de retrait : blocage par transaction individuelle uniquement (pas de cumul sur
    une période, non demandé et absent du manuel LPF)."""

    def test_withdrawal_limit_blocked(self):
        self.savings_product.write({'withdrawal_limit_amount': 30.0})
        account = self._create_active_account(opening_amount=200.0)
        with self.assertRaises(ValidationError):
            account._create_transaction('withdrawal', 40.0)

    def test_withdrawal_limit_allowed_at_limit(self):
        self.savings_product.write({'withdrawal_limit_amount': 30.0})
        account = self._create_active_account(opening_amount=200.0)
        txn = account._create_transaction('withdrawal', 30.0)
        self.assertEqual(txn.state, 'posted')

    def test_withdrawal_limit_allowed_with_explicit_bypass(self):
        self.savings_product.write({'withdrawal_limit_amount': 30.0})
        account = self._create_active_account(opening_amount=200.0)
        txn = account._create_transaction('withdrawal', 40.0, bypass_withdrawal_limit=True)
        self.assertEqual(txn.state, 'posted')

    def test_withdrawal_limit_bypassed_on_closure(self):
        self.savings_product.write({'withdrawal_limit_amount': 10.0})
        account = self._create_active_account(opening_amount=200.0)
        account.action_close()
        self.assertEqual(account.state, 'closed')
        self.assertEqual(account.balance, 0.0)

    def test_bypass_min_balance_does_not_bypass_withdrawal_limit(self):
        # bypass_min_balance et bypass_withdrawal_limit sont deux dérogations indépendantes :
        # activer l'une ne doit pas dispenser du contrôle de l'autre.
        self.savings_product.write({'withdrawal_limit_amount': 30.0})
        account = self._create_active_account(opening_amount=200.0)
        with self.assertRaises(ValidationError):
            self.env['microfinance.savings.transaction'].create({
                'account_id': account.id, 'transaction_type': 'withdrawal', 'amount': 40.0,
                'bypass_min_balance': True,
            })

    def test_withdrawal_limit_not_applied_when_journal_is_bank(self):
        bank_journal = self.env['account.journal'].create({
            'name': 'Banque retrait épargne test', 'code': 'TBQW', 'type': 'bank',
            'company_id': self.env.company.id, 'default_account_id': self.bank_account.id,
        })
        self.savings_product.write({
            'withdrawal_limit_amount': 30.0,
            'withdrawal_journal_id': bank_journal.id,
        })
        account = self._create_active_account(opening_amount=200.0)
        txn = account._create_transaction('withdrawal', 40.0)
        self.assertEqual(txn.state, 'posted')


class TestSavingsCashBalanceCheck(SavingsCommon):
    """Contrôle de solde de caisse réel au retrait : opt-in par produit
    (check_cash_balance_at_withdrawal, désactivé par défaut), sinon tout retrait serait bloqué
    dès l'installation faute d'écriture d'ouverture de caisse (cf. docs_dev/gestion_caisse).
    Utilise un journal/compte de retrait dédié, distinct de savings_withdrawal_journal, pour ne
    pas dépendre du solde déjà accumulé par le dépôt d'ouverture des autres tests de ce fichier
    (deposit_journal_id/withdrawal_journal_id de savings_product partagent bank_account)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dedicated_withdrawal_account = cls.env['account.account'].create({
            'name': 'Caisse retrait dédiée test', 'code': 'TDEDW', 'account_type': 'asset_cash', 'company_id': cls.env.company.id,
        })
        cls.dedicated_withdrawal_journal = cls.env['account.journal'].create({
            'name': 'Caisse retrait dédiée test', 'code': 'TDEDWJ', 'type': 'cash', 'company_id': cls.env.company.id,
            'default_account_id': cls.dedicated_withdrawal_account.id,
        })
        cls.savings_product.write({'withdrawal_journal_id': cls.dedicated_withdrawal_journal.id})

    def _fund_cash_account(self, account, amount):
        journal = self.env['account.journal'].create({
            'name': 'Ouverture caisse épargne test', 'code': 'TOUVE', 'type': 'general', 'company_id': self.env.company.id,
        })
        counterpart = self.env['account.account'].create({
            'name': 'Capital caisse épargne test', 'code': 'TCAPE', 'account_type': 'equity', 'company_id': self.env.company.id,
        })
        move = self.env['account.move'].create({
            'journal_id': journal.id,
            'line_ids': [
                (0, 0, {'account_id': account.id, 'debit': amount, 'credit': 0.0}),
                (0, 0, {'account_id': counterpart.id, 'debit': 0.0, 'credit': amount}),
            ],
        })
        move.action_post()

    def test_check_disabled_by_default_allows_withdrawal_with_empty_journal(self):
        self.assertFalse(self.savings_product.check_cash_balance_at_withdrawal)
        account = self._create_active_account(opening_amount=200.0)
        txn = account._create_transaction('withdrawal', 40.0)
        self.assertEqual(txn.state, 'posted')

    def test_check_enabled_blocks_withdrawal_when_balance_insufficient(self):
        self.savings_product.write({'check_cash_balance_at_withdrawal': True})
        account = self._create_active_account(opening_amount=200.0)
        with self.assertRaises(UserError):
            account._create_transaction('withdrawal', 40.0)

    def test_check_enabled_allows_withdrawal_when_balance_sufficient(self):
        self.savings_product.write({'check_cash_balance_at_withdrawal': True})
        self._fund_cash_account(self.dedicated_withdrawal_account, 1000.0)
        account = self._create_active_account(opening_amount=200.0)
        txn = account._create_transaction('withdrawal', 40.0)
        self.assertEqual(txn.state, 'posted')

    def test_check_enabled_bypass_allows_withdrawal(self):
        self.savings_product.write({'check_cash_balance_at_withdrawal': True})
        account = self._create_active_account(opening_amount=200.0)
        txn = account._create_transaction('withdrawal', 40.0, bypass_cash_balance=True)
        self.assertEqual(txn.state, 'posted')

    def test_check_enabled_not_applied_when_journal_is_bank(self):
        bank_journal = self.env['account.journal'].create({
            'name': 'Banque retrait dédiée test', 'code': 'TDEDB', 'type': 'bank',
            'company_id': self.env.company.id, 'default_account_id': self.dedicated_withdrawal_account.id,
        })
        self.savings_product.write({
            'check_cash_balance_at_withdrawal': True,
            'withdrawal_journal_id': bank_journal.id,
        })
        account = self._create_active_account(opening_amount=200.0)
        txn = account._create_transaction('withdrawal', 40.0)
        self.assertEqual(txn.state, 'posted')


class TestSavingsEarlyWithdrawalPenalty(SavingsCommon):

    def _term_deposit_product(self, **kwargs):
        vals = {
            'name': 'DAT test', 'code': 'PDAT', 'product_type': 'term_deposit', 'term_months': 12,
            'early_withdrawal_penalty_rate': 10.0,
            'account_epargne_individuel_id': self.savings_deposit_account.id,
            'account_epargne_groupe_id': self.savings_deposit_account_groupe.id,
            'account_epargne_entreprise_id': self.savings_deposit_account_entreprise.id,
            'account_interet_paye_individuel_id': self.savings_interest_account.id,
            'account_penalites_id': self.savings_fee_account.id,
            'deposit_journal_id': self.savings_deposit_journal.id,
            'withdrawal_journal_id': self.savings_withdrawal_journal.id,
        }
        vals.update(kwargs)
        return self.env['microfinance.savings.product'].create(vals)

    def test_penalty_applied_before_maturity(self):
        product = self._term_deposit_product(code='PDAT1')
        account = self._create_active_account(opening_amount=1000.0, product_id=product.id)
        self.assertTrue(account.maturity_date and account.maturity_date > fields.Date.today())
        txn = account._create_transaction('withdrawal', 100.0)
        penalty_line = txn.move_id.line_ids.filtered(lambda l: l.account_id == self.savings_fee_account and l.credit > 0)
        cash_line = txn.move_id.line_ids.filtered(lambda l: l.account_id == self.bank_account)
        self.assertEqual(penalty_line.credit, 10.0)
        self.assertEqual(cash_line.credit, 90.0)
        # Le solde du compte épargne diminue bien du montant retiré complet (100), pas du net (90) :
        # la pénalité est prélevée sur ce que le client reçoit en caisse, pas sur son solde épargne.
        self.assertEqual(account.balance, 900.0)

    def test_no_penalty_after_maturity(self):
        product = self._term_deposit_product(code='PDAT2')
        account = self._create_active_account(opening_amount=1000.0, product_id=product.id)
        account.write({'opening_date': fields.Date.today() - timedelta(days=400)})
        account.invalidate_recordset()
        self.assertLess(account.maturity_date, fields.Date.today())
        txn = account._create_transaction('withdrawal', 100.0)
        credit_lines = txn.move_id.line_ids.filtered(lambda l: l.credit > 0)
        self.assertEqual(len(credit_lines), 1)
        self.assertEqual(credit_lines.account_id, self.bank_account)
        self.assertEqual(credit_lines.credit, 100.0)

    def test_no_penalty_for_voluntary_product_without_retention_days(self):
        # early_withdrawal_penalty_rate seul reste sans effet : ni maturity_date (produit
        # volontaire), ni min_retention_days configuré.
        self.savings_product.write({'early_withdrawal_penalty_rate': 10.0})
        account = self._create_active_account(opening_amount=1000.0)
        txn = account._create_transaction('withdrawal', 100.0)
        credit_lines = txn.move_id.line_ids.filtered(lambda l: l.credit > 0)
        self.assertEqual(len(credit_lines), 1)
        self.assertEqual(credit_lines.credit, 100.0)

    def test_penalty_rate_over_amount_blocked(self):
        product = self._term_deposit_product(code='PDAT3', early_withdrawal_penalty_rate=150.0)
        account = self._create_active_account(opening_amount=1000.0, product_id=product.id)
        with self.assertRaises(UserError):
            account._create_transaction('withdrawal', 100.0)

    def test_penalty_applied_via_min_retention_days_on_voluntary_product(self):
        # LPF : le délai minimum de rétention s'applique à n'importe quel produit, y compris
        # l'épargne libre — pas seulement les dépôts à terme.
        self.savings_product.write({
            'early_withdrawal_penalty_rate': 5.0, 'min_retention_days': 30,
            'account_penalites_id': self.savings_fee_account.id,
        })
        account = self._create_active_account(opening_amount=1000.0)
        self.assertFalse(account.maturity_date)
        txn = account._create_transaction('withdrawal', 100.0)
        penalty_line = txn.move_id.line_ids.filtered(lambda l: l.account_id == self.savings_fee_account and l.credit > 0)
        cash_line = txn.move_id.line_ids.filtered(lambda l: l.account_id == self.bank_account)
        self.assertEqual(penalty_line.credit, 5.0)
        self.assertEqual(cash_line.credit, 95.0)

    def test_no_penalty_once_min_retention_days_elapsed(self):
        self.savings_product.write({'early_withdrawal_penalty_rate': 5.0, 'min_retention_days': 30})
        account = self._create_active_account(opening_amount=1000.0)
        account.write({'opening_date': fields.Date.today() - timedelta(days=45)})
        account.invalidate_recordset()
        txn = account._create_transaction('withdrawal', 100.0)
        credit_lines = txn.move_id.line_ids.filtered(lambda l: l.credit > 0)
        self.assertEqual(len(credit_lines), 1)
        self.assertEqual(credit_lines.credit, 100.0)

    def test_penalty_not_duplicated_when_maturity_and_retention_both_apply(self):
        # Produit à terme avec en plus un délai de rétention non écoulé : les deux conditions
        # sont vraies simultanément, la pénalité ne doit être créditée qu'une seule fois (une
        # seule ligne comptable, montant non cumulé).
        product = self._term_deposit_product(code='PDAT4', min_retention_days=3650)
        account = self._create_active_account(opening_amount=1000.0, product_id=product.id)
        txn = account._create_transaction('withdrawal', 100.0)
        penalty_lines = txn.move_id.line_ids.filtered(lambda l: l.account_id == self.savings_fee_account and l.credit > 0)
        self.assertEqual(len(penalty_lines), 1)
        self.assertEqual(penalty_lines.credit, 10.0)
