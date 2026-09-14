# -*- coding: utf-8 -*-
"""Sous-lot D — méthodes backend du guichet (recherche cross-agence, gardes de
register_transfert, action get_transfert_confirm_action).

Le cycle complet (register_transfert -> lot -> validation destination) avec un
crédit actif dans une seconde agence est couvert au sous-lot F, avec les fixtures
multi-société.
"""
from odoo import fields
from odoo.exceptions import UserError
from odoo.addons.microfinance_loan_management.tests.common import MicrofinanceCommon


class TestGuichetBackend(MicrofinanceCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company
        cls.company_b = cls.env['res.company'].create({
            'name': 'Agence B transfert (test backend)', 'agency_code': 'QT',
        })
        cls.client_b = cls.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Rabe Cross-Agence', 'microfinance_partner_type': 'client',
            'company_id': cls.company_b.id,
        })
        cls.non_client_b = cls.env['res.partner'].create({
            'name': 'Rabe Fournisseur', 'microfinance_partner_type': False,
            'company_id': cls.company_b.id,
        })
        cls.env.user.groups_id = [
            (4, cls.env.ref('microfinance_loan_management.group_microfinance_cashier').id),
            (4, cls.env.ref('microfinance_savings_management.group_savings_agent').id),
        ]

    # --- Recherche cross-agence -------------------------------------------------
    def test_search_other_agency_finds_client_of_other_company(self):
        res = self.env['res.partner'].search_other_agency_clients('Rabe', self.company_a.id)
        ids = {r['id'] for r in res}
        self.assertIn(self.client_b.id, ids)
        self.assertNotIn(self.non_client_b.id, ids, "un partenaire non-client est exclu")
        row = next(r for r in res if r['id'] == self.client_b.id)
        self.assertEqual(row['agency_name'], self.company_b.name)
        self.assertEqual(set(row), {'id', 'name', 'account_number', 'agency_name'})

    def test_search_other_agency_excludes_session_own_company(self):
        # Recherché depuis l'agence B : le client de B ne doit PAS ressortir (c'est
        # "sa" propre agence), la recherche cross-agence ne sert qu'aux AUTRES.
        res = self.env['res.partner'].search_other_agency_clients('Rabe', self.company_b.id)
        self.assertNotIn(self.client_b.id, {r['id'] for r in res})

    def test_search_other_agency_short_query_returns_empty(self):
        self.assertEqual(
            self.env['res.partner'].search_other_agency_clients('R', self.company_a.id), [])

    # --- Gardes de register_transfert / get_transfert_confirm_action ----------
    def _open_session_a(self):
        session = self.env['microfinance.caisse.session'].create({
            'journal_id': self.payment_journal.id, 'date': fields.Date.today(),
        })
        session.action_open_session()
        return session

    def test_register_transfert_refuses_same_agency_loan(self):
        loan = self._create_loan()  # crédit de l'agence A
        session = self._open_session_a()  # session de l'agence A
        Transfert = self.env['microfinance.transfert.remboursement']
        with self.assertRaises(UserError):
            Transfert.register_transfert(session.id, loan.id, 100.0)
        with self.assertRaises(UserError):
            Transfert.get_transfert_confirm_action(session.id, loan.id, 100.0)

    def test_register_transfert_refuses_without_open_session(self):
        loan = self._create_loan()
        session = self.env['microfinance.caisse.session'].create({
            'journal_id': self.payment_journal.id, 'date': fields.Date.today(),
        })  # brouillon
        with self.assertRaises(UserError):
            self.env['microfinance.transfert.remboursement'].register_transfert(
                session.id, loan.id, 100.0)

    def test_transfert_tab_data_shape(self):
        # Forme du dict renvoyé au guichet. On n'assène PAS "liste vide" : la base
        # peut déjà contenir des transferts réels de l'agence courante (créés en
        # production) ; le test ne doit vérifier que la structure et le type.
        session = self._open_session_a()
        Transfert = self.env['microfinance.transfert.remboursement']
        src = Transfert.get_transfert_source_data(session.id)
        self.assertEqual(set(src), {'pending', 'draft_lots'})
        self.assertIsInstance(src['pending'], list)
        self.assertIsInstance(src['draft_lots'], list)
        dst = Transfert.get_transfert_destination_data(session.id)
        self.assertEqual(set(dst), {'incoming'})
        self.assertIsInstance(dst['incoming'], list)
