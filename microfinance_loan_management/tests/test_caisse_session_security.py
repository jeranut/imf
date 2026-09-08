# -*- coding: utf-8 -*-
"""Sous-lot D — sécurité des modèles de caisse jusqu'ici non couverts :
microfinance.caisse.session (absent de test_caisse_security.py, cf. AUDIT §6.3),
microfinance.caisse.denomination, microfinance.caisse.comptage. Même patron que
TestCaisseFicheJourneeSecurity : cashier RWC sans unlink, manager CRUD complet, lecture
seule pour finance/comptable/auditeur, cloisonnement multi-société."""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError

from .common import MicrofinanceCommon


class _CaisseSecurityBase(MicrofinanceCommon):

    def _user_in_group(self, group_xmlid, login):
        return self.env['res.users'].create({
            'name': login, 'login': login,
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id, self.env.ref(group_xmlid).id])],
        })


class TestCaisseSessionSecurity(_CaisseSecurityBase):

    def _create_session(self, **kwargs):
        vals = {'journal_id': self.disbursement_journal.id}
        vals.update(kwargs)
        return self.env['microfinance.caisse.session'].create(vals)

    def test_cashier_can_create_read_write_not_unlink(self):
        user = self._user_in_group('microfinance_loan_management.group_microfinance_cashier', 'cashier_sess_test')
        session = self.env['microfinance.caisse.session'].with_user(user).create({
            'journal_id': self.disbursement_journal.id,
        })
        session.with_user(user).read(['state'])
        session.with_user(user).write({'cashier_id': user.id})
        with self.assertRaises(AccessError):
            session.with_user(user).unlink()

    def test_manager_full_crud(self):
        user = self._user_in_group('microfinance_loan_management.group_microfinance_manager', 'manager_sess_test')
        session = self.env['microfinance.caisse.session'].with_user(user).create({
            'journal_id': self.disbursement_journal.id,
        })
        session.with_user(user).write({'cashier_id': user.id})
        session.with_user(user).unlink()

    def test_finance_read_only(self):
        user = self._user_in_group('microfinance_loan_management.group_microfinance_finance', 'finance_sess_test')
        session = self._create_session()
        session.with_user(user).read(['state'])
        with self.assertRaises(AccessError):
            self.env['microfinance.caisse.session'].with_user(user).create({
                'journal_id': self.disbursement_journal.id,
            })

    def test_comptable_read_only(self):
        user = self._user_in_group('microfinance_loan_management.group_microfinance_comptable', 'comptable_sess_test')
        session = self._create_session()
        session.with_user(user).read(['state'])
        with self.assertRaises(AccessError):
            self.env['microfinance.caisse.session'].with_user(user).create({
                'journal_id': self.disbursement_journal.id,
            })

    def test_auditor_read_only(self):
        user = self._user_in_group('microfinance_loan_management.group_microfinance_auditor', 'auditor_sess_test')
        session = self._create_session()
        session.with_user(user).read(['state'])
        with self.assertRaises(AccessError):
            self.env['microfinance.caisse.session'].with_user(user).create({
                'journal_id': self.disbursement_journal.id,
            })

    def test_plain_user_no_access(self):
        user = self._user_in_group('microfinance_loan_management.group_microfinance_user', 'user_sess_test')
        session = self._create_session()
        with self.assertRaises(AccessError):
            session.with_user(user).read(['state'])

    def test_collection_agent_no_access(self):
        user = self._user_in_group('microfinance_loan_management.group_microfinance_collection_agent', 'collection_sess_test')
        session = self._create_session()
        with self.assertRaises(AccessError):
            session.with_user(user).read(['state'])

    def test_company_isolation(self):
        company_b = self.env['res.company'].create({'name': 'Agence B session (test)', 'agency_code': 'SS1'})
        self.env['account.journal'].create({
            'name': 'Caisse agence B session (test)', 'code': 'BSES2', 'type': 'cash',
            'company_id': company_b.id,
        })
        user_b = self.env['res.users'].create({
            'name': 'Manager agence B session (test)', 'login': 'manager_b_session_test',
            'company_id': company_b.id, 'company_ids': [(6, 0, [company_b.id])],
            'groups_id': [(6, 0, [self.env.ref('microfinance_loan_management.group_microfinance_manager').id])],
        })
        session_a = self._create_session()
        self.assertFalse(
            self.env['microfinance.caisse.session'].with_user(user_b).search([('id', '=', session_a.id)]))
        with self.assertRaises(AccessError):
            session_a.with_user(user_b).read(['state'])


