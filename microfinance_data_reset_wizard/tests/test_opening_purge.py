# -*- coding: utf-8 -*-
"""RAZ microfinance : suppression directe, pour les tests, de la balance d'ouverture (même validée), de son écriture et des
clients de la reprise de portefeuille."""
from .common import MicrofinanceDataResetCommon


class TestOpeningPurge(MicrofinanceDataResetCommon):

    def setUp(self):
        super().setUp()
        # Agence de test dédiée (jamais la société réelle de la base)
        self.company, self.product, self.savings_product, self.payment_journal, self.partner = \
            self._setup_second_company('T2')
        self.bank_account = self.env['account.account'].create({
            'name': 'Banque test purge', 'code': 'TPBANK', 'account_type': 'asset_cash', 'company_id': self.company.id})

    def _validated_balance(self):
        if not self.env['account.journal'].search_count([('company_id', '=', self.company.id), ('code', '=', 'AN'),
                                                         ('type', '=', 'general')]):
            self.env['account.journal'].create({'name': 'AN', 'code': 'AN', 'type': 'general', 'company_id': self.company.id})
        capital = self.env['account.account'].create({
            'name': 'Capital test purge', 'code': 'TPURGE', 'account_type': 'equity', 'company_id': self.company.id})
        balance = self.env['microfinance.opening.balance'].with_context(mf_opening_allow_multiple=True).create({
            'company_id': self.company.id, 'date': '2026-10-10',
            'line_ids': [(0, 0, {'account_id': self.bank_account.id, 'debit': 100.0}),
                         (0, 0, {'account_id': capital.id, 'credit': 100.0})]})
        balance.action_validate()
        return balance

    def _run(self, **kwargs):
        wizard = self._make_wizard(self.company, **kwargs)
        wizard.action_start_execute() if kwargs.get('i_confirm') else wizard.action_start_dry_run()
        wizard.action_process_all_remaining()
        return wizard

    def test_purge_supprime_balance_validee_ecriture_et_clients_de_reprise(self):
        balance = self._validated_balance()
        move = balance.move_id
        self.assertEqual(balance.state, 'validated')
        reprise_client = self.env['res.partner'].create({
            'name': 'Client reprise test', 'company_id': self.company.id, 'opening_balance_id': balance.id})
        wizard = self._run(i_confirm=True, confirm_text='SUPPRIMER')
        self.assertEqual(wizard.state, 'done')
        self.assertNotIn('ERREUR', wizard.log)
        self.assertFalse(balance.exists())
        self.assertFalse(move.exists())
        self.assertFalse(reprise_client.exists())
        self.assertTrue(self.partner.exists())  # les autres clients survivent

    def test_simulation_ne_supprime_rien(self):
        balance = self._validated_balance()
        reprise_client = self.env['res.partner'].create({
            'name': 'Client reprise test', 'company_id': self.company.id, 'opening_balance_id': balance.id})
        wizard = self._run()
        self.assertNotIn('ERREUR', wizard.log)
        self.assertTrue(balance.exists() and balance.move_id.exists() and reprise_client.exists())

    def test_le_verrou_de_suppression_reste_sans_le_raz(self):
        from odoo.exceptions import UserError
        balance = self._validated_balance()
        with self.assertRaises(UserError):
            balance.unlink()
