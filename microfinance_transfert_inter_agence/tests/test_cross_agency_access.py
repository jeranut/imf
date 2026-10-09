# -*- coding: utf-8 -*-
"""Régression — AccessError res.partner pendant la (re)lecture d'un transfert.

`microfinance.transfert.remboursement._guichet_row` lisait
`self.partner_id.display_name` SANS sudo. Or le client appartient à l'agence
DESTINATION (société du crédit), hors du périmètre multi-société du caissier
SOURCE : `base.res_partner_rule` lève alors AccessError au rechargement de
l'onglet « Transfert » qui suit l'encaissement — bien que tout le backend
(recherche, encaissement, écritures) ait réussi.

Ce test reproduit exactement ce chemin, en identité d'un CAISSIER PUR mono-agence
(pas Administrator, qui masque le trou), cache ORM vidé entre l'écriture et la
lecture (= nouvelle requête RPC).
"""
import base64

from odoo import fields
from odoo.exceptions import AccessError
from odoo.addons.microfinance_loan_management.tests.common import MicrofinanceCommon


class TestTransfertCrossAgencyAccess(MicrofinanceCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company

        # --- Agence B (destination) : société + jeu comptable minimal + produit ---
        cls.company_b = cls.env['res.company'].create({
            'name': 'Agence B (test access)', 'agency_code': 'ZB',
        })

        def acc(code, atype):
            return cls.env['account.account'].create({
                'name': code, 'code': code, 'account_type': atype,
                'company_id': cls.company_b.id,
            })
        cash_b = acc('ZBCASH', 'asset_cash')
        princ_b = acc('ZBPRET', 'asset_current')
        int_b = acc('ZBINT', 'income')
        pen_b = acc('ZBPEN', 'income_other')
        jrnl_b = cls.env['account.journal'].create({
            'name': 'Caisse B', 'code': 'ZBJ', 'type': 'cash',
            'company_id': cls.company_b.id, 'default_account_id': cash_b.id,
        })
        cls.product_b = cls.env['microfinance.loan.product'].with_company(cls.company_b).create({
            'name': 'Produit B', 'code': 'PB',
            'min_amount': 100.0, 'max_amount': 100000.0, 'min_term': 1, 'max_term': 36,
            'interest_rate': 12.0, 'interest_method': 'flat', 'installment_rounding_unit': 0,
            'repayment_frequency_mode': 'fixed',
            'repayment_frequency_id': cls.env.ref(
                'microfinance_loan_management.repayment_frequency_monthly').id,
            'disbursement_journal_id': jrnl_b.id,
            'payment_journal_id': jrnl_b.id,
            'account_principal_individuel_id': princ_b.id,
            'account_principal_groupe_id': princ_b.id,
            'account_interets_recus_individuel_id': int_b.id,
            'account_interets_recus_groupe_id': int_b.id,
            'account_penalites_id': pen_b.id,
        })
        cls.client_b = cls.env['res.partner'].with_context(microfinance_context=True, allow_microfinance_partner_create=True).create({
            'name': 'RAKOTO Cross-Agence', 'microfinance_partner_type': 'client',
            'company_id': cls.company_b.id,
        })
        cls.loan_b = cls.env['microfinance.loan'].with_company(cls.company_b).with_context(
            allowed_company_ids=[cls.company_b.id]).create({
            'partner_id': cls.client_b.id,
            'product_id': cls.product_b.id,
            'loan_amount': 5000.0,
            'term': 6,
            'company_id': cls.company_b.id,
            'signed_contract': base64.b64encode(b'x'),
            'signed_contract_filename': 'c.pdf',
        })

        # --- Caissier PUR mono-agence A + session ouverte à l'agence A ---
        cls.cashier = cls.env['res.users'].create({
            'name': 'Caissier A pur', 'login': 'cashier_a_xaccess',
            'company_id': cls.company_a.id,
            'company_ids': [(6, 0, [cls.company_a.id])],
            'groups_id': [
                (4, cls.env.ref('microfinance_loan_management.group_microfinance_cashier').id),
                (4, cls.env.ref('microfinance_savings_management.group_savings_agent').id),
            ],
        })
        cls.session_a = cls.env['microfinance.caisse.session'].create({
            'journal_id': cls.payment_journal.id, 'date': fields.Date.today(),
        })
        cls.session_a.action_open_session()

    def test_guichet_row_reads_cross_agency_partner_without_access_error(self):
        Transfert = self.env['microfinance.transfert.remboursement']
        transfert = Transfert.sudo().create({
            'loan_id': self.loan_b.id,
            'session_id': self.session_a.id,
            'amount': 1000.0,
        })
        self.assertEqual(transfert.partner_id, self.client_b)
        self.assertEqual(transfert.source_company_id, self.company_a)
        self.assertEqual(transfert.destination_company_id, self.company_b)

        # nouvelle requête RPC : cache ORM froid
        self.env.invalidate_all()
        as_cashier = Transfert.with_user(self.cashier).with_context(
            allowed_company_ids=[self.company_a.id])

        # garde-fou : le caissier pur ne PEUT PAS lire ce contact directement
        with self.assertRaises(AccessError):
            self.client_b.with_user(self.cashier).with_context(
                allowed_company_ids=[self.company_a.id]).check_access_rule("read")

        # ... mais le rechargement de l'onglet Transfert (source) doit fonctionner
        data = as_cashier.get_transfert_source_data(self.session_a.id)
        row = next(r for r in data['pending'] if r['id'] == transfert.id)
        self.assertEqual(row['partner'], self.client_b.display_name)
        self.assertEqual(row['destination'], self.company_b.name)
        self.assertEqual(row['loan_name'], self.loan_b.name)

    def test_guichet_row_from_source_cashier_reads_all_display_columns(self):
        """_guichet_row appelé en identité du caissier SOURCE mono-agence : toutes
        les colonnes (client + agence destination, hors de son périmètre) doivent
        être lisibles, pas seulement le nom du client."""
        Transfert = self.env['microfinance.transfert.remboursement']
        transfert = Transfert.sudo().create({
            'loan_id': self.loan_b.id, 'session_id': self.session_a.id, 'amount': 800.0,
        })
        self.env.invalidate_all()
        row = transfert.with_user(self.cashier).with_context(
            allowed_company_ids=[self.company_a.id])._guichet_row()
        self.assertEqual(row['partner'], self.client_b.display_name)
        self.assertEqual(row['source'], self.company_a.name)
        self.assertEqual(row['destination'], self.company_b.name)
        self.assertEqual(row['loan_name'], self.loan_b.name)
        self.assertEqual(row['amount'], 800.0)
