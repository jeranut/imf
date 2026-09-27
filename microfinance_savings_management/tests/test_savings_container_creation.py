# -*- coding: utf-8 -*-
from .common import SavingsCommon


class TestSavingsContainerCreation(SavingsCommon):
    """Le conteneur épargne est créé UNIQUEMENT à l'enregistrement du client (cf.
    test_savings_principal_account_on_create.py) - correctif du 2026-09-24 (docs_dev/epargne_auto/
    AUDIT_doublons_creation_client.md §13), qui abroge le déclenchement au 1er crédit (Option A,
    21/09). Ce fichier vérifie que le crédit n'en crée plus jamais."""

    def _containers(self, partner):
        return self.env['microfinance.savings.account'].search([
            ('partner_id', '=', partner.id), ('is_container', '=', True),
        ])

    def test_first_loan_does_not_create_a_savings_container(self):
        # self.partner (MicrofinanceCommon) est créé SANS microfinance_context : aucun conteneur
        # à sa création, et le 1er crédit ne doit plus en créer un non plus.
        self.assertFalse(self._containers(self.partner))
        self._create_loan()
        self.assertFalse(self._containers(self.partner))

    def test_loan_reuses_the_container_created_at_registration(self):
        partner = self._create_context_client('820000000001')
        container_before = self._containers(partner)
        self.assertEqual(len(container_before), 1)
        agency, suffix = partner.microfinance_account_number.split('/', 1)
        self.assertEqual(container_before.name, '%s/I/%s' % (agency, suffix))

        self._create_loan(partner_id=partner.id)
        self.assertEqual(self._containers(partner), container_before)

    def test_second_loan_does_not_create_second_container(self):
        partner = self._create_context_client('820000000002')
        self._create_loan(partner_id=partner.id)
        self._create_loan(partner_id=partner.id)
        self.assertEqual(len(self._containers(partner)), 1)

    def test_borrower_without_client_type_never_gets_a_container(self):
        # Un partenaire non 'client' (ex. bailleur emprunteur) n'a jamais eu de conteneur créé à
        # l'enregistrement (réservé aux clients) ; comme le crédit n'en crée plus non plus
        # (contrairement à l'ancien mécanisme Option A), il n'en a jamais - changement de
        # comportement assumé, cf. rapport d'audit §13.
        partner = self.env['res.partner'].create({'name': 'Bailleur Emprunteur Conteneur Test', 'microfinance_partner_type': 'bailleur'})
        self._create_loan(partner_id=partner.id)
        self.assertFalse(self._containers(partner))
