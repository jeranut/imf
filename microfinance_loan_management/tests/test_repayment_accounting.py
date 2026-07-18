# -*- coding: utf-8 -*-
from .common import MicrofinanceCommon


class TestRepaymentAccounting(MicrofinanceCommon):
    """Comptabilisation cash-basis d'un remboursement (Décision 3, _prepare_payment_move) :
    écriture générée uniquement à l'encaissement effectif (pas à la génération d'échéancier),
    montants proportionnels à la ventilation réelle (Lot 2), sur les comptes PCEC déjà
    configurables par produit (account_type, pas préfixe de code - mapping déjà en place,
    identique à celui utilisé pour le principal au décaissement)."""

    def _pay(self, loan, amount):
        payment = self.env['microfinance.loan.payment'].create({
            'loan_id': loan.id,
            'amount': amount,
            'journal_id': self.payment_journal.id,
        })
        payment.action_post()
        return payment

    def test_move_uses_configured_pcec_accounts_with_real_allocation(self):
        loan = self._activate_loan(loan_amount=900.0, term=3)
        first = loan.installment_ids.sorted('sequence')[0]
        first.write({'principal_amount': 100.0, 'interest_amount': 20.0, 'penalty_amount': 10.0})
        payment = self._pay(loan, first.total_amount)
        move = payment.move_id

        self.assertEqual(move.state, 'posted')
        self.assertEqual(move.company_id, loan.company_id)

        debit_line = move.line_ids.filtered(lambda l: l.debit > 0)
        self.assertEqual(debit_line.account_id, self.payment_journal.default_account_id)
        self.assertAlmostEqual(debit_line.debit, first.total_amount, places=2)

        principal_line = move.line_ids.filtered(lambda l: l.account_id == self.loan_account)
        self.assertAlmostEqual(principal_line.credit, 100.0, places=2)

        interest_line = move.line_ids.filtered(lambda l: l.account_id == self.interest_account)
        self.assertAlmostEqual(interest_line.credit, 20.0, places=2)

        penalty_line = move.line_ids.filtered(lambda l: l.account_id == self.penalty_account)
        self.assertAlmostEqual(penalty_line.credit, 10.0, places=2)

        self.assertAlmostEqual(sum(move.line_ids.mapped('credit')), sum(move.line_ids.mapped('debit')), places=2)

    def test_move_amounts_follow_real_allocation_not_theoretical_installment(self):
        # Cash-basis 1:1 avec la ventilation réelle (Décision 3) : un paiement partiel qui ne
        # touche que l'intérêt ne doit générer AUCUNE ligne principal/pénalité, même si
        # l'échéance en doit par ailleurs - pas de comptabilisation au montant théorique.
        loan = self._activate_loan(loan_amount=900.0, term=3)
        first = loan.installment_ids.sorted('sequence')[0]
        first.write({'principal_amount': 100.0, 'interest_amount': 30.0, 'penalty_amount': 20.0})
        payment = self._pay(loan, 25.0)  # < intérêt dû (30) : ne couvre que l'intérêt, partiellement
        move = payment.move_id

        interest_line = move.line_ids.filtered(lambda l: l.account_id == self.interest_account)
        self.assertAlmostEqual(interest_line.credit, 25.0, places=2)
        self.assertFalse(move.line_ids.filtered(lambda l: l.account_id == self.loan_account))
        self.assertFalse(move.line_ids.filtered(lambda l: l.account_id == self.penalty_account))
        self.assertEqual(len(move.line_ids), 2)  # caisse (débit) + intérêt (crédit) uniquement

    def test_move_generated_only_at_payment_not_at_schedule_generation(self):
        # Pas d'accrual : aucune écriture liée aux intérêts/pénalités tant qu'aucun remboursement
        # n'a été encaissé, même une fois le crédit décaissé et l'échéancier généré.
        loan = self._activate_loan(loan_amount=900.0, term=3)
        self.assertFalse(loan.payment_ids)
        moves_before = self.env['account.move'].search([('microfinance_loan_id', '=', loan.id)])
        # Seule l'écriture de décaissement existe à ce stade (comptabilisation du principal,
        # logique déjà en place et hors périmètre de ce lot).
        self.assertEqual(len(moves_before), 1)

    def test_repayment_move_isolated_to_loan_company(self):
        # Isolation multi-société : le journal et les comptes utilisés dans l'écriture de
        # remboursement doivent être ceux de l'agence du crédit, pas une valeur par défaut
        # globale - même agence que celle qui a décaissé le crédit.
        company_b = self.env['res.company'].create({'name': 'Agence B remboursement (test)', 'agency_code': 'RA1'})
        principal_account_b = self.env['account.account'].create({
            'name': 'Prets clients B (compta remboursement)', 'code': 'RBPRET', 'account_type': 'asset_current',
            'company_id': company_b.id,
        })
        interest_account_b = self.env['account.account'].create({
            'name': 'Interets B (compta remboursement)', 'code': 'RBINT', 'account_type': 'income',
            'company_id': company_b.id,
        })
        penalty_account_b = self.env['account.account'].create({
            'name': 'Penalites B (compta remboursement)', 'code': 'RBPEN', 'account_type': 'income',
            'company_id': company_b.id,
        })
        cash_account_b = self.env['account.account'].create({
            'name': 'Caisse B (compta remboursement)', 'code': 'RBCASH', 'account_type': 'asset_cash',
            'company_id': company_b.id,
        })
        journal_b = self.env['account.journal'].create({
            'name': 'Caisse remboursement B (compta remboursement)', 'code': 'RBDEC', 'type': 'cash',
            'company_id': company_b.id, 'default_account_id': cash_account_b.id,
        })
        product_b = self.env['microfinance.loan.product'].create({
            'name': 'Produit B (compta remboursement)', 'code': 'PRBACC', 'company_id': company_b.id,
            'min_amount': 100.0, 'max_amount': 100000.0, 'min_term': 1, 'max_term': 36,
            'interest_rate': 12.0, 'interest_method': 'flat', 'repayment_frequency_mode': 'fixed',
            'repayment_frequency_id': self.env.ref('microfinance_loan_management.repayment_frequency_monthly').id,
            'disbursement_journal_id': journal_b.id, 'payment_journal_id': journal_b.id,
            'account_principal_individuel_id': principal_account_b.id,
            'account_principal_groupe_id': principal_account_b.id,
            'account_interets_recus_individuel_id': interest_account_b.id,
            'account_interets_recus_groupe_id': interest_account_b.id,
            'account_penalites_id': penalty_account_b.id,
        })
        partner_b = self.env['res.partner'].create({'name': 'Client B (compta remboursement)'})
        loan_b = self.env['microfinance.loan'].with_context(microfinance_loan_creation_allowed=True).create({
            'partner_id': partner_b.id, 'product_id': product_b.id, 'company_id': company_b.id,
            'loan_amount': 900.0, 'term': 3,
        })
        loan_b.action_generate_schedule()
        loan_b.action_submit()
        loan_b.action_manager_validate()
        loan_b.action_finance_validate()
        loan_b.action_approve()
        loan_b.action_disburse()

        first_b = loan_b.installment_ids.sorted('sequence')[0]
        first_b.write({'principal_amount': 100.0, 'interest_amount': 20.0, 'penalty_amount': 10.0})
        payment_b = self.env['microfinance.loan.payment'].create({
            'loan_id': loan_b.id, 'amount': first_b.total_amount, 'journal_id': journal_b.id,
        })
        payment_b.action_post()
        move_b = payment_b.move_id

        self.assertEqual(move_b.company_id, company_b)
        self.assertEqual(move_b.journal_id, journal_b)
        self.assertTrue(move_b.line_ids.filtered(lambda l: l.account_id == principal_account_b))
        self.assertTrue(move_b.line_ids.filtered(lambda l: l.account_id == interest_account_b))
        self.assertTrue(move_b.line_ids.filtered(lambda l: l.account_id == penalty_account_b))
        # Aucune ligne ne doit référencer les comptes de l'agence par défaut (self.env.company).
        self.assertFalse(move_b.line_ids.filtered(lambda l: l.account_id == self.loan_account))
        self.assertFalse(move_b.line_ids.filtered(lambda l: l.account_id == self.interest_account))
        self.assertFalse(move_b.line_ids.filtered(lambda l: l.account_id == self.penalty_account))
