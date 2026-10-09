# -*- coding: utf-8 -*-
from lxml import etree

from odoo.exceptions import UserError, ValidationError

from .common import SavingsCommon


class TestSavingsAccountMenuCreationLock(SavingsCommon):
    """Scission compte / produit (docs_dev/epargne_split/) : un compte épargne n'est jamais créé à
    la main (vues create="false", aucun droit create).

    Attribution d'un produit (docs_dev/attribution_epargne_client/, réversion du lot précédent) :
    le menu « Produits d'épargne » est désormais CONSULTATION SEULE (comme la balance et les
    listes du tableau de bord, mêmes vues *_menu) ; l'attribution (création) ne se fait plus que
    depuis le smart button « Épargne » de res.partner ou le bouton « Épargne » du crédit, tous
    deux via la vue dédiée *_form_attribution (titulaire/agence lecture seule inconditionnelle)."""

    def _root(self, model, view):
        return etree.fromstring(self.env[model].get_view(view.id)['arch'].encode('utf-8'))

    def test_holder_views_not_creatable(self):
        model = 'microfinance.savings.holder.account'
        for xmlid in ('view_microfinance_savings_holder_account_tree', 'view_microfinance_savings_holder_account_form',
                      'view_microfinance_savings_holder_account_kanban'):
            root = self._root(model, self.env.ref('microfinance_savings_management.%s' % xmlid))
            self.assertEqual(root.get('create'), 'false', xmlid)

    def test_no_create_right_on_holder_account(self):
        accesses = self.env['ir.model.access'].search([('model_id.model', '=', 'microfinance.savings.holder.account')])
        self.assertTrue(accesses)
        self.assertFalse(accesses.filtered('perm_create'))

    def test_locked_product_views(self):
        model = 'microfinance.savings.account'
        tree = self._root(model, self.env.ref('microfinance_savings_management.view_microfinance_savings_account_tree_menu'))
        form = self._root(model, self.env.ref('microfinance_savings_management.view_microfinance_savings_account_form_menu'))
        self.assertEqual(tree.get('create'), '0')
        self.assertEqual(tree.get('import'), '0')
        self.assertEqual(form.get('create'), '0')
        self.assertEqual(form.get('duplicate'), '0')

    def test_menus_point_to_the_right_models(self):
        holder_action = self.env.ref('microfinance_savings_management.action_microfinance_savings_holder_account')
        product_action = self.env.ref('microfinance_savings_management.action_microfinance_savings_account')
        self.assertEqual(holder_action.res_model, 'microfinance.savings.holder.account')
        self.assertEqual(product_action.res_model, 'microfinance.savings.account')
        # Réversion : le menu Produits est maintenant verrouillé comme la balance, via les mêmes
        # vues *_menu (create="0" import="0"/duplicate="0") - plus de vues créables ici.
        product_views = {v.view_mode: v.view_id for v in product_action.view_ids}
        self.assertEqual(product_views.get('tree'),
                         self.env.ref('microfinance_savings_management.view_microfinance_savings_account_tree_menu'))
        self.assertEqual(product_views.get('form'),
                         self.env.ref('microfinance_savings_management.view_microfinance_savings_account_form_menu'))
        self.assertTrue(product_action.context and 'savings_menu_readonly' in product_action.context)
        balance = self.env.ref('microfinance_savings_management.action_microfinance_savings_balance_report')
        self.assertEqual({v.view_mode: v.view_id for v in balance.view_ids}.get('tree'),
                         self.env.ref('microfinance_savings_management.view_microfinance_savings_account_tree_menu'))

    def test_create_resolves_its_account(self):
        """create() direct (ORM, hors contexte menu) reste la voie légitime utilisée par le smart
        button/bouton crédit (et les tests) : seul le contexte du MENU est bloqué, pas create()
        en général (cf. test_menu_context_blocks_creation)."""
        product = self.env['microfinance.savings.account'].create({
            'partner_id': self.partner.id, 'product_id': self.savings_product.id,
        })
        self.assertTrue(product.account_id)
        self.assertEqual(product.account_id.partner_id, self.partner)

    def test_menu_context_blocks_creation(self):
        """Garde serveur (point 3 du correctif) : un create() portant le contexte du menu
        (savings_menu_readonly, cf. action_microfinance_savings_account) sans le flag
        d'attribution est refusé, même avec un partner_id parfaitement valide - défense en
        profondeur si les vues create="0" du menu étaient contournées (action forgée)."""
        with self.assertRaises(UserError):
            self.env['microfinance.savings.account'].with_context(savings_menu_readonly=True).create({
                'partner_id': self.partner.id, 'product_id': self.savings_product.id,
            })

    def test_menu_context_with_attribution_flag_is_allowed(self):
        """Le flag d'attribution (posé par le smart button et le bouton crédit) neutralise la
        garde même si, par construction improbable, le contexte menu était aussi présent."""
        product = self.env['microfinance.savings.account'].with_context(
            savings_menu_readonly=True, microfinance_savings_attribution=True,
        ).create({'partner_id': self.partner.id, 'product_id': self.savings_product.id})
        self.assertTrue(product.account_id)

    def test_attribution_form_locks_partner_and_company(self):
        root = self._root(
            'microfinance.savings.account',
            self.env.ref('microfinance_savings_management.view_microfinance_savings_account_form_attribution'),
        )
        partner_field = root.find(".//field[@name='partner_id']")
        company_field = root.find(".//field[@name='company_id']")
        self.assertEqual(partner_field.get('readonly'), '1')
        self.assertEqual(company_field.get('readonly'), '1')

    def test_partner_smart_button_opens_products_for_attribution(self):
        """Réversion : le smart button ouvre désormais les PRODUITS (attribution), plus le
        compte/titulaire (consultable via le menu « Comptes épargne »)."""
        self._create_account()
        action = self.partner.action_view_microfinance_savings()
        self.assertEqual(action['res_model'], 'microfinance.savings.account')
        self.assertEqual(action['domain'], [('partner_id', '=', self.partner.id), ('account_id', '!=', False)])
        self.assertEqual(action['context']['default_partner_id'], self.partner.id)
        self.assertTrue(action['context']['microfinance_savings_attribution'])
        # action['views'] : liste de tuples (view_id, view_mode), convention Odoo standard.
        form_view_id = dict((mode, vid) for vid, mode in action['views'])['form']
        self.assertEqual(
            form_view_id,
            self.env.ref('microfinance_savings_management.view_microfinance_savings_account_form_attribution').id,
        )

    def test_smart_button_counter_matches_opened_list_domain(self):
        """Point 5 du correctif : le compteur du smart button (microfinance_savings_count) doit
        correspondre au nombre de lignes de la liste qu'il ouvre (même domaine)."""
        self.assertEqual(self.partner.microfinance_savings_count, 0)
        self._create_account()
        self.partner.invalidate_recordset(['microfinance_savings_count'])
        action = self.partner.action_view_microfinance_savings()
        count = self.env['microfinance.savings.account'].search_count(action['domain'])
        self.assertEqual(self.partner.microfinance_savings_count, count)

    def test_loan_savings_button_uses_attribution_views(self):
        loan = self._create_loan()
        action = loan.action_view_savings_accounts()
        form_view_id = dict((mode, vid) for vid, mode in action['views'])['form']
        self.assertEqual(
            form_view_id,
            self.env.ref('microfinance_savings_management.view_microfinance_savings_account_form_attribution').id,
        )
        self.assertEqual(action['context']['default_microfinance_loan_id'], loan.id)
        self.assertTrue(action['context']['microfinance_savings_attribution'])

    def test_duplicate_product_on_same_account_blocked(self):
        """Garde fou ajouté en cours de lot (hors périmètre initial du correctif) : un même
        produit d'épargne ne peut pas être souscrit deux fois simultanément sur le même compte."""
        self._create_account()
        with self.assertRaises(ValidationError):
            self.env['microfinance.savings.account'].create({
                'partner_id': self.partner.id, 'product_id': self.savings_product.id,
            })

    def test_duplicate_product_allowed_after_closing_the_first(self):
        first = self._create_active_account()
        first.action_close()
        second = self.env['microfinance.savings.account'].create({
            'partner_id': self.partner.id, 'product_id': self.savings_product.id,
        })
        self.assertTrue(second.id)

    def test_cross_company_attribution_blocked(self):
        """Point 6 du correctif : un produit ne peut pas être attribué pour une agence
        différente de celle du titulaire (message métier clair, avant la contrainte générique de
        microfinance.savings.holder.account)."""
        company_b = self.env['res.company'].create({'name': 'Agence B attribution (test)', 'agency_code': 'ZB'})
        client = self._create_context_client('999999999001', company_id=self.env.company.id)
        with self.assertRaises(ValidationError):
            self.env['microfinance.savings.account'].create({
                'partner_id': client.id, 'product_id': self.savings_product.id, 'company_id': company_b.id,
            })
