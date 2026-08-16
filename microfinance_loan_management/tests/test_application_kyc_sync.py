# -*- coding: utf-8 -*-
from .common import MicrofinanceCommon


class TestApplicationKycSync(MicrofinanceCommon):
    """Synchronisation du Bloc A (fiche d'enquête, microfinance.loan.application) avec
    res.partner (client + conjoint) : synchronisé tant que le dossier est en cours
    (draft/visite), gelé au-delà — sauf partner_current_address/partner_phone, toujours
    modifiables (cf. prompt correctif synchronisation du Bloc A)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.commune = cls.env['microfinance.geo.commune'].create({'name': 'Commune Test KYC'})
        cls.fokontany = cls.env['microfinance.geo.fokontany'].create({
            'name': 'Fokontany Test KYC', 'commune_id': cls.commune.id,
        })
        cls.spouse_fokontany = cls.env['microfinance.geo.fokontany'].create({
            'name': 'Fokontany Conjoint Test KYC', 'commune_id': cls.commune.id,
        })
        cls.profession = cls.env['microfinance.profession'].create({'name': 'Profession Conjoint Test'})
        cls.spouse = cls.env['res.partner'].create({
            'name': 'Conjoint Test KYC',
            'microfinance_id_number': '111222333444',
            'street': 'Rue du conjoint', 'street2': 'Lot II',
            'microfinance_fokontany_id': cls.spouse_fokontany.id,
            'microfinance_profession': cls.profession.id,
            'microfinance_employer': 'Employeur Conjoint',
        })
        cls.client_partner = cls.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client Test KYC',
            'microfinance_partner_type': 'client',
            'microfinance_id_number': '555666777888',
            'microfinance_id_issue_date': '2020-01-15',
            'microfinance_id_issue_place': 'Antananarivo',
            'microfinance_birthdate': '1990-05-20',
            'microfinance_birth_place': 'Antananarivo',
            'microfinance_marital_status': 'married',
            'microfinance_housing_status': 'tenant_paying',
            'microfinance_fokontany_id': cls.fokontany.id,
            'microfinance_next_of_kin_name': 'Contact Urgence',
            'microfinance_next_of_kin_phone': '0341112233',
            'microfinance_spouse_id': cls.spouse.id,
            'microfinance_spouse_phone': '0340009988',
            'street': 'Rue du client',
            'phone': '0340001122',
        })

    def _create_application(self, **kwargs):
        vals = {'partner_id': self.client_partner.id, 'loan_product_id': self.product.id}
        vals.update(kwargs)
        return self.env['microfinance.loan.application'].create(vals)

    def test_creation_prefills_bloc_a_from_partner_and_spouse(self):
        application = self._create_application()
        self.assertEqual(application.partner_surname, self.client_partner.name)
        self.assertEqual(application.partner_id_card_number, '555666777888')
        self.assertEqual(application.partner_id_card_issue_place, 'Antananarivo')
        self.assertEqual(application.partner_birth_place, 'Antananarivo')
        self.assertEqual(application.partner_marital_status, 'married')
        self.assertEqual(application.partner_housing_status, 'tenant_paying')
        self.assertEqual(application.partner_fokontany, self.fokontany.name)
        self.assertEqual(application.partner_reference_contact_name, 'Contact Urgence')
        self.assertEqual(application.partner_reference_contact_phone, '0341112233')
        # Conjoint : lu via microfinance_spouse_id, jamais dupliqué sur le client.
        self.assertEqual(application.spouse_name, self.spouse.name)
        self.assertEqual(application.spouse_id_card_number, '111222333444')
        self.assertIn('Rue du conjoint', application.spouse_address)
        self.assertEqual(application.spouse_fokontany, self.spouse_fokontany.name)
        self.assertEqual(application.spouse_profession, self.profession.name)
        self.assertEqual(application.spouse_employer, 'Employeur Conjoint')
        # Adresse/téléphone : eux aussi préremplis à la création, mais hors du mécanisme de gel.
        self.assertIn('Rue du client', application.partner_current_address)
        self.assertEqual(application.partner_phone, '0340001122')

    def test_partner_change_while_draft_resyncs_bloc_a(self):
        application = self._create_application()
        self.assertEqual(application.state, 'draft')
        new_profession = self.env['microfinance.profession'].create({'name': 'Nouvelle Profession Conjoint'})
        # Écriture directe sur le related (readonly=False) : se répercute aussi sur la fiche du
        # conjoint lui-même (une seule source de vérité).
        self.client_partner.write({'microfinance_spouse_profession': new_profession.id})
        application.invalidate_recordset(['spouse_profession'])
        self.assertEqual(application.spouse_profession, 'Nouvelle Profession Conjoint')

    def test_partner_change_after_analysis_does_not_resync(self):
        application = self._create_application()
        application.action_start_visite()
        application.action_start_contre_visite()
        self.assertEqual(application.state, 'contre_visite')
        frozen_profession = application.spouse_profession
        new_profession = self.env['microfinance.profession'].create({'name': 'Profession Après Gel'})
        self.client_partner.write({'microfinance_spouse_profession': new_profession.id})
        application.invalidate_recordset(['spouse_profession'])
        self.assertEqual(application.spouse_profession, frozen_profession)
        self.assertNotEqual(application.spouse_profession, 'Profession Après Gel')

    def test_manual_edit_preserved_in_progress_without_partner_change(self):
        application = self._create_application()
        application.action_start_visite()
        application.write({'partner_birth_place': 'Correction Enquêteur'})
        application.invalidate_recordset(['partner_birth_place'])
        self.assertEqual(application.partner_birth_place, 'Correction Enquêteur')

    def test_address_and_phone_remain_editable_after_freeze(self):
        application = self._create_application()
        application.action_start_visite()
        application.action_start_contre_visite()
        application.write({
            'partner_current_address': 'Nouvelle adresse saisie après gel',
            'partner_phone': '0349998877',
        })
        self.assertEqual(application.partner_current_address, 'Nouvelle adresse saisie après gel')
        self.assertEqual(application.partner_phone, '0349998877')

    def test_address_and_phone_not_resynced_even_while_in_progress(self):
        # Hors mécanisme de gel : ni gelés, ni resynchronisés automatiquement, même en cours.
        application = self._create_application()
        application.write({'partner_current_address': 'Adresse corrigée manuellement'})
        self.client_partner.write({'street': 'Rue totalement différente'})
        application.invalidate_recordset(['partner_current_address'])
        self.assertEqual(application.partner_current_address, 'Adresse corrigée manuellement')
