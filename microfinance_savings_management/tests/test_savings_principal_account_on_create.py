# -*- coding: utf-8 -*-
import json

from .common import SavingsCommon


class TestSavingsPrincipalAccountOnPartnerCreate(SavingsCommon):
    """Ouverture du compte épargne principal dès la création du contact client (nouveau
    déclencheur, cf. correctif numérotation Sous-lot 2), indépendamment de tout produit de
    crédit visé — res_partner.py::create() (microfinance_savings_management)."""

    def test_client_creation_opens_principal_account_without_credit_product(self):
        self.env.company.microfinance_savings_default_product_id = self.savings_product
        partner = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client Test Épargne Direct',
            'microfinance_partner_type': 'client',
            'microfinance_client_type': 'individual',
        })
        accounts = partner.microfinance_savings_account_ids.filtered(lambda a: a.product_id == self.savings_product)
        self.assertEqual(len(accounts), 1)
        self.assertFalse(partner.microfinance_current_loan_application_id)
        agency, suffix = partner.microfinance_account_number.split('/', 1)
        self.assertEqual(accounts.name, '%s/I/%s' % (agency, suffix))

    def test_no_default_product_configured_skips_silently_at_creation(self):
        self.assertFalse(self.env.company.microfinance_savings_default_product_id)
        bus_before = self.env['bus.bus'].search([])
        partner = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client Sans Produit Défaut', 'microfinance_partner_type': 'client',
        })
        self.assertTrue(partner.id)
        self.assertFalse(partner.microfinance_savings_account_ids)
        # "Silencieux" veut dire pas d'erreur bloquante, pas invisible : une notification bus
        # doit alerter l'agent (demande explicite de Micka, 2026-08-15).
        self.env.cr.flush()
        new_bus_messages = (self.env['bus.bus'].search([]) - bus_before).mapped('message')
        self.assertTrue(any(
            json.loads(msg)['payload']['title'] == 'Compte épargne non ouvert'
            and partner.name in json.loads(msg)['payload']['message']
            and self.env.company.name in json.loads(msg)['payload']['message']
            for msg in new_bus_messages
        ), 'Notification "Compte épargne non ouvert" absente du bus.')

    def test_default_product_configured_does_not_notify(self):
        self.env.company.microfinance_savings_default_product_id = self.savings_product
        bus_before = self.env['bus.bus'].search([])
        self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client Avec Produit Défaut', 'microfinance_partner_type': 'client',
        })
        self.env.cr.flush()
        new_bus_messages = (self.env['bus.bus'].search([]) - bus_before).mapped('message')
        self.assertFalse(any(
            json.loads(msg)['payload']['title'] == 'Compte épargne non ouvert'
            for msg in new_bus_messages
        ))

    def test_client_creation_outside_microfinance_context_does_not_open_account(self):
        # Contact partagé avec d'autres usages de l'instance (EAT, immobilier) hors contexte
        # microfinance : même règle que les autres automatismes de res_partner.py (cf.
        # _check_microfinance_company_required, _check_spouse_required_if_married).
        self.env.company.microfinance_savings_default_product_id = self.savings_product
        partner = self.env['res.partner'].create({
            'name': 'Client Hors Contexte', 'microfinance_partner_type': 'client',
        })
        self.assertFalse(partner.microfinance_savings_account_ids)

    def test_non_client_partner_creation_does_not_open_account(self):
        self.env.company.microfinance_savings_default_product_id = self.savings_product
        partner = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Contact Non Client',
        })
        self.assertFalse(partner.microfinance_savings_account_ids)

    def test_account_attached_to_client_own_company(self):
        other_company = self.env['res.company'].create({'name': 'CEFOR Autre Agence Test', 'agency_code': 'XA'})
        other_account = self.env['account.account'].create({
            'name': 'Passif épargne autre agence test', 'code': 'XASAV',
            'account_type': 'liability_current', 'company_id': other_company.id,
        })
        other_product = self.env['microfinance.savings.product'].create({
            'name': 'Épargne Autre Agence Test', 'code': 'SAVXA', 'product_type': 'voluntary',
            'company_id': other_company.id,
            'account_epargne_individuel_id': other_account.id,
            'account_epargne_groupe_id': other_account.id,
            'account_epargne_entreprise_id': other_account.id,
        })
        other_company.microfinance_savings_default_product_id = other_product
        partner = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client Autre Agence Test', 'microfinance_partner_type': 'client',
            'company_id': other_company.id,
        })
        accounts = partner.microfinance_savings_account_ids
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts.company_id, other_company)
        self.assertTrue(accounts.name.startswith('XA/'))

    def test_selecting_credit_product_after_creation_does_not_duplicate_account(self):
        # Le déclencheur historique (ouverture au 1er dossier de crédit) a été retiré (cf.
        # test_savings_account_number_derivation.py::TestLoanApplicationNoLongerOpensSavingsAccount) :
        # sélectionner un produit de crédit après coup ne doit ni dupliquer le compte déjà
        # ouvert à la création, ni en ouvrir un second.
        self.env.company.microfinance_savings_default_product_id = self.savings_product
        partner = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client Test Double Déclencheur', 'microfinance_partner_type': 'client',
        })
        accounts_after_create = partner.microfinance_savings_account_ids.filtered(
            lambda a: a.product_id == self.savings_product
        )
        self.assertEqual(len(accounts_after_create), 1)
        partner.with_context(microfinance_context=True).write({
            'microfinance_selected_product_id': self.product.id,
        })
        accounts_after_loan_selection = partner.microfinance_savings_account_ids.filtered(
            lambda a: a.product_id == self.savings_product
        )
        self.assertEqual(len(accounts_after_loan_selection), 1)
        self.assertTrue(partner.microfinance_current_loan_application_id)
