# -*- coding: utf-8 -*-
from .common import SavingsCommon


class TestAvisEpargneExigee(SavingsCommon):
    """Épargne exigée (CA/CDAG) calculée automatiquement depuis product_id.guarantee_savings_
    percent, au lieu d'une saisie libre toujours à 0 (cf. docs_dev/epargne_exigee_ca_cdag/
    AUDIT.md) : avis_ca_epargne_exigee/avis_cdag_epargne_exigee (microfinance.loan) sont
    redéclarés en compute+store ici, microfinance.loan.application les reflète via ses champs
    related existants (ca_required_savings/cdag_required_savings)."""

    def setUp(self):
        super().setUp()
        self.env['microfinance.fond.credit'].sudo().search([]).write({'active': False})
        self.product.max_amount = 1000000.0

    def _loan_in_avis_ca(self, loan_amount, term=6):
        loan = self._create_loan(loan_amount=loan_amount, term=term)
        loan.action_generate_schedule()
        loan.action_start_enquete()
        loan.action_ca_review()
        return loan

    def test_computed_from_percent_on_ca_and_cdag(self):
        self.product.write({
            'guarantee_savings_percent': 5.0,
            'guarantee_savings_product_id': self.savings_product.id,
        })
        self._create_active_account(opening_amount=25000.0)  # couvre 500000 x 5% = 25000
        loan = self._loan_in_avis_ca(500000.0)
        self.assertAlmostEqual(loan.avis_ca_epargne_exigee, 25000.0, places=2)  # 500000 x 5%
        loan.action_cdag_review()
        self.assertAlmostEqual(loan.avis_cdag_epargne_exigee, 25000.0, places=2)

    def test_zero_when_product_has_no_requirement(self):
        # guarantee_savings_percent = 0 par défaut : aucune configuration sur ce produit.
        loan = self._loan_in_avis_ca(500000.0)
        self.assertEqual(loan.avis_ca_epargne_exigee, 0.0)

    def test_recomputes_on_avis_amount_change_not_freely_editable(self):
        """Confirme que ce n'est plus une saisie libre : la valeur suit avis_ca_amount, une
        écriture directe sur avis_ca_amount recalcule automatiquement le champ."""
        self.product.write({
            'guarantee_savings_percent': 10.0,
            'guarantee_savings_product_id': self.savings_product.id,
        })
        self._create_active_account(opening_amount=20000.0)  # couvre 200000 x 10% = 20000
        loan = self._loan_in_avis_ca(100000.0)
        self.assertAlmostEqual(loan.avis_ca_epargne_exigee, 10000.0, places=2)
        loan.write({'avis_ca_amount': 200000.0})
        self.assertAlmostEqual(loan.avis_ca_epargne_exigee, 20000.0, places=2)

    def test_application_related_fields_mirror_loan_value(self):
        self.product.write({
            'guarantee_savings_percent': 5.0,
            'guarantee_savings_product_id': self.savings_product.id,
        })
        self._create_active_account(opening_amount=25000.0)  # couvre 500000 x 5% = 25000
        loan = self._loan_in_avis_ca(500000.0)
        application = self.env['microfinance.loan.application'].create({
            'partner_id': self.partner.id,
            'loan_product_id': self.product.id,
            'loan_id': loan.id,
        })
        self.assertAlmostEqual(application.ca_required_savings, 25000.0, places=2)
        self.assertAlmostEqual(application.guarantee_savings_required, 25000.0, places=2)
