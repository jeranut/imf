# -*- coding: utf-8 -*-
"""Paiement du net des bulletins en transit (139500) et tuile « Trésorerie d'exploitation ».

TransactionCase : tout est annulé. Sociétés, comptes (codes PCEC), journaux d'exploitation, règle NET, bulletins et
pièces de bulletin sont créés dans le test ; aucun nom de société ou de banque de production n'est utilisé.
"""
from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase

NET = 680500.0


class TestPayslipPayment(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Company = cls.env['res.company']
        cls.company_a = Company.create({'name': 'Siège paie (test)', 'agency_code': 'PZ1'})
        cls.company_b = Company.create({'name': 'Agence paie B (test)', 'agency_code': 'PZ2'})
        cls.env.user.company_ids = [(4, cls.company_a.id), (4, cls.company_b.id)]
        cls.env = cls.env(context=dict(cls.env.context, allowed_company_ids=[cls.company_a.id, cls.company_b.id]))
        cls.env['ir.config_parameter'].sudo().set_param('microfinance.parent_company_id', cls.company_a.id)
        cls.bmoi = cls.env['res.bank'].create({'name': 'BMOI paie (test)'})
        cls.bni = cls.env['res.bank'].create({'name': 'BNI paie (test)'})
        cls.setup_a = cls._setup_company(cls.company_a, ('X1', 'X2'))
        cls.setup_b = cls._setup_company(cls.company_b, ('Y1',))
        cls.bmop, cls.bnop = cls.setup_a['journals']
        cls.company_a.microfinance_operating_journal_id = cls.bmop
        cls.company_b.microfinance_operating_journal_id = cls.setup_b['journals'][0]

    # ------------------------------------------------------------------ fixtures
    @classmethod
    def _acc(cls, company, code, account_type, reconcile):
        return cls.env['account.account'].create({
            'code': code, 'name': 'Test ' + code, 'account_type': account_type, 'reconcile': reconcile,
            'company_id': company.id})

    @classmethod
    def _setup_company(cls, company, codes):
        acc = lambda *a: cls._acc(company, *a)  # noqa: E731
        res = {
            'due': acc('315100', 'liability_current', True),
            'out': acc('139500', 'liability_current', True),
            'in': acc('139100', 'asset_current', True),
            'charge': acc('652100', 'expense', False),
            'equity': acc('101000', 'equity', False),
            'suspense': acc('324100', 'asset_current', True),
        }
        res['journals'] = []
        for index, code in enumerate(codes):
            bank_account = acc('13110%d' % (4 + index), 'asset_cash', False)
            journal = cls.env['account.journal'].create({
                'name': 'Exploitation %s' % code, 'code': code, 'type': 'bank', 'company_id': company.id,
                'default_account_id': bank_account.id, 'suspense_account_id': res['suspense'].id,
                'microfinance_usage': 'operating', 'microfinance_bank_id': (cls.bmoi if index == 0 else cls.bni).id})
            journal.inbound_payment_method_line_ids.write({'payment_account_id': res['in'].id})
            journal.outbound_payment_method_line_ids.write({'payment_account_id': res['out'].id})
            res['journals'].append(journal)
        res['misc'] = cls.env['account.journal'].create({
            'name': 'Paie test', 'code': 'PAYT', 'type': 'general', 'company_id': company.id})
        category = cls.env.ref('hr_payroll_community.NET', raise_if_not_found=False) or cls.env[
            'hr.salary.rule.category'].search([('code', '=', 'NET')], limit=1)
        res['rule'] = cls.env['hr.salary.rule'].create({
            'name': 'Net (test %s)' % company.name, 'code': 'NET', 'category_id': category.id})
        res['rule'].with_company(company).credit_account_id = res['due']
        res['category'] = category
        return res

    def _opening(self, journal, amount, setup):
        move = self.env['account.move'].create({
            'move_type': 'entry', 'journal_id': setup['misc'].id, 'date': fields.Date.today(),
            'line_ids': [
                (0, 0, {'account_id': journal.default_account_id.id, 'debit': amount, 'credit': 0.0, 'name': 'Ouverture'}),
                (0, 0, {'account_id': setup['equity'].id, 'debit': 0.0, 'credit': amount, 'name': 'Ouverture'})]})
        move.action_post()
        return move

    def _slip(self, company=None, setup=None, net=NET, state='done', post=True, name='Employé'):
        company = company or self.company_a
        setup = setup or self.setup_a
        employee = self.env['hr.employee'].create({'name': '%s %s' % (name, self.env['hr.employee'].search_count([])),
                                                   'company_id': company.id})
        contract = self.env['hr.contract'].create({
            'name': 'Contrat %s' % employee.name, 'employee_id': employee.id, 'company_id': company.id,
            'wage': 1000000.0, 'date_start': '2026-01-01', 'state': 'open'})
        slip = self.env['hr.payslip'].with_company(company).create({
            'employee_id': employee.id, 'company_id': company.id, 'name': 'Bulletin %s' % employee.name,
            'contract_id': contract.id, 'date_from': '2026-11-01', 'date_to': '2026-11-30',
            'number': 'N-%s' % employee.id})
        self.env['hr.payslip.line'].create({
            'slip_id': slip.id, 'contract_id': contract.id, 'salary_rule_id': setup['rule'].id, 'employee_id': employee.id,
            'name': 'Net', 'code': 'NET', 'category_id': setup['category'].id, 'amount': net, 'quantity': 1.0,
            'rate': 100.0, 'sequence': 100})
        if post:
            move = self.env['account.move'].create({
                'move_type': 'entry', 'journal_id': setup['misc'].id, 'date': slip.date_to,
                'line_ids': [
                    (0, 0, {'account_id': setup['charge'].id, 'debit': net, 'credit': 0.0, 'name': slip.name}),
                    (0, 0, {'account_id': setup['due'].id, 'debit': 0.0, 'credit': net, 'name': slip.name})]})
            move.action_post()
            slip.move_id = move
        slip.state = state
        return slip

    def _pay(self, slips, **kwargs):
        payment = self.env['hr.payslip.payment']._create_from_payslips(slips)
        payment.write(kwargs)
        payment.action_validate()
        return payment

    def _bank_balance(self, journal):
        lines = self.env['account.move.line'].search([
            ('account_id', '=', journal.default_account_id.id), ('parent_state', '=', 'posted')])
        return sum(lines.mapped('balance'))

    def _transit_balance(self, account):
        lines = self.env['account.move.line'].search([
            ('account_id', '=', account.id), ('parent_state', '=', 'posted'), ('reconciled', '=', False)])
        return sum(lines.mapped('amount_residual'))

    def _statement_out(self, journal, bank_line, amount=None, name='Virement salaires'):
        amount = amount or abs(bank_line.balance)
        statement = self.env['account.bank.statement'].create({
            'journal_id': journal.id, 'mf_state': 'draft', 'mf_date_from': '2026-11-01', 'mf_date_to': '2026-11-30',
            'balance_start': 0.0, 'balance_end_real': -amount,
            'mf_entry_ids': [(0, 0, {'date': '2026-11-28', 'name': name, 'amount_out': amount})]})
        entry = statement.mf_entry_ids
        entry.write({'treatment': 'reconcile', 'target_line_id': bank_line.id})
        entry.action_treat()
        self.env.invalidate_all()
        return entry

    # ------------------------------------------------------------------ paiement individuel
    def test_single_payslip_creates_net_payment_in_transit(self):
        self._opening(self.bmop, 3000000.0, self.setup_a)
        slip = self._slip()
        self.assertEqual(slip.mf_bank_status, 'unpaid')
        # « Marquer Payé » prépare un brouillon : l'état ne change qu'à la validation
        action = slip.action_payslip_paid()
        payment = self.env['hr.payslip.payment'].browse(action['res_id'])
        self.assertEqual((payment.state, slip.state, payment.journal_id), ('draft', 'done', self.bmop))
        payment.action_validate()
        move = payment.move_id
        self.assertEqual(move.journal_id, self.bmop)
        lines = {l.account_id: (l.debit, l.credit) for l in move.line_ids}
        self.assertEqual(lines, {self.setup_a['due']: (NET, 0.0), self.setup_a['out']: (0.0, NET)})
        slip_line = slip.move_id.line_ids.filtered(lambda l: l.credit)
        self.assertTrue(slip_line.reconciled)
        self.assertEqual(slip_line.matched_debit_ids.debit_move_id.move_id, move)
        # 139500 reste en transit ; la banque (131104) n'est pas touchée
        self.assertFalse(move.line_ids.filtered(lambda l: l.credit).reconciled)
        self.assertEqual(self._bank_balance(self.bmop), 3000000.0)
        self.assertEqual((slip.state, slip.paid, slip.mf_bank_status), ('paid', True, 'transit'))
        self.assertTrue(slip.message_ids.filtered(lambda m: 'Net payé en transit' in (m.body or '')))

    def test_payment_with_other_operating_journal(self):
        slip = self._slip()
        payment = self.env['hr.payslip.payment']._create_from_payslips(slip)
        payment.journal_id = self.bnop
        payment.action_validate()
        self.assertEqual(payment.move_id.journal_id, self.bnop)
        self.assertEqual(payment.bank_id, self.bni)

    def test_non_operating_journal_refused(self):
        slip = self._slip()
        payment = self.env['hr.payslip.payment']._create_from_payslips(slip)
        payment.journal_id = self.setup_a['misc']
        with self.assertRaises(UserError):
            payment.action_validate()

    def test_user_without_payroll_group_refused(self):
        slip = self._slip()
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Sans paie (test)', 'login': 'sans_paie_test', 'company_id': self.company_a.id,
            'company_ids': [(6, 0, self.company_a.ids)],
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])]})
        with self.assertRaises(AccessError):
            slip.with_user(user).action_payslip_paid()

    # ------------------------------------------------------------------ lot
    def test_batch_of_three_one_grouped_move(self):
        slips = self._slip(net=100000.0) | self._slip(net=200000.0) | self._slip(net=300000.0)
        run = self.env['hr.payslip.run'].create({'name': 'Novembre test'})
        slips.write({'payslip_run_id': run.id})
        action = run.action_payslip_paid()
        payment = self.env['hr.payslip.payment'].browse(action['res_id'])
        payment.action_validate()
        move = payment.move_id
        self.assertEqual(len(move.line_ids.filtered('debit')), 3)
        out = move.line_ids.filtered('credit')
        self.assertEqual((len(out), out.credit), (1, 600000.0))
        self.assertEqual(set(slips.mapped('mf_bank_status')), {'transit'})
        self.assertEqual(set(slips.mapped('state')), {'paid'})
        self.assertTrue(run.message_ids.filtered(lambda m: 'Paiement de salaires en transit' in (m.body or '')))
        self.assertEqual(len(self.env['account.move'].search([('mf_salary_payment_id', '=', payment.id)])), 1)

    def test_batch_split_bank_lines_one_credit_per_employee(self):
        slips = self._slip(net=100000.0) | self._slip(net=200000.0)
        payment = self._pay(slips, split_bank_lines=True)
        self.assertEqual(sorted(payment.move_id.line_ids.filtered('credit').mapped('credit')), [100000.0, 200000.0])
        first = payment.line_ids.filtered(lambda l: l.amount == 100000.0)
        self._statement_out(self.bmop, first.bank_line_id)
        self.env.invalidate_all()
        by_amount = {l.amount: l.payslip_id.mf_bank_status for l in payment.line_ids}
        self.assertEqual(by_amount, {100000.0: 'confirmed', 200000.0: 'transit'})

    # ------------------------------------------------------------------ relevé
    def test_statement_line_reconciles_139500(self):
        self._opening(self.bmop, 3000000.0, self.setup_a)
        slip = self._slip()
        payment = self._pay(slip)
        self._statement_out(self.bmop, payment.line_ids.bank_line_id)
        self.assertEqual(self._transit_balance(self.setup_a['out']), 0.0)
        self.assertEqual(self._bank_balance(self.bmop), 3000000.0 - NET)
        self.assertEqual(slip.mf_bank_status, 'confirmed')

    # ------------------------------------------------------------------ refus
    def test_double_payment_refused(self):
        slip = self._slip()
        self._pay(slip)
        with self.assertRaises(UserError):
            slip.action_payslip_paid()
        with self.assertRaises(UserError):
            self.env['hr.payslip.payment']._create_from_payslips(slip)
        slip.state = 'done'   # même remis « Validé », le paiement actif empêche un second paiement
        with self.assertRaises(UserError):
            self.env['hr.payslip.payment']._create_from_payslips(slip)

    def test_zero_or_negative_net_refused(self):
        for net in (0.0, -50.0):
            slip = self._slip(net=net, post=False)
            with self.assertRaises(UserError) as caught:
                slip.action_payslip_paid()
            self.assertIn('nul ou négatif', str(caught.exception))

    def test_payment_above_net_refused(self):
        slip = self._slip()
        payment = self.env['hr.payslip.payment']._create_from_payslips(slip)
        with self.assertRaises(ValidationError):
            payment.line_ids.amount = NET + 1.0

    def test_only_done_payslip_can_be_paid(self):
        slip = self._slip(state='verify')
        with self.assertRaises(UserError):
            slip.action_payslip_paid()

    # ------------------------------------------------------------------ annulation
    def test_cancel_before_statement_reverses_and_restores(self):
        slip = self._slip()
        payment = self._pay(slip)
        payment.action_cancel()
        self.assertEqual((payment.state, slip.state, slip.paid, slip.mf_bank_status), ('cancelled', 'done', False,
                                                                                      'unpaid'))
        self.assertTrue(payment.reversal_move_id)
        self.assertFalse(slip.move_id.line_ids.filtered(lambda l: l.credit).reconciled)
        self.assertEqual(self._transit_balance(self.setup_a['out']), 0.0)
        # le bulletin peut être payé à nouveau
        self.assertEqual(self._pay(slip).state, 'posted')

    def test_cancel_after_statement_refused(self):
        slip = self._slip()
        payment = self._pay(slip)
        self._statement_out(self.bmop, payment.line_ids.bank_line_id)
        with self.assertRaises(UserError) as caught:
            payment.action_cancel()
        self.assertIn('rapprochée', str(caught.exception))
        self.assertEqual((payment.state, slip.state), ('posted', 'paid'))

    # ------------------------------------------------------------------ montants
    def test_amount_rounded_to_currency(self):
        slip = self._slip(net=1000.004)
        currency = slip.company_id.currency_id
        payment = self.env['hr.payslip.payment']._create_from_payslips(slip)
        self.assertEqual(payment.amount_total, currency.round(1000.004))
        payment.action_validate()
        self.assertEqual(payment.move_id.line_ids.filtered('credit').credit, currency.round(1000.004))

    def test_slip_already_paid_without_payment_untouched(self):
        old = self._slip(state='paid')
        before = (old.state, old.paid, old.move_id.id)
        new = self._slip()
        self._pay(new)
        self.assertEqual(old.mf_bank_status, 'unpaid')
        self.assertEqual((old.state, old.paid, old.move_id.id), before)
        self.assertFalse(old.payment_line_ids)

    def test_other_company_journal_untouched(self):
        slip_a = self._slip()
        slip_b = self._slip(self.company_b, self.setup_b)
        pay_a = self._pay(slip_a)
        pay_b = self._pay(slip_b)
        self.assertEqual(pay_a.journal_id.company_id, self.company_a)
        self.assertEqual(pay_b.journal_id.company_id, self.company_b)
        self.assertEqual(pay_b.move_id.company_id, self.company_b)
        lines_b = self.env['account.move.line'].search([('journal_id', '=', self.setup_b['journals'][0].id)])
        self.assertEqual(lines_b.mapped('move_id'), pay_b.move_id)
        with self.assertRaises(UserError):
            self.env['hr.payslip.payment']._create_from_payslips(slip_a | slip_b)

    def test_warning_when_above_available_balance_is_not_blocking(self):
        self._opening(self.bmop, 100000.0, self.setup_a)
        slip = self._slip()
        payment = self.env['hr.payslip.payment']._create_from_payslips(slip)
        self.assertIn('dépasse le solde disponible', payment.warning_message)
        payment.action_validate()   # non bloquant
        self.assertEqual(payment.state, 'posted')
        self.assertFalse(payment.warning_message)

    # ------------------------------------------------------------------ tuile trésorerie
    def _tiles(self, company=None, user=None):
        Loan = self.env['microfinance.loan']
        if user:
            Loan = Loan.with_user(user)
        Loan = Loan.with_company(company or self.company_a).with_context(
            allowed_company_ids=[(company or self.company_a).id])
        return {t['key']: t for t in Loan._get_overview_tiles()}

    def _rows(self, tiles):
        return {row['bank']: row for row in tiles['operating_treasury']['journals']}

    def test_treasury_tile_amounts_and_statement(self):
        self._opening(self.bmop, 3000000.0, self.setup_a)
        payment = self._pay(self._slip())
        receipt = self.env['account.move'].create({
            'move_type': 'entry', 'journal_id': self.bmop.id, 'date': fields.Date.today(),
            'line_ids': [
                (0, 0, {'account_id': self.setup_a['in'].id, 'debit': 1000000.0, 'credit': 0.0, 'name': 'Don'}),
                (0, 0, {'account_id': self.setup_a['equity'].id, 'debit': 0.0, 'credit': 1000000.0, 'name': 'Don'})]})
        receipt.action_post()
        row = self._rows(self._tiles())[self.bmoi.name]
        self.assertEqual((row['bank_balance'], row['out_transit'], row['in_transit'], row['available']),
                         (3000000.0, NET, 1000000.0, 3000000.0 - NET))
        self._statement_out(self.bmop, payment.line_ids.bank_line_id)
        row = self._rows(self._tiles())[self.bmoi.name]
        self.assertEqual((row['bank_balance'], row['out_transit'], row['available']),
                         (3000000.0 - NET, 0.0, 3000000.0 - NET))
        # la tuile est nommée par sa banque, jamais par un code de journal
        tile = self._tiles()['operating_treasury']
        self.assertNotIn(self.bmop.code, ' '.join(item['label'] for item in tile['secondary_items']))

    def test_two_operating_journals_two_rows_and_links(self):
        self._opening(self.bmop, 3000000.0, self.setup_a)
        self._opening(self.bnop, 500000.0, self.setup_a)
        tiles = self._tiles()
        rows = self._rows(tiles)
        self.assertEqual((rows[self.bmoi.name]['bank_balance'], rows[self.bni.name]['bank_balance']),
                         (3000000.0, 500000.0))
        tile = tiles['operating_treasury']
        # clic sur la banque -> le journal ; clic sur « En transit » -> les lignes concernées
        opens = [i['link'] for i in tile['secondary_items'] if i.get('link', {}).get('model') == 'account.journal']
        self.assertEqual({l['res_id'] for l in opens}, {self.bmop.id, self.bnop.id})
        transit = next(i['link'] for i in tile['secondary_items'] if i['label'].endswith('Paiements en transit')
                       and self.bmoi.name in i['label'])
        self.assertEqual(transit['model'], 'account.move.line')

    def test_agency_user_sees_only_own_company(self):
        self._opening(self.bmop, 3000000.0, self.setup_a)
        self._opening(self.setup_b['journals'][0], 70000.0, self.setup_b)
        group = self.env.ref('microfinance_loan_management.group_microfinance_manager')
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Directeur agence B (test)', 'login': 'tres_agence_b', 'company_id': self.company_b.id,
            'company_ids': [(6, 0, self.company_b.ids)],
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id, group.id,
                                  self.env.ref('account.group_account_user').id])]})
        tile = self._tiles(self.company_b, user)['operating_treasury']
        self.assertEqual([row['bank_balance'] for row in tile['journals']], [70000.0])
        self.assertNotIn(self.bni.name, [row['bank'] for row in tile['journals']])

    def test_separation_from_funds_tile(self):
        self._opening(self.bmop, 3000000.0, self.setup_a)
        tiles = self._tiles()
        funds = tiles['exploitation_funds']
        self.assertEqual(funds['value'], 0.0)
        self.assertTrue(all(not item.get('value') for item in funds['secondary_items']))
        self.assertEqual(self._rows(tiles)[self.bmoi.name]['bank_balance'], 3000000.0)
        # contribution de bailleur de 1 000 000, non rapprochée
        self.company_a.microfinance_fond_subvention_account_id = self._acc(
            self.company_a, '762000', 'income_other', False)
        bailleur = self.env['microfinance.bailleur.fonds'].create({'name': 'Bailleur paie (test)'})
        fond = self.env['microfinance.fond.credit'].with_company(self.company_a).create({
            'name': 'Exploitation paie test', 'bailleur_id': bailleur.id, 'date_debut': '2020-01-01',
            'destination': 'exploitation', 'nature': 'subvention', 'bank_id': self.bmoi.id, 'account_id': False})
        contrib = self.env['microfinance.fond.contribution'].with_company(self.company_a).create({
            'fond_id': fond.id, 'type_mouvement': 'depot', 'amount': 1000000.0, 'mode_paiement': 'virement',
            'reference_paiement': 'VIR-PAIE-TEST'})
        contrib.action_post()
        self.env.invalidate_all()
        tiles = self._tiles()
        funds = tiles['exploitation_funds']
        items = {item['label']: item['value'] for item in funds['secondary_items'] if 'value' in item}
        self.assertEqual((funds['value'], items['En transit'], items['Reçu en banque']), (1000000.0, 1000000.0, 0.0))
        row = self._rows(tiles)[self.bmoi.name]
        self.assertEqual((row['bank_balance'], row['in_transit']), (3000000.0, 1000000.0))

    def test_cross_links_between_the_two_tiles(self):
        self._opening(self.bmop, 3000000.0, self.setup_a)
        tiles = self._tiles()
        keys = list(tiles)
        self.assertEqual(keys.index('operating_treasury'), keys.index('exploitation_funds') + 1)
        to_funds = tiles['operating_treasury']['extra_links'][0]
        self.assertEqual((to_funds['label'], to_funds['model']), ("Voir les fonds d'exploitation",
                                                                  'microfinance.fond.credit'))
        self.assertEqual(to_funds['domain'], tiles['exploitation_funds']['domain'])
        to_treasury = tiles['exploitation_funds']['extra_links'][0]
        self.assertEqual((to_treasury['label'], to_treasury['model']),
                         ("Voir la trésorerie d'exploitation", 'account.journal'))
        journals = self.env['account.journal'].search(to_treasury['domain'])
        self.assertEqual(journals, self.bmop | self.bnop)
        # le contenu de la tuile des fonds est inchangé (mêmes lignes qu'avant)
        self.assertEqual([i['label'] for i in tiles['exploitation_funds']['secondary_items']][:3],
                         ['En transit', 'Reçu en banque', 'Dû aux bailleurs (avances)'])
