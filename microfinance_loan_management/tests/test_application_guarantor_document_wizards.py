# -*- coding: utf-8 -*-
from .common import MicrofinanceCommon


class TestApplicationDocumentDefaults(MicrofinanceCommon):
    """Matrice Documents administratifs : 2 lignes standard garanties présentes, sans "Photo
    d'identité" (déjà couverte par res.partner.image_1920) — à la création du dossier, tableau
    document_line_ids directement éditable en ligne sur la fiche (plus de wizard, cf. abandon
    de l'architecture wizard, STATUS.md 2026-07-18)."""

    def _create_application(self, **kwargs):
        vals = {'partner_id': self.partner.id, 'loan_product_id': self.product.id}
        vals.update(kwargs)
        return self.env['microfinance.loan.application'].create(vals)

    def test_default_document_lines_created_on_application_creation(self):
        application = self._create_application()
        names = application.document_line_ids.mapped('name')
        self.assertEqual(set(names), {'Copie CIN', 'Certificat de résidence – 3 mois'})
        self.assertNotIn("Photo d'identité", names)
        self.assertFalse(any(line.provided_by_partner or line.provided_by_guarantor
                              for line in application.document_line_ids))

    def test_default_lines_ensured_on_preexisting_application_without_lines(self):
        # Simule un dossier créé avant ce mécanisme (ou par un chemin qui l'a contourné) :
        # aucune ligne document au départ.
        application = self._create_application()
        application.document_line_ids.unlink()
        self.assertFalse(application.document_line_ids)
        application._ensure_default_document_lines()
        names = application.document_line_ids.mapped('name')
        self.assertEqual(set(names), {'Copie CIN', 'Certificat de résidence – 3 mois'})

    def test_calling_ensure_default_lines_twice_does_not_duplicate(self):
        application = self._create_application()
        application._ensure_default_document_lines()
        application._ensure_default_document_lines()
        names = application.document_line_ids.mapped('name')
        self.assertEqual(len(names), 2)

    def test_missing_default_line_added_without_duplicating_existing_custom_line(self):
        # Un dossier avec déjà UNE ligne personnalisée mais aucune des 2 standard : les 2
        # standard doivent être ajoutées sans dupliquer la ligne personnalisée déjà là.
        application = self._create_application()
        application.document_line_ids.unlink()
        application.document_line_ids = [(0, 0, {'name': 'Plan de localisation'})]
        application._ensure_default_document_lines()
        names = application.document_line_ids.mapped('name')
        self.assertEqual(
            set(names), {'Plan de localisation', 'Copie CIN', 'Certificat de résidence – 3 mois'},
        )
        self.assertEqual(len(names), 3)

    def test_document_checkboxes_and_observation_saved_directly(self):
        application = self._create_application()
        cin_line = application.document_line_ids.filtered(lambda line: line.name == 'Copie CIN')
        cin_line.write({
            'provided_by_partner': True,
            'provided_by_guarantor': False,
            'observation': 'Copie certifiée conforme',
        })
        self.assertTrue(cin_line.provided_by_partner)
        self.assertFalse(cin_line.provided_by_guarantor)
        self.assertEqual(cin_line.observation, 'Copie certifiée conforme')
        self.assertEqual(application.document_provided_count, 1)
        self.assertEqual(application.document_missing_count, 1)

    def test_additional_document_line_can_be_added(self):
        # L'enquêteur peut ajouter d'autres documents en plus des 2 par défaut, directement
        # dans le tableau éditable en ligne.
        application = self._create_application()
        application.write({
            'document_line_ids': [(0, 0, {'name': 'Plan de localisation', 'provided_by_guarantor': True})],
        })
        names = application.document_line_ids.mapped('name')
        self.assertEqual(len(names), 3)
        self.assertIn('Plan de localisation', names)


