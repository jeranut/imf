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

    def test_regular_account_flow_unaffected(self):
        # Non-régression : un compte réel (is_container=False, défaut) continue de fonctionner
        # normalement (produit requis, activation/clôture possibles).
        account = self._create_active_account(opening_amount=100.0)
        self.assertFalse(account.is_container)
        account.action_close()
        self.assertEqual(account.state, 'closed')
