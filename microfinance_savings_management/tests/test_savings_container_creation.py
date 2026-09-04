# -*- coding: utf-8 -*-
from .common import SavingsCommon


class TestSavingsContainerCreation(SavingsCommon):
    """Création automatique du conteneur épargne au 1er crédit (Lot 1.4, docs_dev/
    epargne_exigee_display/AUDIT_LOT0_conteneur_epargne.md) - symétrique du conteneur crédit
    (microfinance.loan.account, microfinance_loan_management), numéro de base synchronisé."""

    def test_first_loan_creates_savings_container(self):
        self.assertFalse(self.env['microfinance.savings.account'].search([
            ('partner_id', '=', self.partner.id), ('is_container', '=', True),
        ]))
        self._create_loan()
        container = self.env['microfinance.savings.account'].search([
            ('partner_id', '=', self.partner.id), ('is_container', '=', True),
        ])
        self.assertEqual(len(container), 1)
        self.assertFalse(container.product_id)

    def test_container_number_synchronized_with_loan_account(self):
        loan = self._create_loan()
        container = self.env['microfinance.savings.account'].search([
            ('partner_id', '=', self.partner.id), ('is_container', '=', True),
        ])
        agency, suffix = loan.loan_account_id.name.split('/', 1)
        self.assertEqual(container.name, '%s/I/%s' % (agency, suffix))

    def test_second_loan_does_not_create_second_container(self):
        self._create_loan()
        self._create_loan()
        containers = self.env['microfinance.savings.account'].search([
            ('partner_id', '=', self.partner.id), ('is_container', '=', True),
        ])
        self.assertEqual(len(containers), 1)

    def test_container_creation_does_not_open_principal_account(self):
        # Non-régression : le "compte principal" (produit par défaut de l'agence, déclenché à la
        # création du client) reste un mécanisme distinct, non déclenché par la création du
        # conteneur au 1er crédit.
        self.env.company.microfinance_savings_default_product_id = self.savings_product
        before = self.partner.microfinance_savings_account_ids.filtered(lambda a: not a.is_container)
        self._create_loan()
        after = self.partner.microfinance_savings_account_ids.filtered(lambda a: not a.is_container)
        self.assertEqual(before, after)

    def test_borrower_without_client_type_also_gets_container(self):
        # Cf. Lot 1.1 : tout partenaire empruntant a désormais un numéro permanent, donc un
        # conteneur correctement synchronisé, quel que soit son microfinance_partner_type.
        partner = self.env['res.partner'].create({'name': 'Bailleur Emprunteur Conteneur Test', 'microfinance_partner_type': 'bailleur'})
        loan = self._create_loan(partner_id=partner.id)
        container = self.env['microfinance.savings.account'].search([
            ('partner_id', '=', partner.id), ('is_container', '=', True),
        ])
        self.assertEqual(len(container), 1)
        agency, suffix = loan.loan_account_id.name.split('/', 1)
        self.assertEqual(container.name, '%s/I/%s' % (agency, suffix))