class TestApplicationGuarantorForm(MicrofinanceCommon):
    """Garant unique par dossier : champs directs sur microfinance.loan.application (préfixe
    guarantor_), plus de modèle de ligne séparé ni de wizard (cf. abandon de l'architecture
    wizard, STATUS.md 2026-07-18). guarantor_partner_id (Many2one res.partner) identifie le
    garant, jamais gelé. guarantor_address/guarantor_profession se synchronisent en continu
    tant que le dossier est en cours (draft/field_survey), puis se figent (même patron que le
    Bloc A) ; guarantor_phone reste toujours modifiable (même exception que partner_phone)."""

    def _create_application(self, **kwargs):
        vals = {'partner_id': self.partner.id, 'loan_product_id': self.product.id}
        vals.update(kwargs)
        return self.env['microfinance.loan.application'].create(vals)

    def test_no_guarantor_by_default(self):
        application = self._create_application()
        self.assertFalse(application.guarantor_partner_id)
        self.assertEqual(application.guarantor_count, 0)
        self.assertFalse(application.primary_guarantor_name)

    def test_guarantor_fields_saved_directly_on_application(self):
        application = self._create_application()
        guarantor_contact = self.env['res.partner'].create({'name': 'RAKOTO Jean'})
        application.write({
            'guarantor_partner_id': guarantor_contact.id,
            'guarantor_id_card_number': '101022334455',
            'guarantor_id_card_issue_date': '2019-04-10',
            'guarantor_id_card_issue_place': 'Antananarivo',
            'guarantor_id_card_duplicate_date': '2022-01-05',
            'guarantor_id_card_duplicate_place': 'Antananarivo',
            'guarantor_fokontany': 'Ankorondrano',
            'guarantor_employer': 'Indépendant',
            'guarantor_relationship_with_borrower': 'Voisin',
            'guarantor_surveyor_comment': 'Garant fiable, connu depuis 5 ans.',
        })
        self.assertEqual(application.guarantor_partner_id, guarantor_contact)
        self.assertEqual(application.guarantor_id_card_issue_place, 'Antananarivo')
        self.assertEqual(application.guarantor_id_card_duplicate_place, 'Antananarivo')
        self.assertEqual(application.guarantor_fokontany, 'Ankorondrano')
        self.assertEqual(application.guarantor_employer, 'Indépendant')
        self.assertEqual(application.guarantor_relationship_with_borrower, 'Voisin')
        self.assertEqual(application.guarantor_surveyor_comment, 'Garant fiable, connu depuis 5 ans.')
        self.assertEqual(application.guarantor_count, 1)
        self.assertEqual(application.primary_guarantor_name, 'RAKOTO Jean')

    def test_guarantor_address_and_phone_synced_from_selected_partner(self):
        application = self._create_application()
        guarantor_contact = self.env['res.partner'].create({
            'name': 'RAKOTO Jean', 'street': 'Lot II M 12', 'street2': 'Antananarivo',
            'phone': '0341234567',
        })
        application.guarantor_partner_id = guarantor_contact
        self.assertEqual(application.guarantor_address, 'Lot II M 12, Antananarivo')
        self.assertEqual(application.guarantor_phone, '0341234567')

    def test_guarantor_phone_stays_editable_and_resyncs_even_after_freeze(self):
        # guarantor_phone suit exactement la même exception que partner_phone sur le Bloc A :
        # jamais gelé, toujours resynchronisé depuis le contact garant.
        application = self._create_application()
        guarantor_contact = self.env['res.partner'].create({
            'name': 'RAKOTO Jean', 'phone': '0341234567',
        })
        application.guarantor_partner_id = guarantor_contact
        application.action_start_visite()
        application.action_start_contre_visite()
        guarantor_contact.phone = '0349999999'
        application.invalidate_recordset(['guarantor_phone'])
        self.assertEqual(application.guarantor_phone, '0349999999')

    def test_guarantor_profession_synced_while_application_in_progress(self):
        profession = self.env['microfinance.profession'].create({'name': 'Profession Test Garant Sync'})
        guarantor_contact = self.env['res.partner'].create({
            'name': 'Contact Garant Profession', 'microfinance_profession': profession.id,
        })
        application = self._create_application()
        application.guarantor_partner_id = guarantor_contact
        self.assertEqual(application.guarantor_profession, 'Profession Test Garant Sync')

    def test_guarantor_profession_frozen_after_application_leaves_in_progress_states(self):
        profession = self.env['microfinance.profession'].create({'name': 'Profession Test Garant Gel'})
        guarantor_contact = self.env['res.partner'].create({
            'name': 'Contact Garant Profession Gel', 'microfinance_profession': profession.id,
        })
        application = self._create_application()
        application.guarantor_partner_id = guarantor_contact
        application.action_start_visite()
        application.action_start_contre_visite()
        frozen_value = application.guarantor_profession
        new_profession = self.env['microfinance.profession'].create({'name': 'Nouvelle Profession Garant'})
        guarantor_contact.microfinance_profession = new_profession.id
        application.invalidate_recordset(['guarantor_profession'])
        self.assertEqual(application.guarantor_profession, frozen_value)
        self.assertNotEqual(application.guarantor_profession, 'Nouvelle Profession Garant')
