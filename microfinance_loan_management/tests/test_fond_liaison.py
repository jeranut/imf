# -*- coding: utf-8 -*-
from odoo.exceptions import UserError

from .test_fond_partage import TestFondPartageBase


class TestFondLiaison(TestFondPartageBase):
    """Partage de fonds : écritures liées siège / agence, rapprochement, rapport d'écarts, annulation.
    Société courante (company_a) = société mère ; company_b = agence ; company_c = agence non configurée."""

    AMOUNT = 1000.0

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.hq, cls.agency, cls.agency2 = cls.company_a, cls.company_b, cls.company_c
        cls.bank = cls.env['res.bank'].create({'name': 'BMOI liaison (test)'})
        cls.hq_liaison = cls._acc(cls.hq, 'T301HQB', 'asset_current', True)
        cls.hq_out = cls._acc(cls.hq, 'T139500H', 'liability_current', True)
        cls.hq_bank = cls._acc(cls.hq, 'T131103H', 'asset_cash', False)
        cls.hq_credit_bank = cls._acc(cls.hq, 'T131101H', 'asset_cash', False)
        cls.hq_fond_account = cls.fond_account
        cls.fdbm = cls._journal(cls.hq, 'FDBM', cls.hq_bank, outbound=cls.hq_out, usage='fund')
        cls.hq_credit_bank = cls._journal(cls.hq, 'BMCR', cls.hq_credit_bank, usage='credit').default_account_id
        cls.hq_bank = cls.fdbm.default_account_id
        cls.ag_in = cls._acc(cls.agency, 'T139100A', 'asset_current', True)
        cls.ag_liaison = cls._acc(cls.agency, 'T301010A', 'asset_current', True)
        cls.ag_bank = cls._acc(cls.agency, 'T131101A', 'asset_cash', False)
        cls.ag_journal = cls._journal(cls.agency, 'BMCR', cls.ag_bank, inbound=cls.ag_in, usage='credit')
        cls.agency.microfinance_liaison_hq_account_id = cls.hq_liaison
        cls.agency.microfinance_liaison_agency_account_id = cls.ag_liaison
        # agence 2 : compte de liaison côté siège seulement (côté agence non configuré)
        cls.hq_liaison2 = cls._acc(cls.hq, 'T301HQC', 'asset_current', True)
        cls.agency2.microfinance_liaison_hq_account_id = cls.hq_liaison2

    @classmethod
    def _acc(cls, company, code, account_type, reconcile):
        Account = cls.env['account.account']
        acc = Account.search([('company_id', '=', company.id), ('code', '=', code)], limit=1)
        return acc or Account.create({'code': code, 'name': 'Test ' + code, 'account_type': account_type,
                                      'reconcile': reconcile, 'company_id': company.id})

    @classmethod
    def _journal(cls, company, code, default_account, inbound=None, outbound=None, usage=None):
        Journal = cls.env['account.journal']
        journal = Journal.search([('company_id', '=', company.id), ('code', '=', code)], limit=1)
        if not journal:
            journal = Journal.create({'name': code, 'code': code, 'type': 'bank', 'company_id': company.id,
                                      'default_account_id': default_account.id})
        if usage:
            journal.write({'microfinance_usage': usage, 'microfinance_bank_id': cls.bank.id})
        if inbound:
            journal.inbound_payment_method_line_ids.write({'payment_account_id': inbound.id})
        if outbound:
            journal.outbound_payment_method_line_ids.write({'payment_account_id': outbound.id})
        return journal

    def setUp(self):
        super().setUp()
        self._set_parent(self.hq)

    def _fond(self, passer_gl=True):
        fond = self._create_shared_fond(
            verification_disponibilite='at_disbursement', passer_gl=passer_gl,
            bank_id=self.bank.id,
            account_id=self.hq_fond_account.id)
        self._create_contribution(fond, amount=5000.0).action_post()
        return fond

    def _partage(self, fond, shares):
        partage = self.env['microfinance.fond.partage'].create({'fond_id': fond.id, 'base_amount': self.AMOUNT})
        for line in partage.line_ids:
            line.percent = shares.get(line.company_id, 0.0)
        return partage

    def _moves(self, partage):
        return self.env['account.move'].sudo().search([('microfinance_fond_partage_id', '=', partage.id)])

    def _validated(self, shares=None):
        partage = self._partage(self._fond(), shares or {self.agency: 100.0})
        partage.action_validate()
        return partage

    def _balance(self, account):
        self.env.flush_all()
        self.env.cr.execute(
            "SELECT COALESCE(SUM(debit - credit), 0) FROM account_move_line WHERE account_id = %s AND parent_state = 'posted'",
            (account.id,))
        return self.env.cr.fetchone()[0]

    def _statement(self, journal, amount, counterpart):
        return self.env['account.bank.statement.line'].sudo().create({
            'journal_id': journal.id, 'amount': amount, 'payment_ref': 'Relevé test',
            'date': '2026-10-08', 'counterpart_account_id': counterpart.id})

    def _reconcile(self, move, account, statement):
        lines = (move.line_ids | statement.move_id.line_ids).filtered(lambda l: l.account_id == account)
        lines.reconcile()

    def test_partage_creates_two_linked_moves_one_per_company(self):
        partage = self._validated()
        moves = self._moves(partage)
        self.assertEqual(len(moves), 2)
        hq_move = moves.filtered(lambda m: m.microfinance_partage_side == 'hq')
        ag_move = moves.filtered(lambda m: m.microfinance_partage_side == 'agency')
        self.assertEqual(hq_move.company_id, self.hq)
        self.assertEqual(ag_move.company_id, self.agency)
        self.assertEqual(hq_move.microfinance_fond_partage_line_id, ag_move.microfinance_fond_partage_line_id)
        self.assertEqual(hq_move.journal_id, self.fdbm)
        self.assertEqual(ag_move.journal_id, self.ag_journal)
        self.assertEqual({(l.account_id, l.debit, l.credit) for l in hq_move.line_ids},
                         {(self.hq_liaison, self.AMOUNT, 0.0), (self.hq_out, 0.0, self.AMOUNT)})
        self.assertEqual({(l.account_id, l.debit, l.credit) for l in ag_move.line_ids},
                         {(self.ag_in, self.AMOUNT, 0.0), (self.ag_liaison, 0.0, self.AMOUNT)})
        self.assertEqual({m.state for m in moves}, {'posted'})
        self.assertEqual(partage.line_ids.filtered(lambda l: l.company_id == self.agency).liaison_state, 'both')

    def test_bank_reconciliation_clears_139500_and_139100(self):
        partage = self._validated()
        moves = self._moves(partage)
        hq_move = moves.filtered(lambda m: m.microfinance_partage_side == 'hq')
        ag_move = moves.filtered(lambda m: m.microfinance_partage_side == 'agency')
        self.assertEqual(self._balance(self.hq_out), -self.AMOUNT)
        self.assertEqual(self._balance(self.ag_in), self.AMOUNT)
        self._reconcile(hq_move, self.hq_out, self._statement(self.fdbm, -self.AMOUNT, self.hq_out))
        self._reconcile(ag_move, self.ag_in, self._statement(self.ag_journal, self.AMOUNT, self.ag_in))
        self.assertEqual(self._balance(self.hq_out), 0.0)
        self.assertEqual(self._balance(self.ag_in), 0.0)

    def test_liaison_report_shows_gap_when_only_one_side_exists(self):
        partage = self._validated({self.agency2: 100.0})  # agence 2 : côté agence non configuré
        line = partage.line_ids.filtered(lambda l: l.company_id == self.agency2)
        self.assertEqual(line.liaison_state, 'hq_only')
        self.assertTrue(line.liaison_note)
        self.assertEqual(len(self._moves(partage)), 1)
        self.env.flush_all()
        row = self.env['microfinance.fond.liaison.report'].search([('line_id', '=', line.id)])
        self.assertEqual((row.state, row.hq_amount, row.agency_amount, row.difference), ('hq_only', self.AMOUNT, 0.0, self.AMOUNT))
        # l'agence est configurée : le bouton génère le côté agence, l'écart disparaît
        ag2_bank = self._acc(self.agency2, 'T131101C', 'asset_cash', False)
        ag2_in = self._acc(self.agency2, 'T139100C', 'asset_current', True)
        self._journal(self.agency2, 'BMCR', ag2_bank, inbound=ag2_in, usage='credit')
        self.agency2.microfinance_liaison_agency_account_id = self._acc(self.agency2, 'T301010C', 'asset_current', True)
        line.action_generate_agency_move()
        self.env.flush_all()
        self.env.invalidate_all()  # la vue SQL n'est pas suivie par le cache de l'ORM
        row = self.env['microfinance.fond.liaison.report'].search([('line_id', '=', line.id)])
        self.assertEqual((row.state, row.difference), ('ok', 0.0))
        self.assertEqual(len(self._moves(partage)), 2)
        solde = self.env['microfinance.fond.liaison.solde'].search([('company_id', '=', self.agency2.id)])
        self.assertEqual((solde.hq_balance, solde.agency_balance, solde.difference), (self.AMOUNT, self.AMOUNT, 0.0))

    def test_liaison_report_zero_when_both_sides_exist(self):
        partage = self._validated()
        line = partage.line_ids.filtered(lambda l: l.company_id == self.agency)
        self.env.flush_all()
        row = self.env['microfinance.fond.liaison.report'].search([('line_id', '=', line.id)])
        self.assertEqual((row.state, row.hq_amount, row.agency_amount, row.difference), ('ok', self.AMOUNT, self.AMOUNT, 0.0))

    def test_cancel_reverses_both_sides(self):
        partage = self._validated()
        originals = self._moves(partage)
        partage.action_cancel()
        self.assertEqual(partage.state, 'cancelled')
        for move in originals:
            reversal = self.env['account.move'].sudo().search([('reversed_entry_id', '=', move.id)])
            self.assertEqual(len(reversal), 1, move.microfinance_partage_side)
            self.assertEqual(reversal.state, 'posted')
        self.assertEqual(self._balance(self.hq_liaison), 0.0)
        self.assertEqual(self._balance(self.ag_liaison), 0.0)
        self.assertEqual(self._balance(self.hq_out), 0.0)
        self.assertEqual(self._balance(self.ag_in), 0.0)
        self.env.flush_all()
        row = self.env['microfinance.fond.liaison.report'].search(
            [('line_id', '=', partage.line_ids.filtered(lambda l: l.company_id == self.agency).id)])
        self.assertEqual(row.difference, 0.0)

    def test_cancel_refused_when_a_side_is_reconciled(self):
        partage = self._validated()
        hq_move = self._moves(partage).filtered(lambda m: m.microfinance_partage_side == 'hq')
        self._reconcile(hq_move, self.hq_out, self._statement(self.fdbm, -self.AMOUNT, self.hq_out))
        with self.assertRaises(UserError):
            partage.action_cancel()
        self.assertEqual(partage.state, 'validated')

    def test_parent_own_share_is_a_single_move_without_liaison(self):
        partage = self._validated({self.hq: 100.0})
        moves = self._moves(partage)
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves.microfinance_partage_side, 'hq_own')
        self.assertEqual({(l.account_id, l.debit, l.credit) for l in moves.line_ids},
                         {(self.hq_credit_bank, self.AMOUNT, 0.0), (self.hq_bank, 0.0, self.AMOUNT)})

    def test_no_moves_without_gl_or_without_fund_journal(self):
        # fonds sans passer_gl
        partage = self._partage(self._fond(passer_gl=False), {self.agency: 100.0})
        partage.action_validate()
        self.assertEqual(partage.state, 'validated')
        self.assertFalse(self._moves(partage))
        # fonds dont le journal de fonds a été archivé après les contributions : plus de journal, plus d'écriture
        fond = self._fond()
        self.fdbm.active = False
        self.env.flush_all()
        self.assertFalse(fond.fund_journal_id)
        partage = self._partage(fond, {self.agency: 100.0})
        partage.action_validate()
        self.assertEqual(partage.state, 'validated')
        self.assertFalse(self._moves(partage))
