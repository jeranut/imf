# -*- coding: utf-8 -*-
from odoo import fields
from odoo.exceptions import AccessError, UserError

from .common import SavingsCommon


class TestCaisseSearchClients(SavingsCommon):
    """Lot 3.1 : res.partner.search_caisse_clients(query, company_id), recherche dédiée (pas une
    surcharge de name_search) par nom OU numéro de compte permanent, scopée par agence."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.other_company = cls.env['res.company'].create({'name': 'Autre agence test', 'agency_code': 'T1'})
        cls.client_a = cls.env['res.partner'].create({
            'name': 'Rakoto Jean', 'microfinance_partner_type': 'client', 'company_id': cls.env.company.id,
        })
        cls.non_client = cls.env['res.partner'].create({
            'name': 'Rakoto Fournisseur', 'microfinance_partner_type': False, 'company_id': cls.env.company.id,
        })
        cls.client_other_company = cls.env['res.partner'].create({
            'name': 'Rasoa Marie', 'microfinance_partner_type': 'client', 'company_id': cls.other_company.id,
        })

    def test_search_by_name(self):
        results = self.env['res.partner'].search_caisse_clients('Rakoto', self.env.company.id)
        self.assertEqual({r['id'] for r in results}, {self.client_a.id})

    def test_search_by_account_number(self):
        results = self.env['res.partner'].search_caisse_clients(
            self.client_a.microfinance_account_number, self.env.company.id,
        )
        self.assertEqual({r['id'] for r in results}, {self.client_a.id})
        self.assertEqual(results[0]['account_number'], self.client_a.microfinance_account_number)

    def test_search_excludes_non_client_partner_type(self):
        results = self.env['res.partner'].search_caisse_clients('Rakoto', self.env.company.id)
        self.assertNotIn(self.non_client.id, {r['id'] for r in results})

    def test_search_scoped_by_company(self):
        results = self.env['res.partner'].search_caisse_clients('Rasoa', self.env.company.id)
        self.assertEqual(results, [])
        results_other = self.env['res.partner'].search_caisse_clients('Rasoa', self.other_company.id)
        self.assertEqual({r['id'] for r in results_other}, {self.client_other_company.id})


class TestCaisseGetClientAccountsSummary(SavingsCommon):
    """Lot 3.2 : agrège comptes épargne actifs et crédits actionnables en un seul appel."""

    def test_summary_includes_active_savings_account(self):
        account = self._create_active_account(opening_amount=150.0)
        summary = self.env['res.partner'].get_client_accounts_summary(self.partner.id, self.env.company.id)
        self.assertEqual(len(summary['savings_accounts']), 1)
        self.assertEqual(summary['savings_accounts'][0]['id'], account.id)
        self.assertAlmostEqual(summary['savings_accounts'][0]['balance'], 150.0, places=2)

    def test_summary_excludes_draft_savings_account(self):
        self._create_account()  # jamais activé : reste en 'draft'
        summary = self.env['res.partner'].get_client_accounts_summary(self.partner.id, self.env.company.id)
        self.assertEqual(summary['savings_accounts'], [])

    def test_summary_includes_active_loan_with_next_due_installment(self):
        loan = self._activate_loan(loan_amount=1200.0, term=6)
        summary = self.env['res.partner'].get_client_accounts_summary(self.partner.id, self.env.company.id)
        self.assertEqual(len(summary['loans']), 1)
        loan_data = summary['loans'][0]
        self.assertEqual(loan_data['id'], loan.id)
        self.assertEqual(loan_data['state'], 'active')
        self.assertAlmostEqual(loan_data['balance_total'], loan.balance_total, places=2)
        self.assertTrue(loan_data['next_due_date'])

    def test_summary_includes_approved_not_yet_disbursed_loan(self):
        loan = self._create_loan(loan_amount=500.0, term=3)
        loan.action_generate_schedule()
        loan.action_start_enquete()
        loan.action_ca_review()
        loan.action_cdag_review()
        loan.action_view_applications()
        loan.application_ids.write({'committee_first_decision': 'accepted'})
        loan.action_approve()
        summary = self.env['res.partner'].get_client_accounts_summary(self.partner.id, self.env.company.id)
        self.assertEqual([l['id'] for l in summary['loans']], [loan.id])
        self.assertEqual(summary['loans'][0]['state'], 'approved')


class TestCaisseRegisterOperation(SavingsCommon):
    """Lot 3.3 : point d'entrée unique du guichet — dispatch par type, réutilise les mécanismes
    déjà existants (transaction épargne, remboursement, décaissement), refuse hors session
    ouverte, vérifie la cohérence d'agence."""

    def _open_session(self, journal=None):
        session = self.env['microfinance.caisse.session'].create({
            'journal_id': (journal or self.disbursement_journal).id, 'date': fields.Date.today(),
        })
        session.action_open_session()
        return session

    def test_register_deposit_creates_transaction_and_mouvement(self):
        account = self._create_active_account(opening_amount=100.0)
        session = self._open_session()
        mouvement = self.env['microfinance.caisse.mouvement'].register_operation(
            session.id, 'depot_epargne', self.partner.id, 80.0, account.id, False,
        )
        self.assertEqual(mouvement.type, 'depot_epargne')
        self.assertEqual(mouvement.session_id, session)
        self.assertTrue(mouvement.savings_transaction_id)
        self.assertEqual(mouvement.savings_transaction_id.transaction_type, 'deposit')
        self.assertEqual(mouvement.savings_transaction_id.state, 'posted')
        self.assertAlmostEqual(account.balance, 180.0, places=2)
        self.assertIn(mouvement, session.mouvement_ids)

    def test_register_withdrawal_creates_transaction(self):
        account = self._create_active_account(opening_amount=200.0)
        session = self._open_session()
        mouvement = self.env['microfinance.caisse.mouvement'].register_operation(
            session.id, 'retrait_epargne', self.partner.id, 50.0, account.id, False,
        )
        self.assertEqual(mouvement.savings_transaction_id.transaction_type, 'withdrawal')
        self.assertAlmostEqual(account.balance, 150.0, places=2)

    def test_register_remboursement_matches_backend_allocation(self):
        loan = self._activate_loan(loan_amount=1200.0, term=6)
        first = loan.installment_ids.sorted('sequence')[0]
        session = self._open_session(journal=self.payment_journal)
        amount = min(80.0, first.total_amount)
        mouvement = self.env['microfinance.caisse.mouvement'].register_operation(
            session.id, 'remboursement_credit', self.partner.id, amount, False, loan.id,
        )
        self.assertTrue(mouvement.payment_id)
        self.assertEqual(mouvement.payment_id.state, 'posted')
        self.assertEqual(mouvement.payment_id.journal_id, self.payment_journal)
        self.assertAlmostEqual(mouvement.interest_amount, mouvement.payment_id.allocated_interest, places=2)
        self.assertAlmostEqual(mouvement.principal_amount, mouvement.payment_id.allocated_principal, places=2)
        self.assertAlmostEqual(mouvement.penalty_amount, mouvement.payment_id.allocated_penalty, places=2)
        self.assertAlmostEqual(
            mouvement.interest_amount + mouvement.principal_amount + mouvement.penalty_amount,
            amount, places=2,
        )

    def test_register_decaissement_disburses_loan(self):
        loan = self._create_loan(loan_amount=500.0, term=3)
        loan.action_generate_schedule()
        loan.action_start_enquete()
        loan.action_ca_review()
        loan.action_cdag_review()
        loan.action_view_applications()
        loan.application_ids.write({'committee_first_decision': 'accepted'})
        loan.action_approve()
        # Découplage activation / décaissement (docs_dev/guichet_caisse/AUDIT_decaissement.md) :
        # le crédit doit être 'active' (clic « Activer » sur la fiche) avant de passer au
        # guichet, qui ne fait plus que le décaissement effectif.
        loan.action_activate()
        self.assertFalse(loan.disbursement_date)
        session = self._open_session()
        mouvement = self.env['microfinance.caisse.mouvement'].register_operation(
            session.id, 'decaissement_credit', self.partner.id, loan.loan_amount, False, loan.id,
        )
        self.assertEqual(loan.state, 'active')
        self.assertTrue(loan.disbursement_date)
        self.assertAlmostEqual(mouvement.amount, loan.net_disbursed_amount, places=2)

    def test_register_blocked_without_open_session(self):
        account = self._create_active_account(opening_amount=100.0)
        draft_session = self.env['microfinance.caisse.session'].create({
            'journal_id': self.disbursement_journal.id, 'date': fields.Date.today(),
        })  # jamais ouverte : reste 'draft'
        with self.assertRaises(UserError):
            self.env['microfinance.caisse.mouvement'].register_operation(
                draft_session.id, 'depot_epargne', self.partner.id, 50.0, account.id, False,
            )

    def test_register_blocked_cross_company_account(self):
        other_company = self.env['res.company'].create({'name': 'Autre agence test 2', 'agency_code': 'T2'})
        other_journal = self.env['account.journal'].create({
            'name': 'Caisse autre agence test', 'code': 'TOTH', 'type': 'cash', 'company_id': other_company.id,
        })
        session = self.env['microfinance.caisse.session'].create({
            'journal_id': other_journal.id, 'date': fields.Date.today(), 'company_id': other_company.id,
        })
        session.action_open_session()
        account = self._create_active_account(opening_amount=100.0)  # société par défaut (env.company)
        with self.assertRaises(UserError):
            self.env['microfinance.caisse.mouvement'].register_operation(
                session.id, 'depot_epargne', self.partner.id, 50.0, account.id, False,
            )


