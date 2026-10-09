# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.addons.base_accounting_kit.controllers.financial_report_controller import FinancialReportController

from ..controllers.financial_report import MfFinancialReportController
from ..models.microfinance_fond_partage import largest_remainder
from ..models.res_company import ResCompany
from .test_fond_liaison import TestFondLiaison

KIT = 'base_accounting_kit.'


class TestBilanResultat(TestFondLiaison):
    """Parts de partage entières, passif positif dans le Bilan, Compte de résultat par identifiant (et non par nom)."""

    @classmethod
    def setUpClass(cls):
        # base déjà configurée avec une société mère (MOWGLI) : les fixtures de départ la refuseraient
        with patch.object(ResCompany, '_get_microfinance_parent', lambda self: self.browse()):
            super().setUpClass()

    def _report_data(self, xmlid, company, lang='en_US'):
        report = self.env.ref(KIT + xmlid)
        wizard = self.env['financial.report'].with_company(company).with_context(lang=lang).new({
            'account_report_id': report.id, 'date_to': '2099-12-31', 'target_move': 'posted', 'company_id': company.id})
        data = {'date_from': False, 'date_to': '2099-12-31', 'enable_filter': False, 'debit_credit': False,
                'account_report_id': [report.id, report.name], 'target_move': 'posted', 'journal_ids': [],
                'view_format': 'vertical', 'company_id': [company.id, company.name],
                'filter_cmp': 'filter_no', 'date_from_cmp': False, 'date_to_cmp': False}
        data['used_context'] = wizard._build_contexts({'form': data})
        return wizard.get_account_lines(data)

    def _lines(self, xmlid, company, lang='en_US'):
        return {line['r_id']: line['balance'] for line in self._report_data(xmlid, company, lang)
                if line['type'] == 'report'}

    def _xml(self, xmlid):
        return self.env.ref(KIT + xmlid).id

    def _post(self, company, lines):
        journal = self.env['account.journal'].search([('company_id', '=', company.id), ('type', '=', 'general')], limit=1)
        if not journal:
            journal = self.env['account.journal'].create({'name': 'Divers test', 'code': 'TDIV', 'type': 'general',
                                                          'company_id': company.id})
        move = self.env['account.move'].with_company(company).create({
            'move_type': 'entry', 'journal_id': journal.id, 'date': '2026-10-09', 'company_id': company.id,
            'line_ids': [(0, 0, {'account_id': acc.id, 'debit': debit, 'credit': credit, 'name': 'test'})
                         for acc, debit, credit in lines]})
        move.action_post()
        return move

    def setUp(self):
        super().setUp()
        Report = self.env['account.financial.report']
        Report._mf_apply_result_under_equity()
        Report._mf_apply_balance_sheet_names()
        Report._mf_apply_net_profit_line()

    def _scenario(self):
        ag = self.agency
        bank = self._acc(ag, 'T131999A', 'asset_cash', False)
        income = self._acc(ag, 'T707301A', 'income', False)
        expense = self._acc(ag, 'T649000A', 'expense', False)
        depreciation = self._acc(ag, 'T681000A', 'expense_depreciation', False)
        payable = self._acc(ag, 'T441000A', 'liability_current', False)
        self._post(ag, [(bank, 100000.0, 0.0), (income, 0.0, 100000.0)])
        self._post(ag, [(expense, 40000.0, 0.0), (bank, 0.0, 40000.0)])
        self._post(ag, [(depreciation, 5000.0, 0.0), (payable, 0.0, 5000.0)])
        self.env.flush_all()  # le module tiers lit les soldes en SQL brut

    # ------------------------------------------------------------------ parts entières
    def test_share_of_50_millions_between_3_7_and_4_7_is_whole_and_exact(self):
        parts = largest_remainder(50000000.0, [3.0, 4.0], 1.0)
        self.assertEqual(parts, [21428571.0, 28571429.0])
        self.assertEqual(sum(parts), 50000000.0)

    def test_partage_lines_are_whole_ariary_and_sum_to_the_base(self):
        self.assertEqual(self.hq.microfinance_transfer_rounding_unit, 1.0)
        partage = self.env['microfinance.fond.partage'].create({'fond_id': self._fond().id, 'base_amount': 1000.0})
        partage.action_partager_egalement()
        amounts = partage.line_ids.mapped('amount')
        self.assertEqual(sum(amounts), 1000.0)
        self.assertTrue(all(a == int(a) for a in amounts))
        partage.write({'base_amount': 50000000.0})
        amounts = partage.line_ids.mapped('amount')
        self.assertEqual(sum(amounts), 50000000.0)
        self.assertTrue(all(a == int(a) for a in amounts))

    def test_currency_precision_is_unchanged(self):
        self.assertEqual(self.env.ref('base.MGA').decimal_places, 2)

    # ------------------------------------------------------------------ signes
    def test_signs_script_is_idempotent_and_targets_liability_and_equity(self):
        Report = self.env['account.financial.report']
        Report._mf_apply_liability_signs()
        self.assertEqual(Report._mf_apply_liability_signs(), [])
        self.assertEqual(self.env.ref(KIT + 'account_financial_report_liabilitysum0').sign, '-1')
        self.assertEqual(self.env.ref(KIT + 'account_financial_report_equitysection0').sign, '-1')
        self.assertEqual(self.env.ref(KIT + 'account_financial_report_assets0').sign, '1')

    def test_balance_check_uses_the_positive_equation(self):
        config = {'section_rank': {'ACTIF': 0, 'PASSIF': 1, 'CAPITAUX PROPRES': 2}}
        lines = [{'name': 'ACTIF', 'parent': False, 'balance': 300.0},
                 {'name': 'PASSIF', 'parent': False, 'balance': 100.0},
                 {'name': 'CAPITAUX PROPRES', 'parent': False, 'balance': 200.0}]
        self.assertTrue(MfFinancialReportController()._get_balance_sheet_check(lines, config)['ok'])
        self.assertFalse(FinancialReportController()._get_balance_sheet_check(lines, config)['ok'])  # ancienne équation

    # ------------------------------------------------------------------ Bilan et Compte de résultat
    def test_balance_sheet_and_profit_loss_agree_in_both_languages(self):
        self._scenario()
        for lang in ('fr_FR', 'en_US'):
            bs = self._lines('account_financial_report_balancesheet0', self.agency, lang)
            pl = self._lines('account_financial_report_profitandloss0', self.agency, lang)
            self.assertEqual(pl[self._xml('account_financial_report_profitandloss0')], 55000.0, lang)
            self.assertEqual(pl[self._xml('account_financial_report_income0')], 100000.0, lang)
            self.assertEqual(pl[self._xml('account_financial_report_expense0')], 45000.0, lang)
            assets = bs[self._xml('account_financial_report_assets0')]
            liability = bs[self._xml('account_financial_report_liabilitysum0')]
            equity = bs[self._xml('account_financial_report_equitysection0')]
            result = bs[self._xml('account_financial_report_profitloss_toreport0')]
            self.assertEqual(assets, 60000.0, lang)
            self.assertEqual(result, pl[self._xml('account_financial_report_profitandloss0')], lang)
            self.assertEqual(liability, 5000.0, lang)    # dettes seules
            self.assertEqual(equity, 55000.0, lang)      # résultat de l'exercice sous CAPITAUX PROPRES
            self.assertEqual(assets, liability + equity, lang)

    def test_expense_line_does_not_depend_on_its_translated_name(self):
        self._scenario()
        regular = self.env.ref(KIT + 'account_financial_report_expense_regular0')
        before = self._lines('account_financial_report_profitandloss0', self.agency)[regular.id]
        self.env['res.lang']._activate_lang('fr_FR')
        regular.with_context(lang='fr_FR').name = 'Charges de fonctionnement'
        after = self._lines('account_financial_report_profitandloss0', self.agency, 'fr_FR')[regular.id]
        self.assertEqual(before, 45000.0)
        self.assertEqual(after, before)

    # ------------------------------------------------------------------ Compte de résultat : produits et charges positifs
    def test_profit_loss_signs_script_is_idempotent_and_leaves_the_balance_sheet_alone(self):
        Report = self.env['account.financial.report']
        Report._mf_apply_profit_loss_signs()
        self.assertEqual(Report._mf_apply_profit_loss_signs(), [])
        self.assertEqual(Report._mf_apply_profit_loss_signs(dry_run=True), [])
        self.assertEqual(self.env.ref(KIT + 'account_financial_report_other_income0').sign, '-1')
        self.assertEqual(self.env.ref(KIT + 'account_financial_report_expense0').sign, '1')
        self.assertEqual(self.env.ref(KIT + 'account_financial_report_assets0').sign, '1')
        self.assertEqual(self.env.ref(KIT + 'account_financial_report_liabilitysum0').sign, '-1')

    def test_profit_loss_shows_positive_products_and_charges_and_net_result(self):
        ag = self.agency
        bank = self._acc(ag, 'T131999B', 'asset_cash', False)
        subvention = self._acc(ag, 'T762000B', 'income_other', False)
        charge = self._acc(ag, 'T622000B', 'expense', False)
        self._post(ag, [(bank, 100000000.0, 0.0), (subvention, 0.0, 100000000.0)])
        self._post(ag, [(charge, 40000000.0, 0.0), (bank, 0.0, 40000000.0)])
        self.env.flush_all()
        for lang in ('fr_FR', 'en_US'):
            data = self._report_data('account_financial_report_profitandloss0', ag, lang)
            by_id = {line['r_id']: line['balance'] for line in data if line['type'] == 'report'}
            self.assertEqual(by_id[self._xml('account_financial_report_income0')], 100000000.0, lang)   # PRODUIT
            self.assertEqual(by_id[self._xml('account_financial_report_other_income0')], 100000000.0, lang)
            self.assertEqual(by_id[self._xml('financial_report_gross_profit')], 0.0, lang)
            self.assertEqual(by_id[self._xml('account_financial_report_expense0')], 40000000.0, lang)   # CHARGE
            self.assertEqual(by_id[self._xml('account_financial_report_expense_regular0')], 40000000.0, lang)
            self.assertEqual(by_id[self._xml('account_financial_report_profitandloss0')], 60000000.0, lang)  # résultat net
            self.assertFalse([line for line in data if (line.get('balance') or 0.0) < 0.0],
                             'Aucune ligne négative pour un montant normal (%s)' % lang)
            account_lines = [line for line in data if line['type'] == 'account' and line['name'].startswith('T762000B')]
            self.assertEqual([line['balance'] for line in account_lines], [100000000.0], lang)
            bs = self._lines('account_financial_report_balancesheet0', ag, lang)
            self.assertEqual(bs[self._xml('account_financial_report_profitloss_toreport0')], 60000000.0, lang)
            assets = bs[self._xml('account_financial_report_assets0')]
            self.assertEqual(assets, 60000000.0, lang)
            self.assertEqual(assets, bs[self._xml('account_financial_report_liabilitysum0')]
                             + bs[self._xml('account_financial_report_equitysection0')], lang)

    # ------------------------------------------------------------------ résultat sous capitaux propres, résultat net
    def _scenario_capitaux(self, company):
        bank = self._acc(company, 'T131999C', 'asset_cash', False)
        subvention = self._acc(company, 'T762000C', 'income_other', False)
        charge = self._acc(company, 'T622000C', 'expense', False)
        capital = self._acc(company, 'T563000C', 'equity', False)
        report_nouveau = self._acc(company, 'T581000C', 'equity', False)
        self._post(company, [(bank, 100000000.0, 0.0), (subvention, 0.0, 100000000.0)])
        self._post(company, [(charge, 40000000.0, 0.0), (bank, 0.0, 40000000.0)])
        self._post(company, [(bank, 10000000.0, 0.0), (capital, 0.0, 10000000.0)])
        self._post(company, [(bank, 5000000.0, 0.0), (report_nouveau, 0.0, 5000000.0)])
        self.env.flush_all()

    def test_result_sits_under_equity_and_balance_sheet_balances_in_both_languages(self):
        self._scenario_capitaux(self.agency)
        result_line = self.env.ref(KIT + 'account_financial_report_profitloss_toreport0')
        self.assertEqual(result_line.parent_id, self.env.ref(KIT + 'account_financial_report_equitysection0'))
        net_profit = self.env.ref('microfinance_loan_management.financial_report_net_profit')
        for lang in ('fr_FR', 'en_US'):
            pl = self._lines('account_financial_report_profitandloss0', self.agency, lang)
            self.assertEqual(pl[net_profit.id], 60000000.0, lang)                                        # Résultat net
            self.assertEqual(pl[self._xml('account_financial_report_profitandloss0')], 60000000.0, lang)
            self.assertEqual(pl[self._xml('account_financial_report_income0')], 100000000.0, lang)       # inchangés
            self.assertEqual(pl[self._xml('account_financial_report_expense0')], 40000000.0, lang)
            bs = self._lines('account_financial_report_balancesheet0', self.agency, lang)
            self.assertEqual(bs[result_line.id], 60000000.0, lang)
            self.assertEqual(bs[result_line.id], pl[net_profit.id], lang)
            self.assertEqual(bs[self._xml('account_financial_report_equity0')], 15000000.0, lang)
            self.assertEqual(bs[self._xml('account_financial_report_equitysection0')], 75000000.0, lang)
            self.assertEqual(bs[self._xml('account_financial_report_liabilitysum0')], 0.0, lang)
            self.assertEqual(bs[self._xml('account_financial_report_assets0')], 75000000.0, lang)
            lines = self._report_data('account_financial_report_balancesheet0', self.agency, lang)
            by_r = {line['r_id']: line for line in lines if line['type'] == 'report'}
            self.assertEqual(by_r[result_line.id]['parent'], by_r[self._xml('account_financial_report_equitysection0')]['id'], lang)

    def test_controller_balance_check_is_ok_with_the_result_under_equity(self):
        self._scenario_capitaux(self.agency)
        lines = [{'name': name, 'parent': False, 'balance': balance} for name, balance in
                 (('ACTIF', 75000000.0), ('PASSIF', 0.0), ('CAPITAUX PROPRES', 75000000.0))]
        check = MfFinancialReportController()._get_balance_sheet_check(
            lines, {'section_rank': {'ACTIF': 0, 'PASSIF': 1, 'CAPITAUX PROPRES': 2}})
        self.assertTrue(check['ok'])

    def test_sub_lines_have_distinct_labels_and_parents_keep_theirs(self):
        for lang in ('fr_FR', 'en_US'):
            names = {xmlid: self.env.ref(KIT + xmlid).with_context(lang=lang).name for xmlid in (
                'account_financial_report_liability0', 'account_financial_report_asset_current0')}
            self.assertEqual(names['account_financial_report_liability0'], 'Dettes', lang)
            self.assertEqual(names['account_financial_report_asset_current0'], 'Autres actifs circulants', lang)
        self.assertEqual(self.env.ref(KIT + 'account_financial_report_liabilitysum0').with_context(lang='en_US').name, 'Liability')
        self.assertEqual(self.env.ref(KIT + 'account_financial_report_asset_current_group0').with_context(lang='en_US').name,
                         'Current Assets Group')

    def test_structure_scripts_are_idempotent(self):
        Report = self.env['account.financial.report']
        before = Report.search_count([])
        self.assertEqual(Report._mf_apply_result_under_equity(), [])
        self.assertEqual(Report._mf_apply_balance_sheet_names(), [])
        self.assertFalse(Report._mf_apply_net_profit_line())
        self.assertEqual(Report.search_count([]), before)
        self.assertEqual(self.env['ir.model.data'].search_count([
            ('module', '=', 'microfinance_loan_management'), ('name', '=', 'financial_report_net_profit')]), 1)

    def test_balance_sheet_of_a_company_without_entries_is_all_zero(self):
        for lang in ('fr_FR', 'en_US'):
            for xmlid in ('account_financial_report_balancesheet0', 'account_financial_report_profitandloss0'):
                data = self._report_data(xmlid, self.agency2, lang)
                self.assertTrue(data)
                self.assertFalse([line for line in data if line['balance']], '%s %s' % (xmlid, lang))
