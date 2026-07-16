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
        spouse = self.env['res.partner'].create({'name': 'Conjoint Test', 'phone': '0341234567'})
        partner = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client marié complet',
            'microfinance_client_type': 'individual',
            'microfinance_marital_status': 'married',
            'microfinance_spouse_id': spouse.id,
        })
        self.assertTrue(partner.id)
        self.assertEqual(partner.microfinance_spouse_phone, '0341234567')

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


class TestPartnerType(MicrofinanceCommon):

    def test_partner_type_empty_by_default(self):
        partner = self.env['res.partner'].create({'name': 'Sans type'})
        self.assertFalse(partner.microfinance_partner_type)

    def test_agency_company_partner_gets_agence_type_on_create(self):
        company = self.env['res.company'].create({
            'name': 'Agence Test Type Sync', 'agency_code': 'ZZ',
        })
        self.assertEqual(company.partner_id.microfinance_partner_type, 'agence')

    def test_agency_company_partner_resynced_on_partner_id_write(self):
        company = self.env['res.company'].create({
            'name': 'Agence Test Resync', 'agency_code': 'ZY',
        })
        company.partner_id.microfinance_partner_type = False
        # Réécrire partner_id (même valeur) doit resynchroniser, comme documenté dans
        # res_company.py::write() (cas rare mais couvert : partner_id changerait de contact).
        company.write({'partner_id': company.partner_id.id})
        self.assertEqual(company.partner_id.microfinance_partner_type, 'agence')

    def test_clients_menu_action_domain_filters_on_client_type(self):
        action = self.env.ref('microfinance_loan_management.action_microfinance_client')
        self.assertEqual(action.domain, "[('microfinance_partner_type', '=', 'client')]")

    def test_clients_menu_excludes_non_client_partner(self):
        agence_partner = self.env['res.company'].create({
            'name': 'Agence Test Menu Filter', 'agency_code': 'ZX',
        }).partner_id
        client_partner = self.env['res.partner'].create({
            'name': 'Client Test Menu Filter', 'microfinance_partner_type': 'client',
        })
        found = self.env['res.partner'].search([('microfinance_partner_type', '=', 'client')])
        self.assertIn(client_partner, found)
        self.assertNotIn(agence_partner, found)

    def test_partner_type_selection_has_only_three_values(self):
        # Périmètre resserré (Lot 1, décision 3) : bailleur/agence/client uniquement, jamais
        # 'fournisseur' — la valeur n'est de toute façon jamais saisie à la main (invisible en vue).
        selection = dict(self.env['res.partner']._fields['microfinance_partner_type'].selection)
        self.assertEqual(set(selection.keys()), {'bailleur', 'agence', 'client'})

    def test_partner_type_set_for_each_origin(self):
        # Les 3 valeurs possibles, chacune via son origine réelle (jamais une saisie manuelle) :
        # agence -> sync res.company, bailleur -> auto-création microfinance.bailleur.fonds,
        # client -> contexte par défaut du menu Clients.
        agence_partner = self.env['res.company'].create({
            'name': 'Agence Test Origine', 'agency_code': 'ZW',
        }).partner_id
        bailleur_partner = self.env['microfinance.bailleur.fonds'].create({
            'name': 'Bailleur Test Origine',
        }).partner_id
        client_partner = self.env['res.partner'].with_context(
            microfinance_context=True, default_microfinance_partner_type='client',
        ).create({'name': 'Client Test Origine', 'microfinance_client_type': 'individual'})

        self.assertEqual(agence_partner.microfinance_partner_type, 'agence')
        self.assertEqual(bailleur_partner.microfinance_partner_type, 'bailleur')
        self.assertEqual(client_partner.microfinance_partner_type, 'client')


class TestClientTypeIndividualOrCompanyOnly(MicrofinanceCommon):
    """microfinance_client_type perd l'option 'Groupe' (décision 4) : reste Particulier/Société
    uniquement. microfinance_sub_group_count et microfinance_member_ids restent sur le modèle
    (non-destructif) mais ne sont plus atteignables depuis ce radio."""

    def test_client_type_selection_has_only_two_values(self):
        selection = dict(self.env['res.partner']._fields['microfinance_client_type'].selection)
        self.assertEqual(set(selection.keys()), {'individual', 'company'})

    def test_group_value_no_longer_accepted(self):
        with self.assertRaises(ValueError):
            self.env['res.partner'].create({'name': 'Ancien groupe', 'microfinance_client_type': 'group'})

    def test_onchange_sets_is_company_true_for_company_type(self):
        partner = self.env['res.partner'].new({'microfinance_client_type': 'company'})
        partner._onchange_microfinance_client_type()
        self.assertTrue(partner.is_company)

    def test_onchange_sets_is_company_false_for_individual_type(self):
        partner = self.env['res.partner'].new({'microfinance_client_type': 'individual'})
        partner._onchange_microfinance_client_type()
        self.assertFalse(partner.is_company)


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
