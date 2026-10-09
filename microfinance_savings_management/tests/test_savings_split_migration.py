# -*- coding: utf-8 -*-
import random
import tempfile

from odoo.exceptions import UserError

from odoo.addons.microfinance_loan_management.tests.common import MicrofinanceNoFundMixin

from .common import SavingsCommon
from .. import savings_split_migration as split


class TestSavingsSplitMigration(MicrofinanceNoFundMixin, SavingsCommon):
    """Migration 17.0.1.7.0 : anciens conteneurs -> comptes épargne, produits rattachés, crédits
    repointés ou vidés, garde société, passage 2. Les données « d'avant » sont reconstituées en SQL
    (un conteneur ne peut plus être créé par l'ORM)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_b = cls.env['res.company'].create({'name': 'Agence B migration split (test)', 'agency_code': 'ZM'})
        cls.env.user.company_ids = [(4, cls.company_b.id)]

    def setUp(self):
        super().setUp()
        self.log_dir = tempfile.mkdtemp()
        # Correction manuelle préalable des données réelles de la base (conteneur rangé dans une
        # autre agence que son titulaire, cf. D6) : sinon la garde bloque tout passage réel.
        self.env.cr.execute("""UPDATE microfinance_savings_account s SET company_id = p.company_id
                                 FROM res_partner p WHERE p.id = s.partner_id AND s.is_container
                                  AND p.company_id IS NOT NULL AND p.company_id <> s.company_id""")
        self.Holder = self.env['microfinance.savings.holder.account']
        self.Product = self.env['microfinance.savings.account']

    def _cin(self):
        Partner = self.env['res.partner'].with_context(active_test=False)
        while True:
            cin = ''.join(str(random.randint(0, 9)) for _ in range(12))
            if not Partner.search_count([('microfinance_id_number', '=', cin)]):
                return cin

    def _legacy_client(self, container=True, products=0, container_company=None):
        """Client « d'avant » : compte crédit, pas de compte épargne, éventuel conteneur et produits
        non rattachés."""
        client = self._create_context_client(self._cin(), company_id=self.env.company.id)
        made = self.Product.browse()
        for _i in range(products):
            product = self._create_account(partner_id=client.id)
            product._create_transaction('deposit', 100.0)
            product.action_activate()
            made |= product
        self.env.flush_all()
        cr = self.env.cr
        if made:
            cr.execute("UPDATE microfinance_savings_account SET account_id = NULL, rank = NULL, "
                       "name = 'OLD/' || id WHERE id IN %s", [tuple(made.ids)])
        cr.execute("DELETE FROM microfinance_savings_holder_account WHERE partner_id = %s", [client.id])
        container_id = False
        if container:
            company = container_company or self.env.company
            cr.execute("""INSERT INTO microfinance_savings_account
                          (name, partner_id, company_id, is_container, state, balance, create_date, write_date)
                          VALUES (%s, %s, %s, true, 'draft', 0, now(), now()) RETURNING id""",
                       ['%s/I/%s' % (company.agency_code, client.microfinance_account_number.split('/')[1]),
                        client.id, company.id])
            container_id = cr.fetchone()[0]
        self.env.invalidate_all()
        return client, self.Product.browse(container_id), made

    def _statuses(self, rows, record, etape):
        return [r['statut'] for r in rows if r['id'] == record.id and r['etape'] == etape]

    def _scenario(self):
        with_product, container_1, products_1 = self._legacy_client(products=1)
        empty, container_2, _p = self._legacy_client()
        no_container, _c, _p = self._legacy_client(container=False)
        orphan_product, _c, products_4 = self._legacy_client(container=False, products=1)
        loan_1 = self._create_loan(partner_id=with_product.id)
        loan_2 = self._create_loan(partner_id=empty.id)
        self.env.cr.execute("UPDATE microfinance_loan SET savings_account_id = %s WHERE id = %s", [container_1.id, loan_1.id])
        self.env.cr.execute("UPDATE microfinance_loan SET savings_account_id = %s WHERE id = %s", [container_2.id, loan_2.id])
        self.env.invalidate_all()
        return locals()

    def test_dry_run_writes_nothing(self):
        s = self._scenario()
        holders_before = self.Holder.search_count([])
        rows, checks, before, after = split.run_split_pass1(self.env, dry_run=True, log_dir=self.log_dir)
        self.env.invalidate_all()
        self.assertEqual(self.Holder.search_count([]), holders_before)
        self.assertFalse(s['products_1'].account_id)
        self.assertEqual(s['loan_1'].savings_account_id, s['container_1'])
        self.assertIn('COMPTE_CREE', self._statuses(rows, s['container_1'], 'b_conteneur'))
        self.assertTrue(all(ok for ok, _detail in checks.values()), checks)
        self.assertEqual(before, after)

    def test_dry_run_is_default(self):
        self.env['ir.config_parameter'].sudo().search([('key', '=', split.PARAM_DRY_RUN)]).unlink()
        self.assertTrue(split.is_dry_run(self.env))
        self.assertEqual(self.env['ir.config_parameter'].sudo().get_param(split.PARAM_DRY_RUN), 'True')

    def test_real_pass1_then_idempotent(self):
        s = self._scenario()
        rows, checks, before, after = split.run_split_pass1(self.env, dry_run=False, log_dir=self.log_dir)
        self.env.invalidate_all()
        self.assertTrue(all(ok for ok, _detail in checks.values()), checks)
        self.assertEqual(before, after, "Produits, soldes, transactions, caisse, écritures identiques.")
        for client in (s['with_product'], s['empty'], s['no_container'], s['orphan_product']):
            holder = client.microfinance_savings_holder_account_ids
            loan_account = self.env['microfinance.loan.account'].search([('partner_id', '=', client.id)])
            self.assertEqual(len(holder), 1, client.name)
            self.assertEqual(holder.name, 'CE/%s' % loan_account.name)
        self.assertEqual(s['empty'].microfinance_savings_holder_account_ids.legacy_number, s['container_2'].name)
        product = s['products_1']
        self.assertEqual(product.account_id, s['with_product'].microfinance_savings_holder_account_ids)
        self.assertEqual((product.rank, product.legacy_number, product.name), (1, product.name, product.name))
        self.assertTrue(s['products_4'].account_id, "Produit sans conteneur : compte créé.")
        self.assertEqual(s['loan_1'].savings_account_id, product, "Unique produit actif : crédit repointé.")
        self.assertFalse(s['loan_2'].savings_account_id, "Aucun produit actif : crédit vidé, rien deviné.")
        self.assertIn('VIDE', self._statuses(rows, s['loan_2'], 'e_credit'))
        rows, checks, _b, _a = split.run_split_pass1(self.env, dry_run=False, log_dir=self.log_dir)
        self.assertFalse([r for r in rows if r['statut'] in ('COMPTE_CREE', 'RATTACHE', 'REPOINTE', 'VIDE')])
        self.assertTrue(all(ok for ok, _detail in checks.values()), checks)

    def test_guard_blocks_real_run_on_company_mismatch(self):
        _client, container, _p = self._legacy_client(container_company=self.company_b)
        rows, _checks, _b, _a = split.run_split_pass1(self.env, dry_run=True, log_dir=self.log_dir)
        self.assertIn('A_CORRIGER_MANUELLEMENT', self._statuses(rows, container, 'a_garde'))
        with self.assertRaises(UserError):
            split.run_split_pass1(self.env, dry_run=False, log_dir=self.log_dir)
        self.assertFalse(_client.microfinance_savings_holder_account_ids)

    def test_pass2_requires_explicit_parameter_and_keeps_referenced(self):
        s = self._scenario()
        split.run_split_pass1(self.env, dry_run=False, log_dir=self.log_dir)
        rows, removed = split.run_split_pass2(self.env, dry_run=False, log_dir=self.log_dir)
        self.assertEqual((removed, rows[0]['statut']), (0, 'NON_DEMANDE'))
        self.env['ir.config_parameter'].sudo().set_param(split.PARAM_REMOVE_CONTAINERS, 'True')
        self.env['account.move'].create({
            'move_type': 'entry', 'journal_id': self.disbursement_journal.id,
            'microfinance_savings_account_id': s['container_2'].id,
        })
        rows, removed = split.run_split_pass2(self.env, dry_run=False, log_dir=self.log_dir)
        self.assertFalse(s['container_1'].exists(), "Conteneur sans référence retiré.")
        self.assertTrue(s['container_2'].exists(), "Conteneur encore référencé conservé.")
        self.assertIn('CONSERVE', self._statuses(rows, s['container_2'], 'retrait'))
        self.assertGreaterEqual(removed, 1)

    def test_pass2_refused_when_pass1_checks_not_green(self):
        s = self._scenario()
        self.env['ir.config_parameter'].sudo().set_param(split.PARAM_REMOVE_CONTAINERS, 'True')
        with self.assertRaises(UserError):
            split.run_split_pass2(self.env, dry_run=False, log_dir=self.log_dir)
        self.assertTrue(s['container_1'].exists())

    def test_renumber_wizard_dry_run_then_real_never_touches_moves(self):
        s = self._scenario()
        split.run_split_pass1(self.env, dry_run=False, log_dir=self.log_dir)
        product = s['products_1']
        old_name = product.name
        move = self.env['account.move'].create({
            'move_type': 'entry', 'journal_id': self.disbursement_journal.id, 'ref': old_name,
        })
        Wizard = self.env['microfinance.savings.renumber.wizard']
        Wizard.create({'dry_run': True}).action_run()
        self.assertEqual(product.name, old_name, "Le dry-run n'écrit rien.")
        Wizard.create({'dry_run': False}).action_run()
        self.assertEqual(product.name, '%s-01' % product.account_id.name)
        self.assertEqual(product.legacy_number, old_name)
        self.assertEqual(move.ref, old_name, "Les références d'écritures ne sont jamais réécrites.")
