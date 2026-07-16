# -*- coding: utf-8 -*-
from .common import MicrofinanceCommon


class TestClientBlacklistMenuAction(MicrofinanceCommon):

    def test_action_targets_blacklist_model_with_tree_form_views(self):
        action = self.env.ref('microfinance_loan_management.action_microfinance_client_blacklist')
        self.assertEqual(action.res_model, 'microfinance.client.blacklist')
        self.assertEqual(action.view_mode, 'tree,form')

    def test_clients_root_menu_is_a_pure_parent(self):
        # menu_clients_root ne porte plus d'action propre depuis l'ajout du sous-menu Liste
        # noire : seuls ses deux enfants (Clients, Liste noire) portent une action.
        menu = self.env.ref('microfinance_loan_management.menu_clients_root')
        self.assertFalse(menu.action)

    def test_clients_and_blacklist_submenus_exist_under_clients_root(self):
        root = self.env.ref('microfinance_loan_management.menu_clients_root')
        clients_menu = self.env.ref('microfinance_loan_management.menu_microfinance_client_list')
        blacklist_menu = self.env.ref('microfinance_loan_management.menu_microfinance_client_blacklist')
        self.assertEqual(clients_menu.parent_id, root)
        self.assertEqual(blacklist_menu.parent_id, root)
        self.assertEqual(clients_menu.action.res_model, 'res.partner')
        self.assertEqual(blacklist_menu.action.res_model, 'microfinance.client.blacklist')

    def test_search_view_inactive_filter_matches_active_field(self):
        search_view = self.env.ref('microfinance_loan_management.view_microfinance_client_blacklist_search')
        self.assertIn("'active', '=', False", search_view.arch_db)


class TestClientBlacklistDefaultVisibility(MicrofinanceCommon):

    def test_inactive_entries_hidden_by_default_search_domain(self):
        # L'action ne force pas 'active_test': False, donc les entrées désactivées restent
        # masquées par défaut (comportement standard du champ 'active' sur ce modèle).
        self.env['microfinance.client.blacklist'].create({
            'partner_id': self.partner.id,
            'reason': 'Test visibilité',
            'active': False,
        })
        entries = self.env['microfinance.client.blacklist'].search([('partner_id', '=', self.partner.id)])
        self.assertFalse(entries)