class TestCaissePosNoRegression(SavingsCommon):
    """Vérifie que les opérations existantes créées HORS de ce nouveau flux (script, import,
    utilisation directe des mécanismes déjà en place) restent inchangées par les hooks ajoutés
    pour la caisse — aucun microfinance.caisse.mouvement n'est requis ni créé implicitement."""

    def test_direct_savings_transaction_unaffected(self):
        account = self._create_active_account(opening_amount=100.0)
        transaction = account._create_transaction('deposit', 50.0)
        self.assertEqual(transaction.state, 'posted')
        self.assertFalse(self.env['microfinance.caisse.mouvement'].search([
            ('savings_transaction_id', '=', transaction.id),
        ]))

    def test_direct_loan_payment_unaffected(self):
        loan = self._activate_loan(loan_amount=1200.0, term=6)
        payment = self.env['microfinance.loan.payment'].create({
            'loan_id': loan.id, 'amount': 50.0, 'journal_id': self.payment_journal.id,
        })
        payment.action_post()
        self.assertEqual(payment.state, 'posted')
        self.assertFalse(self.env['microfinance.caisse.mouvement'].search([
            ('payment_id', '=', payment.id),
        ]))

    def test_direct_disbursement_unaffected(self):
        loan = self._create_loan(loan_amount=500.0, term=3)
        loan.action_generate_schedule()
        loan.action_start_enquete()
        loan.action_ca_review()
        loan.action_cdag_review()
        loan.action_view_applications()
        loan.application_ids.write({'committee_first_decision': 'accepted'})
        loan.action_approve()
        # Chemin fiche crédit (hors guichet) : activation puis décaissement direct.
        loan.action_activate()
        loan.action_process_disbursement()
        self.assertEqual(loan.state, 'active')
        self.assertTrue(loan.disbursement_date)
        self.assertFalse(self.env['microfinance.caisse.mouvement'].search([
            ('loan_id', '=', loan.id),
        ]))


