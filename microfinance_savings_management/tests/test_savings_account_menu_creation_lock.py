# -*- coding: utf-8 -*-
from lxml import etree

from .common import SavingsCommon


class TestSavingsAccountMenuCreationLock(SavingsCommon):
    """Le menu "Comptes épargne" (action_microfinance_savings_account) et le rapport "Balance
    épargne" (action_microfinance_savings_balance_report) ne doivent plus exposer de bouton
    "Nouveau" : seul le smart button "Épargne" sur res.partner
    (action_view_microfinance_savings, action ad hoc distincte sans view_id) reste un point de
    création valide. Les vues dédiées *_menu portent create="0" et sont rattachées uniquement à
    ces deux actions - les vues génériques (view_microfinance_savings_account_tree/form)
    restent inchangées pour le smart button. ir.model.access.csv non touché pour ce modèle."""

    def _assert_xpath_sets_create_zero(self, view):
        root = etree.fromstring(view.arch.encode('utf-8'))
        attributes = root.findall('.//attribute[@name="create"]')
        self.assertTrue(attributes, "Aucune <attribute name=\"create\"> trouvée dans %s" % view.name)
        self.assertEqual(attributes[0].text, '0')

    def _assert_resolved_view_creatable(self, view, expected):
        resolved = self.env['microfinance.savings.account'].get_view(view_id=view.id)
        root = etree.fromstring(resolved['arch'].encode('utf-8'))
        creatable = root.get('create') != '0'
        self.assertEqual(creatable, expected, "create sur la vue résolue %s" % view.name)

    def test_menu_views_have_create_locked(self):
        tree = self.env.ref('microfinance_savings_management.view_microfinance_savings_account_tree_menu')
        form = self.env.ref('microfinance_savings_management.view_microfinance_savings_account_form_menu')
        for view in (tree, form):
            self._assert_xpath_sets_create_zero(view)
            self._assert_resolved_view_creatable(view, expected=False)

    def test_actions_use_locked_views(self):
        tree_menu = self.env.ref('microfinance_savings_management.view_microfinance_savings_account_tree_menu')
        form_menu = self.env.ref('microfinance_savings_management.view_microfinance_savings_account_form_menu')

        account_action = self.env.ref('microfinance_savings_management.action_microfinance_savings_account')
        views_by_mode = {v.view_mode: v.view_id for v in account_action.view_ids}
        self.assertEqual(views_by_mode.get('tree'), tree_menu)
        self.assertEqual(views_by_mode.get('form'), form_menu)

        balance_action = self.env.ref('microfinance_savings_management.action_microfinance_savings_balance_report')
        balance_views_by_mode = {v.view_mode: v.view_id for v in balance_action.view_ids}
        self.assertEqual(balance_views_by_mode.get('tree'), tree_menu)

    def test_generic_views_remain_creatable(self):
        # Vues génériques utilisées par le smart button res.partner (action ad hoc sans
        # view_id) : leur balise racine ne doit jamais recevoir create="0".
        tree = self.env.ref('microfinance_savings_management.view_microfinance_savings_account_tree')
        form = self.env.ref('microfinance_savings_management.view_microfinance_savings_account_form')
        for view in (tree, form):
            root = etree.fromstring(view.arch.encode('utf-8'))
            self.assertNotEqual(root.get('create'), '0', "%s racine ne doit pas porter create=\"0\"" % view.name)

    def test_partner_smart_button_still_creates_account(self):
        action = self.partner.action_view_microfinance_savings()
        self.assertEqual(action['res_model'], 'microfinance.savings.account')
        self.assertNotIn('view_id', action)
        self.assertNotIn('views', action)
        account = self.env['microfinance.savings.account'].with_context(
            default_partner_id=self.partner.id,
        ).create({
            'partner_id': self.partner.id,
            'product_id': self.savings_product.id,
        })
        self.assertEqual(account.partner_id, self.partner)

    def test_access_rights_unchanged_for_savings_account(self):
        # Étape 3 : ir.model.access.csv ne doit pas être touché pour ce modèle - le create
        # reste disponible pour le flux légitime via smart button.
        access = self.env['ir.model.access'].search([
            ('model_id.model', '=', 'microfinance.savings.account'),
            ('group_id', '=', self.env.ref('microfinance_savings_management.group_savings_agent').id),
        ])
        self.assertTrue(access.perm_create)
