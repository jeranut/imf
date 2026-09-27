# -*- coding: utf-8 -*-
from psycopg2 import IntegrityError

from odoo import tools
from odoo.exceptions import ValidationError
from odoo.tools import mute_logger

from odoo.addons.microfinance_loan_management.tests.common import MicrofinanceNoFundMixin

from .common import SavingsCommon


class TestSavingsContainerNumbering(MicrofinanceNoFundMixin, SavingsCommon):
    """Correctif du 2026-09-24 (docs_dev/epargne_auto/AUDIT_doublons_creation_client.md §13) :
    le conteneur épargne partage l'espace de noms AGENCE/I/N avec les comptes réels de type
    volontaire, mais réserve le N du client (= celui du compte crédit) en étant créé EN PREMIER,
    à l'enregistrement du client. Abroge l'« Option A » du 21/09 (espace de noms séparé
    AGENCE/IC/..., compte principal distinct)."""

    def _containers(self, partner):
        return self.env['microfinance.savings.account'].search([
            ('partner_id', '=', partner.id), ('is_container', '=', True)])

    def test_client_creation_gives_exactly_one_container_named_on_permanent_number(self):
        partner = self._create_context_client('821000000001')
        container = self._containers(partner)
        self.assertEqual(len(container), 1)
        agency, suffix = partner.microfinance_account_number.split('/', 1)
        self.assertEqual(container.name, '%s/I/%s' % (agency, suffix))
        self.assertEqual(len(partner.microfinance_savings_account_ids), 1)

    def test_real_account_created_after_skips_the_container_number(self):
        # Le conteneur étant créé en premier, la boucle de _get_next_available_savings_account_
        # name doit sauter son nom : plus jamais la collision historique (crédit SY/000001,
        # conteneur relégué sur SY/I/000002 - cf. audit §5).
        partner = self._create_context_client('821000000002')
        container = self._containers(partner)
        account = self._create_account(partner_id=partner.id)
        self.assertNotEqual(account.name, container.name)
        self.assertTrue(account.name.startswith(container.name.rsplit('/', 1)[0] + '/'))

    def test_existing_target_name_raises_instead_of_silent_fallback(self):
        partner = self._create_context_client('821000000003')
        target = self.env['microfinance.savings.account']._get_container_target_name(
            partner.company_id, partner)
        # On rejoue le scénario de collision : le conteneur créé par create() est supprimé, un
        # compte réel vient squatter son nom cible, puis on force une recréation.
        self._containers(partner).unlink()
        self._create_account(partner_id=partner.id, name=target)
        with self.assertRaises(ValidationError):
            partner._get_or_create_microfinance_savings_container()

    def test_container_creation_is_idempotent(self):
        partner = self._create_context_client('821000000004')
        first = self._containers(partner)
        self.assertEqual(len(first), 1)
        again = partner._get_or_create_microfinance_savings_container()
        self.assertEqual(again, first)
        self.assertEqual(len(self._containers(partner)), 1)

    def test_container_named_on_client_own_company_not_session_company(self):
        other = self.env['res.company'].create({'name': 'CEFOR Conteneur Autre Agence', 'agency_code': 'XC'})
        partner = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client Autre Agence Conteneur', 'microfinance_partner_type': 'client',
            'microfinance_id_type': 'cin', 'microfinance_id_number': '821000000008',
            'company_id': other.id,
        })
        self.assertNotEqual(self.env.company, other)
        container = self._containers(partner)
        self.assertEqual(len(container), 1)
        self.assertEqual(container.company_id, other)
        suffix = partner.microfinance_account_number.split('/', 1)[1]
        self.assertEqual(container.name, 'XC/I/%s' % suffix)

    def test_unique_partial_index_rejects_second_container_but_not_real_accounts(self):
        if not tools.index_exists(self.env.cr, 'microfinance_savings_account_container_uniq_idx'):
            self.skipTest("Index non posé sur cette base (doublons de conteneurs préexistants).")
        partner = self._create_context_client('821000000007')
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            # Nom explicite : contourne la garde de nom pour atteindre l'index lui-même.
            self.env['microfinance.savings.account'].create({
                'partner_id': partner.id, 'company_id': partner.company_id.id,
                'is_container': True, 'name': 'ZZ/I/999999',
            })
        # Comptes réels multiples pour un même client : toujours autorisés (bouton « Épargne »).
        self._create_account(partner_id=partner.id)
        self._create_account(partner_id=partner.id)
        self.assertGreaterEqual(len(self._containers(partner) | partner.microfinance_savings_account_ids), 3)
