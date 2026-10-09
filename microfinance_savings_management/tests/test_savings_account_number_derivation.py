# -*- coding: utf-8 -*-
from .common import SavingsCommon


class TestLoanApplicationNoLongerOpensSavingsAccount(SavingsCommon):
    """Le déclencheur historique (ouverture du compte épargne principal au 1er dossier
    d'instruction de crédit, via res.partner._get_or_create_loan_application) a été retiré :
    décision validée par Micka lors du correctif numérotation Sous-lot 2. Seule la création du
    contact client ouvre désormais ce compte (cf. test_savings_holder_account.py).
    Cette classe fige explicitement la suppression plutôt que de supprimer silencieusement les
    anciens tests : self.partner (MicrofinanceCommon) est créé sans microfinance_context, donc
    n'a jamais eu de compte épargne ouvert à sa création — sélectionner un produit de crédit
    après coup ne doit plus en ouvrir un non plus."""

    def _select_product_for_partner(self, partner, product=None):
        partner.with_context(microfinance_context=True, allow_microfinance_partner_create=True).write({
            'microfinance_selected_product_id': (product or self.product).id,
        })

    def test_dossier_creation_no_longer_opens_principal_savings_account(self):
        self.env.company.microfinance_savings_default_product_id = self.savings_product
        self.assertFalse(self.partner.microfinance_savings_account_ids)
        self._select_product_for_partner(self.partner)
        self.assertTrue(self.partner.microfinance_current_loan_application_id)
        self.assertFalse(self.partner.microfinance_savings_account_ids)