class TestCaisseDenominationSecurity(_CaisseSecurityBase):

    def _denom(self):
        return self.env['microfinance.caisse.denomination'].create({
            'name': 'Sécurité test 100', 'value': 100.0,
            'currency_id': self.env.company.currency_id.id,
        })

    def test_cashier_read_only(self):
        user = self._user_in_group('microfinance_loan_management.group_microfinance_cashier', 'cashier_denom_test')
        denom = self._denom()
        denom.with_user(user).read(['value'])
        with self.assertRaises(AccessError):
            self.env['microfinance.caisse.denomination'].with_user(user).create({
                'name': 'Interdit', 'value': 50.0, 'currency_id': self.env.company.currency_id.id,
            })

    def test_finance_can_create_write_not_unlink(self):
        user = self._user_in_group('microfinance_loan_management.group_microfinance_finance', 'finance_denom_test')
        denom = self.env['microfinance.caisse.denomination'].with_user(user).create({
            'name': 'Finance test 200', 'value': 200.0, 'currency_id': self.env.company.currency_id.id,
        })
        denom.with_user(user).write({'value': 250.0})
        with self.assertRaises(AccessError):
            denom.with_user(user).unlink()

    def test_manager_full_crud(self):
        user = self._user_in_group('microfinance_loan_management.group_microfinance_manager', 'manager_denom_test')
        denom = self.env['microfinance.caisse.denomination'].with_user(user).create({
            'name': 'Manager test 500', 'value': 500.0, 'currency_id': self.env.company.currency_id.id,
        })
        denom.with_user(user).unlink()

    def test_auditor_read_only(self):
        user = self._user_in_group('microfinance_loan_management.group_microfinance_auditor', 'auditor_denom_test')
        denom = self._denom()
        denom.with_user(user).read(['value'])
        with self.assertRaises(AccessError):
            self.env['microfinance.caisse.denomination'].with_user(user).create({
                'name': 'Interdit auditeur', 'value': 50.0, 'currency_id': self.env.company.currency_id.id,
            })


class TestCaisseComptageSecurity(_CaisseSecurityBase):

    def _session(self):
        # Date distincte à chaque appel : plusieurs sessions dans un même test sans buter sur
        # unique(journal_id, date).
        self._sess_seq = getattr(self, '_sess_seq', 0) + 1
        return self.env['microfinance.caisse.session'].create({
            'journal_id': self.disbursement_journal.id,
            'date': fields.Date.today() - timedelta(days=self._sess_seq),
        })

    def _comptage(self):
        return self.env['microfinance.caisse.comptage'].create({'session_id': self._session().id})

    def test_cashier_can_create_read_write_not_unlink(self):
        user = self._user_in_group('microfinance_loan_management.group_microfinance_cashier', 'cashier_compt_test')
        comptage = self.env['microfinance.caisse.comptage'].with_user(user).create({
            'session_id': self._session().id,
        })
        comptage.with_user(user).read(['counted_total'])
        comptage.with_user(user).write({'variance_comment': 'note'})
        with self.assertRaises(AccessError):
            comptage.with_user(user).unlink()

    def test_manager_full_crud(self):
        user = self._user_in_group('microfinance_loan_management.group_microfinance_manager', 'manager_compt_test')
        comptage = self.env['microfinance.caisse.comptage'].with_user(user).create({
            'session_id': self._session().id,
        })
        comptage.with_user(user).unlink()

    def test_finance_read_only(self):
        user = self._user_in_group('microfinance_loan_management.group_microfinance_finance', 'finance_compt_test')
        comptage = self._comptage()
        comptage.with_user(user).read(['counted_total'])
        with self.assertRaises(AccessError):
            self.env['microfinance.caisse.comptage'].with_user(user).create({
                'session_id': self._session().id,
            })

    def test_auditor_read_only(self):
        user = self._user_in_group('microfinance_loan_management.group_microfinance_auditor', 'auditor_compt_test')
        comptage = self._comptage()
        comptage.with_user(user).read(['counted_total'])
        with self.assertRaises(AccessError):
            self.env['microfinance.caisse.comptage'].with_user(user).create({
                'session_id': self._session().id,
            })

    def test_company_isolation(self):
        company_b = self.env['res.company'].create({'name': 'Agence B comptage (test)', 'agency_code': 'CP1'})
        journal_b = self.env['account.journal'].create({
            'name': 'Caisse agence B comptage (test)', 'code': 'BCPT2', 'type': 'cash',
            'company_id': company_b.id,
        })
        user_b = self.env['res.users'].create({
            'name': 'Manager agence B comptage (test)', 'login': 'manager_b_comptage_test',
            'company_id': company_b.id, 'company_ids': [(6, 0, [company_b.id])],
            'groups_id': [(6, 0, [self.env.ref('microfinance_loan_management.group_microfinance_manager').id])],
        })
        comptage_a = self._comptage()
        self.assertFalse(
            self.env['microfinance.caisse.comptage'].with_user(user_b).search([('id', '=', comptage_a.id)]))
        with self.assertRaises(AccessError):
            comptage_a.with_user(user_b).read(['counted_total'])
