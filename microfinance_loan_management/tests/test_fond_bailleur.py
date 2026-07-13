# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError, UserError, ValidationError

from .common import MicrofinanceCommon


class TestFondBailleurCommon(MicrofinanceCommon):
    """Base commune aux tests du fonds de crédit rotatif bailleur : ajoute un bailleur, un compte
    GL valide (liability_current) et un compte invalide (income), sur la société par défaut."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.bailleur = cls.env['microfinance.bailleur.fonds'].create({'name': 'Bailleur Test'})
        cls.fond_account = cls.env['account.account'].create({
            'name': 'Dette bailleur test', 'code': 'TFONDGL', 'account_type': 'liability_current',
            'company_id': cls.env.company.id,
        })
        cls.income_account = cls.env['account.account'].create({
            'name': 'Compte revenu test (invalide pour fonds)', 'code': 'TFONDBAD', 'account_type': 'income',
            'company_id': cls.env.company.id,
        })

    def _create_fond(self, **kwargs):
        vals = {
            'name': 'Fonds Test',
            'bailleur_id': self.bailleur.id,
            'date_debut': '2020-01-01',
            'account_id': self.fond_account.id,
        }
        vals.update(kwargs)
        return self.env['microfinance.fond.credit'].create(vals)

    def _create_contribution(self, fond, **kwargs):
        vals = {
            'fond_id': fond.id,
            'type_mouvement': 'depot',
            'amount': 1000.0,
            'mode_paiement': 'especes',
            'journal_id': self.disbursement_journal.id,
        }
        vals.update(kwargs)
        return self.env['microfinance.fond.contribution'].create(vals)

    def _approve_loan(self, **kwargs):
        loan = self._create_loan(**kwargs)
        loan.action_generate_schedule()
        loan.action_submit()
        loan.action_manager_validate()
        loan.action_finance_validate()
        loan.action_approve()
        return loan


class TestFondCompteGL(TestFondBailleurCommon):
    """Cas 1 : compte GL du fonds restreint à liability_current/liability_non_current/equity."""

    def test_fond_account_liability_current_ok(self):
        fond = self._create_fond()
        self.assertEqual(fond.account_id, self.fond_account)

    def test_fond_account_income_rejected(self):
        with self.assertRaises(ValidationError):
            self._create_fond(account_id=self.income_account.id)


class TestFondContributionComptabilisation(TestFondBailleurCommon):
    """Cas 2 et 3 : comptabilisation (ou non) des contributions selon passer_gl."""

    def test_deposit_passer_gl_true_generates_balanced_move(self):
        fond = self._create_fond(passer_gl=True)
        contrib = self._create_contribution(fond, type_mouvement='depot', amount=5000.0)
        contrib.action_post()

        self.assertEqual(contrib.state, 'posted')
        self.assertTrue(contrib.move_id)
        self.assertEqual(contrib.move_id.state, 'posted')
        debit_total = sum(contrib.move_id.line_ids.mapped('debit'))
        credit_total = sum(contrib.move_id.line_ids.mapped('credit'))
        self.assertEqual(debit_total, credit_total)
        self.assertEqual(debit_total, 5000.0)
        debit_line = contrib.move_id.line_ids.filtered(lambda l: l.debit > 0)
        credit_line = contrib.move_id.line_ids.filtered(lambda l: l.credit > 0)
        self.assertEqual(debit_line.account_id, self.bank_account)
        self.assertEqual(credit_line.account_id, self.fond_account)

    def test_withdrawal_passer_gl_true_generates_inverse_move(self):
        fond = self._create_fond(passer_gl=True)
        self._create_contribution(fond, type_mouvement='depot', amount=5000.0).action_post()
        withdrawal = self._create_contribution(fond, type_mouvement='retrait', amount=2000.0)
        withdrawal.action_post()

        debit_line = withdrawal.move_id.line_ids.filtered(lambda l: l.debit > 0)
        credit_line = withdrawal.move_id.line_ids.filtered(lambda l: l.credit > 0)
        self.assertEqual(debit_line.account_id, self.fond_account)
        self.assertEqual(credit_line.account_id, self.bank_account)
        self.assertEqual(fond.solde_disponible, 3000.0)

    def test_contribution_passer_gl_false_generates_no_move(self):
        fond = self._create_fond(passer_gl=False, account_id=False)
        contrib = self._create_contribution(fond)
        contrib.action_post()

        self.assertEqual(contrib.state, 'posted')
        self.assertFalse(contrib.move_id)
        # L'historique du mouvement reste néanmoins visible/consulté (solde mis à jour).
        self.assertEqual(fond.solde_disponible, 1000.0)


class TestFondVerificationDisponibilite(TestFondBailleurCommon):
    """Cas 4, 5, 6, 8 : la vérification de disponibilité au décaissement."""

    def test_at_request_has_no_observable_effect_at_disbursement(self):
        # Documenté (pas simulé comme s'il existait un point d'ancrage) : puisque
        # microfinance.loan.application est hors-périmètre, 'at_request' ne déclenche AUCUN
        # contrôle nulle part, y compris au décaissement (seul point d'ancrage réel du module).
        # Un fonds vide avec 'at_request' doit donc laisser passer le décaissement, exactement
        # comme 'never' - ce n'est pas un repli silencieux vers 'at_disbursement'.
        fond = self._create_fond(verification_disponibilite='at_request')
        loan = self._approve_loan(loan_amount=1000.0, term=3, fond_credit_id=fond.id)
        loan.action_disburse()
        self.assertEqual(loan.state, 'active')

    def test_never_allows_disbursement_even_when_fond_empty(self):
        fond = self._create_fond(verification_disponibilite='never')
        loan = self._approve_loan(loan_amount=1000.0, term=3, fond_credit_id=fond.id)
        loan.action_disburse()
        self.assertEqual(loan.state, 'active')

    def test_disbursement_blocked_after_date_cloture(self):
        fond = self._create_fond(
            verification_disponibilite='at_disbursement',
            date_cloture='2020-06-30',
        )
        self._create_contribution(fond, amount=10000.0).action_post()
        loan = self._approve_loan(loan_amount=1000.0, term=3, fond_credit_id=fond.id)
        with self.assertRaises(UserError):
            loan.action_disburse()

    def test_empty_fond_blocks_disbursement_with_dedicated_message(self):
        fond = self._create_fond(verification_disponibilite='at_disbursement')
        self.assertEqual(fond.solde_disponible, 0.0)
        loan = self._approve_loan(loan_amount=1000.0, term=3, fond_credit_id=fond.id)
        with self.assertRaises(UserError) as ctx:
            loan.action_disburse()
        self.assertIn('aucun solde disponible', str(ctx.exception))

    def test_insufficient_balance_blocks_disbursement_with_amounts(self):
        fond = self._create_fond(verification_disponibilite='at_disbursement')
        self._create_contribution(fond, amount=500.0).action_post()
        loan = self._approve_loan(loan_amount=1000.0, term=3, fond_credit_id=fond.id)
        with self.assertRaises(UserError) as ctx:
            loan.action_disburse()
        self.assertIn('Solde insuffisant', str(ctx.exception))

    def test_sufficient_balance_allows_disbursement_and_consumes_it(self):
        fond = self._create_fond(verification_disponibilite='at_disbursement')
        self._create_contribution(fond, amount=5000.0).action_post()
        loan = self._approve_loan(loan_amount=1000.0, term=3, fond_credit_id=fond.id)
        loan.action_disburse()
        self.assertEqual(loan.state, 'active')
        # Encours consommé : solde_disponible diminue du principal du crédit décaissé.
        self.assertEqual(fond.solde_disponible, 4000.0)


class TestFondScopeReadonly(TestFondBailleurCommon):
    """Cas 10 : scope et company_id figés après la première sauvegarde."""

    def test_change_scope_after_save_blocked(self):
        fond = self._create_fond()
        with self.assertRaises(UserError):
            fond.write({'scope': 'multi_company'})

    def test_change_company_id_after_save_blocked(self):
        fond = self._create_fond()
        other_company = self.env['res.company'].create({'name': 'Autre agence (test readonly)'})
        with self.assertRaises(UserError):
            fond.write({'company_id': other_company.id})

    def test_multi_company_requires_empty_company_id(self):
        with self.assertRaises(ValidationError):
            self._create_fond(scope='multi_company', company_id=self.env.company.id)

    def test_single_company_requires_company_id(self):
        with self.assertRaises(ValidationError):
            self._create_fond(scope='single_company', company_id=False)


class TestFondMultiCompany(TestFondBailleurCommon):
    """Cas 7 et 9 : isolation single_company vs consolidation multi_company entre agences."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_b = cls.env['res.company'].create({'name': 'Agence B fonds (test)'})
        cls.user_b = cls.env['res.users'].create({
            'name': 'Agent Agence B fonds (test)',
            'login': 'agent_agence_b_fonds_test',
            'company_id': cls.company_b.id,
            'company_ids': [(6, 0, [cls.company_b.id])],
            'groups_id': [(6, 0, [cls.env.ref('microfinance_loan_management.group_microfinance_user').id])],
        })
        # Infrastructure comptable dédiée à l'agence B, pour pouvoir y décaisser un crédit
        # réellement rattaché à company_b (pas seulement changer le company_id d'un objet
        # existant de l'agence A).
        cls.principal_account_b = cls.env['account.account'].create({
            'name': 'Prêts clients agence B (fonds)', 'code': 'BFPRET', 'account_type': 'asset_current',
            'company_id': cls.company_b.id,
        })
        cls.interest_account_b = cls.env['account.account'].create({
            'name': 'Intérêts agence B (fonds)', 'code': 'BFINT', 'account_type': 'income',
            'company_id': cls.company_b.id,
        })
        cls.cash_account_b = cls.env['account.account'].create({
            'name': 'Caisse agence B (fonds)', 'code': 'BFCASH', 'account_type': 'asset_cash',
            'company_id': cls.company_b.id,
        })
        cls.journal_b = cls.env['account.journal'].create({
            'name': 'Caisse décaissement agence B (fonds)', 'code': 'BFDEC', 'type': 'cash',
            'company_id': cls.company_b.id, 'default_account_id': cls.cash_account_b.id,
        })
        cls.product_b = cls.env['microfinance.loan.product'].create({
            'name': 'Produit agence B (fonds)', 'code': 'PFONDB', 'company_id': cls.company_b.id,
            'min_amount': 100.0, 'max_amount': 100000.0, 'min_term': 1, 'max_term': 36,
            'interest_rate': 12.0, 'interest_method': 'flat', 'repayment_frequency_mode': 'fixed',
            'repayment_frequency_id': cls.env.ref('microfinance_loan_management.repayment_frequency_monthly').id,
            'disbursement_journal_id': cls.journal_b.id, 'payment_journal_id': cls.journal_b.id,
            'account_principal_individuel_id': cls.principal_account_b.id,
            'account_principal_groupe_id': cls.principal_account_b.id,
            'account_interets_recus_individuel_id': cls.interest_account_b.id,
            'account_interets_recus_groupe_id': cls.interest_account_b.id,
        })
        cls.partner_b = cls.env['res.partner'].create({'name': 'Client Test Fonds Agence B'})

    def test_single_company_fond_invisible_from_other_agency(self):
        fond = self._create_fond(scope='single_company')
        found = self.env['microfinance.fond.credit'].with_user(self.user_b).search([('id', '=', fond.id)])
        self.assertFalse(found)
        with self.assertRaises(AccessError):
            fond.with_user(self.user_b).read(['name'])

    def test_multi_company_fond_same_balance_and_visibility_from_both_agencies(self):
        fond = self._create_fond(scope='multi_company', company_id=False, passer_gl=False)

        # Contribution saisie depuis l'agence A (société par défaut du test).
        self._create_contribution(fond, amount=5000.0, saisie_company_id=self.env.company.id).action_post()

        # Décaissement d'un crédit rattaché à l'agence B.
        loan_b = self.env['microfinance.loan'].create({
            'partner_id': self.partner_b.id,
            'product_id': self.product_b.id,
            'company_id': self.company_b.id,
            'loan_amount': 1000.0,
            'term': 3,
            'fond_credit_id': fond.id,
        })
        loan_b.action_generate_schedule()
        # Contournement volontaire du circuit d'approbation complet (hors sujet de ce test) :
        # seul l'effet du décaissement sur le fonds partagé nous intéresse ici.
        loan_b.write({'state': 'approved'})
        loan_b.action_disburse()
        self.assertEqual(loan_b.state, 'active')

        expected_solde = 5000.0 - 1000.0

        # Non-régression du cas 7 : un fonds single_company de l'agence A reste invisible
        # depuis l'agence B, y compris en présence d'un fonds multi_company partagé.
        isolated_fond = self._create_fond(scope='single_company', name='Fonds isolé agence A')
        self.assertFalse(
            self.env['microfinance.fond.credit'].with_user(self.user_b).search([('id', '=', isolated_fond.id)])
        )

        # Le fonds partagé, lui, est visible et affiche le même solde consolidé des deux côtés.
        fond_as_a = fond
        fond_as_b = fond.with_user(self.user_b)
        found_by_b = self.env['microfinance.fond.credit'].with_user(self.user_b).search([('id', '=', fond.id)])
        self.assertIn(fond, found_by_b)
        self.assertEqual(fond_as_a.solde_disponible, expected_solde)
        self.assertEqual(fond_as_b.solde_disponible, expected_solde)
        self.assertEqual(fond_as_a.total_contributions, fond_as_b.total_contributions)
        self.assertEqual(fond_as_a.total_decaisse, fond_as_b.total_decaisse)
