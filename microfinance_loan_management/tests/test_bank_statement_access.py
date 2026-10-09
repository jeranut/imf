# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError

from .test_fond_liaison import TestFondLiaison


class TestBankStatementAccess(TestFondLiaison):
    """Relevés bancaires : menu Comptabilité > Banque, droits par groupe, accès direct refusé au caissier."""

    MENU = 'microfinance_loan_management.menu_microfinance_bank_statement'
    ACTION = 'microfinance_loan_management.action_microfinance_bank_statement'

    @classmethod
    def _user(cls, login, group_xmlids, companies):
        groups = [cls.env.ref('base.group_user').id] + [cls.env.ref(x).id for x in group_xmlids]
        return cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'company_id': companies[0].id,
            'company_ids': [(6, 0, [c.id for c in companies])], 'groups_id': [(6, 0, groups)]})

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cashier = cls._user('acc_cashier', ['microfinance_loan_management.group_microfinance_cashier'], [cls.agency])
        # chef d'agence : Gestionnaire (implique Manager crédit et Finance) + lecture de la comptabilité
        cls.chief = cls._user('acc_chief', ['microfinance_loan_management.group_microfinance_gestionnaire',
                                            'account.group_account_readonly'], [cls.agency])
        cls.accountant = cls._user('acc_manager', ['account.group_account_manager'], [cls.agency, cls.hq])
        cls.hq_stmt = cls._statement_for(cls.fdbm, 10.0)
        cls.ag_stmt = cls._statement_for(cls.ag_journal, 10.0)

    @classmethod
    def _statement_for(cls, journal, amount):
        return cls.env['account.bank.statement'].create({
            'journal_id': journal.id, 'mf_state': 'draft', 'mf_date_from': '2026-10-01', 'mf_date_to': '2026-10-31',
            'balance_start': 0.0, 'balance_end_real': amount,
            'mf_entry_ids': [(0, 0, {'date': '2026-10-05', 'name': 'Dépôt', 'amount_in': amount})]})

    # ------------------------------------------------------------------ menu
    def test_menu_is_under_accounting_bank_section_not_under_cashier_menu(self):
        menu = self.env.ref(self.MENU)
        self.assertEqual(menu.parent_id, self.env.ref('microfinance_loan_management.menu_microfinance_bank_section'))
        self.assertEqual(menu.parent_id.parent_id, self.env.ref('account.menu_finance_entries'))
        self.assertLess(self.env.ref('account.menu_finance_entries_accounting_miscellaneous').sequence, menu.parent_id.sequence)
        self.assertLess(menu.parent_id.sequence, self.env.ref('account.menu_finance_entries_management').sequence)
        caisse = self.env.ref('microfinance_loan_management.menu_caisse_root')
        self.assertNotIn(menu, caisse.child_id)
        self.assertNotIn(menu, caisse.child_id.child_id)

    def test_menu_visibility_per_role(self):
        menu = self.env.ref(self.MENU)
        visible = {u: self.env['ir.ui.menu'].with_user(u)._visible_menu_ids() for u in (self.cashier, self.chief, self.accountant)}
        self.assertNotIn(menu.id, visible[self.cashier])
        self.assertIn(menu.id, visible[self.chief])
        self.assertIn(menu.id, visible[self.accountant])
        # le caissier garde ses menus de caisse
        guichet = self.env.ref('microfinance_loan_management.menu_microfinance_caisse_pos')
        self.assertIn(guichet.id, visible[self.cashier])
        # et ne voit le menu Comptabilité nulle part
        self.assertNotIn(self.env.ref('account.menu_finance_entries').id, visible[self.cashier])

    # ------------------------------------------------------------------ droits ORM et accès direct
    def test_cashier_has_no_access_to_statement_models(self):
        Statement = self.env['account.bank.statement'].with_user(self.cashier)
        for model in ('account.bank.statement', 'account.bank.statement.line', 'microfinance.bank.statement.entry',
                      'microfinance.bank.statement.log'):
            with self.assertRaises(AccessError):
                self.env[model].with_user(self.cashier).search([])
        with self.assertRaises(AccessError):
            Statement.create({'journal_id': self.ag_journal.id, 'mf_state': 'draft'})
        with self.assertRaises(AccessError):
            Statement.browse(self.ag_stmt.id).read(['name'])

    def test_cashier_cannot_open_the_action_directly(self):
        action = self.env.ref(self.ACTION)
        self.assertNotIn(self.env.ref('microfinance_loan_management.group_microfinance_cashier'), action.groups_id)
        with self.assertRaises(AccessError):
            self.env['ir.actions.act_window'].with_user(self.cashier).browse(action.id).read(['res_model'])

    def test_chief_and_accountant_read_and_create_statements(self):
        for user, company in ((self.chief, self.agency), (self.accountant, self.agency)):
            Statement = self.env['account.bank.statement'].with_user(user).with_company(company)
            created = Statement.create({
                'journal_id': self.ag_journal.id, 'mf_state': 'draft', 'mf_date_from': '2026-11-01',
                'mf_date_to': '2026-11-30', 'balance_start': 0.0, 'balance_end_real': 5.0,
                'mf_entry_ids': [(0, 0, {'date': '2026-11-05', 'name': 'Dépôt', 'amount_in': 5.0})]})
            self.assertEqual(created.mf_gap, 0.0)
            self.assertTrue(Statement.search([('id', '=', created.id)]))

    def test_chief_sees_only_its_company_statements_accountant_sees_both(self):
        Statement = self.env['account.bank.statement']
        ids = (self.hq_stmt | self.ag_stmt).ids
        self.assertEqual(Statement.with_user(self.chief).with_company(self.agency).search([('id', 'in', ids)]), self.ag_stmt)
        both = Statement.with_user(self.accountant).with_context(allowed_company_ids=[self.hq.id, self.agency.id]).search([('id', 'in', ids)])
        self.assertEqual(both, self.hq_stmt | self.ag_stmt)
        entries = self.env['microfinance.bank.statement.entry'].with_user(self.chief).with_company(self.agency).search([])
        self.assertEqual(entries.mapped('statement_id'), self.ag_stmt)

    def test_cancel_and_reopen_remain_reserved_to_the_accountant(self):
        self.ag_stmt.action_mf_validate()
        with self.assertRaises(AccessError):
            self.ag_stmt.with_user(self.chief)._mf_reopen('test')
        self.ag_stmt.with_user(self.accountant)._mf_reopen('Correction')
        self.assertEqual(self.ag_stmt.mf_state, 'draft')

    # ------------------------------------------------------------------ kanban des journaux
    def test_new_statement_button_follows_the_same_groups(self):
        view = self.env.ref('account.account_journal_dashboard_kanban_view')
        def arch(user):
            return self.env['account.journal'].with_user(user).get_view(view_id=view.id, view_type='kanban')['arch']
        self.assertIn('Saisir un relevé', arch(self.chief))
        self.assertIn('Saisir un relevé', arch(self.accountant))
        self.assertNotIn('Saisir un relevé', arch(self.cashier))
