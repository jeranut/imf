# -*- coding: utf-8 -*-
from .common import MicrofinanceCommon


class TestAgencyNumbering(MicrofinanceCommon):
    """Numérotation AGENCE/SÉRIE pour microfinance.loan (crédit actif).

    microfinance.loan.application ('dossier d'instruction') a aussi reçu la même logique de
    numérotation dans son create(), mais ce modèle n'est actuellement pas fonctionnel dans ce
    codebase : jamais importé dans models/__init__.py (donc jamais enregistré dans le registre),
    et référence en plus 6 sous-modèles inexistants (microfinance.loan.application.dependent,
    .guarantor.line, .document.line, .income.line, .field.visit, .social.score). Remise en état
    hors périmètre de cette tâche (numérotation) — voir docs_dev/savings/ecarts_lpf.md pour le
    détail. Pas de test possible tant que ce modèle ne charge pas."""

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
