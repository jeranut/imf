# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError

from .common import MicrofinanceCommon


class TestPartnerAccountNumber(MicrofinanceCommon):
    """Numéro de compte client permanent (microfinance_account_number) : attribué une seule
    fois à la création d'un contact reconnu comme client microfinance
    (microfinance_partner_type == 'client'), jamais modifié ensuite, format AGENCE/NNNNNN — cf.
    correctif de numérotation à trois niveaux (compte client / épargne dérivée / crédit)."""

    def test_new_client_gets_account_number_on_creation(self):
        company = self.env['res.company'].create({
            'name': 'Agence Test Numéro Client', 'agency_code': 'ZN',
        })
        partner = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client Test Numéro',
            'microfinance_partner_type': 'client',
            'company_id': company.id,
        })
        self.assertEqual(partner.microfinance_account_number, 'ZN/000001')

    def test_account_number_independent_per_agency(self):
        company_a = self.env['res.company'].create({'name': 'Agence Test Num A', 'agency_code': 'ZA'})
        company_b = self.env['res.company'].create({'name': 'Agence Test Num B', 'agency_code': 'ZB'})
        partner_a = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client Test Num A', 'microfinance_partner_type': 'client', 'company_id': company_a.id,
        })
        partner_b = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client Test Num B', 'microfinance_partner_type': 'client', 'company_id': company_b.id,
        })
        self.assertEqual(partner_a.microfinance_account_number, 'ZA/000001')
        self.assertEqual(partner_b.microfinance_account_number, 'ZB/000001')

    def test_second_client_same_agency_gets_next_number(self):
        company = self.env['res.company'].create({'name': 'Agence Test Num Suite', 'agency_code': 'ZS'})
        partner1 = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client Test Num Suite 1', 'microfinance_partner_type': 'client', 'company_id': company.id,
        })
        partner2 = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client Test Num Suite 2', 'microfinance_partner_type': 'client', 'company_id': company.id,
        })
        self.assertEqual(partner1.microfinance_account_number, 'ZS/000001')
        self.assertEqual(partner2.microfinance_account_number, 'ZS/000002')

    def test_non_client_partner_gets_no_account_number(self):
        # Contact partagé (EAT/immobilier) : jamais 'client' au sens microfinance, jamais de
        # numéro de compte attribué.
        partner = self.env['res.partner'].create({'name': 'Contact hors microfinance'})
        self.assertFalse(partner.microfinance_account_number)

    def test_account_number_never_changes_after_multiple_writes(self):
        partner = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client Test Permanence', 'microfinance_partner_type': 'client',
        })
        original_number = partner.microfinance_account_number
        self.assertTrue(original_number)
        partner.write({'phone': '0341234567'})
        partner.write({'microfinance_registration_number': 'ABC123'})
        self.assertEqual(partner.microfinance_account_number, original_number)

    def test_manual_modification_blocked(self):
        partner = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client Test Verrou Numéro', 'microfinance_partner_type': 'client',
        })
        with self.assertRaises(ValidationError):
            partner.write({'microfinance_account_number': 'XX/999999'})

    def test_manual_value_at_creation_is_ignored(self):
        partner = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client Test Création Forcée',
            'microfinance_partner_type': 'client',
            'microfinance_account_number': 'XX/999999',
        })
        self.assertNotEqual(partner.microfinance_account_number, 'XX/999999')
        self.assertTrue(partner.microfinance_account_number)
