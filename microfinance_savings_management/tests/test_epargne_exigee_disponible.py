# -*- coding: utf-8 -*-
from .common import SavingsCommon


class TestEpargneExigeeDisponible(SavingsCommon):
    """required_savings/available_savings sur microfinance.loan.application (chantier "Épargne
    exigée/disponible", docs_dev/epargne_exigee_disponible/AUDIT.md) : plus des champs en saisie
    libre, désormais related='loan_id.guarantee_savings_required'/'loan_id.guarantee_savings_
    balance' - réutilisation pure du mécanisme d'épargne garantie de crédit déjà existant et
    testé (cf. test_guarantee_savings.py), aucun nouveau calcul."""

    def _application_for(self, loan):
        loan.action_view_applications()
        return loan.application_ids

    def test_required_savings_matches_guarantee_savings_required(self):
        self.product.write({
            'guarantee_savings_percent': 20.0,
            'guarantee_savings_product_id': self.savings_product.id,
        })
        loan = self._create_loan(loan_amount=1000.0, term=3)
        application = self._application_for(loan)
        self.assertEqual(application.required_savings, loan.guarantee_savings_required)
        self.assertEqual(application.required_savings, 200.0)

    def test_available_savings_matches_guarantee_savings_balance(self):
        self.product.write({
            'guarantee_savings_percent': 20.0,
            'guarantee_savings_product_id': self.savings_product.id,
        })
        self._create_active_account(opening_amount=250.0)
        loan = self._create_loan(loan_amount=1000.0, term=3)
        application = self._application_for(loan)
        self.assertEqual(application.available_savings, loan.guarantee_savings_balance)
        self.assertEqual(application.available_savings, 250.0)

    def test_available_savings_zero_without_any_account(self):
        self.product.write({
            'guarantee_savings_percent': 20.0,
            'guarantee_savings_product_id': self.savings_product.id,
        })
        loan = self._create_loan(loan_amount=1000.0, term=3)
        application = self._application_for(loan)
        self.assertEqual(application.available_savings, 0.0)

    def test_zero_when_product_has_no_guarantee_configured(self):
        # Produit sans épargne garantie configurée (guarantee_savings_percent = 0 par défaut) :
        # les deux champs restent à 0, sans erreur.
        loan = self._create_loan(loan_amount=1000.0, term=3)
        application = self._application_for(loan)
        self.assertEqual(application.required_savings, 0.0)
        self.assertEqual(application.available_savings, 0.0)

    def test_fields_are_readonly_not_free_entry(self):
        # Non-régression du changement de comportement : ces champs ne sont plus modifiables
        # manuellement (cf. décision Micka, docs_dev/epargne_exigee_disponible/AUDIT.md).
        loan = self._create_loan(loan_amount=1000.0, term=3)
        application = self._application_for(loan)
        self.assertTrue(application._fields['required_savings'].readonly)
        self.assertTrue(application._fields['available_savings'].readonly)