class TestCaissePureCashierSavingsAccess(SavingsCommon):
    """Lot 1.1 : group_microfinance_cashier implique désormais group_savings_agent
    (microfinance_savings_management/security/savings_security.xml) — un caissier « pur » peut
    lire les modèles épargne.

    Lot 1.1bis (option 2, sudo ciblé) : microfinance.caisse.mouvement._run_posting_sudo()
    exécute en sudo la seule étape comptabilisante des opérations de guichet
    (_create_transaction / microfinance.loan.payment.action_post / microfinance.loan.
    action_disburse), circonscrit à register_operation. Un caissier strictement
    group_microfinance_cashier + group_savings_agent (aucun groupe comptable) peut donc servir
    les 4 opérations de bout en bout, sans que le bypass ne fuite hors de ce chemin.
    Ces chemins n'étaient couverts par aucun test avant ces lots (docs_dev/guichet_caisse/
    AUDIT.md §1.1 / §5.5)."""

    # tracking_disable / mail_notify_force_send=False : les message_post déclenchés par
    # action_post() / action_open_session() ne doivent pas dépendre d'une configuration de
    # serveur de mail (sinon échec parasite sur une base où l'e-mail sortant est configuré
    # mais l'utilisateur de test n'a pas d'adresse).
    _NO_MAIL_CTX = {'tracking_disable': True, 'mail_notify_force_send': False, 'mail_create_nolog': True}

    def _pure_cashier(self):
        # base.group_user (utilisateur interne) + le seul groupe métier group_microfinance_cashier,
        # comme le ferait la création d'un compte caissier via Réglages > Utilisateurs. Aucun
        # groupe épargne ni comptable ajouté explicitement : on teste bien l'implication mise en
        # place par le Lot 1.1, pas un contournement par cumul de groupes.
        return self.env['res.users'].create({
            'name': 'Caissier guichet test', 'login': 'cashier_guichet_savings_test',
            'company_id': self.env.company.id, 'company_ids': [(6, 0, [self.env.company.id])],
            # email + notification_type='inbox' : les message_post émis par action_post() en
            # tant que ce user aboutissent (message_post exige une adresse d'auteur résoluble,
            # raise_on_email=True) sans dépendre d'un serveur mail configuré sur la base.
            'email': 'caissier.guichet@example.com',
            'notification_type': 'inbox',
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('microfinance_loan_management.group_microfinance_cashier').id,
            ])],
        })

    def _neutralize_funds(self):
        # SEFOR (et toute base réelle) a un microfinance.fond.credit actif pour la société :
        # sans fond_credit_id sur le crédit, action_disburse() lève « Un fonds de crédit
        # rotatif actif existe pour cette agence » (_check_fond_disponibilite). On désactive
        # les fonds le temps du test (TransactionCase => rollback, aucune donnée réelle
        # touchée) pour que les flux crédit soient testables partout, comme les tests
        # TestCaisseRegisterOperation existants le supposent sur base vierge.
        self.env['microfinance.fond.credit'].sudo().search([('active', '=', True)]).write({'active': False})

    def _open_session(self, journal):
        session = self.env['microfinance.caisse.session'].with_context(**self._NO_MAIL_CTX).create({
            'journal_id': journal.id, 'date': fields.Date.today(),
        })
        session.action_open_session()
        return session

    def _approve_loan_not_disbursed(self, **kwargs):
        loan = self._create_loan(**kwargs)
        loan.action_generate_schedule()
        loan.action_start_enquete()
        loan.action_ca_review()
        loan.action_cdag_review()
        loan.action_view_applications()
        loan.application_ids.write({'committee_first_decision': 'accepted'})
        loan.action_approve()
        return loan

    def test_implied_group_is_effective(self):
        cashier = self._pure_cashier()
        self.assertTrue(
            cashier.has_group('microfinance_savings_management.group_savings_agent'),
            "group_microfinance_cashier doit impliquer group_savings_agent après le Lot 1.1.",
        )

    def test_pure_cashier_can_read_savings_models(self):
        account = self._create_active_account(opening_amount=120.0)
        cashier = self._pure_cashier()
        # Ni search ni read ne doivent lever d'AccessError.
        found = self.env['microfinance.savings.account'].with_user(cashier).search(
            [('id', '=', account.id)])
        self.assertEqual(found, account)
        found.read(['name', 'balance', 'state'])
        txns = self.env['microfinance.savings.transaction'].with_user(cashier).search(
            [('account_id', '=', account.id)])
        self.assertTrue(txns)
        txns.read(['transaction_type', 'amount', 'state'])

    def test_pure_cashier_get_client_accounts_summary(self):
        self._create_active_account(opening_amount=120.0)
        cashier = self._pure_cashier()
        summary = self.env['res.partner'].with_user(cashier).get_client_accounts_summary(
            self.partner.id, self.env.company.id)
        self.assertEqual(len(summary['savings_accounts']), 1)

    # --- Lot 1.1bis : les 4 opérations servies de bout en bout par un caissier PUR ---

    def _cashier_mouvement(self, cashier):
        return self.env['microfinance.caisse.mouvement'].with_user(cashier).with_context(**self._NO_MAIL_CTX)

    def test_pure_cashier_depot_epargne(self):
        account = self._create_active_account(opening_amount=100.0)
        session = self._open_session(self.savings_deposit_journal)
        cashier = self._pure_cashier()
        mouvement = self._cashier_mouvement(cashier).register_operation(
            session.id, 'depot_epargne', self.partner.id, 40.0, account.id, False,
        )
        self.assertEqual(mouvement.type, 'depot_epargne')
        self.assertEqual(mouvement.savings_transaction_id.state, 'posted')
        self.assertAlmostEqual(account.balance, 140.0, places=2)

    def test_pure_cashier_retrait_epargne(self):
        account = self._create_active_account(opening_amount=200.0)
        session = self._open_session(self.savings_withdrawal_journal)
        cashier = self._pure_cashier()
        mouvement = self._cashier_mouvement(cashier).register_operation(
            session.id, 'retrait_epargne', self.partner.id, 60.0, account.id, False,
        )
        self.assertEqual(mouvement.savings_transaction_id.transaction_type, 'withdrawal')
        self.assertEqual(mouvement.savings_transaction_id.state, 'posted')
        self.assertAlmostEqual(account.balance, 140.0, places=2)

    def test_pure_cashier_remboursement_credit(self):
        self._neutralize_funds()
        loan = self._activate_loan(loan_amount=1200.0, term=6)
        first = loan.installment_ids.sorted('sequence')[0]
        amount = min(80.0, first.total_amount)
        session = self._open_session(self.payment_journal)
        cashier = self._pure_cashier()
        mouvement = self._cashier_mouvement(cashier).register_operation(
            session.id, 'remboursement_credit', self.partner.id, amount, False, loan.id,
        )
        self.assertTrue(mouvement.payment_id)
        self.assertEqual(mouvement.payment_id.state, 'posted')
        self.assertAlmostEqual(
            mouvement.interest_amount + mouvement.principal_amount + mouvement.penalty_amount,
            amount, places=2,
        )

    def test_pure_cashier_decaissement_credit(self):
        self._neutralize_funds()
        loan = self._approve_loan_not_disbursed(loan_amount=500.0, term=3)
        # Découplage activation / décaissement : le crédit doit être activé (fiche) avant que
        # le guichet ne réalise le décaissement effectif.
        loan.action_activate()
        session = self._open_session(self.disbursement_journal)
        cashier = self._pure_cashier()
        mouvement = self._cashier_mouvement(cashier).register_operation(
            session.id, 'decaissement_credit', self.partner.id, loan.loan_amount, False, loan.id,
        )
        self.assertEqual(loan.state, 'active')
        self.assertTrue(loan.disbursement_date)
        self.assertAlmostEqual(mouvement.amount, loan.net_disbursed_amount, places=2)

    # --- Lot 1.1bis : le sudo ne fuit pas hors de register_operation ---

    def test_sudo_does_not_leak_arbitrary_account_move(self):
        # Le bypass est circonscrit à _run_posting_sudo : un caissier pur reste incapable de
        # créer un account.move par une voie directe.
        cashier = self._pure_cashier()
        with self.assertRaises(AccessError):
            self.env['account.move'].with_user(cashier).create({
                'move_type': 'entry',
                'journal_id': self.savings_deposit_journal.id,
            })

    def test_cross_company_operation_still_blocked_with_sudo(self):
        # La garde d'agence (amont dans register_operation + re-vérification dans
        # _run_posting_sudo) reste effective malgré le sudo : compte d'une agence, session
        # d'une autre => UserError, jamais de comptabilisation. Le caissier a ici accès aux
        # deux sociétés pour que la session se charge et que ce soit bien la garde d'agence
        # (et non l'ir.rule de session) qui bloque.
        other_company = self.env['res.company'].create({'name': 'Autre agence sudo test', 'agency_code': 'SU1'})
        other_journal = self.env['account.journal'].create({
            'name': 'Caisse autre agence sudo test', 'code': 'SUOT', 'type': 'cash',
            'company_id': other_company.id,
        })
        session = self.env['microfinance.caisse.session'].with_context(**self._NO_MAIL_CTX).create({
            'journal_id': other_journal.id, 'date': fields.Date.today(), 'company_id': other_company.id,
        })
        session.action_open_session()
        account = self._create_active_account(opening_amount=100.0)  # société courante, pas other_company
        cashier = self._pure_cashier()
        cashier.company_ids = [(6, 0, [self.env.company.id, other_company.id])]
        with self.assertRaises(UserError):
            self._cashier_mouvement(cashier).register_operation(
                session.id, 'depot_epargne', self.partner.id, 30.0, account.id, False,
            )
        self.assertFalse(account.transaction_ids.filtered(lambda t: abs(t.amount - 30.0) < 0.01))

    def test_cashier_with_accounting_group_still_ok(self):
        # Non-régression : un caissier qui porte AUSSI un groupe comptable standard sert
        # toujours un dépôt épargne (le sudo ciblé ne casse pas ce profil).
        account = self._create_active_account(opening_amount=100.0)
        session = self._open_session(self.savings_deposit_journal)
        cashier = self._pure_cashier()
        cashier.groups_id = [(4, self.env.ref('account.group_account_user').id)]
        mouvement = self._cashier_mouvement(cashier).register_operation(
            session.id, 'depot_epargne', self.partner.id, 40.0, account.id, False,
        )
        self.assertEqual(mouvement.savings_transaction_id.state, 'posted')
        self.assertAlmostEqual(account.balance, 140.0, places=2)

    # --- Lot 1 étendu : type 'frais_dossier' via register_operation (sous-lot B) ---

    def _setup_fee_product(self, fee_amount=30.0):
        receivable = self.env['account.account'].create({
            'name': 'Frais à recevoir caisse test', 'code': 'TFEERC',
            'account_type': 'asset_current', 'reconcile': True, 'company_id': self.env.company.id,
        })
        od_journal = self.env['account.journal'].create({
            'name': 'OD frais caisse test', 'code': 'TODFC', 'type': 'general',
            'company_id': self.env.company.id,
        })
        self.product.write({
            'fee_type': 'fixed', 'fee_amount': fee_amount, 'fee_charged_before_disbursement': True,
            'account_commission_credit_id': self.savings_fee_account.id,
            'account_fee_receivable_id': receivable.id,
            'fee_journal_id': self.savings_deposit_journal.id,   # cash, default_account_id = bank_account
            'fee_engagement_journal_id': od_journal.id,
        })
        return receivable

    def _approved_loan_fee_sent(self, **kwargs):
        loan = self._approve_loan_not_disbursed(**kwargs)
        loan.action_send_fee_to_cashier()
        return loan

    def test_pure_cashier_frais_dossier_end_to_end(self):
        self._setup_fee_product(fee_amount=30.0)
        loan = self._approved_loan_fee_sent(loan_amount=1000.0, term=3)
        self.assertFalse(loan.fee_paid)
        session = self._open_session(self.savings_deposit_journal)
        cashier = self._pure_cashier()
        mouvement = self._cashier_mouvement(cashier).register_operation(
            session.id, 'frais_dossier', self.partner.id, 0.0, False, loan.id,
        )
        self.assertEqual(mouvement.type, 'frais_dossier')
        self.assertEqual(mouvement.loan_id, loan)
        self.assertTrue(loan.fee_paid)
        self.assertTrue(loan.fee_move_id)
        self.assertEqual(mouvement.fee_move_id, loan.fee_move_id)
        self.assertEqual(mouvement.fee_move_id.state, 'posted')
        self.assertAlmostEqual(mouvement.amount, 30.0, places=2)
        self.assertEqual(loan.fee_payment_state, 'paid')

    def test_frais_dossier_blocked_if_not_sent(self):
        self._setup_fee_product()
        loan = self._approve_loan_not_disbursed(loan_amount=1000.0, term=3)  # PAS d'envoi en caisse
        session = self._open_session(self.savings_deposit_journal)
        cashier = self._pure_cashier()
        with self.assertRaises(UserError):
            self._cashier_mouvement(cashier).register_operation(
                session.id, 'frais_dossier', self.partner.id, 0.0, False, loan.id,
            )
        self.assertFalse(loan.fee_paid)

    def test_frais_dossier_double_call_no_double_move(self):
        self._setup_fee_product(fee_amount=30.0)
        loan = self._approved_loan_fee_sent(loan_amount=1000.0, term=3)
        session = self._open_session(self.savings_deposit_journal)
        cashier = self._pure_cashier()
        self._cashier_mouvement(cashier).register_operation(
            session.id, 'frais_dossier', self.partner.id, 0.0, False, loan.id,
        )
        first_move = loan.fee_move_id
        self.assertTrue(first_move)
        with self.assertRaises(UserError):
            self._cashier_mouvement(cashier).register_operation(
                session.id, 'frais_dossier', self.partner.id, 0.0, False, loan.id,
            )
        self.assertEqual(loan.fee_move_id, first_move)
        self.assertEqual(
            self.env['microfinance.caisse.mouvement'].search_count([
                ('loan_id', '=', loan.id), ('type', '=', 'frais_dossier'),
            ]), 1)

    def test_frais_dossier_cross_company_blocked(self):
        self._setup_fee_product()
        loan = self._approved_loan_fee_sent(loan_amount=1000.0, term=3)  # société courante
        other_company = self.env['res.company'].create({'name': 'Autre agence frais caisse', 'agency_code': 'FC1'})
        other_journal = self.env['account.journal'].create({
            'name': 'Caisse autre agence frais', 'code': 'FCOT', 'type': 'cash', 'company_id': other_company.id,
        })
        session = self.env['microfinance.caisse.session'].with_context(**self._NO_MAIL_CTX).create({
            'journal_id': other_journal.id, 'date': fields.Date.today(), 'company_id': other_company.id,
        })
        session.action_open_session()
        cashier = self._pure_cashier()
        cashier.company_ids = [(6, 0, [self.env.company.id, other_company.id])]
        with self.assertRaises(UserError):
            self._cashier_mouvement(cashier).register_operation(
                session.id, 'frais_dossier', self.partner.id, 0.0, False, loan.id,
            )
        self.assertFalse(loan.fee_paid)
