# -*- coding: utf-8 -*-
from odoo.exceptions import UserError, ValidationError

from .common import SavingsCommon


class TestSavingsAccountContainer(SavingsCommon):
    """Structure conteneur (Lot 1.2, docs_dev/epargne_exigee_display/
    AUDIT_LOT0_conteneur_epargne.md) : un microfinance.savings.account avec is_container=True
    est un enregistrement vide (pas de produit, jamais de solde/transaction), distinct des
    comptes réels. La création automatique au 1er crédit (Lot 1.4) n'est pas traitée ici."""

    def _create_container(self, **kwargs):
        vals = {'partner_id': self.partner.id, 'is_container': True}
        vals.update(kwargs)
        return self.env['microfinance.savings.account'].create(vals)

    def test_container_created_without_product(self):
        container = self._create_container()
        self.assertFalse(container.product_id)
        self.assertTrue(container.is_container)

    def test_container_created_active_not_draft(self):
        # Correctif : un conteneur ne doit jamais rester en brouillon, même sans produit -
        # l'état est posé directement à la création, action_activate() restant interdit sur un
        # conteneur (cf. test_container_cannot_be_activated ci-dessous).
        container = self._create_container()
        self.assertEqual(container.state, 'active')

    def test_container_explicit_state_respected(self):
        # Un appelant qui fournit explicitement un état (ex. migration/reprise de données) n'est
        # pas écrasé par le forçage automatique.
        container = self._create_container(state='closed')
        self.assertEqual(container.state, 'closed')

    def test_real_account_without_product_raises(self):
        with self.assertRaises(ValidationError):
            self.env['microfinance.savings.account'].create({
                'partner_id': self.partner.id, 'is_container': False,
            })

    def test_container_cannot_be_activated(self):
        container = self._create_container()
        with self.assertRaises(UserError):
            container.action_activate()

    def test_container_cannot_be_closed(self):
        container = self._create_container()
        with self.assertRaises(UserError):
            container.action_close()

    def test_container_cannot_receive_transaction(self):
        container = self._create_container()
        with self.assertRaises(UserError):
            container._create_transaction('deposit', 100.0)

    def test_container_not_flagged_dormant_by_cron(self):
        # Défense en profondeur (cf. cron_detect_dormant_accounts) : un conteneur actif depuis
        # longtemps, sans transaction ni date d'ouverture, ne doit jamais être marqué dormant.
        container = self._create_container()
        self.env['microfinance.savings.account'].cron_detect_dormant_accounts()
        self.assertEqual(container.state, 'active')

    def test_regular_account_flow_unaffected(self):
        # Non-régression : un compte réel (is_container=False, défaut) continue de fonctionner
        # normalement (produit requis, activation/clôture possibles).
        account = self._create_active_account(opening_amount=100.0)
        self.assertFalse(account.is_container)
        account.action_close()
        self.assertEqual(account.state, 'closed')
