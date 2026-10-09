# -*- coding: utf-8 -*-
import random
from unittest.mock import patch

import psycopg2

from odoo.exceptions import UserError, ValidationError
from odoo.tools import mute_logger

from odoo.addons.microfinance_loan_management.tests.common import MicrofinanceNoFundMixin

from .common import SavingsCommon


class TestSavingsHolderAccount(MicrofinanceNoFundMixin, SavingsCommon):
    """Scission compte épargne / produit d'épargne (docs_dev/epargne_split/)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Holder = cls.env['microfinance.savings.holder.account']
        cls.company_b = cls.env['res.company'].create({'name': 'Agence B épargne split (test)', 'agency_code': 'ZB'})
        cls.env.user.company_ids = [(4, cls.company_b.id)]

    def _cin(self):
        Partner = self.env['res.partner'].with_context(active_test=False)
        while True:
            cin = ''.join(str(random.randint(0, 9)) for _ in range(12))
            if not Partner.search_count([('microfinance_id_number', '=', cin)]):
                return cin

    def _client(self, **kwargs):
        return self._create_context_client(self._cin(), company_id=self.env.company.id, **kwargs)

    def _product(self, partner, **kwargs):
        vals = {'partner_id': partner.id, 'product_id': self.savings_product.id}
        vals.update(kwargs)
        return self.env['microfinance.savings.account'].create(vals)

    def _loan_account(self, partner, company=None):
        return self.env['microfinance.loan.account'].search([
            ('partner_id', '=', partner.id), ('company_id', '=', (company or self.env.company).id)])

    # --- Création couplée ---
    def test_client_creation_creates_both_accounts_with_same_number(self):
        client = self._client()
        loan_account = self._loan_account(client)
        holder = client.microfinance_savings_holder_account_ids
        self.assertEqual(len(loan_account), 1)
        self.assertEqual(len(holder), 1)
        self.assertEqual(holder.name, 'CE/%s' % loan_account.name)
        self.assertEqual(loan_account.name, client.microfinance_account_number)
        self.assertEqual(holder.loan_account_id, loan_account)
        self.assertEqual((holder.partner_id, holder.company_id), (loan_account.partner_id, loan_account.company_id))
        self.assertEqual(holder.state, 'open')
        self.assertFalse(holder.product_ids)

    def test_prefix_is_configurable_per_company(self):
        self.env.company.savings_holder_account_prefix = 'EPX'
        client = self._client()
        self.assertEqual(client.microfinance_savings_holder_account_ids.name,
                         'EPX/%s' % self._loan_account(client).name)

    def test_savings_account_failure_rolls_back_credit_account(self):
        cin = self._cin()
        with patch.object(type(self.Holder), 'create', side_effect=ValidationError('échec simulé')):
            with self.assertRaises(ValidationError), self.env.cr.savepoint():
                self._create_context_client(cin, company_id=self.env.company.id)
        self.assertFalse(self.env['res.partner'].search([('microfinance_id_number', '=', cin)]))
        self.assertFalse(self.env['microfinance.loan.account'].search([('partner_id.microfinance_id_number', '=', cin)]))

    def test_credit_account_failure_rolls_back_savings_account(self):
        cin = self._cin()
        with patch.object(type(self.env['microfinance.loan.account']), 'create',
                          side_effect=ValidationError('échec simulé')):
            with self.assertRaises(ValidationError), self.env.cr.savepoint():
                self._create_context_client(cin, company_id=self.env.company.id)
        self.assertFalse(self.Holder.search([('partner_id.microfinance_id_number', '=', cin)]))

    def test_coherence_between_credit_and_savings_accounts(self):
        client, other = self._client(), self._client()
        holder = client.microfinance_savings_holder_account_ids
        with self.assertRaises(ValidationError):
            holder.sudo().write({'loan_account_id': self._loan_account(other).id})

    # --- Cycle de vie couplé ---
    def test_company_change_refused_when_accounts_exist(self):
        client = self._client()
        with self.assertRaises(UserError):
            client.write({'company_id': self.company_b.id})

    def test_archiving_refused_with_activity_allowed_without(self):
        busy, idle = self._client(), self._client()
        self._create_active_account(partner_id=busy.id, opening_amount=100.0)
        with self.assertRaises(UserError):
            busy.write({'active': False})
        idle.write({'active': False})
        self.assertFalse(idle.active)

    # --- Contrôle d'intégrité ---
    def test_sync_check_reports_without_fixing(self):
        missing_savings = self._client()
        self.env.cr.execute("DELETE FROM microfinance_savings_holder_account WHERE partner_id = %s", [missing_savings.id])
        mismatch = self._client()
        holder = mismatch.microfinance_savings_holder_account_ids
        self.env.cr.execute("UPDATE microfinance_savings_holder_account SET name = 'CE/XX/999999' WHERE id = %s", [holder.id])
        orphan = self._client()
        self.env.cr.execute("DELETE FROM microfinance_loan_account WHERE partner_id = %s", [orphan.id])
        self.env.invalidate_all()
        kinds = {(i['kind'], i['partner_id']) for i in self.Holder.get_credit_savings_sync_issues()}
        self.assertIn(('missing_savings', missing_savings.id), kinds)
        self.assertIn(('number_mismatch', mismatch.id), kinds)
        self.assertIn(('missing_credit', orphan.id), kinds)
        with self.assertLogs('odoo.addons.microfinance_savings_management.models.microfinance_savings_holder_account',
                             level='WARNING'):
            self.assertGreaterEqual(self.Holder.cron_check_credit_savings_sync(), 3)
        self.assertFalse(missing_savings.microfinance_savings_holder_account_ids, "Le cron ne corrige rien.")
        self.assertEqual(holder.name, 'CE/XX/999999')

    # --- Produits : rang, nom, solde ---
    def test_three_products_one_account_ranks_and_balance(self):
        client = self._client()
        products = (
            self._product(client)
            | self._product(client, product_id=self.savings_product_2.id)
            | self._product(client, product_id=self.savings_product_3.id)
        )
        holder = client.microfinance_savings_holder_account_ids
        self.assertEqual(products.mapped('account_id'), holder)
        self.assertEqual(products.mapped('name'), ['%s-0%d' % (holder.name, rank) for rank in (1, 2, 3)])
        for product, amount in zip(products, (100.0, 250.0, 75.0)):
            product._create_transaction('deposit', amount)
            product.action_activate()
        products[2].action_close()
        self.env.flush_all()
        self.env.cr.execute("SELECT coalesce(sum(balance), 0) FROM microfinance_savings_account "
                            "WHERE account_id = %s AND state != 'closed'", [holder.id])
        self.assertAlmostEqual(holder.balance_total, self.env.cr.fetchone()[0], places=2)
        self.assertAlmostEqual(holder.balance_total, 350.0, places=2)
        # Réutilise le produit du 3e (products[2], clôturé ci-dessus) : un produit clôturé peut
        # être resouscrit (cf. test_duplicate_product_allowed_after_closing_the_first) - le 1er
        # et le 2e produit sont, eux, toujours ouverts.
        fourth = self._product(client, product_id=self.savings_product_3.id)
        self.assertEqual(fourth.rank, 4, "Un rang n'est jamais réutilisé.")
        self.assertEqual(fourth.name, '%s-04' % holder.name)

    def test_duplicate_rank_rejected_by_database(self):
        client = self._client()
        first = self._product(client)
        second = self._product(client, product_id=self.savings_product_2.id)
        with self.assertRaises(psycopg2.IntegrityError), mute_logger('odoo.sql_db'), self.env.cr.savepoint():
            second.sudo().with_context(savings_split_migration=True).write({'rank': first.rank})
            self.env.flush_all()

    def test_get_or_create_is_idempotent_and_safety_net(self):
        client = self._client()
        holder = client.microfinance_savings_holder_account_ids
        self.assertEqual(self.Holder._get_or_create_for(client, self.env.company), holder)
        self.env.cr.execute("DELETE FROM microfinance_savings_holder_account WHERE id = %s", [holder.id])
        self.env.invalidate_all()
        product = self._product(client)
        self.assertTrue(product.account_id, "Filet de sécurité : compte créé à la souscription.")
        self.assertEqual(product.account_id.name, 'CE/%s' % self._loan_account(client).name)

    def test_same_client_in_two_agencies_gets_two_accounts(self):
        product_a = self._product(self.partner)
        product_b = self._product(self.partner, company_id=self.company_b.id)
        holder_a, holder_b = product_a.account_id, product_b.account_id
        self.assertNotEqual(holder_a, holder_b)
        self.assertEqual((holder_a.company_id, holder_b.company_id), (self.env.company, self.company_b))
        for holder in (holder_a, holder_b):
            self.assertEqual(holder.name, 'CE/%s' % holder.loan_account_id.name)
            self.assertEqual(holder.loan_account_id.company_id, holder.company_id)
        self.assertNotEqual(holder_a.name, holder_b.name)

    def test_product_constraints(self):
        client = self._client()
        with self.assertRaises(ValidationError):
            self._product(client, product_id=False)
        product = self._product(client)
        other_holder = self._client().microfinance_savings_holder_account_ids
        with self.assertRaises(UserError):
            product.write({'account_id': other_holder.id})
        self.assertNotIn('is_container', self.env['microfinance.savings.account'].get_view(
            self.env.ref('microfinance_savings_management.view_microfinance_savings_account_form').id)['arch'])

    def test_product_of_other_agency_client_rejected(self):
        client = self._client()
        with self.assertRaises(ValidationError):
            self._product(client, company_id=self.company_b.id)

    def test_states_follow_products(self):
        client = self._client()
        holder = client.microfinance_savings_holder_account_ids
        self.assertEqual(holder.state, 'open')
        first = self._product(client)
        self.assertEqual(holder.state, 'open', "Produit en brouillon : compte ouvert.")
        first._create_transaction('deposit', 50.0)
        first.action_activate()
        self.assertEqual(holder.state, 'active')
        first.write({'state': 'dormant'})
        self.assertEqual(holder.state, 'dormant')
        first.write({'state': 'active'})
        first.action_close()
        self.assertEqual(holder.state, 'closed')

    # --- Guichet ---
    def test_guichet_returns_account_and_products(self):
        client = self._client()
        product = self._create_active_account(partner_id=client.id, opening_amount=120.0)
        holder = client.microfinance_savings_holder_account_ids
        summary = self.env['res.partner'].get_client_accounts_summary(client.id, self.env.company.id)
        self.assertEqual(summary['savings_holder_account']['name'], holder.name)
        self.assertEqual([a['id'] for a in summary['savings_accounts']], [product.id])
        self.assertEqual(summary['savings_accounts'][0]['account_name'], holder.name)
        found = self.env['res.partner'].search_caisse_clients(client.name, self.env.company.id)
        self.assertEqual([r['savings_account_name'] for r in found if r['id'] == client.id], [holder.name])
