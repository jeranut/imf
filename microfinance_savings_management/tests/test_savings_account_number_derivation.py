# -*- coding: utf-8 -*-
from .common import SavingsCommon


class TestSavingsAccountNumberDerivation(SavingsCommon):
    """Numérotation épargne (Lot 1.3, docs_dev/epargne_exigee_display/
    AUDIT_LOT0_conteneur_epargne.md) : TOUT compte épargne réel - le premier d'un type donné pour
    un client comme les suivants - tire son numéro d'une séquence partagée par type
    (AGENCE/TYPE/NNNNNN, indépendante par type_code, partagée entre tous les clients de
    l'agence). Le numéro de compte permanent du client (microfinance_account_number) n'est plus
    jamais réutilisé par un compte réel - il est désormais réservé exclusivement au conteneur
    épargne (Lot 1.4).

    Changement de comportement assumé : avant ce Lot, le 1er compte d'un type donné pour un
    client reprenait directement AGENCE/TYPE/NNNNNN avec le même suffixe que son numéro de
    compte permanent (IS/000001 -> IS/I/000001) - ce n'est plus le cas, ces tests documentent
    explicitement le nouveau comportement plutôt que de le laisser se réécrire silencieusement."""

    def test_first_account_of_type_uses_shared_sequence_not_client_number(self):
        account = self._create_account()
        agency, suffix = self.partner.microfinance_account_number.split('/', 1)
        # Ne doit PLUS reprendre le suffixe du numéro de compte permanent du client.
        self.assertNotEqual(account.name, '%s/I/%s' % (agency, suffix))
        self.assertTrue(account.name.startswith('%s/I/' % agency))

    def test_successive_accounts_same_type_get_sequential_numbers(self):
        account1 = self._create_account()
        account2 = self._create_account()
        self.assertNotEqual(account1.name, account2.name)
        agency = self.partner.microfinance_account_number.split('/', 1)[0]
        suffix1 = int(account1.name.rsplit('/', 1)[1])
        suffix2 = int(account2.name.rsplit('/', 1)[1])
        self.assertEqual(suffix2, suffix1 + 1)
        self.assertTrue(account1.name.startswith('%s/I/' % agency))

    def test_different_type_code_gets_its_own_sequence(self):
        # Type G (garantie, produit 'compulsory') : séquence I et séquence G totalement
        # indépendantes, chacune démarre à 1 - même client, mais la lettre dépend du type de
        # produit, jamais du titulaire.
        self._create_account()
        guarantee_product = self.env['microfinance.savings.product'].create({
            'name': 'Épargne garantie Test', 'code': 'SAVGARTEST', 'product_type': 'compulsory',
            'account_epargne_individuel_id': self.savings_deposit_account.id,
            'account_epargne_groupe_id': self.savings_deposit_account_groupe.id,
            'account_epargne_entreprise_id': self.savings_deposit_account_entreprise.id,
        })
        account_g = self._create_account(product_id=guarantee_product.id)
        agency = self.partner.microfinance_account_number.split('/', 1)[0]
        self.assertEqual(account_g.name, '%s/G/000001' % agency)

    def test_sequence_shared_across_clients_stays_unique_and_sequential(self):
        # La numérotation n'étant plus qu'une seule séquence partagée par type (plus de
        # dérivation directe du numéro client), l'unicité est garantie par construction - ce
        # test fige ce comportement plutôt que de le supposer.
        account1 = self._create_account()  # 1er compte, client #1
        account2 = self._create_account()  # 2e compte, client #1
        partner2 = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client Test Numéro 2', 'microfinance_partner_type': 'client',
            'microfinance_client_type': 'individual',
        })
        account3 = self._create_account(partner_id=partner2.id)  # 1er compte, client #2
        names = (account1 + account2 + account3).mapped('name')
        self.assertEqual(len(names), len(set(names)), 'Numéros de compte épargne en collision : %s' % names)
        suffixes = [int(n.rsplit('/', 1)[1]) for n in names]
        self.assertEqual(suffixes, sorted(suffixes))

    def test_no_account_number_uses_same_shared_sequence(self):
        # Client sans microfinance_account_number (jamais marqué 'client') : comportement
        # désormais identique à un client normal, plus un cas particulier de repli (cf.
        # test_agency_numbering.py) - il n'y a plus qu'un seul mécanisme.
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
