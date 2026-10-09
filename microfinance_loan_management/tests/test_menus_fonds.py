# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError, UserError

from .test_fond_partage import TestFondPartageBase

MF = 'microfinance_loan_management.'
# Modèles transactionnels : jamais ouverts depuis Configuration (à étendre au besoin).
TRANSACTIONAL_MODELS = {
    'microfinance.fond.credit', 'microfinance.fond.contribution', 'microfinance.fond.partage',
    'microfinance.fond.partage.line', 'microfinance.fond.allocation', 'microfinance.portfolio.allocation',
    'microfinance.portfolio.allocation.line', 'microfinance.fond.liaison.report', 'microfinance.fond.liaison.solde',
    'microfinance.loan', 'microfinance.loan.payment', 'microfinance.loan.installment', 'microfinance.loan.application',
    'microfinance.caisse.session', 'microfinance.caisse.fiche.journee', 'microfinance.caisse.comptage',
    'microfinance.savings.transaction', 'microfinance.bank.statement.entry', 'account.bank.statement',
    'account.move', 'account.move.line', 'account.payment',
}
FUND_OPERATION_MENUS = [
    'menu_microfinance_fond_credit', 'menu_microfinance_fond_exploitation', 'menu_microfinance_fond_contribution',
    'menu_microfinance_fond_contribution_exploitation', 'menu_microfinance_fond_partage',
    'menu_microfinance_portfolio_allocation', 'menu_microfinance_portfolio_allocation_line_history']
LIAISON_MENUS = ['menu_microfinance_fond_liaison_report', 'menu_microfinance_fond_liaison_solde']
CREDIT_CATALOGUES = [
    'menu_microfinance_financial_designation_income', 'menu_microfinance_financial_designation_activity_expense',
    'menu_microfinance_financial_designation_family_expense', 'menu_microfinance_financial_frequency']


