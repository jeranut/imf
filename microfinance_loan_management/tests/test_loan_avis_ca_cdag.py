# -*- coding: utf-8 -*-
from odoo.tests import Form

from .common import MicrofinanceCommon


class TestLoanAvisCaCdag(MicrofinanceCommon):
    """Lot 1 du chantier Avis CA/CDAG : champs avis_ca_*/avis_cdag_* sur microfinance.loan,
    calcul bidirectionnel (réutilisation stricte du mécanisme Lot 1-bis), cascade CA -> CDAG,
    et propagation vers loan_amount/term/installment_amount à chaque sauvegarde. Utilise Form()
    pour les tests de cascade onchange - même méthode que le Lot 1-bis (rejoue exactement la
    cascade onchange du client web, condition nécessaire pour détecter une boucle éventuelle)."""

    def setUp(self):
        super().setUp()
        # Cf. test_loan_term_installment_feedback_loop.py : Form() applique strictement les
        # modifiers de la vue lors de .save(), y compris fond_credit_id required="has_active_
        # fond" - sans rapport avec ce que ces tests vérifient.
        self.env['microfinance.fond.credit'].sudo().search([]).write({'active': False})

    def _configure_is000289_product(self):
        # Mêmes paramètres que test_loan_term_installment_feedback_loop.py (IS/000289 réel) :
        # 36%/an, hebdomadaire, arrondi ceiling à 1000 Ar.
        self.product.interest_rate = 36.0
        self.product.max_amount = 1000000.0
        self.product.installment_rounding_unit = 1000.0
        self.product.repayment_frequency_id = self.env.ref(
            'microfinance_loan_management.repayment_frequency_weekly'
        ).id

    def _loan_to_enquete(self, loan_amount=500000.0, term=24):
        self._configure_is000289_product()
        loan = self._create_loan(loan_amount=loan_amount, term=term)
        loan.action_start_enquete()
        return loan

    def test_1_defaults_populated_on_ca_review(self):
        loan = self._loan_to_enquete()
        loan.action_ca_review()
        self.assertEqual(loan.state, 'avis_ca')
        self.assertEqual(loan.avis_ca_amount, 500000.0)
        self.assertEqual(loan.avis_ca_term, 24)
        self.assertAlmostEqual(loan.avis_ca_installment_amount, 25000.0, places=2)
        # Cascade CA -> CDAG dès la première population (avis_cdag_manually_set encore False).
        self.assertEqual(loan.avis_cdag_amount, 500000.0)
        self.assertEqual(loan.avis_cdag_term, 24)
        self.assertAlmostEqual(loan.avis_cdag_installment_amount, 25000.0, places=2)

    def test_2_ca_amount_change_recomputes_installment_and_cascades(self):
        loan = self._loan_to_enquete()
        loan.action_ca_review()
        with Form(loan) as f:
            f.avis_ca_amount = 450000.0
        loan = f.save()
        # Cible ceiling recalculée pour le nouveau montant, même terme (24).
        self.assertAlmostEqual(loan.avis_ca_installment_amount, loan._compute_installment_target(
            450000.0, 24), places=2)
        self.assertNotAlmostEqual(loan.avis_ca_installment_amount, 25000.0, places=2)
        # Cascade : le bloc CDAG suit automatiquement (pas encore modifié manuellement).
        self.assertEqual(loan.avis_cdag_amount, 450000.0)
        self.assertEqual(loan.avis_cdag_term, 24)
        self.assertAlmostEqual(loan.avis_cdag_installment_amount, loan.avis_ca_installment_amount, places=2)

    def test_3_ca_term_change_recomputes_installment_and_cascades(self):
        loan = self._loan_to_enquete()
        loan.action_ca_review()
        with Form(loan) as f:
            f.avis_ca_term = 20
        loan = f.save()
        self.assertEqual(loan.avis_ca_term, 20)
        self.assertAlmostEqual(loan.avis_ca_installment_amount, loan._compute_installment_target(
            500000.0, 20), places=2)
        self.assertEqual(loan.avis_cdag_term, 20)
        self.assertAlmostEqual(loan.avis_cdag_installment_amount, loan.avis_ca_installment_amount, places=2)

    def test_4_no_drift_across_repeated_edits(self):
        """Reproduit la méthode Form() du Lot 1-bis (docs_dev/regression_nb_echeances/) sur les
        nouveaux champs avis_ca_* : aucune valeur ne doit dériver au fil d'éditions successives."""
        loan = self._loan_to_enquete()
        loan.action_ca_review()
        with Form(loan) as f:
            f.avis_ca_term = 24
            self.assertEqual(f.avis_ca_term, 24)
            for _ in range(8):
                f.avis_ca_amount = 500000.0
                self.assertEqual(f.avis_ca_term, 24)
                self.assertAlmostEqual(f.avis_ca_installment_amount, 25000.0, places=2)

    def test_5_cdag_manual_edit_stops_cascade(self):
        loan = self._loan_to_enquete()
        loan.action_ca_review()
        loan.action_cdag_review()
        self.assertFalse(loan.avis_cdag_manually_set)
        with Form(loan) as f:
            f.avis_cdag_amount = 480000.0
        loan = f.save()
        self.assertTrue(loan.avis_cdag_manually_set)
        self.assertEqual(loan.avis_cdag_amount, 480000.0)
        # Le CA modifie à nouveau son propre montant : le CDAG ne doit plus se faire écraser.
        with Form(loan) as f:
            f.avis_ca_amount = 460000.0
        loan = f.save()
        self.assertEqual(loan.avis_ca_amount, 460000.0)
        self.assertEqual(loan.avis_cdag_amount, 480000.0)  # inchangé, cascade figée

    def test_6_propagation_to_loan_on_save_in_avis_ca_state(self):
        loan = self._loan_to_enquete()
        loan.action_ca_review()
        with Form(loan) as f:
            f.avis_ca_amount = 450000.0
            f.avis_ca_term = 20
        loan = f.save()
        self.assertEqual(loan.loan_amount, 450000.0)
        self.assertEqual(loan.term, 20)
        self.assertAlmostEqual(loan.installment_amount, loan.avis_ca_installment_amount, places=2)
        installments = loan.installment_ids.sorted('sequence')
        self.assertEqual(len(installments), 20)
        total = sum(i.principal_amount + i.interest_amount for i in installments)
        self.assertAlmostEqual(total, 450000.0 + 450000.0 * 0.36 * (1 / 52.0) * 20, places=2)

    def test_6bis_propagation_uses_cdag_once_in_avis_cdag_state(self):
        loan = self._loan_to_enquete()
        loan.action_ca_review()
        loan.action_cdag_review()
        with Form(loan) as f:
            f.avis_cdag_amount = 420000.0
        loan = f.save()
        self.assertEqual(loan.loan_amount, 420000.0)
        self.assertEqual(loan.term, 24)
        self.assertAlmostEqual(loan.installment_amount, loan.avis_cdag_installment_amount, places=2)

    def test_7_no_propagation_once_disbursed(self):
        self._configure_is000289_product()
        loan = self._activate_loan(loan_amount=500000.0, term=24)
        self.assertEqual(loan.state, 'active')
        loan_amount_before, term_before = loan.loan_amount, loan.term
        # Écriture directe hors formulaire (l'attrs readonly de la vue ne protège pas un write()
        # ORM direct) : la garde doit être serveur, pas seulement côté vue.
        loan.write({'avis_ca_amount': 999999.0, 'avis_ca_term': 5})
        self.assertEqual(loan.loan_amount, loan_amount_before)
        self.assertEqual(loan.term, term_before)
