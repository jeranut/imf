# -*- coding: utf-8 -*-
import base64

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
        # Banque et journal de fonds de la société courante : le journal d'une contribution est imposé
        # par le fonds (banque du fonds -> journal d'usage « Fonds »).
        cls.bank = cls.env['res.bank'].create({'name': 'Banque fonds test'})
        cls.fund_bank_account = cls.env['account.account'].create({
            'name': 'Banque fonds test', 'code': 'TFONDBK', 'account_type': 'asset_cash',
            'company_id': cls.env.company.id,
        })
        cls.fund_journal = cls.env['account.journal'].create({
            'name': 'Fonds test', 'code': 'FDBT', 'type': 'bank', 'company_id': cls.env.company.id,
            'default_account_id': cls.fund_bank_account.id,
            'microfinance_usage': 'fund', 'microfinance_bank_id': cls.bank.id,
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
            'bank_id': self.bank.id,
        }
        vals.update(kwargs)
        return self.env['microfinance.fond.credit'].create(vals)

    def _create_contribution(self, fond, **kwargs):
        vals = {
            'fond_id': fond.id,
            'type_mouvement': 'depot',
            'amount': 1000.0,
            'mode_paiement': 'virement',
        }
        vals.update(kwargs)
        return self.env['microfinance.fond.contribution'].create(vals)

    def _approve_loan(self, **kwargs):
        loan = self._create_loan(**kwargs)
        loan.action_generate_schedule()
        loan.action_start_enquete()
        loan.action_ca_review()
        loan.action_cdag_review()
        loan.action_view_applications()
        loan.application_ids.write({'committee_first_decision': 'accepted'})
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
        self.assertEqual(debit_line.account_id, self.fund_bank_account)
        self.assertEqual(credit_line.account_id, self.fond_account)

    def test_withdrawal_passer_gl_true_generates_inverse_move(self):
        fond = self._create_fond(passer_gl=True)
        self._create_contribution(fond, type_mouvement='depot', amount=5000.0).action_post()
        withdrawal = self._create_contribution(fond, type_mouvement='retrait', amount=2000.0)
        withdrawal.action_post()

        debit_line = withdrawal.move_id.line_ids.filtered(lambda l: l.debit > 0)
        credit_line = withdrawal.move_id.line_ids.filtered(lambda l: l.credit > 0)
        self.assertEqual(debit_line.account_id, self.fond_account)
        self.assertEqual(credit_line.account_id, self.fund_bank_account)
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
        other_company = self.env['res.company'].create({'name': 'Autre agence (test readonly)', 'agency_code': 'FB1'})
        with self.assertRaises(UserError):
            fond.write({'company_id': other_company.id})

    def test_multi_company_requires_empty_company_id(self):
        with self.assertRaises(ValidationError):
            self._create_fond(scope='multi_company', company_id=self.env.company.id)

    def test_single_company_requires_company_id(self):
        with self.assertRaises(ValidationError):
            self._create_fond(scope='single_company', company_id=False)


class TestFondCreditIdMandatoryIfActiveFond(TestFondBailleurCommon):
    """fond_credit_id devient obligatoire au décaissement dès qu'un fonds actif existe pour la
    société du crédit, mais reste facultatif pour une agence purement mutualiste (non-régression
    du Lot 2 : pas de fonds actif -> pas de blocage)."""

    def test_disbursement_without_fond_blocked_when_active_fond_exists(self):
        self._create_fond()
        loan = self._approve_loan(loan_amount=1000.0, term=3)
        self.assertFalse(loan.fond_credit_id)
        with self.assertRaises(UserError):
            loan.action_disburse()

    def test_disbursement_without_fond_still_allowed_when_no_active_fond(self):
        # Aucun fonds créé dans ce test : société purement mutualiste, non-régression du Lot 2.
        loan = self._activate_loan(loan_amount=1000.0, term=3)
        self.assertEqual(loan.state, 'active')
        self.assertFalse(loan.fond_credit_id)


class TestFondCreditIdLockedAfterDisbursement(TestFondBailleurCommon):
    """Correction prioritaire : un crédit décaissé ne peut plus voir son fond_credit_id modifié -
    sinon le solde_disponible du fonds est restauré à tort sans annuler l'écriture comptable
    posée sur ce fonds (bug constaté en test manuel)."""

    def _disbursed_loan_with_fond(self):
        fond = self._create_fond(verification_disponibilite='at_disbursement')
        self._create_contribution(fond, amount=5000.0).action_post()
        loan = self._approve_loan(loan_amount=1000.0, term=3, fond_credit_id=fond.id)
        loan.action_disburse()
        return fond, loan

    def test_clearing_fond_after_disbursement_blocked(self):
        fond, loan = self._disbursed_loan_with_fond()
        with self.assertRaises(ValidationError):
            loan.write({'fond_credit_id': False})

    def test_reassigning_fond_after_disbursement_blocked(self):
        fond, loan = self._disbursed_loan_with_fond()
        other_fond = self._create_fond(name='Autre fonds (lock test)')
        with self.assertRaises(ValidationError):
            loan.write({'fond_credit_id': other_fond.id})

    def test_clearing_fond_after_disbursement_does_not_restore_solde(self):
        fond, loan = self._disbursed_loan_with_fond()
        self.assertEqual(fond.solde_disponible, 4000.0)
        with self.assertRaises(ValidationError):
            loan.write({'fond_credit_id': False})
        # Le solde reste diminué : l'écriture comptable, elle, n'a jamais été annulée.
        self.assertEqual(fond.solde_disponible, 4000.0)
        self.assertEqual(loan.fond_credit_id, fond)

    def test_fond_still_editable_before_disbursement(self):
        fond = self._create_fond()
        other_fond = self._create_fond(name='Autre fonds (avant décaissement)')
        loan = self._approve_loan(loan_amount=1000.0, term=3, fond_credit_id=fond.id)
        self.assertEqual(loan.state, 'approved')
        loan.write({'fond_credit_id': other_fond.id})
        self.assertEqual(loan.fond_credit_id, other_fond)


class TestFondMultiCompany(TestFondBailleurCommon):
    """Cas 7 et 9 : isolation single_company vs consolidation multi_company entre agences."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_b = cls.env['res.company'].create({'name': 'Agence B fonds (test)', 'agency_code': 'FB2'})
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
            # Arrondi désactivé (même raison que common.py MicrofinanceCommon.setUpClass) : les
            # montants ronds et courts utilisés dans ces tests (ex. 1000 Ar / 3 échéances) n'ont
            # aucun rapport avec la granularité réelle CEFOR et tombent dans la zone à risque du
            # garde-fou reliquat négatif (cf. docs_dev/garde_fou_reliquat_negatif/AUDIT.md) sans
            # que ce soit ce que ces tests vérifient.
            'installment_rounding_unit': 0,
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
            # Prérequis d'activation (cf. common._create_loan) : sans rapport avec ce test.
            'signed_contract': base64.b64encode(b'test signed contract'),
            'signed_contract_filename': 'contrat_signe_test.pdf',
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


class TestBailleurPartnerLink(TestFondBailleurCommon):
    """partner_id devenu required=True sur microfinance.bailleur.fonds : auto-création d'un
    res.partner de type 'bailleur' quand aucun n'est fourni, sync bidirectionnelle du nom."""

    def test_create_without_partner_id_auto_creates_partner(self):
        bailleur = self.env['microfinance.bailleur.fonds'].create({'name': 'Bailleur Auto'})
        self.assertTrue(bailleur.partner_id)
        self.assertEqual(bailleur.partner_id.name, 'Bailleur Auto')
        self.assertEqual(bailleur.partner_id.microfinance_partner_type, 'bailleur')
        self.assertFalse(bailleur.partner_id.company_id)

    def test_create_with_explicit_partner_id_does_not_create_a_second_partner(self):
        partner = self.env['res.partner'].create({
            'name': 'Contact Bailleur Existant', 'microfinance_partner_type': 'bailleur',
        })
        bailleur = self.env['microfinance.bailleur.fonds'].create({
            'name': 'Bailleur Avec Contact', 'partner_id': partner.id,
        })
        self.assertEqual(bailleur.partner_id, partner)

    def test_name_is_related_to_partner_name_bidirectional(self):
        bailleur = self.env['microfinance.bailleur.fonds'].create({'name': 'Nom Initial'})
        partner = bailleur.partner_id

        bailleur.name = 'Nom Modifié Depuis Bailleur'
        self.assertEqual(partner.name, 'Nom Modifié Depuis Bailleur')

        partner.name = 'Nom Modifié Depuis Partner'
        self.assertEqual(bailleur.name, 'Nom Modifié Depuis Partner')

    def test_setup_class_bailleur_without_explicit_partner_id_still_works(self):
        # Non-régression : TestFondBailleurCommon.setUpClass crée cls.bailleur sans partner_id
        # explicite (create({'name': 'Bailleur Test'})) — doit continuer à fonctionner grâce à
        # l'auto-création, sans backfill manuel nécessaire dans les tests existants.
        self.assertTrue(self.bailleur.partner_id)
        self.assertEqual(self.bailleur.partner_id.name, 'Bailleur Test')


class TestFondAccountDefaultPerCompany(TestFondBailleurCommon):
    """res.company.microfinance_fond_account_default_id : préremplissage de
    microfinance.fond.credit.account_id à la création d'un fonds - même principe que
    TestFondCreditDefaultPerCompany (test_fond_default_company.py) pour
    microfinance_fond_credit_default_id, appliqué ici au compte comptable bailleur plutôt
    qu'au fonds proposé par défaut sur un crédit."""

    def _create_fond_no_explicit_account(self, **kwargs):
        # TestFondBailleurCommon._create_fond() injecte toujours account_id dans vals (y
        # compris à None) : pour tester le repli create()/default= sur l'absence réelle de la
        # clé (cf. spec "si 'account_id' absent de vals"), on construit vals directement ici
        # plutôt que de passer par ce helper.
        vals = {'name': 'Fonds Test', 'bailleur_id': self.bailleur.id, 'date_debut': '2020-01-01'}
        vals.update(kwargs)
        return self.env['microfinance.fond.credit'].create(vals)

    def test_default_applied_at_creation_without_explicit_account(self):
        self.env.company.microfinance_fond_account_default_id = self.fond_account.id
        fond = self._create_fond_no_explicit_account()
        # Aucun account_id dans vals ici : le default= du champ (création via le formulaire,
        # api.model_create_multi) l'applique déjà avant même le repli de create().
        self.assertEqual(fond.account_id, self.fond_account)

    def test_no_default_configured_leaves_account_id_empty(self):
        # Comportement actuel inchangé : société sans défaut configuré (cas par défaut de
        # TestFondBailleurCommon.setUpClass, jamais modifié ici) -> account_id reste vide.
        self.assertFalse(self.env.company.microfinance_fond_account_default_id)
        fond = self._create_fond_no_explicit_account(passer_gl=False)
        self.assertFalse(fond.account_id)

    def test_default_overridable_at_creation(self):
        other_account = self.env['account.account'].create({
            'name': 'Dette bailleur test 2', 'code': 'TFONDGL2',
            'account_type': 'liability_current', 'company_id': self.env.company.id,
        })
        self.env.company.microfinance_fond_account_default_id = self.fond_account.id
        fond = self._create_fond(account_id=other_account.id)
        self.assertEqual(fond.account_id, other_account)

    def test_default_overridable_after_creation(self):
        other_account = self.env['account.account'].create({
            'name': 'Dette bailleur test 2', 'code': 'TFONDGL2',
            'account_type': 'liability_current', 'company_id': self.env.company.id,
        })
        self.env.company.microfinance_fond_account_default_id = self.fond_account.id
        fond = self._create_fond_no_explicit_account()
        self.assertEqual(fond.account_id, self.fond_account)

        fond.account_id = other_account.id
        self.assertEqual(fond.account_id, other_account)

    def test_changing_company_default_has_no_retroactive_effect_on_existing_funds(self):
        other_account = self.env['account.account'].create({
            'name': 'Dette bailleur test 2', 'code': 'TFONDGL2',
            'account_type': 'liability_current', 'company_id': self.env.company.id,
        })
        self.env.company.microfinance_fond_account_default_id = self.fond_account.id
        fond = self._create_fond_no_explicit_account()
        self.assertEqual(fond.account_id, self.fond_account)

        # Changer le défaut de la société après coup ne doit jamais toucher un fonds déjà créé.
        self.env.company.microfinance_fond_account_default_id = other_account.id
        self.assertEqual(fond.account_id, self.fond_account)

    def test_empty_default_with_passer_gl_still_raises_validation_error(self):
        # _check_account_required inchangée : un défaut vide + passer_gl actif doit toujours
        # bloquer, exactement comme avant l'introduction de ce défaut.
        self.assertFalse(self.env.company.microfinance_fond_account_default_id)
        with self.assertRaises(ValidationError):
            self._create_fond_no_explicit_account(passer_gl=True)

    def test_default_income_account_rejected_on_company(self):
        with self.assertRaises(ValidationError):
            self.env.company.microfinance_fond_account_default_id = self.income_account.id

    def test_default_account_from_another_company_rejected(self):
        other_company = self.env['res.company'].create({
            'name': 'Agence B compte bailleur (test)', 'agency_code': 'Z9',
        })
        other_account = self.env['account.account'].create({
            'name': 'Dette bailleur autre société', 'code': 'ZFONDGL',
            'account_type': 'liability_current', 'company_id': other_company.id,
        })
        with self.assertRaises(ValidationError):
            self.env.company.microfinance_fond_account_default_id = other_account.id

    def test_onchange_prefills_account_id_when_empty(self):
        self.env.company.microfinance_fond_account_default_id = self.fond_account.id
        # account_id explicitement False (plutôt qu'absent) : bypass le default= du champ pour
        # isoler la logique de l'onchange lui-même, pas celle du default à la création.
        fond_form = self.env['microfinance.fond.credit'].new({
            'name': 'Fonds Test Onchange', 'bailleur_id': self.bailleur.id,
            'date_debut': '2020-01-01', 'account_id': False,
        })
        fond_form._onchange_scope_account_domain()
        self.assertEqual(fond_form.account_id, self.fond_account)

    def test_onchange_replaces_account_from_another_company_on_company_change(self):
        # Scénario réaliste du spec : un compte d'une AUTRE société traîne encore sur le champ
        # (résidu d'un changement de société) -> l'onchange doit le remplacer par le défaut de
        # la nouvelle société, pas le laisser tel quel.
        other_company = self.env['res.company'].create({
            'name': 'Agence B onchange (test)', 'agency_code': 'Z8',
        })
        other_company_account = self.env['account.account'].create({
            'name': 'Dette bailleur autre société', 'code': 'Z8FONDGL',
            'account_type': 'liability_current', 'company_id': other_company.id,
        })
        self.env.company.microfinance_fond_account_default_id = self.fond_account.id
        fond_form = self.env['microfinance.fond.credit'].new({
            'name': 'Fonds Test Onchange', 'bailleur_id': self.bailleur.id,
            'date_debut': '2020-01-01', 'account_id': other_company_account.id,
            'company_id': self.env.company.id,
        })
        fond_form._onchange_scope_account_domain()
        self.assertEqual(fond_form.account_id, self.fond_account)

    def test_onchange_never_overwrites_manual_choice_of_same_company(self):
        other_account = self.env['account.account'].create({
            'name': 'Dette bailleur test 2', 'code': 'TFONDGL2',
            'account_type': 'liability_current', 'company_id': self.env.company.id,
        })
        self.env.company.microfinance_fond_account_default_id = self.fond_account.id
        fond_form = self.env['microfinance.fond.credit'].new({
            'name': 'Fonds Test Onchange', 'bailleur_id': self.bailleur.id,
            'date_debut': '2020-01-01', 'account_id': other_account.id,
        })
        fond_form._onchange_scope_account_domain()
        self.assertEqual(fond_form.account_id, other_account)
