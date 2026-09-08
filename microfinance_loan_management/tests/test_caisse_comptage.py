# -*- coding: utf-8 -*-
"""Sous-lot D — modèles de billetage : microfinance.caisse.denomination,
microfinance.caisse.comptage (+ .line). Calculs (counted_total, variance, subtotal),
contrainte de motif obligatoire si écart, contraintes de cohérence."""
from psycopg2 import IntegrityError

from odoo.exceptions import ValidationError
from odoo.tools import mute_logger

from .common import MicrofinanceCommon


class TestCaisseComptage(MicrofinanceCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.currency = cls.env.company.currency_id
        cls.d1000 = cls.env['microfinance.caisse.denomination'].create({
            'name': 'Comptage test 1000', 'value': 1000.0, 'currency_id': cls.currency.id,
        })
        cls.d500 = cls.env['microfinance.caisse.denomination'].create({
            'name': 'Comptage test 500', 'value': 500.0, 'currency_id': cls.currency.id,
        })
        cls.d100 = cls.env['microfinance.caisse.denomination'].create({
            'name': 'Comptage test 100', 'value': 100.0, 'currency_id': cls.currency.id,
        })

    def _session(self):
        return self.env['microfinance.caisse.session'].create({
            'journal_id': self.disbursement_journal.id,
        })

    def _comptage(self, session, theoretical, line_specs, comment='motif test'):
        return self.env['microfinance.caisse.comptage'].create({
            'session_id': session.id,
            'theoretical_total': theoretical,
            'variance_comment': comment,
            'line_ids': [
                (0, 0, {'denomination_id': denomination.id, 'quantity': quantity})
                for denomination, quantity in line_specs
            ],
        })

    # --- Calculs ---

    def test_line_subtotal_is_value_times_quantity(self):
        session = self._session()
        comptage = self._comptage(session, 500.0, [(self.d100, 5)])
        line = comptage.line_ids
        self.assertEqual(line.subtotal, 500.0)
        self.assertEqual(line.denomination_value, 100.0)

    def test_counted_total_is_sum_of_subtotals(self):
        session = self._session()
        comptage = self._comptage(session, 1000.0, [(self.d500, 1), (self.d100, 5)])
        self.assertEqual(comptage.counted_total, 1000.0)

    def test_variance_is_counted_minus_theoretical(self):
        session = self._session()
        comptage = self._comptage(session, 1200.0, [(self.d500, 1), (self.d100, 5)])
        self.assertEqual(comptage.variance, -200.0)

    def test_company_and_currency_come_from_session(self):
        session = self._session()
        comptage = self._comptage(session, 0.0, [(self.d100, 1)])
        self.assertEqual(comptage.company_id, session.company_id)
        self.assertEqual(comptage.currency_id, session.currency_id)

    # --- Contrainte : motif obligatoire si écart ---

    def test_comment_required_when_variance_nonzero(self):
        session = self._session()
        with self.assertRaises(ValidationError):
            with self.env.cr.savepoint():
                self._comptage(session, 1000.0, [(self.d100, 1)], comment=False)

    def test_comment_whitespace_only_rejected_when_variance(self):
        session = self._session()
        with self.assertRaises(ValidationError):
            with self.env.cr.savepoint():
                self._comptage(session, 1000.0, [(self.d100, 1)], comment='   ')

    def test_comment_not_required_when_exact(self):
        session = self._session()
        comptage = self._comptage(session, 100.0, [(self.d100, 1)], comment=False)
        self.assertEqual(comptage.variance, 0.0)

    def test_writing_lines_to_zero_variance_clears_comment_requirement(self):
        # Un comptage d'abord en écart (avec motif), ramené ensuite à l'exact : le retrait du
        # motif doit alors être accepté (la contrainte ne se déclenche plus).
        session = self._session()
        comptage = self._comptage(session, 100.0, [(self.d100, 5)], comment='écart initial')
        self.assertEqual(comptage.variance, 400.0)
        comptage.line_ids.quantity = 1
        comptage.variance_comment = False
        self.assertEqual(comptage.variance, 0.0)

    # --- Contraintes de cohérence ---

    def test_negative_quantity_rejected(self):
        session = self._session()
        with self.assertRaises(ValidationError):
            with self.env.cr.savepoint():
                self._comptage(session, 0.0, [(self.d100, -1)], comment='motif')

    def test_denomination_value_must_be_positive(self):
        with self.assertRaises(ValidationError):
            with self.env.cr.savepoint():
                self.env['microfinance.caisse.denomination'].create({
                    'name': 'Coupure nulle', 'value': 0.0, 'currency_id': self.currency.id,
                })

    def test_denomination_name_currency_unique(self):
        self.env['microfinance.caisse.denomination'].create({
            'name': 'Doublon test', 'value': 111.0, 'currency_id': self.currency.id,
        })
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.env['microfinance.caisse.denomination'].create({
                    'name': 'Doublon test', 'value': 222.0, 'currency_id': self.currency.id,
                })

    def test_line_denomination_unique_per_comptage(self):
        session = self._session()
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self._comptage(session, 0.0, [(self.d100, 1), (self.d100, 2)], comment='motif')
