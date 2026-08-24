# -*- coding: utf-8 -*-
from odoo.tests import Form

from .common import MicrofinanceCommon


class TestLoanTermInstallmentFeedbackLoop(MicrofinanceCommon):
    """Non-régression Lot 1-bis : boucle de rétroaction entre `term` et `installment_amount`
    (_onchange_loan_amount_recompute_installment <-> _onchange_installment_amount_recompute_terms,
    microfinance_loan.py:637-720). Avant correctif, saisir `term` dans le formulaire pouvait le
    faire retomber à une autre valeur dans le même cycle onchange (régression confirmée sur
    IS/000289, cf. docs_dev/regression_nb_echeances/AUDIT.md). Ces tests utilisent Form(), qui
    rejoue exactement la cascade onchange du client web - même méthode que l'audit."""

    def setUp(self):
        super().setUp()
        # Form() applique strictement les modifiers de la vue lors de .save(), y compris
        # fond_credit_id required="has_active_fond" - sans rapport avec ce que ces tests
        # vérifient (la boucle term <-> installment_amount). Désactivé explicitement pour ne
        # pas dépendre de l'absence de fonds bailleurs actifs dans l'environnement de test.
        self.env['microfinance.fond.credit'].sudo().search([]).write({'active': False})

    def _configure_is000289_product(self):
        # Reprend la configuration réelle de IS/000289 (PRET RURAL, 500 000 Ar, 36%/an,
        # hebdomadaire, arrondi ceiling à 1000 Ar) - mêmes paramètres que
        # test_interest_first_schedule.py pour rester cohérent avec la suite existante.
        self.product.interest_rate = 36.0
        self.product.max_amount = 1000000.0
        self.product.installment_rounding_unit = 1000.0
        self.product.repayment_frequency_id = self.env.ref(
            'microfinance_loan_management.repayment_frequency_weekly'
        ).id

    def test_term_survives_direct_entry(self):
        """Séquence simple : fixer term=24 doit le laisser à 24, pas le faire retomber à 23."""
        self._configure_is000289_product()
        with Form(self.env['microfinance.loan']) as f:
            f.partner_id = self.partner
            f.product_id = self.product
            f.loan_amount = 500000.0
            f.term = 24
            self.assertEqual(f.term, 24)
            self.assertAlmostEqual(f.installment_amount, 25000.0, places=2)
        loan = f.save()
        self.assertEqual(loan.term, 24)
        self.assertAlmostEqual(loan.installment_amount, 25000.0, places=2)

    def test_term_stable_across_repeated_edits(self):
        """Séquence multi-éditions : after term=24, re-toucher loan_amount plusieurs fois (ex.
        l'utilisateur corrige/reconfirme le montant) ne doit jamais faire dériver `term`, à
        aucune étape intermédiaire - pas seulement à la fin."""
        self._configure_is000289_product()
        with Form(self.env['microfinance.loan']) as f:
            f.partner_id = self.partner
            f.product_id = self.product
            f.loan_amount = 500000.0
            f.term = 24
            self.assertEqual(f.term, 24)
            for _ in range(8):
                f.loan_amount = 500000.0
                self.assertEqual(f.term, 24)
                self.assertAlmostEqual(f.installment_amount, 25000.0, places=2)

    def test_term_stable_across_frequency_change(self):
        """L'utilisateur change de périodicité en cours de saisie (ex. Journalier puis
        Hebdomadaire) après avoir déjà fixé `term` : `term` ne doit pas dériver."""
        self.product.interest_rate = 36.0
        self.product.max_amount = 1000000.0
        self.product.installment_rounding_unit = 1000.0
        daily = self.env.ref('microfinance_loan_management.repayment_frequency_daily')
        weekly = self.env.ref('microfinance_loan_management.repayment_frequency_weekly')
        # Un seul write() : la contrainte _check_repayment_frequency_mode exige au moins une
        # périodicité autorisée dès que le mode passe à 'client_choice' - deux assignations
        # séparées verraient un état intermédiaire incohérent (mode déjà 'client_choice' mais
        # allowed_repayment_frequency_ids encore vide).
        self.product.write({
            'repayment_frequency_mode': 'client_choice',
            'repayment_frequency_id': False,
            'allowed_repayment_frequency_ids': [(6, 0, [daily.id, weekly.id])],
        })
        with Form(self.env['microfinance.loan']) as f:
            f.partner_id = self.partner
            f.product_id = self.product
            f.loan_amount = 500000.0
            f.repayment_frequency_id = daily
            f.term = 24
            f.repayment_frequency_id = weekly
            self.assertEqual(f.term, 24)
            self.assertAlmostEqual(f.installment_amount, 25000.0, places=2)

    def test_installment_amount_manual_edit_recomputes_term_once_and_sticks(self):
        """Sens inverse : fixer installment_amount directement à une valeur cible doit recalculer
        `term` une seule fois et s'y stabiliser, sans revenir en arrière sur installment_amount
        (le montant que l'utilisateur vient de taper doit rester affiché tel quel)."""
        self._configure_is000289_product()
        with Form(self.env['microfinance.loan']) as f:
            f.partner_id = self.partner
            f.product_id = self.product
            f.loan_amount = 500000.0
            f.term = 24
            f.installment_amount = 40000.0
            self.assertEqual(f.installment_amount, 40000.0)
            # term recalculé une seule fois à partir de 40 000 (attendu 14, cf. audit) ...
            expected_term = f.term
            self.assertGreater(expected_term, 0)
            # ... et ne doit plus bouger en retouchant un champ non lié à installment_amount.
            f.loan_amount = 500000.0
            self.assertEqual(f.term, expected_term)
            self.assertEqual(f.installment_amount, 40000.0)

    def test_is000289_non_regression_schedule_unchanged(self):
        """Non-régression du dossier réel IS/000289 : après une séquence d'onchange réaliste,
        `term` reste à 24 et l'échéancier généré reste identique à celui déjà validé par
        test_interest_first_schedule.py (25 000 Ar x 23 + reliquat 8 076,92)."""
        self._configure_is000289_product()
        with Form(self.env['microfinance.loan']) as f:
            f.partner_id = self.partner
            f.product_id = self.product
            f.loan_amount = 500000.0
            f.term = 24
            f.loan_amount = 500000.0
            f.loan_amount = 500000.0
        loan = f.save()
        self.assertEqual(loan.term, 24)
        loan.action_generate_schedule()
        installments = loan.installment_ids.sorted('sequence')
        self.assertEqual(len(installments), 24)
        others_total = installments[0].principal_amount + installments[0].interest_amount
        last_total = installments[-1].principal_amount + installments[-1].interest_amount
        self.assertAlmostEqual(others_total, 25000.0, places=2)
        self.assertAlmostEqual(last_total, 8076.92, places=2)
