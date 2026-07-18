# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError

from .common import MicrofinanceCommon


class TestCaisseFicheJourneeSecurity(MicrofinanceCommon):
    """Sécurité de la fiche journalière de caisse (Lot 4 du prompt « Menu Caisse ») :
    lecture/écriture pour cashier et manager, lecture seule pour finance/comptable/auditor,
    aucun accès pour les autres groupes ; cloisonnement multi-société."""

    def _user_in_group(self, group_xmlid, login):
        # base.group_user (Internal User) : ajouté explicitement comme le ferait la création
        # d'un utilisateur interne via Réglages > Utilisateurs (sélection du type "Utilisateur
        # interne"), sans quoi l'ORM brut ne l'ajoute pas et les modèles mail.thread (followers,
        # subtypes) restent inaccessibles — aucun des groupes microfinance n'implique
        # base.group_user lui-même.
        return self.env['res.users'].create({
            'name': login, 'login': login,
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id, self.env.ref(group_xmlid).id])],
        })

    def _create_fiche(self, **kwargs):
        vals = {'journal_id': self.disbursement_journal.id}
        vals.update(kwargs)
        return self.env['microfinance.caisse.fiche.journee'].create(vals)

    def test_cashier_can_create_read_write_not_unlink(self):
        user = self._user_in_group('microfinance_loan_management.group_microfinance_cashier', 'cashier_sec_test')
        fiche = self.env['microfinance.caisse.fiche.journee'].with_user(user).create({
            'journal_id': self.disbursement_journal.id,
        })
        fiche.with_user(user).read(['state'])
        fiche.with_user(user).write({'reopen_reason': 'motif test'})
        with self.assertRaises(AccessError):
            fiche.with_user(user).unlink()

    def test_manager_full_crud(self):
        user = self._user_in_group('microfinance_loan_management.group_microfinance_manager', 'manager_sec_test')
        fiche = self.env['microfinance.caisse.fiche.journee'].with_user(user).create({
            'journal_id': self.disbursement_journal.id,
        })
        fiche.with_user(user).write({'reopen_reason': 'motif test'})
        fiche.with_user(user).unlink()

    def test_finance_read_only(self):
        user = self._user_in_group('microfinance_loan_management.group_microfinance_finance', 'finance_sec_test')
        fiche = self._create_fiche()
        fiche.with_user(user).read(['state'])
        with self.assertRaises(AccessError):
            self.env['microfinance.caisse.fiche.journee'].with_user(user).create({
                'journal_id': self.disbursement_journal.id,
                'date': fields.Date.today() - timedelta(days=1),
            })

    def test_comptable_read_only(self):
        user = self._user_in_group('microfinance_loan_management.group_microfinance_comptable', 'comptable_sec_test')
        fiche = self._create_fiche()
        fiche.with_user(user).read(['state'])
        with self.assertRaises(AccessError):
            self.env['microfinance.caisse.fiche.journee'].with_user(user).create({
                'journal_id': self.disbursement_journal.id,
                'date': fields.Date.today() - timedelta(days=1),
            })

    def test_auditor_read_only(self):
        user = self._user_in_group('microfinance_loan_management.group_microfinance_auditor', 'auditor_sec_test')
        fiche = self._create_fiche()
        fiche.with_user(user).read(['state'])
        with self.assertRaises(AccessError):
            self.env['microfinance.caisse.fiche.journee'].with_user(user).create({
                'journal_id': self.disbursement_journal.id,
                'date': fields.Date.today() - timedelta(days=1),
            })

    def test_collection_agent_no_access(self):
        user = self._user_in_group('microfinance_loan_management.group_microfinance_collection_agent', 'collection_sec_test')
        fiche = self._create_fiche()
        with self.assertRaises(AccessError):
            fiche.with_user(user).read(['state'])

    def test_plain_user_no_access(self):
        user = self._user_in_group('microfinance_loan_management.group_microfinance_user', 'user_sec_test')
        fiche = self._create_fiche()
        with self.assertRaises(AccessError):
            fiche.with_user(user).read(['state'])

    def test_company_isolation(self):
        company_b = self.env['res.company'].create({'name': 'Agence B caisse (test)', 'agency_code': 'CS1'})
        self.env['account.journal'].create({
            'name': 'Caisse agence B (test)', 'code': 'BCAI2', 'type': 'cash', 'company_id': company_b.id,
        })
        user_b = self.env['res.users'].create({
            'name': 'Manager agence B caisse (test)', 'login': 'manager_b_caisse_test',
            'company_id': company_b.id, 'company_ids': [(6, 0, [company_b.id])],
            'groups_id': [(6, 0, [self.env.ref('microfinance_loan_management.group_microfinance_manager').id])],
        })
        fiche_a = self._create_fiche()
        fiches_for_b = self.env['microfinance.caisse.fiche.journee'].with_user(user_b).search(
            [('id', '=', fiche_a.id)])
        self.assertFalse(fiches_for_b)
        with self.assertRaises(AccessError):
            fiche_a.with_user(user_b).read(['state'])
