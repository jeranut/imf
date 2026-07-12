# -*- coding: utf-8 -*-
from odoo.exceptions import UserError, ValidationError

from .common import SavingsCommon


class TestGuaranteeSavings(SavingsCommon):
    """Épargne garantie de crédit (mécanisme LPF) : remplace l'ancien upfront_apport. Contrôle du
    solde réel du client au moment de la demande de crédit (action_submit), pas seulement au
    décaissement/à l'approbation."""

    def test_submit_allowed_when_guarantee_sufficient(self):
        self.product.write({
            'guarantee_savings_percent': 20.0,
            'guarantee_savings_product_id': self.savings_product.id,
        })
        self._create_active_account(opening_amount=250.0)  # requis : 1000 * 20% = 200
        loan = self._create_loan(loan_amount=1000.0, term=3)
        loan.action_generate_schedule()
        loan.action_submit()
        self.assertEqual(loan.state, 'submitted')

    def test_submit_blocked_when_guarantee_insufficient(self):
        self.product.write({
            'guarantee_savings_percent': 20.0,
            'guarantee_savings_product_id': self.savings_product.id,
        })
        self._create_active_account(opening_amount=50.0)  # requis 200, manque 150
        loan = self._create_loan(loan_amount=1000.0, term=3)
        loan.action_generate_schedule()
        with self.assertRaises(UserError) as ctx:
            loan.action_submit()
        self.assertIn('150.00', str(ctx.exception))
        self.assertEqual(loan.state, 'draft')

    def test_no_check_when_percent_not_set(self):
        # guarantee_savings_percent = 0 par défaut : aucune vérification, même sans aucun compte
        # épargne pour le client.
        loan = self._create_loan(loan_amount=1000.0, term=3)
        loan.action_generate_schedule()
        loan.action_submit()
        self.assertEqual(loan.state, 'submitted')

    def test_no_check_for_company_client(self):
        # La garantie sur compte d'épargne est réservée aux particuliers/groupes, pas aux
        # sociétés — cohérent avec le reste du module épargne.
        self.product.write({
            'guarantee_savings_percent': 20.0,
            'guarantee_savings_product_id': self.savings_product.id,
        })
        company_partner = self.env['res.partner'].create({
            'name': 'Client Entreprise Test', 'microfinance_client_type': 'company',
        })
        loan = self._create_loan(loan_amount=1000.0, term=3, partner_id=company_partner.id)
        loan.action_generate_schedule()
        loan.action_submit()
        self.assertEqual(loan.state, 'submitted')

    def test_config_requires_guarantee_product_when_percent_set(self):
        with self.assertRaises(ValidationError):
            self.product.write({'guarantee_savings_percent': 10.0, 'guarantee_savings_product_id': False})