class TestMenusFonds(TestFondPartageBase):
    """Menu « Fonds », contrôles de liaison dans Comptabilité > Banque, Configuration réduite aux réglages."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.hq = cls.company_a
        base = cls.env.ref('base.group_user')

        def user(login, company, groups):
            return cls.env['res.users'].with_context(no_reset_password=True).create({
                'name': login, 'login': login, 'company_id': company.id, 'company_ids': [(6, 0, [company.id])],
                'groups_id': [(6, 0, [base.id] + [cls.env.ref(g).id for g in groups])]})

        cls.chef_agence = user('menu_chef_agence', cls.company_b, [MF + 'group_microfinance_gestionnaire'])
        cls.caissier = user('menu_caissier', cls.hq, [MF + 'group_microfinance_cashier'])
        cls.direction = user('menu_direction', cls.hq, [
            MF + 'group_microfinance_gestionnaire', MF + 'group_microfinance_comptable', 'account.group_account_manager'])
        bank = cls.env['res.bank'].create({'name': 'BMOI menus (test)'})
        account = cls.env['account.account'].create({
            'code': 'TMENUBK', 'name': 'Banque menus', 'account_type': 'asset_cash', 'company_id': cls.hq.id})
        cls.env['account.journal'].create({
            'name': 'BMOP menus', 'code': 'BMPM', 'type': 'bank', 'company_id': cls.hq.id,
            'default_account_id': account.id, 'microfinance_usage': 'operating', 'microfinance_bank_id': bank.id})
        cls.bmoi = bank

    def setUp(self):
        super().setUp()
        self._set_parent(self.hq)

    def _visible(self, user):
        return self.env['ir.ui.menu'].with_user(user).with_context(
            allowed_company_ids=user.company_ids.ids)._visible_menu_ids()

    def _menu(self, xmlid):
        # liste complète : child_id masque sinon les menus invisibles pour l'utilisateur courant
        return self.env['ir.ui.menu'].with_context(**{'ir.ui.menu.full_list': True}).browse(self.env.ref(MF + xmlid).id)

    # ---------------------------------------------------------------- emplacement
    def test_menus_moved_out_of_configuration(self):
        fonds = self._menu('menu_fonds_root')
        for xmlid in FUND_OPERATION_MENUS:
            self.assertEqual(self._menu(xmlid).parent_id, fonds, xmlid)
        bank = self.env.ref(MF + 'menu_microfinance_bank_section')
        for xmlid in LIAISON_MENUS:
            self.assertEqual(self._menu(xmlid).parent_id, bank, xmlid)
        credit = self._menu('menu_microfinance_config_credit')
        for xmlid in CREDIT_CATALOGUES:
            self.assertEqual(self._menu(xmlid).parent_id, credit, xmlid)
        self.assertEqual(self._menu('menu_microfinance_bailleur_fonds').parent_id,
                         self._menu('menu_microfinance_config_financing'))
        root = self._menu('menu_microfinance_root')
        order = root.child_id.sorted(lambda m: (m.sequence, m.id))
        self.assertLess(order.ids.index(self._menu('menu_credits_root').id), order.ids.index(fonds.id))
        self.assertLess(order.ids.index(fonds.id), order.ids.index(self._menu('menu_caisse_root').id))

    def test_configuration_opens_no_transactional_model(self):
        config = self._menu('menu_microfinance_config')
        found, stack = [], [config]
        while stack:
            menu = stack.pop()
            stack.extend(menu.child_id)
            action = menu.action
            if action and action._name == 'ir.actions.act_window':
                found.append((menu.complete_name, action.res_model))
        self.assertTrue(found)
        offenders = [(name, model) for name, model in found if model in TRANSACTIONAL_MODELS]
        self.assertEqual(offenders, [])

    # ---------------------------------------------------------------- visibilité
    def test_cashier_sees_no_fund_menu_and_no_configuration(self):
        visible = self._visible(self.caissier)
        for xmlid in ['menu_fonds_root', 'menu_microfinance_config'] + FUND_OPERATION_MENUS + LIAISON_MENUS:
            self.assertNotIn(self._menu(xmlid).id, visible, xmlid)

    def test_agency_manager_sees_fund_operations_but_not_exploitation_data(self):
        visible = self._visible(self.chef_agence)
        self.assertIn(self._menu('menu_fonds_root').id, visible)
        for xmlid in ['menu_microfinance_fond_credit', 'menu_microfinance_portfolio_allocation',
                      'menu_microfinance_portfolio_allocation_line_history', 'menu_microfinance_fond_partage']:
            self.assertIn(self._menu(xmlid).id, visible, xmlid)
        self.assertIn(self._menu('menu_microfinance_bailleur_fonds').id, visible)
        for xmlid in CREDIT_CATALOGUES:
            self.assertIn(self._menu(xmlid).id, visible, xmlid)

    def test_head_office_direction_sees_everything_about_funds(self):
        visible = self._visible(self.direction)
        for xmlid in ['menu_fonds_root'] + FUND_OPERATION_MENUS + LIAISON_MENUS + CREDIT_CATALOGUES:
            self.assertIn(self._menu(xmlid).id, visible, xmlid)
        self.assertIn(self._menu('menu_microfinance_bailleur_fonds').id, visible)

    # ---------------------------------------------------------------- appel direct aux actions
    def _exploitation_fund(self):
        return self._create_fond(
            name='Exploitation menus', destination='exploitation', nature='subvention', bank_id=self.bmoi.id,
            account_id=False)

    def test_direct_action_on_exploitation_funds_is_refused_to_agency_and_cashier(self):
        fond = self._exploitation_fund()
        action = self.env.ref(MF + 'action_microfinance_fond_exploitation')
        domain = eval(action.domain)
        for user, company in ((self.chef_agence, self.company_b), (self.caissier, self.hq)):
            Fond = self.env['microfinance.fond.credit'].with_user(user).with_company(company)
            self.assertFalse(Fond.search(domain), user.login)
            with self.assertRaises(AccessError):
                Fond.browse(fond.id).read(['name'])
            with self.assertRaises(UserError):  # AccessError en est une sous-classe
                Fond.create({'name': 'Intrus', 'bailleur_id': self.bailleur.id, 'destination': 'exploitation',
                             'nature': 'subvention', 'bank_id': self.bmoi.id})
        Fond = self.env['microfinance.fond.credit'].with_user(self.direction).with_company(self.hq)
        self.assertEqual(Fond.search(domain), fond)

    def test_cashier_cannot_open_fund_operation_models(self):
        for model in ('microfinance.fond.contribution', 'microfinance.fond.partage', 'microfinance.fond.liaison.report',
                      'microfinance.fond.liaison.solde', 'microfinance.portfolio.allocation',
                      'microfinance.portfolio.allocation.line'):
            with self.assertRaises(AccessError, msg=model):
                self.env[model].with_user(self.caissier).with_company(self.hq).search([])
