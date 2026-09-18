# -*- coding: utf-8 -*-
"""session.theoretical_balance (défini dans microfinance_loan_management) : calcul du solde
théorique de la session de caisse depuis SES PROPRES mouvements (microfinance.caisse.mouvement),
pas depuis le journal comptable de la journée entière (fiche_journee) — cf.
AUDIT_session_zigzag §7 pt 4. microfinance.caisse.mouvement vit dans ce module
(microfinance_savings_management), chargé après microfinance_loan_management à l'installation :
ces tests sont donc ici, où le modèle est garanti disponible. Une tentative équivalente dans
microfinance_loan_management/tests/ échouerait toujours avec
KeyError('microfinance.caisse.mouvement'), quel que soit l'état d'installation final de la base,
puisque les tests d'un module s'exécutent dès la fin de son propre chargement, avant celui des
modules qui en dépendent (cf. docstring de test_caisse_close_wizard.py côté loan_management)."""
from odoo import fields

from .common import SavingsCommon


class TestCaisseSessionTheoreticalBalance(SavingsCommon):

    def _open_session(self, journal=None):
        session = self.env['microfinance.caisse.session'].create({
            'journal_id': (journal or self.disbursement_journal).id, 'date': fields.Date.today(),
        })
        session.action_open_session()
        return session

    def _neutralize_funds(self):
        # Cette base (MOWGLI) a un microfinance.fond.credit actif pour la société : sans
        # fond_credit_id sur le crédit, action_activate()/action_disburse() lève « Un fonds de
        # crédit rotatif actif existe pour cette agence » (_check_fond_disponibilite). Désactivé
        # le temps du test (TransactionCase => rollback), même pattern que TestCaisseRegisterOperation
        # dans test_caisse_pos.py.
        self.env['microfinance.fond.credit'].sudo().search([('active', '=', True)]).write({'active': False})

    def _approve_loan_not_disbursed(self, **kwargs):
        self._neutralize_funds()
        loan = self._create_loan(**kwargs)
        loan.action_generate_schedule()
        loan.action_start_enquete()
        loan.action_ca_review()
        loan.action_cdag_review()
        loan.action_view_applications()
        loan.application_ids.write({'committee_first_decision': 'accepted'})
        loan.action_approve()
        return loan

    def test_theoretical_balance_zero_with_no_movements(self):
        session = self._open_session()
        self.assertEqual(session.theoretical_balance, 0.0)

    def test_theoretical_balance_reflects_cash_deposit(self):
        account = self._create_active_account(opening_amount=0.0)
        session = self._open_session()
        self.env['microfinance.caisse.mouvement'].register_operation(
            session.id, 'depot_epargne', self.partner.id, 300.0, account.id, False,
        )
        session.invalidate_recordset(['theoretical_balance'])
        self.assertAlmostEqual(session.theoretical_balance, 300.0, places=2)

    def test_theoretical_balance_reflects_cash_withdrawal(self):
        account = self._create_active_account(opening_amount=500.0)
        session = self._open_session()
        self.env['microfinance.caisse.mouvement'].register_operation(
            session.id, 'retrait_epargne', self.partner.id, 200.0, account.id, False,
        )
        session.invalidate_recordset(['theoretical_balance'])
        self.assertAlmostEqual(session.theoretical_balance, -200.0, places=2)

    def test_theoretical_balance_nets_deposit_and_withdrawal(self):
        account = self._create_active_account(opening_amount=0.0)
        session = self._open_session()
        self.env['microfinance.caisse.mouvement'].register_operation(
            session.id, 'depot_epargne', self.partner.id, 300.0, account.id, False,
        )
        self.env['microfinance.caisse.mouvement'].register_operation(
            session.id, 'retrait_epargne', self.partner.id, 120.0, account.id, False,
        )
        session.invalidate_recordset(['theoretical_balance'])
        self.assertAlmostEqual(session.theoretical_balance, 180.0, places=2)

    def test_theoretical_balance_reflects_cash_decaissement(self):
        loan = self._approve_loan_not_disbursed(loan_amount=500.0, term=3)
        loan.action_activate()
        session = self._open_session()
        self.env['microfinance.caisse.mouvement'].register_operation(
            session.id, 'decaissement_credit', self.partner.id, loan.loan_amount, False, loan.id,
        )
        session.invalidate_recordset(['theoretical_balance'])
        self.assertAlmostEqual(session.theoretical_balance, -loan.net_disbursed_amount, places=2)

    def test_theoretical_balance_ignores_bank_settled_decaissement(self):
        # Décaissement réglé par virement (journal 'bank') : impacte le compte de ce journal,
        # pas le compte caisse de la session -> ne doit pas réduire le théorique ESPÈCES, sans
        # qu'il soit nécessaire de retracer le moyen de paiement choisi au guichet (cf.
        # session._compute_theoretical_balance, filtrage account_id).
        bank_account = self.env['account.account'].create({
            'name': 'Banque test théorique', 'code': 'TBANKTHEO',
            'account_type': 'asset_cash', 'company_id': self.env.company.id,
        })
        alt_journal = self.env['account.journal'].create({
            'name': 'Journal bancaire test théorique', 'code': 'TBKTHEO', 'type': 'bank',
            'company_id': self.env.company.id, 'default_account_id': bank_account.id,
        })
        loan = self._approve_loan_not_disbursed(loan_amount=500.0, term=3)
        loan.action_activate()
        session = self._open_session()
        self.env['microfinance.caisse.mouvement'].register_operation(
            session.id, 'decaissement_credit', self.partner.id, loan.loan_amount, False, loan.id,
            journal_id=alt_journal.id, payment_method='bank_transfer',
        )
        session.invalidate_recordset(['theoretical_balance'])
        self.assertEqual(session.theoretical_balance, 0.0)

    def test_theoretical_balance_ignores_postings_unrelated_to_session(self):
        # Une écriture comptable sur le compte caisse SANS microfinance.caisse.mouvement
        # rattaché à la session ne doit pas compter (c'était le comportement de l'ancien
        # closing_balance, related fiche_journee, corrigé par ce lot).
        session = self._open_session()
        counterpart = self.env['account.account'].create({
            'name': 'Contrepartie test théorique', 'code': 'TCPTHEO',
            'account_type': 'equity', 'company_id': self.env.company.id,
        })
        move = self.env['account.move'].create({
            'date': fields.Date.today(), 'journal_id': self.disbursement_journal.id,
            'line_ids': [
                (0, 0, {'account_id': self.bank_account.id, 'debit': 500.0, 'credit': 0.0}),
                (0, 0, {'account_id': counterpart.id, 'debit': 0.0, 'credit': 500.0}),
            ],
        })
        move.action_post()
        session.invalidate_recordset(['theoretical_balance'])
        self.assertEqual(session.theoretical_balance, 0.0)

    # Le calcul du théorique à travers le wizard de clôture en 3 temps (Comptage ->
    # Récapitulatif -> Écart) est testé end-to-end dans test_caisse_close_wizard_confirm.py :
    # theoretical_total n'existe plus sur le wizard de comptage (temps 1) et n'est calculé
    # qu'à la confirmation du récapitulatif (temps 2 -> 3), cf. AUDIT_session_close_3temps.
