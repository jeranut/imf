# -*- coding: utf-8 -*-
from odoo.exceptions import UserError

from ..models.microfinance_fond_partage import largest_remainder
from .test_fond_liaison import TestFondLiaison


class TestFondOrigine(TestFondLiaison):
    """Compte d'origine par fonds (240xxx privé / 250xxx public), contrepartie du dépôt, parts exactes
    (plus fort reste), libellés et références, part gardée par les comptes en suspens."""

    def _auto_fond(self, **kwargs):
        vals = {'bank_id': self.bank.id, 'account_id': False, 'passer_gl': True}
        vals.update(kwargs)
        return self._create_shared_fond(**vals)

    def _deposit(self, fond, amount):
        contrib = self._create_contribution(fond, amount=amount)
        contrib.action_post()
        return contrib

    def _balance_where(self, company, codes):
        self.env.flush_all()
        self.env.cr.execute(
            "SELECT COALESCE(SUM(l.debit - l.credit), 0) FROM account_move_line l "
            "JOIN account_account a ON a.id = l.account_id "
            "WHERE l.company_id = %s AND a.code IN %s AND l.parent_state = 'posted'", (company.id, tuple(codes)))
        return self.env.cr.fetchone()[0]

    # (1) compte d'origine
    def test_private_fund_gets_240_account_public_gets_250(self):
        private = self._auto_fond(origine='prive')
        public = self._auto_fond(origine='public')
        self.assertTrue(private.account_id.code.startswith('240'))
        self.assertTrue(public.account_id.code.startswith('250'))
        for fond in (private, public):
            self.assertEqual(fond.account_id.account_type, 'liability_current')
            self.assertFalse(fond.account_id.reconcile)
            self.assertEqual(fond.account_id.company_id, self.hq)
            self.assertIn(fond.code, fond.account_id.name)
            self.assertTrue(fond.account_auto)

    def test_default_origin_is_private_and_two_funds_never_share_an_account(self):
        first, second = self._auto_fond(), self._auto_fond()
        self.assertEqual(first.origine, 'prive')
        self.assertNotEqual(first.account_id, second.account_id)
        self.assertEqual(int(second.account_id.code), int(first.account_id.code) + 1)

    def test_origin_change_renumbers_empty_account_then_is_locked(self):
        fond = self._auto_fond()
        account = fond.account_id
        fond.origine = 'public'
        self.assertEqual(fond.account_id, account)
        self.assertTrue(account.code.startswith('250'))
        self._deposit(fond, 100.0)
        with self.assertRaises(UserError):
            fond.origine = 'prive'
        with self.assertRaises(UserError):
            fond.account_id = self.fond_account

    def test_origin_can_be_chosen_from_the_contribution(self):
        fond = self._auto_fond()
        contrib = self._create_contribution(fond, amount=100.0)
        contrib.fond_origine = 'public'
        self.assertEqual(fond.origine, 'public')
        self.assertTrue(contrib.fond_account_id.code.startswith('250'))

    # (2) contrepartie du dépôt
    def test_deposit_counterpart_is_fund_account_never_company_default(self):
        decoy = self._acc(self.hq, 'T116000D', 'liability_current', False)
        self.hq.microfinance_fond_account_default_id = decoy
        fond = self._auto_fond()
        self.assertNotEqual(fond.account_id, decoy)
        contrib = self._deposit(fond, 700.0)
        credit = contrib.move_id.line_ids.filtered(lambda l: l.credit)
        debit = contrib.move_id.line_ids.filtered(lambda l: l.debit)
        self.assertEqual(credit.account_id, fond.account_id)
        self.assertNotEqual(credit.account_id, decoy)
        # le dépôt passe par le compte en suspens entrant, pas par la banque (rapprochement du relevé)
        self.assertEqual(debit.account_id, self.env['microfinance.fond.partage']._payment_account(self.fdbm, 'inbound'))
        self.assertNotEqual(debit.account_id, self.fdbm.default_account_id)

    # (3) parts exactes
    def test_largest_remainder_three_sevenths_four_sevenths(self):
        parts = largest_remainder(50000000.0, [3, 4], 0.01)
        self.assertEqual(parts, [21428571.43, 28571428.57])
        self.assertEqual(round(sum(parts), 2), 50000000.0)

    def test_largest_remainder_sum_is_exact_for_any_precision(self):
        for rounding in (0.01, 1.0, 0.001):
            for total in (100.0, 100000000.0, 1234.0):
                parts = largest_remainder(total, [1, 1, 1], rounding)
                self.assertAlmostEqual(sum(parts), total, places=6)
                self.assertLessEqual(round(max(parts) - min(parts), 6), rounding)

    def test_validation_normalizes_shares_to_exact_base(self):
        fond = self._auto_fond()
        self._deposit(fond, 100000.0)
        partage = self.env['microfinance.fond.partage'].create({'fond_id': fond.id, 'base_amount': 50000.0})
        lines = partage.line_ids.filtered(lambda l: l.company_id in (self.hq, self.agency))
        lines.filtered(lambda l: l.company_id == self.hq).write({'amount': 21428.56})
        lines.filtered(lambda l: l.company_id == self.agency).write({'amount': 28571.43})
        # 49999.99 réparti sur 50000.00 : un centime d'écart, ramené à la base à la validation
        partage.action_validate()
        self.assertEqual(round(sum(partage.line_ids.mapped('amount')), 2), 50000.0)

    def test_validation_refuses_incomplete_sharing(self):
        fond = self._auto_fond()
        self._deposit(fond, 100000.0)
        partage = self.env['microfinance.fond.partage'].create({'fond_id': fond.id, 'base_amount': 50000.0})
        partage.line_ids.filtered(lambda l: l.company_id == self.agency).write({'amount': 40000.0})
        with self.assertRaises(UserError):
            partage.action_validate()

    # (4) libellés, références, liens ; (5) miroir agence ; (8) part gardée
    def _shared(self, hq_amount, agency_amount):
        fond = self._auto_fond()
        self._deposit(fond, 100000.0)
        partage = self.env['microfinance.fond.partage'].create({
            'fond_id': fond.id, 'base_amount': hq_amount + agency_amount})
        partage.line_ids.filtered(lambda l: l.company_id == self.hq).write({'amount': hq_amount})
        partage.line_ids.filtered(lambda l: l.company_id == self.agency).write({'amount': agency_amount})
        partage.action_validate()
        return fond, partage

    def test_labels_reference_and_links_on_both_sides(self):
        fond, partage = self._shared(500.0, 300.0)
        moves = self._moves(partage)
        self.assertEqual(len(moves), 4)   # siège + agence + part gardée (2 pièces : journal de fonds, journal crédit)
        for move in moves:
            self.assertEqual(move.ref, partage.name)
            self.assertEqual(move.microfinance_fond_partage_id, partage)
            self.assertTrue(move.microfinance_fond_partage_line_id)
            self.assertIn(fond.code, move.line_ids[0].name)
        hq_move = moves.filtered(lambda m: m.microfinance_partage_side == 'hq')
        self.assertIn(self.agency.name, hq_move.line_ids[0].name)
        own = moves.filtered(lambda m: m.microfinance_partage_side == 'hq_own')
        self.assertTrue(own[0].line_ids[0].name.startswith('Fonds %s alloué à' % fond.code))

    def test_agency_mirror_in_agency_company_with_right_accounts(self):
        fond, partage = self._shared(500.0, 300.0)
        mirror = self._moves(partage).filtered(lambda m: m.microfinance_partage_side == 'agency')
        self.assertEqual(mirror.company_id, self.agency)
        self.assertEqual(mirror.journal_id, self.ag_journal)
        self.assertEqual({(l.account_id, l.debit, l.credit) for l in mirror.line_ids},
                         {(self.ag_in, 300.0, 0.0), (self.ag_liaison, 0.0, 300.0)})

    def test_kept_share_goes_through_suspense_accounts(self):
        fond, partage = self._shared(500.0, 300.0)
        own = self._moves(partage).filtered(lambda m: m.microfinance_partage_side == 'hq_own')
        self.assertEqual(own.company_id, self.hq)
        credit_journal = partage._credit_journal_for(self.fdbm, self.hq)
        inbound = partage._payment_account(credit_journal, 'inbound')
        outbound = partage._payment_account(self.fdbm, 'outbound')
        transfer = self.hq.transfer_account_id
        self.assertEqual({(l.journal_id, l.account_id, l.debit, l.credit) for l in own.line_ids},
                         {(credit_journal, inbound, 500.0, 0.0), (credit_journal, transfer, 0.0, 500.0),
                          (self.fdbm, transfer, 500.0, 0.0), (self.fdbm, outbound, 0.0, 500.0)})
        banks = {self.fdbm.default_account_id, credit_journal.default_account_id}
        self.assertFalse(set(own.line_ids.account_id) & banks)

    # (6) fonds sans compte
    def test_contribution_on_fund_without_account_is_refused(self):
        fond = self._auto_fond()
        contrib = self._create_contribution(fond, amount=100.0)
        self.env.flush_all()
        self.env.cr.execute("UPDATE microfinance_fond_credit SET account_id = NULL WHERE id = %s", (fond.id,))
        fond.invalidate_recordset()
        with self.assertRaises(UserError):
            contrib.action_post()

    # (7) compensation siège / agence
    def test_hq_and_agency_liaison_accounts_offset_after_full_sharing(self):
        fond, partage = self._shared(500.0, 300.0)
        hq_side = self._balance(self.hq_liaison)
        agency_side = self._balance(self.ag_liaison)
        self.assertEqual(hq_side + agency_side, 0.0)
        self.assertEqual(hq_side, 300.0)

    # annulation d'une contribution (extourne)
    def test_cancel_contribution_reverses_the_entry_and_frees_the_fund(self):
        fond = self._auto_fond()
        contrib = self._deposit(fond, 700.0)
        self.assertEqual(fond.total_contributions, 700.0)
        contrib.action_cancel()
        self.assertEqual(contrib.state, 'cancelled')
        self.assertEqual(fond.total_contributions, 0.0)
        reversal = self.env['account.move'].sudo().search([('reversed_entry_id', '=', contrib.move_id.id)])
        self.assertEqual(len(reversal), 1)
        self.assertEqual(self._balance(fond.account_id), 0.0)
        with self.assertRaises(UserError):
            contrib.action_cancel()

    def test_cancel_contribution_refused_when_fund_already_shared(self):
        fond, partage = self._shared(500.0, 300.0)
        contrib = fond.contribution_ids
        with self.assertRaises(UserError):
            contrib.action_cancel()
        partage.action_cancel()
        contrib.action_cancel()
        self.assertEqual(contrib.state, 'cancelled')
