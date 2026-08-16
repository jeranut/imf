# -*- coding: utf-8 -*-
from datetime import date

from .common import MicrofinanceCommon


class TestApplicationPartnerWizardCeforFields(MicrofinanceCommon):
    """Mise en conformité avec la fiche papier CEFOR : champs section Partenaire/Conjoint
    directement éditables sur la fiche (plus de wizard, cf. abandon de l'architecture wizard),
    refonte du tableau Enfants et personnes à charge (âge calculé, compteurs)."""

    def _create_application(self, **kwargs):
        vals = {'partner_id': self.partner.id, 'loan_product_id': self.product.id}
        vals.update(kwargs)
        return self.env['microfinance.loan.application'].create(vals)

    def test_new_fields_saved_directly_on_application(self):
        application = self._create_application()
        application.write({
            'partner_nickname': 'Tiko',
            'partner_id_card_duplicate_date': '2021-03-01',
            'partner_id_card_duplicate_place': 'Antananarivo',
            'partner_address_changed': True,
            'partner_agency_distance_km': 8,
            'partner_phone_type': 'neighbor',
            'spouse_id_card_issue_date': '2015-06-15',
            'spouse_id_card_issue_place': 'Antananarivo',
        })
        self.assertEqual(application.partner_nickname, 'Tiko')
        self.assertEqual(str(application.partner_id_card_duplicate_date), '2021-03-01')
        self.assertEqual(application.partner_id_card_duplicate_place, 'Antananarivo')
        self.assertTrue(application.partner_address_changed)
        self.assertEqual(application.partner_agency_distance_km, 8)
        self.assertEqual(application.partner_phone_type, 'neighbor')
        self.assertEqual(str(application.spouse_id_card_issue_date), '2015-06-15')
        self.assertEqual(application.spouse_id_card_issue_place, 'Antananarivo')

    def test_kyc_fields_readonly_in_view_once_out_of_survey(self):
        # L'édition directe des champs gelés du Bloc A n'est plus bloquée par le wizard mais
        # par la vue (readonly conditionné par state) : l'ORM lui-même reste toujours
        # inscriptible (readonly=False sur les champs compute), seule la vue empêche la saisie
        # une fois le dossier hors instruction. Ce test vérifie juste que l'écriture ORM directe
        # continue de fonctionner (pas de régression de blocage côté modèle).
        application = self._create_application()
        application.action_start_visite()
        application.action_start_contre_visite()
        application.write({'partner_nickname': 'Écrit après gel'})
        self.assertEqual(application.partner_nickname, 'Écrit après gel')

    def test_dependent_line_age_recomputed_on_birth_date_change(self):
        application = self._create_application()
        today = date.today()
        birth_date = today.replace(year=today.year - 10)
        dependent = self.env['microfinance.loan.application.dependent'].create({
            'application_id': application.id, 'name': 'Enfant Test', 'birth_date': birth_date,
        })
        self.assertEqual(dependent.age, 10)
        dependent.write({'birth_date': birth_date.replace(year=birth_date.year - 5)})
        self.assertEqual(dependent.age, 15)

    def test_children_counters_consistent_with_table(self):
        application = self._create_application()
        self.env['microfinance.loan.application.dependent'].create([
            {
                'application_id': application.id, 'name': 'Enfant Scolarisé',
                'relationship': 'child', 'school_name': 'École Test',
            },
            {
                'application_id': application.id, 'name': 'Enfant Non Scolarisé',
                'relationship': 'child',
            },
            {
                'application_id': application.id, 'name': 'Autre Personne à Charge',
                'relationship': 'other_dependent',
            },
        ])
        application.invalidate_recordset(['children_count', 'children_schooled_count'])
        self.assertEqual(application.children_count, 2)
        self.assertEqual(application.children_schooled_count, 1)
        # dependent_count (déjà existant, total incl. non-enfants) reste distinct et inchangé.
        self.assertEqual(application.dependent_count, 3)

    def test_dependent_lines_saved_directly_on_application(self):
        application = self._create_application()
        application.write({
            'dependent_ids': [(0, 0, {
                'name': 'Enfant Direct', 'relationship': 'child',
                'birth_date': date.today().replace(year=date.today().year - 8),
                'school_class': 'CE2', 'school_name': 'École Directe', 'remark': 'RAS',
            })],
        })
        self.assertEqual(len(application.dependent_ids), 1)
        line = application.dependent_ids
        self.assertEqual(line.school_class, 'CE2')
        self.assertEqual(line.school_name, 'École Directe')
        self.assertEqual(line.remark, 'RAS')
        self.assertEqual(line.age, 8)
        self.assertEqual(application.children_count, 1)
        self.assertEqual(application.children_schooled_count, 1)
