# -*- coding: utf-8 -*-
from .common import SavingsCommon


class TestSavingsAccountNumberDerivation(SavingsCommon):
    """Numéro épargne dérivé du numéro de compte client permanent (cf. correctif numérotation
    à trois niveaux) : le 1er compte épargne d'un type donné pour un client reprend
    AGENCE/TYPE/NNNNNN avec le même suffixe numérique que microfinance_account_number ; un
    compte supplémentaire du même type garde l'ancienne numérotation par séquence indépendante,
    pour ne jamais entrer en collision."""

    def test_first_account_of_type_derives_number_from_client_account_number(self):
        account = self._create_account()
        agency, suffix = self.partner.microfinance_account_number.split('/', 1)
        self.assertEqual(account.name, '%s/I/%s' % (agency, suffix))

    def test_second_account_same_type_falls_back_to_independent_sequence(self):
        account1 = self._create_account()
        account2 = self._create_account()
        agency, suffix = self.partner.microfinance_account_number.split('/', 1)
        self.assertEqual(account1.name, '%s/I/%s' % (agency, suffix))
        self.assertNotEqual(account2.name, account1.name)

    def test_different_type_code_gets_its_own_derived_number(self):
        # Type E (entreprise) : premier compte de CE type pour ce client, donc dérivé aussi,
        # même si un autre client a déjà un compte de type I.
        self._create_account()
        company_partner = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client Test Entreprise Numéro', 'microfinance_partner_type': 'client',
            'microfinance_client_type': 'company',
        })
        account_e = self._create_account(partner_id=company_partner.id)
        agency, suffix = company_partner.microfinance_account_number.split('/', 1)
        self.assertEqual(account_e.name, '%s/E/%s' % (agency, suffix))

    def test_no_account_number_falls_back_to_independent_sequence(self):
        # Client sans microfinance_account_number (jamais marqué 'client') : comportement
        # préexistant intact (cf. test_agency_numbering.py).
        partner = self.env['res.partner'].create({'name': 'Client Sans Numéro Compte'})
        account = self._create_account(partner_id=partner.id)
        self.assertFalse(partner.microfinance_account_number)
        self.assertTrue(account.name)
        self.assertIn('/I/', account.name)


class TestSavingsPrincipalAccountAutoCreation(SavingsCommon):
    """Ouverture automatique du compte épargne principal à la création du premier dossier
    d'instruction de crédit (res.partner._get_or_create_microfinance_savings_principal_account,
    câblé sur _get_or_create_loan_application, cf. correctif numérotation)."""

    def _select_product_for_partner(self, partner, product=None):
        partner.with_context(microfinance_context=True).write({
            'microfinance_selected_product_id': (product or self.product).id,
        })

    def test_dossier_creation_opens_principal_savings_account(self):
        self.env.company.microfinance_savings_default_product_id = self.savings_product
        self.assertFalse(self.partner.microfinance_savings_account_ids)
        self._select_product_for_partner(self.partner)
        accounts = self.partner.microfinance_savings_account_ids.filtered(
            lambda a: a.product_id == self.savings_product
        )
        self.assertEqual(len(accounts), 1)
        agency, suffix = self.partner.microfinance_account_number.split('/', 1)
        self.assertEqual(accounts.name, '%s/I/%s' % (agency, suffix))

    def test_no_default_product_configured_skips_silently(self):
        self.assertFalse(self.env.company.microfinance_savings_default_product_id)
        self._select_product_for_partner(self.partner)
        self.assertFalse(self.partner.microfinance_savings_account_ids)
        # Le dossier de crédit, lui, a bien été créé malgré l'absence de produit épargne par
        # défaut : l'ouverture du compte épargne est une amélioration best-effort, jamais
        # bloquante pour le parcours crédit.
        self.assertTrue(self.partner.microfinance_current_loan_application_id)

    def test_hook_is_idempotent_no_duplicate_account(self):
        self.env.company.microfinance_savings_default_product_id = self.savings_product
        self._select_product_for_partner(self.partner)
        self._select_product_for_partner(self.partner)  # ré-enregistrement (même produit)
        accounts = self.partner.microfinance_savings_account_ids.filtered(
            lambda a: a.product_id == self.savings_product
        )
        self.assertEqual(len(accounts), 1)
