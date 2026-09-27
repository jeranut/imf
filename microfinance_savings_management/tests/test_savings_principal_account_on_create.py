# -*- coding: utf-8 -*-
from .common import SavingsCommon


class TestSavingsContainerAccountOnPartnerCreate(SavingsCommon):
    """Ouverture du conteneur épargne (AGENCE/I/N, seul compte épargne créé automatiquement) dès
    la création du contact client - res_partner.py::create() (microfinance_savings_management).
    Correctif du 2026-09-24 (docs_dev/epargne_auto/AUDIT_doublons_creation_client.md §13) : abroge
    l'« Option A » du 21/09 (compte principal réel + conteneur créé séparément, au 1er crédit)."""

    def test_client_creation_opens_container_without_credit_product(self):
        partner = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client Test Épargne Direct',
            'microfinance_partner_type': 'client',
            'microfinance_id_type': 'cin', 'microfinance_id_number': '810000000001',
            'microfinance_client_type': 'individual',
        })
        containers = partner.microfinance_savings_account_ids.filtered(lambda a: a.is_container)
        self.assertEqual(len(containers), 1)
        self.assertFalse(partner.microfinance_current_loan_application_id)
        agency, suffix = partner.microfinance_account_number.split('/', 1)
        self.assertEqual(containers.name, '%s/I/%s' % (agency, suffix))
        self.assertFalse(containers.product_id)

    def test_client_creation_opens_only_the_container_no_other_account(self):
        # Plus de « compte principal » séparé : un seul enregistrement épargne créé, le conteneur.
        partner = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client Sans Produit Défaut', 'microfinance_partner_type': 'client',
            'microfinance_id_type': 'cin', 'microfinance_id_number': '810000000002',
        })
        self.assertTrue(partner.id)
        self.assertEqual(len(partner.microfinance_savings_account_ids), 1)
        self.assertTrue(partner.microfinance_savings_account_ids.is_container)

    def test_client_creation_outside_microfinance_context_does_not_open_container(self):
        # Contact partagé avec d'autres usages de l'instance (EAT, immobilier) hors contexte
        # microfinance : même règle que les autres automatismes de res_partner.py (cf.
        # _check_microfinance_company_required, _check_spouse_required_if_married).
        partner = self.env['res.partner'].create({
            'name': 'Client Hors Contexte', 'microfinance_partner_type': 'client',
            'microfinance_id_type': 'cin', 'microfinance_id_number': '810000000004',
        })
        self.assertFalse(partner.microfinance_savings_account_ids)

    def test_non_client_partner_creation_does_not_open_container(self):
        partner = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Contact Non Client',
        })
        self.assertFalse(partner.microfinance_savings_account_ids)

    def test_container_attached_to_client_own_company(self):
        other_company = self.env['res.company'].create({'name': 'CEFOR Autre Agence Test', 'agency_code': 'XA'})
        partner = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client Autre Agence Test', 'microfinance_partner_type': 'client',
            'microfinance_id_type': 'cin', 'microfinance_id_number': '810000000005',
            'company_id': other_company.id,
        })
        containers = partner.microfinance_savings_account_ids.filtered(lambda a: a.is_container)
        self.assertEqual(len(containers), 1)
        self.assertEqual(containers.company_id, other_company)
        self.assertTrue(containers.name.startswith('XA/I/'))

    def test_selecting_credit_product_after_creation_does_not_duplicate_container(self):
        partner = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client Test Double Déclencheur', 'microfinance_partner_type': 'client',
            'microfinance_id_type': 'cin', 'microfinance_id_number': '810000000006',
        })
        containers_after_create = partner.microfinance_savings_account_ids.filtered(lambda a: a.is_container)
        self.assertEqual(len(containers_after_create), 1)
        partner.with_context(microfinance_context=True).write({
            'microfinance_selected_product_id': self.product.id,
        })
        containers_after_loan_selection = partner.microfinance_savings_account_ids.filtered(lambda a: a.is_container)
        self.assertEqual(containers_after_loan_selection, containers_after_create)
        self.assertTrue(partner.microfinance_current_loan_application_id)
