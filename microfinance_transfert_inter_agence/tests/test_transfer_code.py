# -*- coding: utf-8 -*-
import datetime

from odoo import fields
from odoo.tests.common import TransactionCase


class TestTransferCodeFormat(TransactionCase):
    """Sous-lot A — res.company._build_microfinance_transfer_code.

    Vérifie le format exact du code de transfert inter-agences, le padding à 3 du
    numéro d'ordre, le tirage des DEUX numéros d'ordre à chaque appel et
    l'isolation des séquences par société.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Codes agence volontairement improbables pour ne pas heurter la contrainte
        # unique(agency_code) d'une base réelle. Les assertions dérivent des champs,
        # jamais d'un code en dur, pour rester robustes quel que soit le code retenu.
        cls.source_company = cls.env['res.company'].create({
            'name': 'Agence source transfert (test)', 'agency_code': 'QA',
        })
        cls.dest_company = cls.env['res.company'].create({
            'name': 'Agence destination transfert (test)', 'agency_code': 'QB',
        })
        cls.fixed_date = datetime.date(2027, 5, 1)  # -> jj/mm/aa = 01/05/27

    def _code(self, source, dest, account_number, date=None):
        return source._build_microfinance_transfer_code(
            dest, account_number, date=date or self.fixed_date)

    def test_full_format_and_padding(self):
        code = self._code(self.source_company, self.dest_company, 'QA/00042')
        self.assertEqual(
            code,
            'T/QA00042/%s/001/01/05/27/%s/001' % (
                self.source_company.agency_code, self.dest_company.agency_code),
        )
        # Padding strictement à 3 (ni 6, ni 1).
        self.assertIn('/001/', code)
        self.assertNotIn('/000001/', code)
        self.assertNotIn('/1/', code)

    def test_order_numbers_increment_on_each_call(self):
        first = self._code(self.source_company, self.dest_company, 'QA/1')
        second = self._code(self.source_company, self.dest_company, 'QA/1')
        self.assertTrue(first.endswith('/QA/001/01/05/27/QB/001'), first)
        self.assertTrue(second.endswith('/QA/002/01/05/27/QB/002'), second)

    def test_source_and_dest_sequences_are_isolated_per_company(self):
        # 1er transfert : source = QA (« sortant » #1), dest = QB (« entrant » #1).
        self._code(self.source_company, self.dest_company, 'X')
        # Transfert inverse : QB devient source (sa propre séquence « sortant », #1)
        # et QA devient destination (sa propre séquence « entrant », #1).
        reverse = self._code(self.dest_company, self.source_company, 'X')
        self.assertEqual(reverse, 'T/X/QB/001/01/05/27/QA/001')

    def test_client_account_number_slashes_are_stripped(self):
        code = self._code(self.source_company, self.dest_company, 'IS/000/123')
        self.assertIn('/IS000123/', code)
        self.assertNotIn('IS/000/123', code)

    def test_empty_account_number_is_tolerated(self):
        code = self._code(self.source_company, self.dest_company, '')
        self.assertTrue(code.startswith('T//%s/001/' % self.source_company.agency_code), code)

    def test_none_account_number_is_tolerated(self):
        code = self._code(self.source_company, self.dest_company, None)
        self.assertTrue(code.startswith('T//%s/001/' % self.source_company.agency_code), code)

    def test_date_defaults_to_today(self):
        code = self.source_company._build_microfinance_transfer_code(
            self.dest_company, 'QA/1')
        today = fields.Date.context_today(self.env.user)
        self.assertIn(
            '/%s/%s/%s/' % (today.strftime('%d'), today.strftime('%m'), today.strftime('%y')),
            code,
        )

    def test_requires_single_companies(self):
        pair = self.source_company | self.dest_company
        with self.assertRaises(ValueError):
            pair._build_microfinance_transfer_code(self.dest_company, 'QA/1')
        with self.assertRaises(ValueError):
            self.source_company._build_microfinance_transfer_code(pair, 'QA/1')
