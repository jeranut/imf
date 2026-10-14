# -*- coding: utf-8 -*-
"""Correctifs CAISSE (docs_dev/guichet_caisse/CORRECTIFS_CAISSE.md) : écart persisté à la
clôture, solde caisse (dépôt épargne / frais / retrait, comptes distincts ou coïncidents),
remboursement hors guichet refusé, une seule session ouverte par caissier.

Vit dans microfinance_savings_management : microfinance.caisse.mouvement n'existe pas côté
microfinance_loan_management (cf. docstring de test_caisse_session_theoretical_balance.py)."""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.addons.microfinance_loan_management.models.res_company import ResCompany
from odoo.addons.microfinance_loan_management.tests.common import MicrofinanceNoFundMixin

from .common import SavingsCommon


class TestCaisseCorrectifs(MicrofinanceNoFundMixin, SavingsCommon):

    def setUp(self):
        # MOWGLI a une société mère réelle qui bloque la neutralisation des fonds du mixin.
        self.patch(ResCompany, '_get_microfinance_parent', lambda rec: rec.browse())
        super().setUp()
        self.env['microfinance.caisse.denomination'].search([]).write({'active': False})
        self.d1000 = self.env['microfinance.caisse.denomination'].create({
            'name': 'Correctifs caisse test 1000', 'value': 1000.0,
            'currency_id': self.env.company.currency_id.id,
        })
        self.mouvement = self.env['microfinance.caisse.mouvement']

    # --- Outils ---

    def _open_session(self, journal=None, date=None, cashier=None):
        vals = {
            'journal_id': (journal or self.disbursement_journal).id,
            'date': date or fields.Date.today(),
        }
        if cashier:
            vals['cashier_id'] = cashier.id
        session = self.env['microfinance.caisse.session'].create(vals)
        session.action_open_session()
        return session

    def _cashier(self, login):
        return self.env['res.users'].create({
            'name': login, 'login': login,
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('microfinance_loan_management.group_microfinance_cashier').id,
            ])],
        })

    def _distinct_cash_journal(self, code):
        """Journal espèces dont le compte diffère du compte caisse de la session."""
        account = self.env['account.account'].create({
            'name': 'Compte distinct %s' % code, 'code': code,
            'account_type': 'asset_cash', 'company_id': self.env.company.id,
        })
        self.assertNotEqual(account, self.bank_account)
        return self.env['account.journal'].create({
            'name': 'Journal distinct %s' % code, 'code': code, 'type': 'cash',
            'company_id': self.env.company.id, 'default_account_id': account.id,
        })

    def _setup_fee_product(self, fee_journal, fee_amount=30.0):
        receivable = self.env['account.account'].create({
            'name': 'Frais à recevoir correctifs test', 'code': 'TFEERCCOR',
            'account_type': 'asset_current', 'reconcile': True, 'company_id': self.env.company.id,
        })
        od_journal = self.env['account.journal'].create({
            'name': 'OD frais correctifs test', 'code': 'TODFCOR', 'type': 'general',
            'company_id': self.env.company.id,
        })
        self.product.write({
            'fee_type': 'fixed', 'fee_amount': fee_amount, 'fee_charged_before_disbursement': True,
            'account_commission_credit_id': self.savings_fee_account.id,
            'account_fee_receivable_id': receivable.id,
            'fee_journal_id': fee_journal.id,
            'fee_engagement_journal_id': od_journal.id,
        })

    def _loan_fee_sent(self):
        loan = self._create_loan(loan_amount=1000.0, term=3)
        loan.action_generate_schedule()
        loan.action_start_enquete()
        loan.action_ca_review()
        loan.action_cdag_review()
        loan.action_view_applications()
        loan.application_ids.write({'committee_first_decision': 'accepted'})
        loan.action_approve()
        loan.action_send_fee_to_cashier()
        return loan

    def _balance(self, session):
        session.invalidate_recordset(['theoretical_balance'])
        return session.theoretical_balance

    # --- A. Écart persisté à la clôture ---

    def test_ecart_et_motif_persistes_avant_cloture(self):
        session = self._open_session()
        account = self._create_active_account(opening_amount=0.0)
        self.mouvement.register_operation(session.id, 'depot_epargne', self.partner.id, 1500.0, account.id, False)
        wizard = self.env['microfinance.caisse.close.session.wizard'].with_context(
            default_session_id=session.id).create({})
        wizard.line_ids.filtered(lambda l: l.denomination_id == self.d1000).quantity = 1
        recap = self.env['microfinance.caisse.close.session.recap.wizard'].browse(
            wizard.action_confirm_count()['res_id'])
        variance = self.env['microfinance.caisse.close.session.variance.wizard'].browse(
            recap.action_confirm_recap()['res_id'])
        variance.variance_comment = 'Billet déchiré remis au client.'
        variance.action_confirm_close()

        self.assertEqual(session.state, 'closed')
        comptage = self.env['microfinance.caisse.comptage'].search([('session_id', '=', session.id)])
        self.assertEqual(len(comptage), 1)
        self.assertEqual(comptage.counted_total, 1000.0)
        self.assertEqual(comptage.theoretical_total, 1500.0)
        self.assertEqual(comptage.variance, -500.0)
        self.assertEqual(comptage.variance_comment, 'Billet déchiré remis au client.')
        self.assertEqual(comptage.line_ids.denomination_id, self.d1000)
        # Écart autorisé sans approbation manager : écriture en attente, pas de blocage.
        self.assertEqual(comptage.variance_state, 'en_attente')

    # --- B. Solde caisse ---

    def test_solde_depot_frais_retrait_comptes_distincts(self):
        dep_journal = self._distinct_cash_journal('TDEPD')
        wd_journal = self._distinct_cash_journal('TWDRD')
        fee_journal = self._distinct_cash_journal('TFEED')
        self.savings_product.write({
            'deposit_journal_id': dep_journal.id, 'withdrawal_journal_id': wd_journal.id})
        self._setup_fee_product(fee_journal)
        loan = self._loan_fee_sent()
        account = self._create_active_account(opening_amount=1000.0)
        session = self._open_session()
        self.mouvement.register_operation(session.id, 'depot_epargne', self.partner.id, 50000.0, account.id, False)
        self.mouvement.register_operation(session.id, 'frais_dossier', self.partner.id, 0.0, False, loan.id)
        self.mouvement.register_operation(session.id, 'retrait_epargne', self.partner.id, 200.0, account.id, False)
        fee = sum(session.mouvement_ids.filtered(lambda m: m.type == 'frais_dossier').mapped('amount'))
        self.assertEqual(fee, 30.0)
        self.assertAlmostEqual(self._balance(session), 50000.0 + 30.0 - 200.0, places=2)

    def test_solde_depot_frais_retrait_comptes_coincidents_sans_double_comptage(self):
        # Journaux épargne et frais = compte caisse de la session (SavingsCommon par défaut).
        self.assertEqual(self.savings_deposit_journal.default_account_id, self.bank_account)
        self._setup_fee_product(self.savings_deposit_journal)
        loan = self._loan_fee_sent()
        account = self._create_active_account(opening_amount=1000.0)
        session = self._open_session()
        self.mouvement.register_operation(session.id, 'depot_epargne', self.partner.id, 50000.0, account.id, False)
        self.mouvement.register_operation(session.id, 'frais_dossier', self.partner.id, 0.0, False, loan.id)
        self.mouvement.register_operation(session.id, 'retrait_epargne', self.partner.id, 200.0, account.id, False)
        self.assertAlmostEqual(self._balance(session), 50000.0 + 30.0 - 200.0, places=2)

    def test_solde_guichet_egal_total_du_ticket(self):
        """Le « Solde caisse » du guichet (theoretical_balance) = ouverture + total du ticket
        (entrées − sorties des mouvements espèces) : même total dans les deux affichages."""
        account = self._create_active_account(opening_amount=1000.0)
        session = self._open_session()
        self.mouvement.register_operation(session.id, 'depot_epargne', self.partner.id, 700.0, account.id, False)
        self.mouvement.register_operation(session.id, 'retrait_epargne', self.partner.id, 100.0, account.id, False)
        ticket = sum(
            m.amount if m.type in ('depot_epargne', 'remboursement_credit', 'frais_dossier') else -m.amount
            for m in session.mouvement_ids)
        self.assertAlmostEqual(self._balance(session), session.opening_balance + ticket, places=2)

    def test_remboursement_compte_coincident_compte_une_fois(self):
        # Journal de remboursement du guichet = journal de la session : l'écriture touche le
        # compte caisse, elle est lue dans le grand livre et PAS une seconde fois par montant.
        loan = self._activate_loan(loan_amount=900.0, term=3)
        session = self._open_session()
        self.mouvement.register_operation(session.id, 'remboursement_credit', self.partner.id, 100.0, False, loan.id)
        self.assertAlmostEqual(self._balance(session), 100.0, places=2)

    def test_decaissement_especes_sur_journal_distinct_compte_par_montant(self):
        # Espèces décaissées depuis un AUTRE journal de caisse que celui de la session : aucune
        # ligne sur le compte de la session, donc compté par mouvement.amount (net décaissé).
        other_cash = self._distinct_cash_journal('TDECD')
        self._neutralize_loan_funds()
        loan = self._approve_not_disbursed()
        session = self._open_session()
        self.mouvement.register_operation(
            session.id, 'decaissement_credit', self.partner.id, loan.loan_amount, False, loan.id,
            journal_id=other_cash.id, payment_method='cash')
        self.assertAlmostEqual(self._balance(session), -loan.net_disbursed_amount, places=2)

    def test_decaissement_virement_jamais_compte_en_especes(self):
        bank_account = self.env['account.account'].create({
            'name': 'Banque virement correctifs', 'code': 'TBKVCOR',
            'account_type': 'asset_cash', 'company_id': self.env.company.id,
        })
        bank_journal = self.env['account.journal'].create({
            'name': 'Banque virement correctifs', 'code': 'TBKVC', 'type': 'bank',
            'company_id': self.env.company.id, 'default_account_id': bank_account.id,
        })
        self._neutralize_loan_funds()
        loan = self._approve_not_disbursed()
        session = self._open_session()
        self.mouvement.register_operation(
            session.id, 'decaissement_credit', self.partner.id, loan.loan_amount, False, loan.id,
            journal_id=bank_journal.id, payment_method='bank_transfer')
        self.assertAlmostEqual(self._balance(session), 0.0, places=2)

    def _neutralize_loan_funds(self):
        self.env['microfinance.fond.credit'].sudo().search([('active', '=', True)]).write({'active': False})

    def _approve_not_disbursed(self):
        loan = self._create_loan(loan_amount=500.0, term=3)
        loan.action_generate_schedule()
        loan.action_start_enquete()
        loan.action_ca_review()
        loan.action_cdag_review()
        loan.action_view_applications()
        loan.application_ids.write({'committee_first_decision': 'accepted'})
        loan.action_approve()
        loan._activate_with_auto_confirm()
        return loan

    # --- C.1 Remboursement hors guichet ---

    def test_remboursement_hors_guichet_refuse_cote_serveur(self):
        loan = self._activate_loan(loan_amount=900.0, term=3)
        with self.assertRaises(UserError):
            loan.action_open_payment_wizard()
        wizard = self.env['microfinance.loan.payment.wizard'].create({
            'loan_id': loan.id, 'amount': 100.0, 'journal_id': self.disbursement_journal.id})
        with self.assertRaises(UserError):
            wizard.action_create_payment()

    def test_bouton_remboursement_absent_de_la_fiche_credit(self):
        arch = self.env['microfinance.loan'].get_view(view_type='form')['arch']
        self.assertNotIn('action_open_payment_wizard', arch)
        self.assertNotIn('Enregistrer remboursement', arch)

    # --- C.2 Sessions multiples ---

    def test_deuxieme_session_meme_caissier_refusee(self):
        self._open_session(date=fields.Date.today() - timedelta(days=2))
        with self.assertRaises(UserError):
            self._open_session()

    def test_creation_directe_session_open_meme_caissier_refusee(self):
        self._open_session(date=fields.Date.today() - timedelta(days=2))
        with self.assertRaises(UserError):
            self.env['microfinance.caisse.session'].create({
                'journal_id': self.disbursement_journal.id, 'date': fields.Date.today(),
                'state': 'open'})

    def test_autre_caissier_peut_ouvrir_sa_session(self):
        self._open_session(date=fields.Date.today() - timedelta(days=2))
        other = self._cashier('autre_caissier_correctifs_test')
        session = self._open_session(cashier=other)
        self.assertEqual(session.state, 'open')
