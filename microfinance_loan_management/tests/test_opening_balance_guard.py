# -*- coding: utf-8 -*-
"""Une seule balance d'ouverture par société : blocage au clic sur Nouveau (default_get), filet dans create(), duplication
refusée, index unique partiel sur les brouillons, portée stricte à la société active."""
from psycopg2 import IntegrityError

from odoo.exceptions import UserError
from odoo.tests import TransactionCase
from odoo.tools import mute_logger

from .common import MicrofinanceNoFundMixin


class TestOpeningBalanceGuard(MicrofinanceNoFundMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({'name': 'Agence GF (test)', 'agency_code': 'GF1'})
        cls.other = cls.env['res.company'].create({'name': 'Agence GF 2 (test)', 'agency_code': 'GF2'})
        cls.bank = cls._acc(cls.company, '131101', 'asset_cash')
        cls.capital = cls._acc(cls.company, '563000', 'equity')
        cls.env['account.journal'].create({'name': 'AN GF', 'code': 'AN', 'type': 'general', 'company_id': cls.company.id})

    @classmethod
    def _acc(cls, company, code, account_type):
        return cls.env['account.account'].create({'code': code, 'name': 'Test ' + code, 'account_type': account_type,
                                                  'company_id': company.id})

    def _model(self, company):
        return self.env['microfinance.opening.balance'].with_company(company).with_context(allowed_company_ids=company.ids)

    def test_nouveau_autorise_sans_balance_puis_bloque_avec_brouillon(self):
        Balance = self._model(self.company)
        self.assertEqual(Balance.default_get(['company_id', 'date'])['company_id'], self.company.id)
        Balance.create({'company_id': self.company.id})
        with self.assertRaises(UserError) as error:
            Balance.default_get(['company_id', 'date'])
        self.assertIn("existe déjà", error.exception.args[0])
        self.assertIn('brouillon', error.exception.args[0])

    def test_nouveau_bloque_aussi_avec_balance_validee(self):
        Balance = self._model(self.company)
        balance = Balance.create({'company_id': self.company.id, 'line_ids': [
            (0, 0, {'account_id': self.bank.id, 'debit': 10.0}), (0, 0, {'account_id': self.capital.id, 'credit': 10.0})]})
        balance.action_validate()
        with self.assertRaises(UserError) as error:
            Balance.default_get(['company_id'])
        self.assertIn('validée', error.exception.args[0])
        with self.assertRaises(UserError):
            Balance.create({'company_id': self.company.id})

    def test_deuxieme_societe_independante(self):
        self._model(self.company).create({'company_id': self.company.id})
        Other = self._model(self.other)
        self.assertEqual(Other.default_get(['company_id'])['company_id'], self.other.id)
        self.assertTrue(Other.create({'company_id': self.other.id}))

    def test_chargement_de_la_liste_ne_declenche_pas_le_blocage(self):
        Balance = self._model(self.company)
        Balance.create({'company_id': self.company.id})
        self.assertTrue(Balance.search([('company_id', '=', self.company.id)]))
        Balance.get_views([(False, 'list'), (False, 'form')])

    def test_create_rpc_et_duplication_refuses(self):
        Balance = self._model(self.company)
        balance = Balance.create({'company_id': self.company.id})
        with self.assertRaises(UserError):
            Balance.create({'company_id': self.company.id, 'date': '2026-10-12'})
        with self.assertRaises(UserError):
            Balance.create([{'company_id': self.other.id}, {'company_id': self.other.id}])
        with self.assertRaises(UserError):
            balance.copy()

    def test_index_unique_partiel_sur_les_brouillons(self):
        Balance = self._model(self.company).with_context(mf_opening_allow_multiple=True)
        Balance.create({'company_id': self.company.id})
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'), self.env.cr.savepoint():
            Balance.create({'company_id': self.company.id})
