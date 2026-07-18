# -*- coding: utf-8 -*-
from datetime import timedelta

from .common import MicrofinanceCommon


class TestLoanProgressiveProgram(MicrofinanceCommon):
    """Programmes progressifs (prêts successifs par palier) : calcul d'éligibilité
    purement informatif sur microfinance.loan.application (progressive_eligibility_status/
    _message), jamais bloquant — _check_eligibility() sur microfinance.loan n'est jamais
    touché par ce champ."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # cls.product (hérité de MicrofinanceCommon) sert de produit d'étape 2 ; un second
        # produit dédié sert d'étape 1 du programme.
        cls.product_step1 = cls.env['microfinance.loan.product'].create({
            'name': 'Prêt initial (test programme progressif)', 'code': 'PPROG1',
            'min_amount': 100.0, 'max_amount': 100000.0, 'min_term': 1, 'max_term': 36,
            'interest_rate': 12.0, 'interest_method': 'flat', 'installment_rounding_unit': 0,
            'repayment_frequency_mode': 'fixed',
            'repayment_frequency_id': cls.env.ref('microfinance_loan_management.repayment_frequency_monthly').id,
            'disbursement_journal_id': cls.disbursement_journal.id, 'payment_journal_id': cls.payment_journal.id,
            'account_principal_individuel_id': cls.loan_account.id,
            'account_principal_groupe_id': cls.loan_account_groupe.id,
            'account_interets_recus_individuel_id': cls.interest_account.id,
            'account_interets_recus_groupe_id': cls.interest_account_groupe.id,
            'account_penalites_id': cls.penalty_account.id,
        })
        cls.program = cls.env['microfinance.loan.progressive.program'].create({
            'name': 'Programme test',
            'step_ids': [
                (0, 0, {
                    'sequence_number': 1, 'product_id': cls.product_step1.id,
                    'late_tolerance_days': 7, 'late_tolerance_amount_percent': 5.0,
                }),
                (0, 0, {
                    'sequence_number': 2, 'product_id': cls.product.id,
                    'late_tolerance_days': 7, 'late_tolerance_amount_percent': 5.0,
                }),
            ],
        })

    def _create_application(self, **kwargs):
        vals = {'partner_id': self.partner.id, 'loan_product_id': self.product.id}
        vals.update(kwargs)
        return self.env['microfinance.loan.application'].create(vals)

    def _close_loan_without_arrears(self, **kwargs):
        loan = self._create_loan(product_id=self.product_step1.id, **kwargs)
        loan.action_generate_schedule()
        for inst in loan.installment_ids:
            inst.write({
                'paid_principal': inst.principal_amount,
                'paid_interest': inst.interest_amount,
                'paid_penalty': inst.penalty_amount,
            })
        loan.action_close()
        return loan

    def test_independent_product_not_applicable(self):
        """Produit indépendant (hors programme progressif) : non applicable."""
        independent_product = self.env['microfinance.loan.product'].create({
            'name': 'Produit indépendant (test)', 'code': 'PINDEP',
            'min_amount': 100.0, 'max_amount': 100000.0, 'min_term': 1, 'max_term': 36,
            'interest_rate': 12.0, 'interest_method': 'flat', 'repayment_frequency_mode': 'fixed',
            'repayment_frequency_id': self.env.ref('microfinance_loan_management.repayment_frequency_monthly').id,
            'disbursement_journal_id': self.disbursement_journal.id, 'payment_journal_id': self.payment_journal.id,
            'account_principal_individuel_id': self.loan_account.id,
            'account_principal_groupe_id': self.loan_account_groupe.id,
            'account_interets_recus_individuel_id': self.interest_account.id,
            'account_interets_recus_groupe_id': self.interest_account_groupe.id,
        })
        application = self._create_application(loan_product_id=independent_product.id)
        self.assertEqual(application.progressive_eligibility_status, 'not_applicable')
        self.assertFalse(application.progressive_eligibility_message)

    def test_first_step_not_applicable(self):
        """Produit en étape 1 d'un programme : pas de prêt précédent à vérifier."""
        application = self._create_application(loan_product_id=self.product_step1.id)
        self.assertEqual(application.progressive_eligibility_status, 'not_applicable')

    def test_no_prior_loan(self):
        """Étape 2, aucun prêt du client sur le produit d'étape 1."""
        application = self._create_application()
        self.assertEqual(application.progressive_eligibility_status, 'no_prior_loan')
        self.assertIn('prérequis', application.progressive_eligibility_message)

    def test_eligible_after_closed_loan_without_arrears(self):
        """Prêt précédent clôturé sans aucun retard : éligible."""
        self._close_loan_without_arrears()
        application = self._create_application()
        self.assertEqual(application.progressive_eligibility_status, 'eligible')

    def test_warning_after_closed_loan_with_late_payment(self):
        """Prêt précédent clôturé mais avec un retard hors tolérance (15 jours > 7 tolérés)."""
        loan = self._create_loan(product_id=self.product_step1.id)
        loan.action_generate_schedule()
        late_inst = loan.installment_ids[0]
        late_inst.write({
            'arrears_onset_date': late_inst.due_date,
            'arrears_cured_date': late_inst.due_date + timedelta(days=15),
        })
        for inst in loan.installment_ids:
            inst.write({
                'paid_principal': inst.principal_amount,
                'paid_interest': inst.interest_amount,
                'paid_penalty': inst.penalty_amount,
            })
        loan.action_close()
        application = self._create_application()
        self.assertEqual(application.progressive_eligibility_status, 'warning')
        self.assertIn('15', application.progressive_eligibility_message)

    def test_defaulted_prior_loan(self):
        """Prêt précédent radié : défaut."""
        loan = self._create_loan(product_id=self.product_step1.id)
        loan.write({'state': 'written_off'})
        application = self._create_application()
        self.assertEqual(application.progressive_eligibility_status, 'defaulted')

    def test_prior_active_loan_not_closed(self):
        """Prêt précédent existant mais pas encore clôturé."""
        self._create_loan(product_id=self.product_step1.id)  # reste en 'draft'
        application = self._create_application()
        self.assertEqual(application.progressive_eligibility_status, 'prior_active')

    def test_most_favorable_status_retained_among_multiple_loans(self):
        """Un prêt radié + un prêt clôturé sans retard sur le même produit précédent : le
        statut global retient le plus favorable (eligible), pas defaulted."""
        defaulted_loan = self._create_loan(product_id=self.product_step1.id)
        defaulted_loan.write({'state': 'written_off'})
        self._close_loan_without_arrears()
        application = self._create_application()
        self.assertEqual(application.progressive_eligibility_status, 'eligible')

    def test_cross_company_eligibility(self):
        """Prêt d'étape 1 pris dans une autre société : le statut est calculé malgré la
        différence de société (recherche cross-agency documentée, cf. matrice fonds
        bailleurs)."""
        company_b = self.env['res.company'].create({'name': 'Agence B programme (test)', 'agency_code': 'PB2'})
        loan = self._create_loan(product_id=self.product_step1.id, company_id=company_b.id)
        loan.action_generate_schedule()
        for inst in loan.installment_ids:
            inst.write({
                'paid_principal': inst.principal_amount,
                'paid_interest': inst.interest_amount,
                'paid_penalty': inst.penalty_amount,
            })
        loan.action_close()
        # Le dossier, lui, reste dans la société par défaut (différente de company_b).
        application = self._create_application()
        self.assertNotEqual(application.company_id, company_b)
        self.assertEqual(application.progressive_eligibility_status, 'eligible')
