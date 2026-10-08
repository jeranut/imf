# -*- coding: utf-8 -*-
from odoo.exceptions import UserError, ValidationError

from .test_fond_partage import TestFondPartageBase


class TestFondJournalAuto(TestFondPartageBase):
    """Le journal d'une contribution est déduit du fonds : banque du fonds -> journal de fonds (usage
    « Fonds ») de cette banque, dans la société du fonds."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Bank, Account, Journal = cls.env['res.bank'], cls.env['account.account'], cls.env['account.journal']
        cls.bmoi = Bank.create({'name': 'BMOI auto (test)'})
        cls.bni = Bank.create({'name': 'BNI auto (test)'})
        cls.fdbm = cls._fund_journal('FDBMT', cls.bmoi, cls.env.company)
        cls.fdbn = cls._fund_journal('FDBNT', cls.bni, cls.env.company)
        cls.other_journal = Journal.create({
            'name': 'Autre banque (test)', 'code': 'OTHT', 'type': 'bank', 'company_id': cls.env.company.id,
            'default_account_id': Account.create({'name': 'Autre', 'code': 'TOTHBK', 'account_type': 'asset_cash',
                                                  'company_id': cls.env.company.id}).id})

    @classmethod
    def _fund_journal(cls, code, bank, company):
        account = cls.env['account.account'].create({
            'name': 'Banque ' + code, 'code': 'TBK' + code, 'account_type': 'asset_cash', 'company_id': company.id})
        return cls.env['account.journal'].create({
            'name': 'Fonds ' + code, 'code': code, 'type': 'bank', 'company_id': company.id,
            'default_account_id': account.id, 'microfinance_usage': 'fund', 'microfinance_bank_id': bank.id})

    def setUp(self):
        super().setUp()
        self._set_parent(self.company_a)

    def test_contribution_gets_fund_journal_of_the_fund_bank(self):
        fond_m = self._create_shared_fond(bank_id=self.bmoi.id, passer_gl=True)
        fond_n = self._create_shared_fond(name='Fonds BNI', bank_id=self.bni.id, passer_gl=True)
        self.assertEqual(fond_m.fund_journal_id, self.fdbm)
        self.assertEqual(fond_n.fund_journal_id, self.fdbn)
        self.assertEqual(self._create_contribution(fond_m).journal_id, self.fdbm)
        self.assertEqual(self._create_contribution(fond_n).journal_id, self.fdbn)

    def test_changing_the_fund_bank_recomputes_journal(self):
        fond = self._create_shared_fond(bank_id=self.bmoi.id)
        fond.bank_id = self.bni
        self.assertEqual(fond.fund_journal_id, self.fdbn)

    def test_other_journal_through_orm_is_refused(self):
        fond = self._create_shared_fond(bank_id=self.bmoi.id)
        contrib = self._create_contribution(fond)
        with self.assertRaises(ValidationError):
            contrib.write({'journal_id': self.other_journal.id})
        with self.assertRaises(ValidationError):
            self._create_contribution(fond, journal_id=self.other_journal.id)

    def test_fund_without_bank_blocks_validation(self):
        fond = self._create_shared_fond(bank_id=False, passer_gl=True)
        contrib = self._create_contribution(fond)
        self.assertFalse(contrib.journal_id)
        with self.assertRaises(UserError):
            contrib.action_post()
        self.assertEqual(contrib.state, 'draft')

    def test_fund_without_gl_does_not_need_a_bank(self):
        fond = self._create_shared_fond(bank_id=False, passer_gl=False)
        contrib = self._create_contribution(fond)
        contrib.action_post()
        self.assertEqual(contrib.state, 'posted')
        self.assertFalse(contrib.move_id)

    def test_bank_without_or_with_several_fund_journals_is_refused_at_fund_save(self):
        bank = self.env['res.bank'].create({'name': 'Banque sans journal (test)'})
        with self.assertRaises(ValidationError):
            self._create_shared_fond(bank_id=bank.id)
        self._fund_journal('DUP1', bank, self.env.company)
        self._fund_journal('DUP2', bank, self.env.company)
        with self.assertRaises(ValidationError):
            self._create_shared_fond(bank_id=bank.id)

    def test_bank_cannot_change_once_a_contribution_exists(self):
        fond = self._create_shared_fond(bank_id=self.bmoi.id)
        self._create_contribution(fond)
        with self.assertRaises(UserError):
            fond.bank_id = self.bni

    def test_entry_is_created_in_the_fund_company_even_if_entered_from_another_agency(self):
        company_b = self.company_b
        account_b = self.env['account.account'].create({
            'name': 'Dette bailleur B', 'code': 'TFONDGLB', 'account_type': 'liability_current', 'company_id': company_b.id})
        journal_b = self._fund_journal('FDBB', self.bmoi, company_b)
        # le dépôt passe par le compte de paiement en suspens entrant du journal de fonds (139100 en production)
        suspense_b = self.env['account.account'].create({
            'name': 'Entrant en suspens B', 'code': 'TFONDSB', 'account_type': 'asset_current',
            'reconcile': True, 'company_id': company_b.id})
        journal_b.inbound_payment_method_line_ids.write({'payment_account_id': suspense_b.id})
        fond = self._create_fond(name='Fonds agence B', scope='single_company', company_id=company_b.id,
                                 account_id=account_b.id, bank_id=self.bmoi.id)
        contrib = self._create_contribution(fond, saisie_company_id=self.env.company.id)  # saisie depuis company_a
        self.assertNotEqual(contrib.saisie_company_id, fond.company_id)
        contrib.action_post()
        self.assertEqual(contrib.move_id.company_id, company_b)
        self.assertEqual(contrib.move_id.journal_id.code, 'FDBB')

    def test_archiving_the_fund_journal_clears_the_fund_journal(self):
        fond = self._create_shared_fond(bank_id=self.bmoi.id)
        self.fdbm.active = False
        self.env.flush_all()
        self.assertFalse(fond.fund_journal_id)
