# -*- coding: utf-8 -*-
from .common import MicrofinanceCommon


class TestLoanProductValidationAuthority(MicrofinanceCommon):
    """Champ de configuration pur (cf. microfinance_loan_product.py) : aucun effet sur le
    workflow actuel avis_ca/avis_cdag de microfinance.loan, seule la valeur par défaut est
    vérifiée ici."""

    def _product_vals(self, **kwargs):
        vals = {
            'name': 'Produit auto', 'min_amount': 100.0, 'max_amount': 100000.0,
            'min_term': 1, 'max_term': 36, 'interest_rate': 12.0, 'interest_method': 'flat',
            'repayment_frequency_mode': 'fixed',
            'repayment_frequency_id': self.env.ref('microfinance_loan_management.repayment_frequency_monthly').id,
            'disbursement_journal_id': self.disbursement_journal.id,
            'payment_journal_id': self.payment_journal.id,
            'account_principal_individuel_id': self.loan_account.id,
            'account_principal_groupe_id': self.loan_account_groupe.id,
            'account_interets_recus_individuel_id': self.interest_account.id,
            'account_interets_recus_groupe_id': self.interest_account_groupe.id,
            'account_penalites_id': self.penalty_account.id,
        }
        vals.update(kwargs)
        return vals

    def test_validation_authority_defaults_to_cdag(self):
        product = self.env['microfinance.loan.product'].create(self._product_vals())
        self.assertEqual(product.validation_authority, 'cdag')

    def test_validation_authority_explicit_value_kept(self):
        product = self.env['microfinance.loan.product'].create(self._product_vals(validation_authority='ca'))
        self.assertEqual(product.validation_authority, 'ca')
