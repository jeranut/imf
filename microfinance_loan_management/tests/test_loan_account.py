# -*- coding: utf-8 -*-
from psycopg2 import IntegrityError

from odoo.tools import mute_logger

from .common import MicrofinanceCommon


class TestLoanAccountCreationOnPartnerCreate(MicrofinanceCommon):
    """Ouverture du compte crédit conteneur à la création du contact client, même déclencheur
    que le compte épargne principal (cf. correctif numérotation, microfinance.loan.account)."""

    def test_client_creation_opens_loan_account(self):
        partner = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client Test Compte Crédit', 'microfinance_partner_type': 'client',
            'microfinance_client_type': 'individual',
        })
        self.assertEqual(len(partner.microfinance_loan_account_ids), 1)
        self.assertEqual(partner.microfinance_loan_account_ids.company_id, self.env.company)

    def test_client_creation_outside_microfinance_context_does_not_open_account(self):
        partner = self.env['res.partner'].create({
            'name': 'Client Hors Contexte Compte Crédit', 'microfinance_partner_type': 'client',
        })
        self.assertFalse(partner.microfinance_loan_account_ids)

    def test_non_client_partner_creation_does_not_open_account(self):
        partner = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Contact Non Client Compte Crédit',
        })
        self.assertFalse(partner.microfinance_loan_account_ids)

    def test_idempotent_repeated_call_does_not_duplicate(self):
        partner = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client Test Idempotence Compte Crédit', 'microfinance_partner_type': 'client',
        })
        partner._get_or_create_microfinance_loan_account()
        partner._get_or_create_microfinance_loan_account()
        self.assertEqual(len(partner.microfinance_loan_account_ids), 1)


class TestLoanAccountLazyFallback(MicrofinanceCommon):
    """Rattrapage paresseux pour un client déjà en base sans compte crédit (créé avant ce
    correctif, ou hors microfinance_context) : résolu à la création de son prochain crédit,
    plutôt qu'une migration globale (cf. microfinance.loan.create())."""

    def test_loan_creation_creates_missing_loan_account(self):
        # self.partner (MicrofinanceCommon) est créé sans microfinance_context : n'a jamais eu
        # de compte crédit ouvert à sa création.
        self.assertFalse(self.partner.microfinance_loan_account_ids)
        loan = self._create_loan()
        self.assertTrue(loan.loan_account_id)
        self.assertEqual(loan.loan_account_id.partner_id, self.partner)
        self.assertIn(loan, loan.loan_account_id.loan_ids)

    def test_second_loan_reuses_same_loan_account(self):
        loan1 = self._create_loan()
        loan2 = self._create_loan()
        self.assertEqual(loan1.loan_account_id, loan2.loan_account_id)
        self.assertEqual(loan1.loan_account_id.loan_count, 2)


class TestLoanAccountSqlConstraint(MicrofinanceCommon):

    def test_unique_partner_company_constraint(self):
        self.env['microfinance.loan.account'].create({
            'partner_id': self.partner.id, 'company_id': self.env.company.id,
        })
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.env['microfinance.loan.account'].create({
                    'partner_id': self.partner.id, 'company_id': self.env.company.id,
                })


class TestLoanAccountReferenceNumbering(MicrofinanceCommon):
    """Génération de la référence (name) du compte crédit conteneur, calquée sur
    microfinance.savings.account._get_savings_account_name() (cf. audit numérotation compte
    crédit) : remplace l'ancien placeholder 'Compte crédit - <nom>' en dur. Sans segment TYPE
    (décision Micka, contrairement à l'épargne) : format AGENCE/NNNNNN, identique au numéro de
    compte permanent du client dans le cas courant."""

    def test_reference_derives_from_partner_permanent_account_number(self):
        # self.partner (MicrofinanceCommon) a microfinance_partner_type='client' : possède déjà
        # un microfinance_account_number (AGENCE/NNNNNN) attribué à sa création.
        self.assertTrue(self.partner.microfinance_account_number)
        account = self.env['microfinance.loan.account'].create({
            'partner_id': self.partner.id, 'company_id': self.env.company.id,
        })
        self.assertEqual(account.name, self.partner.microfinance_account_number)

    def test_reference_falls_back_to_independent_sequence_without_permanent_account_number(self):
        # Partenaire jamais marqué microfinance_partner_type='client' : pas de
        # microfinance_account_number, le compte crédit ne peut donc pas en dériver le sien.
        partner = self.env['res.partner'].create({'name': 'Emprunteur Sans Numéro Permanent'})
        self.assertFalse(partner.microfinance_account_number)
        account = self.env['microfinance.loan.account'].create({
            'partner_id': partner.id, 'company_id': self.env.company.id,
        })
        self.assertRegex(account.name, r'^%s/\d{6}$' % self.env.company.agency_code)

    def test_two_partners_without_permanent_account_number_get_distinct_references(self):
        partner_a = self.env['res.partner'].create({'name': 'Emprunteur A Sans Numéro'})
        partner_b = self.env['res.partner'].create({'name': 'Emprunteur B Sans Numéro'})
        account_a = self.env['microfinance.loan.account'].create({
            'partner_id': partner_a.id, 'company_id': self.env.company.id,
        })
        account_b = self.env['microfinance.loan.account'].create({
            'partner_id': partner_b.id, 'company_id': self.env.company.id,
        })
        self.assertNotEqual(account_a.name, account_b.name)

    def test_existing_hardcoded_reference_not_renumbered_retroactively(self):
        # Simule un compte crédit créé avant ce correctif (ancien format 'Compte crédit - X'),
        # écrit directement en base hors create() : aucune migration ne doit le retoucher.
        partner = self.env['res.partner'].create({'name': 'Client Ancien Format'})
        account = self.env['microfinance.loan.account'].create({
            'partner_id': partner.id, 'company_id': self.env.company.id,
        })
        self.env.cr.execute(
            "UPDATE microfinance_loan_account SET name = %s WHERE id = %s",
            ('Compte crédit - Client Ancien Format', account.id),
        )
        account.invalidate_recordset(['name'])
        self.assertEqual(account.name, 'Compte crédit - Client Ancien Format')
