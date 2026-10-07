# -*- coding: utf-8 -*-
from lxml import etree

from .common import MicrofinanceCommon


class TestCreditMenuCreationLock(MicrofinanceCommon):
    """Le menu Crédits (action_microfinance_loan, id 695) ne doit plus exposer de bouton
    "Nouveau" (liste/kanban/formulaire) : seul le smart button "Crédit" sur res.partner
    (action_view_microfinance_loans, action ad hoc distincte sans view_id) reste un point de
    création valide. Les vues dédiées *_credits_menu portent create="0" et sont rattachées
    uniquement à action_microfinance_loan - les vues génériques (view_microfinance_loan_tree/
    kanban/form) restent inchangées pour tout autre consommateur."""

    def _assert_xpath_sets_create_zero(self, view):
        # Vue dédiée (mode="primary", héritage par xpath) : son arch_db propre est le PATCH
        # xpath, pas la vue résolue - on vérifie donc que le patch pose bien
        # <attribute name="create">0</attribute>, pas la présence littérale de 'create="0"'.
        root = etree.fromstring(view.arch.encode('utf-8'))
        attributes = root.findall('.//attribute[@name="create"]')
        self.assertTrue(attributes, "Aucune <attribute name=\"create\"> trouvée dans %s" % view.name)
        self.assertEqual(attributes[0].text, '0')

    def _assert_resolved_view_creatable(self, model_name, view, expected):
        # Vue résolue (après application des héritages) telle que le client la recevrait :
        # seule cette lecture garantit qu'aucun héritage tiers ne réintroduit la création.
        resolved = self.env[model_name].get_view(view_id=view.id)
        root = etree.fromstring(resolved['arch'].encode('utf-8'))
        creatable = root.get('create') != '0'
        self.assertEqual(creatable, expected, "create sur la vue résolue %s" % view.name)

    def test_credits_menu_views_have_create_locked(self):
        tree = self.env.ref('microfinance_loan_management.view_microfinance_loan_tree_credits_menu')
        kanban = self.env.ref('microfinance_loan_management.view_microfinance_loan_kanban_credits_menu')
        form = self.env.ref('microfinance_loan_management.view_microfinance_loan_form_credits_menu')
        for view in (tree, kanban, form):
            self._assert_xpath_sets_create_zero(view)
            self._assert_resolved_view_creatable('microfinance.loan', view, expected=False)

    def test_action_microfinance_loan_uses_locked_views(self):
        action = self.env.ref('microfinance_loan_management.action_microfinance_loan')
        views_by_mode = {v.view_mode: v.view_id for v in action.view_ids}
        self.assertEqual(
            views_by_mode.get('tree'),
            self.env.ref('microfinance_loan_management.view_microfinance_loan_tree_credits_menu'),
        )
        self.assertEqual(
            views_by_mode.get('kanban'),
            self.env.ref('microfinance_loan_management.view_microfinance_loan_kanban_credits_menu'),
        )
        self.assertEqual(
            views_by_mode.get('form'),
            self.env.ref('microfinance_loan_management.view_microfinance_loan_form_credits_menu'),
        )

    def test_generic_views_remain_creatable(self):
        # Vues génériques utilisées par le smart button res.partner et le dashboard "Nouveau
        # prêt" (actions ad hoc sans view_id) : leur balise racine ne doit jamais recevoir
        # create="0" (une balise interne non pertinente - ex. old_installment_ids en lecture
        # seule dans le form - peut légitimement en porter un, d'où la vérification ciblée sur
        # la seule racine plutôt qu'une recherche de sous-chaîne sur tout l'arch).
        tree = self.env.ref('microfinance_loan_management.view_microfinance_loan_tree')
        kanban = self.env.ref('microfinance_loan_management.view_microfinance_loan_kanban')
        form = self.env.ref('microfinance_loan_management.view_microfinance_loan_form')
        for view in (tree, kanban, form):
            root = etree.fromstring(view.arch.encode('utf-8'))
            self.assertNotEqual(root.get('create'), '0', "%s racine ne doit pas porter create=\"0\"" % view.name)

    def test_partner_smart_button_still_creates_loan(self):
        action = self.partner.action_view_microfinance_loans()
        self.assertEqual(action['res_model'], 'microfinance.loan')
        self.assertNotIn('view_id', action)
        self.assertNotIn('views', action)
        loan = self.env['microfinance.loan'].with_context(
            default_partner_id=self.partner.id,
        ).create({
            'partner_id': self.partner.id,
            'product_id': self.product.id,
            'loan_amount': 500.0,
            'term': 3,
        })
        self.assertEqual(loan.partner_id, self.partner)
