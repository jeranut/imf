# -*- coding: utf-8 -*-
"""Sous-lot E du découplage activation / décaissement (docs_dev/guichet_caisse/
AUDIT_decaissement.md §4) : verrou pessimiste dans action_process_disbursement contre le
double-décaissement concurrent (bouton fiche déprécié + guichet register_operation)."""
from odoo.exceptions import UserError

from .common import MicrofinanceCommon


class TestDisbursementConcurrentGuard(MicrofinanceCommon):

    def setUp(self):
        super().setUp()
        # Neutralise les fonds bailleurs actifs (cf. test_guichet_backend_lists) : sinon
        # action_activate() lève « Un fonds de crédit rotatif actif existe ».
        self.env['microfinance.fond.credit'].sudo().search([('active', '=', True)]).write({'active': False})

    def _disbursement_moves(self, loan):
        return self.env['account.move'].search([
            ('microfinance_loan_id', '=', loan.id),
            ('ref', '=like', 'Décaissement crédit%'),
        ])

    def test_second_process_disbursement_blocked_no_double_move(self):
        """Un vrai test multi-worker n'est pas réalisable dans TransactionCase (un second
        curseur ne voit pas les données non committées). On verrouille ici le filet garanti
        par le FOR UPDATE + invalidate_recordset : après un premier décaissement, toute
        ré-exécution échoue sur la garde disbursement_date (relue sous verrou) et ne crée
        AUCUNE seconde écriture."""
        loan = self._activate_loan_without_disbursement(loan_amount=1000.0, term=3)

        loan.action_process_disbursement()
        first_move = self._disbursement_moves(loan)
        self.assertEqual(len(first_move), 1)

        with self.assertRaises(UserError):
            loan.action_process_disbursement()
        self.assertEqual(len(self._disbursement_moves(loan)), 1,
                         "aucune seconde écriture de décaissement ne doit être créée")

    def test_process_disbursement_requires_active_state(self):
        loan = self._approve_loan(loan_amount=1000.0, term=3)  # encore 'approved'
        with self.assertRaises(UserError):
            loan.action_process_disbursement()
