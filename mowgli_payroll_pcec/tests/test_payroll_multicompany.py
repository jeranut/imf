# -*- coding: utf-8 -*-
"""Paie multi-sociétés : structure et règles partagées, comptes par société.

Suppose les données réelles de MOWGLI (copie jetable uniquement, migration
appliquée). TransactionCase : rollback automatique.
"""
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged

ROLES = ('debit_account_id', 'credit_account_id')


@tagged('post_install', '-at_install')
class TestPayrollMulticompany(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Company = cls.env['res.company']
        cls.c1 = Company.search([('name', '=', 'CEFOR Isotry')], limit=1)
        cls.c6 = Company.search([('name', '=', 'CEFOR Mahitsy')], limit=1)
        cls.c7 = Company.search([('name', '=', 'CEFOR Tsaramasay')], limit=1)
        cls.c9 = Company.search([('name', '=', 'CEFOR Andoharanofotsy')], limit=1)
        cls.structure = cls.env['hr.payroll.structure'].search(
            [('code', '=', 'BASE')], limit=1)
        cls.rules = {r.code: r for r in cls.structure.rule_ids}

    def setUp(self):
        super().setUp()
        if not (self.c1 and self.c6 and self.c9 and self.structure):
            self.skipTest("Données MOWGLI absentes de cette base.")
        # Paramètre de migration : sans effet ici, la migration est faite.
        self.Account = self.env['account.account'].sudo()

    def _acc(self, code, company):
        return self.Account.search(
            [('code', '=', code), ('company_id', '=', company.id)], limit=1)

    def _delete_account(self, code, company):
        """Odoo refuse de supprimer un compte référencé par une propriété
        (dont la valeur par société d'une règle) : on retire d'abord la
        valeur de la règle, comme le ferait un administrateur."""
        account = self._acc(code, company)
        for rule in self.env['hr.salary.rule'].search([]):
            for fname in ROLES:
                if rule.sudo().with_company(company)[fname] == account:
                    rule.sudo().with_company(company).write({fname: False})
        account.unlink()

    def _user(self, login, companies, group_xmlid):
        return self.env['res.users'].with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'email': login + '@example.com',
            'company_id': companies[0].id, 'company_ids': [(6, 0, companies.ids)],
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref(group_xmlid).id])],
        })

    # --- partage ------------------------------------------------------
    def test_structure_and_rules_are_shared(self):
        self.assertFalse(self.structure.company_id)
        for rule in self.env['hr.salary.rule'].search([]):
            self.assertFalse(rule.company_id, rule.code)
        self.assertFalse(self.env['hr.payroll.structure'].default_get(
            ['company_id']).get('company_id'))
        self.assertFalse(self.env['hr.salary.rule'].default_get(
            ['company_id']).get('company_id'))

    def test_accounts_resolved_per_company(self):
        for company in self.env['res.company'].search(
                [('chart_template', '!=', False)]):
            basic = self.rules['BASIC'].sudo().with_company(company)
            net = self.rules['NET'].sudo().with_company(company)
            self.assertEqual(basic.debit_account_id,
                             self._acc('652100', company), company.name)
            self.assertEqual(net.credit_account_id,
                             self._acc('315000', company), company.name)
        self.assertEqual(self.rules['BASIC'].sudo().with_company(
            self.c9).debit_account_id.id, 8713)

    def test_wrong_company_account_refused(self):
        with self.assertRaises(ValidationError):
            self.rules['BASIC'].sudo().with_company(self.c9).write(
                {'debit_account_id': self._acc('652100', self.c1).id})

    def test_existing_value_never_overwritten(self):
        other = self._acc('316000', self.c6)
        rule = self.rules['BASIC'].sudo().with_company(self.c6)
        rule.write({'debit_account_id': other.id})
        rows = self.env['hr.salary.rule']._mowgli_complete_company_accounts(
            self.rules['BASIC'], self.c6, apply=True)
        self.assertEqual(rule.debit_account_id, other)
        self.assertEqual(
            [r['statut'] for r in rows if r['role'] == 'debit'],
            ['deja_renseigne'])

    def test_setup_idempotent_and_company_stays_empty(self):
        Rule = self.env['hr.salary.rule']
        before = {(r.code, c.id, f): r.sudo().with_company(c)[f].id
                  for r in self.structure.rule_ids
                  for c in self.env['res.company'].search([])
                  for f in ROLES}
        Rule._mowgli_setup_payroll_rules()
        Rule._microfinance_payroll_setup_loan_rule()
        Rule._mowgli_setup_payroll_rules()
        after = {(r.code, c.id, f): r.sudo().with_company(c)[f].id
                 for r in self.structure.rule_ids
                 for c in self.env['res.company'].search([])
                 for f in ROLES}
        self.assertEqual(before, after)
        self.assertFalse(self.structure.company_id)
        self.assertFalse(Rule.search([('company_id', '!=', False)]))
        self.assertTrue(after[('BASIC', self.c9.id, 'debit_account_id')])

    # --- création automatique ----------------------------------------
    def test_missing_code_recreated_once_with_xmlid(self):
        self._delete_account('652100', self.c6)
        self.assertFalse(self._acc('652100', self.c6))
        rule = self.rules['BASIC']
        account = rule._mowgli_account_for_company('debit_account_id', self.c6)
        self.assertEqual(account.company_id, self.c6)
        self.assertEqual(account.code, '652100')
        self.assertTrue(account.mowgli_auto_created)
        self.assertEqual(account.account_type, 'expense')
        self.assertEqual(account.name, 'Rémunérations du personnel')
        self.assertEqual(account.group_id.company_id, self.c6)
        self.assertEqual(self.env.ref('account.%d_pcec_6521' % self.c6.id), account)
        self.assertEqual(rule.sudo().with_company(self.c6).debit_account_id, account)
        again = rule._mowgli_account_for_company('debit_account_id', self.c6)
        self.assertEqual(again, account)
        self.assertEqual(self.Account.search_count([
            ('code', '=', '652100'), ('company_id', '=', self.c6.id)]), 1)
        other = self._acc('652100', self.c1)
        self.assertNotEqual(account, other)

    def test_non_whitelisted_code_refused(self):
        count = self.Account.search_count([('company_id', '=', self.c6.id)])
        with self.assertRaises(UserError):
            self.c6._mowgli_get_or_create_account('ZZ9999')
        self.assertEqual(
            self.Account.search_count([('company_id', '=', self.c6.id)]), count)

    def test_unknown_whitelisted_code_refused(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'mowgli_payroll_pcec.extra_account_codes', '888888')
        count = self.Account.search_count([('company_id', '=', self.c6.id)])
        with self.assertRaisesRegex(UserError, 'inconnu'):
            self.c6._mowgli_get_or_create_account('888888')
        self.assertEqual(
            self.Account.search_count([('company_id', '=', self.c6.id)]), count)

    # --- société sans plan -------------------------------------------
    def test_company_without_chart_refused_then_hook_fills(self):
        if not self.c7 or self.c7.chart_template:
            self.skipTest("Tsaramasay absente ou déjà dotée d'un plan.")
        with self.assertRaisesRegex(UserError, "Installez d'abord le plan"):
            self.c7._mowgli_get_or_create_account('652100')
        self.assertFalse(self.Account.search_count([('company_id', '=', self.c7.id)]))
        self.env['account.chart.template'].try_loading(
            'mg_pcec', self.c7, install_demo=False)
        basic = self.rules['BASIC'].sudo().with_company(self.c7)
        self.assertEqual(basic.debit_account_id, self._acc('652100', self.c7))
        self.assertFalse(self._acc('652100', self.c7).mowgli_auto_created)

    # --- fiche de paie ------------------------------------------------
    def _slip(self, company):
        slip = self.env['hr.payslip'].search(
            [('state', '=', 'verify'), ('company_id', '=', self.c9.id)], limit=1)
        if not slip:
            self.skipTest("Aucune fiche 'verify' en société 9.")
        if company != self.c9:
            slip.sudo().write({'company_id': company.id})
        return slip

    def test_slip_company_9_posts_on_company_9_accounts(self):
        slip = self._slip(self.c9)
        user = self._user('paie_manager_9', self.c9,
                          'hr_payroll_community.group_hr_payroll_community_manager')
        user.groups_id = [(4, self.env.ref('account.group_account_invoice').id)]
        # L'indemnité de transport (Travel) n'a aucun compte : écart connu,
        # hors périmètre. On la retire pour obtenir une écriture équilibrée.
        slip.sudo().line_ids.filtered(lambda l: l.code == 'Travel').unlink()
        net = slip.sudo().line_ids.filtered(lambda l: l.code == 'NET')
        others = sum(slip.sudo().line_ids.filtered(
            lambda l: l.category_id.code == 'DED').mapped('total'))
        basic = sum(slip.sudo().line_ids.filtered(
            lambda l: l.category_id.code == 'BASIC').mapped('total'))
        net.write({'total': basic + others})
        slip = slip.with_user(user).with_company(self.c9)
        slip.action_payslip_done()
        self.assertTrue(slip.move_id)
        accounts = slip.move_id.sudo().line_ids.account_id
        self.assertTrue(accounts)
        self.assertEqual(set(accounts.company_id.ids), {self.c9.id})
        self.assertIn(8713, accounts.ids)

    def test_slip_uses_its_company_when_several_checked(self):
        slip = self._slip(self.c9).sudo()
        slip = slip.with_context(
            allowed_company_ids=[self.c1.id, self.c6.id, self.c9.id])
        lines = slip._prepare_account_move_line_vals()
        accounts = self.Account.browse([l[2]['account_id'] for l in lines])
        self.assertEqual(set(accounts.company_id.ids), {self.c9.id})

    def test_slip_other_company_uses_its_own_accounts(self):
        slip = self._slip(self.c6).sudo()
        lines = slip._prepare_account_move_line_vals()
        accounts = self.Account.browse([l[2]['account_id'] for l in lines])
        self.assertEqual(set(accounts.company_id.ids), {self.c6.id})
        self.assertIn(self._acc('652100', self.c6).id, accounts.ids)

    def test_slip_company_without_chart_raises_user_error(self):
        if not self.c7 or self.c7.chart_template:
            self.skipTest("Tsaramasay absente ou déjà dotée d'un plan.")
        slip = self._slip(self.c7).sudo()
        with self.assertRaisesRegex(UserError, "Installez d'abord le plan"):
            slip._prepare_account_move_line_vals()
        self.assertFalse(self.Account.search_count([('company_id', '=', self.c7.id)]))

    # --- droits ---------------------------------------------------------
    def test_officer_read_only_manager_can_write(self):
        officer = self._user('paie_officer_t', self.c9,
                             'hr_payroll_community.group_hr_payroll_community_user')
        manager = self._user('paie_manager_t', self.c9,
                             'hr_payroll_community.group_hr_payroll_community_manager')
        rule = self.env['hr.salary.rule'].search([('code', '=', 'HRA')], limit=1)
        self.assertTrue(rule.with_user(officer).with_company(self.c9).read(['name']))
        self.assertTrue(self.structure.with_user(officer).with_company(self.c9).read(['name']))
        with self.assertRaises(AccessError):
            rule.with_user(officer).with_company(self.c9).write({'name': 'X'})
        with self.assertRaises(AccessError):
            self.structure.with_user(officer).with_company(self.c9).write({'name': 'X'})
        with self.assertRaises(AccessError):
            self.env['hr.salary.rule'].with_user(officer).create(
                {'name': 'X', 'code': 'XX', 'category_id': rule.category_id.id})
        rule.with_user(manager).with_company(self.c9).write({'note': 'ok'})
        self.structure.with_user(manager).with_company(self.c9).write({'note': 'ok'})

    def test_account_rule_81_intact(self):
        rule = self.env['ir.rule'].browse(81)
        self.assertEqual(rule.name, 'Account multi-company')
        self.assertEqual(rule.domain_force,
                         "[('company_id', 'parent_of', company_ids)]")
        user = self._user('compta_9_seule', self.c9,
                          'hr_payroll_community.group_hr_payroll_community_user')
        user.groups_id = [(4, self.env.ref('account.group_account_user').id)]
        other = self._acc('652100', self.c1)
        with self.assertRaises(AccessError):
            other.with_user(user).with_company(self.c9).read(['code'])
        mine = self._acc('652100', self.c9)
        self.assertTrue(mine.with_user(user).with_company(self.c9).read(['code']))

    # --- wizard -----------------------------------------------------------
    def test_wizard_preview_writes_nothing_apply_idempotent(self):
        manager = self._user('wiz_manager', self.c9,
                             'hr_payroll_community.group_hr_payroll_community_manager')
        manager.company_ids = [(4, self.c6.id)]
        self._delete_account('652100', self.c6)
        wizard = self.env['mowgli.payroll.sync.wizard'].with_user(manager).create({
            'structure_id': self.structure.id,
            'target_company_ids': [(6, 0, [self.c6.id])]})
        wizard.action_preview()
        self.assertIn('a_creer', wizard.report_text)
        self.assertFalse(self._acc('652100', self.c6))
        wizard.action_apply()
        self.assertTrue(self._acc('652100', self.c6).mowgli_auto_created)
        wizard.action_apply()
        self.assertEqual(self.Account.search_count([
            ('code', '=', '652100'), ('company_id', '=', self.c6.id)]), 1)

    def test_wizard_refused_for_officer(self):
        officer = self._user('wiz_officer', self.c9,
                             'hr_payroll_community.group_hr_payroll_community_user')
        with self.assertRaises(AccessError):
            self.env['mowgli.payroll.sync.wizard'].with_user(officer).create(
                {'structure_id': self.structure.id}).action_apply()
