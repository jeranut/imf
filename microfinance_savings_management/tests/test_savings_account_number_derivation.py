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
        # Type G (garantie, produit 'compulsory') : premier compte de CE type pour ce client,
        # donc dérivé aussi, même si ce même client a déjà un compte de type I (produit
        # 'voluntary'). La lettre dépend désormais du type de produit, plus du titulaire.
        self._create_account()
        guarantee_product = self.env['microfinance.savings.product'].create({
            'name': 'Épargne garantie Test', 'code': 'SAVGARTEST', 'product_type': 'compulsory',
            'account_epargne_individuel_id': self.savings_deposit_account.id,
            'account_epargne_groupe_id': self.savings_deposit_account_groupe.id,
            'account_epargne_entreprise_id': self.savings_deposit_account_entreprise.id,
        })
        account_g = self._create_account(product_id=guarantee_product.id)
        agency, suffix = self.partner.microfinance_account_number.split('/', 1)
        self.assertEqual(account_g.name, '%s/G/%s' % (agency, suffix))

    def test_cross_client_collision_between_derived_and_sequence_numbers_is_avoided(self):
        # Bug détecté (cf. audit numérotation) : les deux mécanismes (dérivation directe du
        # numéro de compte client, séquence indépendante pour les comptes suivants du même
        # type) partagent le même espace de numéros sans se coordonner — une collision est
        # possible dans les deux sens, pas seulement pour le tout premier compte. Ici : le 2e
        # compte de type I du 1er client consomme via la séquence indépendante le numéro
        # correspondant au suffixe du 2e client, avant que ce 2e client n'ouvre son propre
        # 1er compte de type I.
        account1 = self._create_account()  # 1er compte du client #1 -> dérivé de son propre numéro
        account2 = self._create_account()  # 2e compte du client #1 -> séquence indépendante
        partner2 = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client Test Numéro 2', 'microfinance_partner_type': 'client',
            'microfinance_client_type': 'individual',
        })
        account3 = self._create_account(partner_id=partner2.id)  # 1er compte du client #2
        names = (account1 + account2 + account3).mapped('name')
        self.assertEqual(len(names), len(set(names)), 'Numéros de compte épargne en collision : %s' % names)

    def test_no_account_number_falls_back_to_independent_sequence(self):
        # Client sans microfinance_account_number (jamais marqué 'client') : comportement
        # préexistant intact (cf. test_agency_numbering.py).
        partner = self.env['res.partner'].create({'name': 'Client Sans Numéro Compte'})
        account = self._create_account(partner_id=partner.id)
        self.assertFalse(partner.microfinance_account_number)
        self.assertTrue(account.name)
        self.assertIn('/I/', account.name)


class TestLoanApplicationNoLongerOpensSavingsAccount(SavingsCommon):
    """Le déclencheur historique (ouverture du compte épargne principal au 1er dossier
    d'instruction de crédit, via res.partner._get_or_create_loan_application) a été retiré :
    décision validée par Micka lors du correctif numérotation Sous-lot 2. Seule la création du
    contact client ouvre désormais ce compte (cf. test_savings_principal_account_on_create.py).
    Cette classe fige explicitement la suppression plutôt que de supprimer silencieusement les
    anciens tests : self.partner (MicrofinanceCommon) est créé sans microfinance_context, donc
    n'a jamais eu de compte épargne ouvert à sa création — sélectionner un produit de crédit
    après coup ne doit plus en ouvrir un non plus."""

    def _select_product_for_partner(self, partner, product=None):
        partner.with_context(microfinance_context=True).write({
            'microfinance_selected_product_id': (product or self.product).id,
        })

    def test_dossier_creation_no_longer_opens_principal_savings_account(self):
        self.env.company.microfinance_savings_default_product_id = self.savings_product
        self.assertFalse(self.partner.microfinance_savings_account_ids)
        self._select_product_for_partner(self.partner)
        self.assertTrue(self.partner.microfinance_current_loan_application_id)
        self.assertFalse(self.partner.microfinance_savings_account_ids)
