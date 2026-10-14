# -*- coding: utf-8 -*-
from unittest.mock import patch

from ..models.res_company import ResCompany
from .common import MicrofinanceCommon, MicrofinanceNoFundMixin


class TestDisbursementWaitingAccount(MicrofinanceNoFundMixin, MicrofinanceCommon):
    """Décaissement par chèque ou virement : crédit du compte « paiements émis en attente » et non de la banque ;
    dénouement par le pointage du relevé ; rejet = contre-passation ; transit visible au tableau de bord."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company = cls.env.company
        Account = cls.env['account.account']
        cls.real_bank_account = Account.create({
            'name': 'Banque test', 'code': 'TBNK', 'account_type': 'asset_cash', 'company_id': company.id})
        cls.cheque_waiting = Account.create({
            'name': 'Attente chèques émis test', 'code': 'TCHQW', 'account_type': 'liability_current',
            'reconcile': True, 'company_id': company.id})
        cls.transfer_waiting = Account.create({
            'name': 'Attente virements émis test', 'code': 'TVIRW', 'account_type': 'liability_current',
            'reconcile': True, 'company_id': company.id})
        cls.product.write({'account_cheques_emis_attente_id': cls.cheque_waiting.id,
                           'account_virements_emis_attente_id': cls.transfer_waiting.id})
        cls.bank_journal = cls.env['account.journal'].create({
            'name': 'Banque décaissement test', 'code': 'TBNKJ', 'type': 'bank', 'company_id': company.id,
            'default_account_id': cls.real_bank_account.id, 'microfinance_usage': 'credit'})

    def setUp(self):
        # base MOWGLI déjà configurée avec une société mère : sans ce patch, le mixin (écriture sur les fonds) refuse
        patcher = patch.object(ResCompany, '_get_microfinance_parent', lambda self: self.browse())
        patcher.start()
        self.addCleanup(patcher.stop)
        super().setUp()

    # ------------------------------------------------------------------ outils
    def _disburse(self, method):
        loan = self._activate_loan_without_disbursement()
        loan.write({'disbursement_payment_method': method})
        if method != 'cash':
            loan.write({'disbursement_journal_id': self.bank_journal.id})
            if method == 'cheque':
                loan.write({'disbursement_cheque_number': 'CHQ1', 'disbursement_cheque_date': '2026-10-05'})
        loan.action_process_disbursement()
        return loan

    def _balance(self, account):
        lines = self.env['account.move.line'].search([('account_id', '=', account.id), ('parent_state', '=', 'posted')])
        return sum(lines.mapped('balance'))

    def _amounts(self):
        return self.bank_journal._mf_treasury_amounts()[self.bank_journal.id]

    def _statement(self, start, end, entries, day=1):
        stamp = '2026-10-%02d' % day
        return self.env['account.bank.statement'].create({
            'journal_id': self.bank_journal.id, 'mf_state': 'draft', 'mf_date_from': stamp, 'mf_date_to': stamp,
            'balance_start': start, 'balance_end_real': end,
            'mf_entry_ids': [(0, 0, dict({'date': stamp}, **e)) for e in entries]})

    def _flat_statement(self, day=1):
        """Relevé sans mouvement net (une entrée et une sortie égales) : le relevé affiche 0, comme la banque."""
        return self._statement(0.0, 0.0, [{'name': 'Entrée', 'amount_in': 500.0},
                                          {'name': 'Sortie', 'amount_out': 500.0}], day)

    def _row(self):
        with patch.object(type(self.env['microfinance.loan']), '_treasury_has_rights', lambda self: True):
            rows = self.env['microfinance.loan']._treasury_rows()[0]
        return next(r for r in rows if r['journal_id'] == self.bank_journal.id)

    # ------------------------------------------------------------------ règle de comptabilisation
    def test_cash_disbursement_unchanged(self):
        loan = self._disburse('cash')
        self.assertFalse(loan.disbursement_cheque_state)
        self.assertAlmostEqual(self._balance(self.bank_account), -loan.net_disbursed_amount, places=2)
        self.assertAlmostEqual(self._balance(self.cheque_waiting) + self._balance(self.transfer_waiting), 0.0, places=2)

    def test_cheque_and_transfer_credit_waiting_not_bank(self):
        for method, waiting in (('cheque', self.cheque_waiting), ('bank_transfer', self.transfer_waiting)):
            before = self._balance(waiting)
            loan = self._disburse(method)
            self.assertEqual(loan.disbursement_cheque_state, 'en_attente', method)
            self.assertAlmostEqual(self._balance(waiting) - before, -loan.net_disbursed_amount, places=2)
            self.assertAlmostEqual(self._balance(self.real_bank_account), 0.0, places=2,
                                   msg="Le journal bancaire reste égal au relevé tant que le dénouement n'a pas eu lieu.")

    def test_transfer_falls_back_on_cheque_waiting_account(self):
        self.product.account_virements_emis_attente_id = False
        loan = self._disburse('bank_transfer')
        self.assertAlmostEqual(self._balance(self.cheque_waiting), -loan.net_disbursed_amount, places=2)

    # ------------------------------------------------------------------ tableau de bord
    def test_transit_shown_and_bank_equals_statement(self):
        loan = self._disburse('bank_transfer')
        amounts = self._amounts()
        self.assertAlmostEqual(amounts['bank'], 0.0, places=2)
        self.assertAlmostEqual(amounts['out_transit'], loan.net_disbursed_amount, places=2)
        self.assertAlmostEqual(amounts['available'], -loan.net_disbursed_amount, places=2)
        self._flat_statement().action_mf_validate()
        row = self._row()
        self.assertAlmostEqual(row['out_transit'], loan.net_disbursed_amount, places=2)
        self.assertEqual(row['unexplained'], 0.0, "Relevé = comptable : aucun écart non expliqué.")
        journal_data = {self.bank_journal.id: {}}
        self.bank_journal._fill_bank_cash_dashboard_data(journal_data)
        self.assertTrue(journal_data[self.bank_journal.id]['mf_transit_nonzero'])
        self.assertFalse(journal_data[self.bank_journal.id]['mf_gap_nonzero'])

    def test_unexplained_gap_counts_only_what_transit_does_not_cover(self):
        loan = self._disburse('cheque')
        net = loan.net_disbursed_amount
        # chèque encaissé par le client, ligne pas encore pointée : écart couvert par le transit
        self._statement(0.0, -net, [{'name': 'Chèque', 'amount_out': net}], day=1).action_mf_validate()
        self.assertEqual(self._row()['unexplained'], 0.0)
        # sortie plus grosse que le transit : le surplus reste non expliqué
        self._statement(-net, -net - 500.0, [{'name': 'Frais', 'amount_out': 500.0}], day=2).action_mf_validate()
        self.assertAlmostEqual(self._row()['unexplained'], -500.0, places=2)

    def test_overview_tile_has_transit_line_and_unexplained_counter(self):
        loan = self._disburse('bank_transfer')
        self._flat_statement().action_mf_validate()
        with patch.object(type(self.env['microfinance.loan']), '_treasury_has_rights', lambda self: True):
            tile = self.env['microfinance.loan']._treasury_overview_tile()
        items = {item['label']: item for item in tile['secondary_items']}
        # la base réelle peut déjà porter des écarts sur d'autres banques : on compare au calcul par ligne
        with patch.object(type(self.env['microfinance.loan']), '_treasury_has_rights', lambda self: True):
            rows = self.env['microfinance.loan']._treasury_rows()[0]
        expected = sum(1 for row in rows if row['unexplained'])
        self.assertAlmostEqual(items['En transit']['value'], sum(row['out_transit'] for row in rows), places=2)
        self.assertGreaterEqual(items['En transit']['value'], loan.net_disbursed_amount)
        self.assertIn('Écarts non expliqués : %s' % expected, items)
        self.assertEqual(tile['counts']['unexplained'], expected)
        self.assertEqual(self._row()['unexplained'], 0.0, "La banque de test (relevé = comptable) n'a aucun écart.")

    # ------------------------------------------------------------------ dénouement par le relevé
    def _point_statement(self, method, waiting):
        loan = self._disburse(method)
        net = loan.net_disbursed_amount
        waiting_line = loan.disbursement_move_id.line_ids.filtered(lambda l: l.account_id == waiting)
        statement = self._statement(0.0, -net, [{'name': 'Sortie %s' % method, 'amount_out': net}])
        entry = statement.mf_entry_ids
        self.assertIn(waiting_line, entry.candidate_line_ids,
                      "Le rapprochement manuel doit proposer l'écriture d'attente.")
        entry.write({'treatment': 'reconcile', 'target_line_id': waiting_line.id})
        entry.action_treat()
        return loan, entry, statement, waiting_line

    def _check_pointing_clears(self, method, waiting):
        loan, entry, statement, waiting_line = self._point_statement(method, waiting)
        net = loan.net_disbursed_amount
        self.assertEqual(loan.disbursement_cheque_state, 'compense')
        self.assertEqual(loan.disbursement_clearing_move_id, entry.statement_line_id.move_id)
        self.assertTrue(waiting_line.reconciled)
        self.assertAlmostEqual(self._balance(waiting), 0.0, places=2)
        self.assertAlmostEqual(self._balance(self.real_bank_account), -net, places=2)
        self.assertAlmostEqual(self._amounts()['out_transit'], 0.0, places=2)
        statement.action_mf_validate()
        self.assertEqual(self._row()['unexplained'], 0.0)

    def test_statement_pointing_clears_waiting_entry_cheque(self):
        self._check_pointing_clears('cheque', self.cheque_waiting)

    def test_statement_pointing_clears_waiting_entry_transfer(self):
        self._check_pointing_clears('bank_transfer', self.transfer_waiting)

    def test_cancel_pointing_puts_payment_back_on_hold(self):
        loan, entry, _statement, _line = self._point_statement('bank_transfer', self.transfer_waiting)
        entry._cancel_treatment_unchecked('test')
        self.assertEqual(loan.disbursement_cheque_state, 'en_attente')
        self.assertFalse(loan.disbursement_clearing_move_id)
        self.assertAlmostEqual(self._amounts()['out_transit'], loan.net_disbursed_amount, places=2)
        self.assertAlmostEqual(self._balance(self.real_bank_account), 0.0, places=2)

    def test_candidates_limited_to_the_statement_journal(self):
        other_journal = self.env['account.journal'].create({
            'name': 'Autre banque test', 'code': 'TBNK2', 'type': 'bank', 'company_id': self.env.company.id,
            'default_account_id': self.real_bank_account.id, 'microfinance_usage': 'credit'})
        loan = self._disburse('bank_transfer')
        line = loan.disbursement_move_id.line_ids.filtered(lambda l: l.account_id == self.transfer_waiting)
        entry = self._statement(0.0, -loan.net_disbursed_amount,
                                [{'name': 'x', 'amount_out': loan.net_disbursed_amount}]).mf_entry_ids
        self.assertIn(line, entry.candidate_line_ids)
        other_entry = self.env['account.bank.statement'].create({
            'journal_id': other_journal.id, 'mf_state': 'draft', 'mf_date_from': '2026-10-01',
            'mf_date_to': '2026-10-01', 'balance_start': 0.0, 'balance_end_real': -loan.net_disbursed_amount,
            'mf_entry_ids': [(0, 0, {'date': '2026-10-01', 'name': 'y', 'amount_out': loan.net_disbursed_amount})],
        }).mf_entry_ids
        self.assertNotIn(line, other_entry.candidate_line_ids, "Une autre banque ne doit pas voir cette attente.")

    # ------------------------------------------------------------------ rejet
    def test_reject_reverses_waiting_entry_for_cheque_and_transfer(self):
        for method, waiting in (('cheque', self.cheque_waiting), ('bank_transfer', self.transfer_waiting)):
            loan = self._disburse(method)
            loan.action_reject_disbursement_cheque(reason='Rejet')
            self.assertEqual(loan.disbursement_cheque_state, 'rejete', method)
            self.assertFalse(loan.disbursement_date)
            self.assertAlmostEqual(self._balance(waiting), 0.0, places=2)
            self.assertAlmostEqual(self._balance(self.real_bank_account), 0.0, places=2)
            self.assertAlmostEqual(self._amounts()['out_transit'], 0.0, places=2)

    def test_clear_action_available_for_transfer(self):
        loan = self._disburse('bank_transfer')
        action = loan.action_clear_disbursement_cheque()
        self.assertEqual(action['res_model'], 'account.move.line.writeoff.wizard')
