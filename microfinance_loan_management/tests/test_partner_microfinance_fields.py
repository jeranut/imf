# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError

from .common import MicrofinanceCommon


class TestPartnerSpouseRequired(MicrofinanceCommon):

    def test_married_without_spouse_info_blocked_in_microfinance_context(self):
        with self.assertRaises(ValidationError):
            self.env['res.partner'].with_context(microfinance_context=True).create({
                'name': 'Client marié incomplet',
                'microfinance_client_type': 'individual',
                'microfinance_marital_status': 'married',
            })

    def test_married_with_spouse_info_allowed(self):
        partner = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client marié complet',
            'microfinance_client_type': 'individual',
            'microfinance_marital_status': 'married',
            'microfinance_spouse_name': 'Conjoint Test',
            'microfinance_spouse_phone': '0341234567',
        })
        self.assertTrue(partner.id)

    def test_married_incomplete_not_blocked_outside_microfinance_context(self):
        # Contact partagé avec d'autres usages de l'instance (EAT, immobilier) hors contexte
        # microfinance : aucune contrainte spécifique ne doit s'y appliquer.
        partner = self.env['res.partner'].create({
            'name': 'Client hors contexte',
            'microfinance_marital_status': 'married',
        })
        self.assertTrue(partner.id)

    def test_single_client_no_spouse_required(self):
        partner = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client célibataire',
            'microfinance_client_type': 'individual',
            'microfinance_marital_status': 'single',
        })
        self.assertTrue(partner.id)


class TestPartnerProfession(MicrofinanceCommon):

    def test_profession_is_many2one_reference(self):
        profession = self.env.ref('microfinance_loan_management.microfinance_profession_agriculteur')
        partner = self.env['res.partner'].create({
            'name': 'Client agriculteur', 'microfinance_profession': profession.id,
        })
        self.assertEqual(partner.microfinance_profession.name, 'Agriculteur')

    def test_manager_can_create_new_profession(self):
        profession = self.env['microfinance.profession'].create({'name': 'Boulanger'})
        self.assertEqual(profession.name, 'Boulanger')


class TestPartnerCinDisplay(MicrofinanceCommon):

    def test_cin_display_groups_by_three_digits(self):
        partner = self.env['res.partner'].create({
            'name': 'Client CIN', 'microfinance_id_type': 'cin', 'microfinance_id_number': '101023456789',
        })
        self.assertEqual(partner.microfinance_id_number_display, '101 023 456 789')

    def test_cin_inverse_strips_non_digits_back_to_raw(self):
        partner = self.env['res.partner'].create({
            'name': 'Client CIN 2', 'microfinance_id_type': 'cin', 'microfinance_id_number': '101023456789',
        })
        partner.microfinance_id_number_display = '101 023 456 780'
        self.assertEqual(partner.microfinance_id_number, '101023456780')

    def test_cin_validation_still_enforced_via_raw_field(self):
        with self.assertRaises(ValidationError):
            self.env['res.partner'].create({
                'name': 'Client CIN invalide', 'microfinance_id_type': 'cin', 'microfinance_id_number': '12345',
            })

    def test_non_cin_id_number_display_passthrough(self):
        partner = self.env['res.partner'].create({
            'name': 'Client passeport', 'microfinance_id_type': 'passport', 'microfinance_id_number': 'AB1234567',
        })
        self.assertEqual(partner.microfinance_id_number_display, 'AB1234567')
