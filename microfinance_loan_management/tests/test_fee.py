# -*- coding: utf-8 -*-
from odoo.exceptions import UserError

from .common import MicrofinanceCommon


class TestFee(MicrofinanceCommon):

    def setUp(self):
        super().setUp()
        self.fee_account = self.env['account.account'].create({
            'name': 'Frais de dossier test', 'code': 'TFEE', 'account_type': 'income_other', 'company_id': self.env.company.id,
        })
        # Flux Option A (docs_dev/frais_dossier_creance_pcec/) : compte de créance
        # "frais à recevoir" (reconcile=True pour le lettrage engagement<->règlement) +
        # journal d'opérations diverses pour l'écriture d'engagement.
        self.fee_receivable_account = self.env['account.account'].create({
            'name': 'Frais de dossier à recevoir test', 'code': 'TFEER',
            'account_type': 'asset_current', 'reconcile': True, 'company_id': self.env.company.id,
        })
        self.od_journal = self.env['account.journal'].create({
            'name': 'Opérations diverses test', 'code': 'TOD', 'type': 'general',
            'company_id': self.env.company.id,
        })
        self.product.write({
            'account_commission_credit_id': self.fee_account.id,
            'account_fee_receivable_id': self.fee_receivable_account.id,
            'fee_journal_id': self.disbursement_journal.id,
            'fee_engagement_journal_id': self.od_journal.id,
        })

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

    def test_fee_amount_fixed(self):
        self.product.write({'fee_type': 'fixed', 'fee_amount': 25.0})
        loan = self._create_loan(loan_amount=1000.0)
        self.assertEqual(loan.fee_amount_due, 25.0)

    def test_fee_amount_percentage(self):
        self.product.write({'fee_type': 'percentage', 'fee_rate': 2.0})
        loan = self._create_loan(loan_amount=1000.0)
        self.assertEqual(loan.fee_amount_due, 20.0)

    def test_fee_payment_state_badge(self):
        """État frais dérivé pour le badge (docs_dev/badges_fee_guarantee/) :
        'none' sans frais, 'unpaid' frais dus non encaissés, 'paid' après encaissement."""
        self.product.write({'fee_type': 'fixed', 'fee_amount': 0.0})
        no_fee_loan = self._create_loan(loan_amount=1000.0)
        self.assertEqual(no_fee_loan.fee_payment_state, 'none')

        self.product.write({'fee_type': 'fixed', 'fee_amount': 25.0, 'fee_charged_before_disbursement': True})
        loan = self._approve_loan(loan_amount=1000.0, term=3)
        self.assertEqual(loan.fee_payment_state, 'unpaid')

        loan.action_charge_fee()
        self.assertEqual(loan.fee_payment_state, 'paid')

    def test_disburse_blocked_when_fee_unpaid_and_required(self):
        self.product.write({'fee_type': 'fixed', 'fee_amount': 25.0, 'fee_charged_before_disbursement': True})
        loan = self._approve_loan(loan_amount=1000.0, term=3)
        with self.assertRaises(UserError):
            loan.action_disburse()

    def test_disburse_allowed_when_fee_not_required(self):
        self.product.write({'fee_type': 'fixed', 'fee_amount': 25.0, 'fee_charged_before_disbursement': False})
        loan = self._approve_loan(loan_amount=1000.0, term=3)
        loan.action_disburse()
        self.assertEqual(loan.state, 'active')

    def test_charge_fee_generates_move_and_unblocks_disbursement(self):
        self.product.write({'fee_type': 'fixed', 'fee_amount': 25.0, 'fee_charged_before_disbursement': True})
        loan = self._approve_loan(loan_amount=1000.0, term=3)

        # Écriture d'engagement créée à l'approbation : débit créance / crédit produit (717003).
        self.assertTrue(loan.fee_receivable_move_id)
        self.assertEqual(loan.fee_receivable_move_id.state, 'posted')
        eng_debit = loan.fee_receivable_move_id.line_ids.filtered(lambda l: l.debit > 0)
        eng_credit = loan.fee_receivable_move_id.line_ids.filtered(lambda l: l.credit > 0)
        self.assertEqual(eng_debit.account_id, self.fee_receivable_account)
        self.assertEqual(eng_credit.account_id, self.fee_account)
        self.assertEqual(sum(eng_debit.mapped('debit')), 25.0)

        loan.action_charge_fee()

        # Écriture de règlement : débit caisse / crédit créance (solde), le produit ayant déjà
        # été constaté à l'engagement.
        self.assertTrue(loan.fee_paid)
        self.assertTrue(loan.fee_move_id)
        self.assertEqual(loan.fee_move_id.state, 'posted')
        debit_lines = loan.fee_move_id.line_ids.filtered(lambda l: l.debit > 0)
        credit_lines = loan.fee_move_id.line_ids.filtered(lambda l: l.credit > 0)
        self.assertEqual(sum(debit_lines.mapped('debit')), 25.0)
        self.assertEqual(credit_lines.account_id, self.fee_receivable_account)

        # La créance est soldée : compte 208005 lettré des deux côtés, solde net nul.
        receivable_lines = (loan.fee_receivable_move_id.line_ids + loan.fee_move_id.line_ids).filtered(
            lambda l: l.account_id == self.fee_receivable_account)
        self.assertTrue(all(receivable_lines.mapped('reconciled')))
        self.assertEqual(sum(receivable_lines.mapped('balance')), 0.0)

        loan.action_disburse()
        self.assertEqual(loan.state, 'active')

    def test_fee_engagement_skipped_when_fee_netted(self):
        """Mode « frais nettés du décaissement » (fee_charged_before_disbursement=False,
        décision Micka Q5/issue 1) : aucune écriture d'engagement à l'approbation, les frais
        restent comptabilisés dans l'écriture de décaissement."""
        self.product.write({'fee_type': 'fixed', 'fee_amount': 25.0, 'fee_charged_before_disbursement': False})
        loan = self._approve_loan(loan_amount=1000.0, term=3)
        self.assertFalse(loan.fee_receivable_move_id)

    def test_charge_fee_retrofits_missing_engagement(self):
        """Dossier approuvé AVANT config du produit pour le flux Option A : l'engagement
        n'existe pas à l'encaissement. action_charge_fee doit le créer à la volée, puis le
        solder - la créance 208005 est donc bien mouvementée et lettrée."""
        self.product.write({'fee_type': 'fixed', 'fee_amount': 25.0, 'fee_charged_before_disbursement': True})
        loan = self._approve_loan(loan_amount=1000.0, term=3)
        # Simule un dossier antérieur au flux : on retire l'engagement créé à l'approbation.
        loan.fee_receivable_move_id.button_draft()
        loan.fee_receivable_move_id.unlink()
        loan.fee_receivable_move_id = False

        loan.action_charge_fee()

        self.assertTrue(loan.fee_receivable_move_id, "engagement créé en rattrapage à l'encaissement")
        self.assertEqual(loan.fee_receivable_move_id.state, 'posted')
        credit_lines = loan.fee_move_id.line_ids.filtered(lambda l: l.credit > 0)
        self.assertEqual(credit_lines.account_id, self.fee_receivable_account)
        receivable_lines = (loan.fee_receivable_move_id.line_ids + loan.fee_move_id.line_ids).filtered(
            lambda l: l.account_id == self.fee_receivable_account)
        self.assertTrue(all(receivable_lines.mapped('reconciled')))

    def test_fee_settlement_falls_back_to_commission_when_product_unconfigured(self):
        """Repli : si l'engagement n'existe pas ET que le produit n'a pas de compte de créance
        configuré, le règlement crédite le compte de commission (717003), comportement
        historique - l'encaissement ne doit jamais être bloqué."""
        self.product.write({
            'fee_type': 'fixed', 'fee_amount': 25.0, 'fee_charged_before_disbursement': True,
            'account_fee_receivable_id': False, 'fee_engagement_journal_id': False,
        })
        loan = self._approve_loan(loan_amount=1000.0, term=3)
        self.assertFalse(loan.fee_receivable_move_id)

        loan.action_charge_fee()

        self.assertFalse(loan.fee_receivable_move_id)
        credit_lines = loan.fee_move_id.line_ids.filtered(lambda l: l.credit > 0)
        self.assertEqual(credit_lines.account_id, self.fee_account)

    def test_charge_fee_twice_blocked(self):
        self.product.write({'fee_type': 'fixed', 'fee_amount': 25.0})
        loan = self._approve_loan(loan_amount=1000.0, term=3)
        loan.action_charge_fee()
        with self.assertRaises(UserError):
            loan.action_charge_fee()

    def test_charge_fee_concurrent_guard_no_double_move(self):
        """Verrou anti double-comptabilisation, docs_dev/refactor_frais_dossier_account_move/
        (Lot 1). Un vrai test multi-worker n'est pas réalisable proprement dans
        TransactionCase : un second curseur ouvre sa propre transaction et ne voit pas les
        données non committées du test (produit, partenaire, crédit), il ne peut donc pas
        cibler le même loan pour provoquer la course réelle. On verrouille ici le filet
        fonctionnel garanti par le FOR UPDATE + invalidate_recordset : après un premier
        encaissement, toute ré-exécution de action_charge_fee sur le même dossier échoue sur
        la garde fee_paid (désormais relue sous verrou) et ne crée AUCUNE seconde écriture."""
        self.product.write({'fee_type': 'fixed', 'fee_amount': 25.0})
        loan = self._approve_loan(loan_amount=1000.0, term=3)

        loan.action_charge_fee()
        first_move = loan.fee_move_id
        self.assertTrue(first_move)

        def _fee_moves():
            return self.env['account.move'].search([
                ('microfinance_loan_id', '=', loan.id),
                ('ref', '=like', 'Frais de dossier crédit%'),
            ])

        self.assertEqual(len(_fee_moves()), 1)
        with self.assertRaises(UserError):
            loan.action_charge_fee()
        self.assertEqual(len(_fee_moves()), 1, 'aucune seconde écriture de frais ne doit être créée')
        self.assertEqual(loan.fee_move_id, first_move, 'fee_move_id reste sur la première écriture')

    def test_net_disbursed_amount_equals_loan_amount_when_fee_charged_separately(self):
        self.product.write({'fee_type': 'fixed', 'fee_amount': 25.0, 'fee_charged_before_disbursement': True})
        loan = self._create_loan(loan_amount=1000.0)
        self.assertEqual(loan.net_disbursed_amount, 1000.0)

    def test_disburse_nets_fee_in_single_move(self):
        self.product.write({'fee_type': 'fixed', 'fee_amount': 25.0, 'fee_charged_before_disbursement': False})
        loan = self._approve_loan(loan_amount=1000.0, term=3)

        self.assertEqual(loan.net_disbursed_amount, 975.0)
        loan.action_disburse()

        move = loan.move_ids
        self.assertEqual(len(move), 1)
        debit_lines = move.line_ids.filtered(lambda l: l.debit > 0)
        self.assertEqual(sum(debit_lines.mapped('debit')), 1000.0)
        self.assertEqual(debit_lines.account_id, self.loan_account)
        fee_line = move.line_ids.filtered(lambda l: l.account_id == self.fee_account)
        self.assertEqual(fee_line.credit, 25.0)
        cash_line = move.line_ids.filtered(lambda l: l.account_id == self.bank_account)
        self.assertEqual(cash_line.credit, 975.0)
        # Le capital dû reste plein : le client rembourse 1000, pas 975. balance_total inclut
        # les intérêts de l'échéancier (résiduel = principal + intérêt + pénalité - payé) et ne
        # convient donc pas à cette vérification pour un prêt à terme > 1 : on compare la somme
        # des seuls principal_amount des échéances, qui reste indépendante du nettage des frais.
        self.assertEqual(sum(loan.installment_ids.mapped('principal_amount')), 1000.0)

    def test_fee_frozen_from_approval(self):
        """Un changement du taux de frais sur le produit ne bouge pas les frais dus
        d'un dossier déjà approuvé ; seuls les nouveaux dossiers héritent du nouveau taux
        (docs_dev/product_fee/AUDIT.md point 5)."""
        self.product.write({'fee_type': 'percentage', 'fee_rate': 5.0})
        approved = self._approve_loan(loan_amount=1000.0, term=3)
        self.assertEqual(approved.fee_amount_due, 50.0)

        editable = self._create_loan(loan_amount=1000.0)
        self.assertEqual(editable.state, 'draft')

        self.product.write({'fee_rate': 3.0})
        approved.invalidate_recordset(['fee_amount_due'])
        editable.invalidate_recordset(['fee_amount_due'])

        # dossier approuvé : figé sur l'ancienne valeur
        self.assertEqual(approved.fee_amount_due, 50.0)
        # dossier encore modifiable : suit le nouveau taux
        self.assertEqual(editable.fee_amount_due, 30.0)
        # nouveau dossier créé après le changement : nouveau taux
        new_loan = self._create_loan(loan_amount=1000.0)
        self.assertEqual(new_loan.fee_amount_due, 30.0)
