# -*- coding: utf-8 -*-
from odoo import fields
from odoo.exceptions import UserError
from odoo.addons.microfinance_loan_management.tests.common import MicrofinanceCommon


class TestTransfertEncaissement(MicrofinanceCommon):
    """Sous-lot C — étape 1 (encaissement à l'agence source).

    Le cycle complet à 4 écritures (remise au coursier, réception destination,
    remboursement) est couvert au sous-lot F, avec les fixtures multi-société
    (deux agences PCEC, crédit dans l'agence destination, deux sessions).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        Account = cls.env['account.account']
        Journal = cls.env['account.journal']
        # Les sociétés de test n'ont pas le plan PCEC : on crée à la main le
        # compte de transit 302000 et le journal TRANSIT (idempotent).
        cls.transit_account = Account.search(
            [('code', '=', '302000'), ('company_id', '=', cls.company.id)], limit=1)
        if not cls.transit_account:
            cls.transit_account = Account.create({
                'name': 'Opérations entre succursales/agences (test)', 'code': '302000',
                'account_type': 'asset_current', 'reconcile': True, 'company_id': cls.company.id,
            })
        cls.transit_journal = Journal.search(
            [('code', '=', 'TRANSIT'), ('company_id', '=', cls.company.id)], limit=1)
        if not cls.transit_journal:
            cls.transit_journal = Journal.create({
                'name': 'Transit inter-agences (test)', 'code': 'TRANSIT', 'type': 'general',
                'company_id': cls.company.id, 'default_account_id': cls.transit_account.id,
            })
        elif not cls.transit_journal.default_account_id:
            cls.transit_journal.default_account_id = cls.transit_account.id

        # Rôle caissier pur : exerce le vrai chemin de droits + sudo ciblé.
        cls.env.user.groups_id = [
            (4, cls.env.ref('microfinance_loan_management.group_microfinance_cashier').id),
            (4, cls.env.ref('microfinance_savings_management.group_savings_agent').id),
        ]

    def _open_session(self):
        session = self.env['microfinance.caisse.session'].create({
            'journal_id': self.payment_journal.id, 'date': fields.Date.today(),
        })
        session.action_open_session()
        return session

    def test_encaissement_posts_transit_move_and_ticket(self):
        loan = self._create_loan()
        session = self._open_session()
        transfert = self.env['microfinance.transfert.remboursement'].create({
            'loan_id': loan.id, 'session_id': session.id, 'amount': 150.0,
        })
        self.assertTrue(transfert.transfer_code.startswith('T/'))
        self.assertEqual(transfert.state, 'en_attente')
        self.assertEqual(transfert.source_company_id, self.company)
        self.assertEqual(transfert.destination_company_id, loan.company_id)

        transfert.action_encaisser()

        move = transfert.encaissement_move_id
        self.assertTrue(move, "L'écriture d'encaissement doit être créée")
        self.assertEqual(move.state, 'posted')
        self.assertEqual(move.journal_id, self.transit_journal)
        cash_line = move.line_ids.filtered(
            lambda l: l.account_id == self.payment_journal.default_account_id)
        transit_line = move.line_ids.filtered(lambda l: l.account_id == self.transit_account)
        self.assertAlmostEqual(cash_line.debit, 150.0)
        self.assertAlmostEqual(cash_line.credit, 0.0)
        self.assertAlmostEqual(transit_line.credit, 150.0)
        self.assertAlmostEqual(transit_line.debit, 0.0)
        self.assertEqual(transfert.caisse_account_id, self.payment_journal.default_account_id)
        self.assertEqual(transfert.cashier_source_id, self.env.user)

        mvt = transfert.caisse_mouvement_source_id
        self.assertEqual(mvt.type, 'transfert_sortant')
        self.assertEqual(mvt.session_id, session)
        self.assertEqual(mvt.transfert_remboursement_id, transfert)
        self.assertEqual(mvt.loan_id, loan)
        self.assertAlmostEqual(mvt.amount, 150.0)

    def test_double_encaissement_refused(self):
        loan = self._create_loan()
        session = self._open_session()
        transfert = self.env['microfinance.transfert.remboursement'].create({
            'loan_id': loan.id, 'session_id': session.id, 'amount': 50.0,
        })
        transfert.action_encaisser()
        with self.assertRaises(UserError):
            transfert.action_encaisser()

    def test_encaissement_requires_open_session(self):
        loan = self._create_loan()
        session = self.env['microfinance.caisse.session'].create({
            'journal_id': self.payment_journal.id, 'date': fields.Date.today(),
        })
        # session laissée en brouillon
        transfert = self.env['microfinance.transfert.remboursement'].create({
            'loan_id': loan.id, 'session_id': session.id, 'amount': 50.0,
        })
        with self.assertRaises(UserError):
            transfert.action_encaisser()
