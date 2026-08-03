# -*- coding: utf-8 -*-
from .common import MicrofinanceCommon


class TestAgencyNumbering(MicrofinanceCommon):
    """Numérotation AGENCE/SÉRIE pour microfinance.loan (crédit accordé) : séquence dédiée et
    indépendante (microfinance.loan.agency), incrémentée à chaque crédit créé, tous clients
    confondus de l'agence — exactement le "numéro crédit" attendu par le correctif de
    numérotation à trois niveaux (cf. docs_dev/programme_progressif/STATUS.md), déjà correct
    avant ce correctif, aucun changement de code n'a été nécessaire ici.

    Remarque : le commentaire précédent de cette classe affirmait que
    microfinance.loan.application n'était pas fonctionnel (jamais importé, sous-modèles
    manquants) — c'est obsolète, ce modèle est pleinement implémenté et testé ailleurs
    (tests/test_application_workflow.py, etc.), sa propre numérotation (name) a été corrigée
    séparément par le correctif de numérotation (related vers
    partner_id.microfinance_account_number, cf. tests/test_partner_account_number.py)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_isotry = cls.env['res.company'].create({'name': 'CEFOR Isotry (test)', 'agency_code': 'YI'})
        cls.company_ambanidia = cls.env['res.company'].create({'name': 'CEFOR Ambanidia (test)', 'agency_code': 'YB'})

    def test_loan_numbering_per_agency(self):
        loan1 = self._create_loan(company_id=self.company_isotry.id)
        loan2 = self._create_loan(company_id=self.company_isotry.id)
        self.assertEqual(loan1.name, 'YI/000001')
        self.assertEqual(loan2.name, 'YI/000002')

    def test_loan_numbering_independent_per_agency(self):
        self._create_loan(company_id=self.company_isotry.id)
        loan_other = self._create_loan(company_id=self.company_ambanidia.id)
        self.assertEqual(loan_other.name, 'YB/000001')
