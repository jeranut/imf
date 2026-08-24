# -*- coding: utf-8 -*-
from .common import MicrofinanceCommon


class TestLoanInstallmentAmount(MicrofinanceCommon):
    """Échéance dynamique (installment_amount) sur microfinance.loan : aperçu avant génération
    de l'échéancier détaillé. Les onchange ne s'exécutant jamais via create()/write() en Python
    (seulement dans le client web), ces tests les appellent directement comme des méthodes
    normales - ce qui exerce la logique de calcul, mais pas le cycle onchange<->onchange réel du
    navigateur (à vérifier manuellement, cf. prompt)."""

    def test_installment_amount_direct_calculation_with_rounding(self):
        # Mêmes chiffres que le cas de référence IS/01913 (test_interest_first_schedule.py) :
        # cible brute 931000/11 = 84 636,36, arrondie à 85 000 au plus proche multiple de 1000.
        self.product.interest_rate = 36.0
        self.product.max_amount = 1000000.0
        self.product.installment_rounding_unit = 1000.0
        loan = self._create_loan(loan_amount=700000.0, term=11)
        loan._onchange_loan_amount_recompute_installment()
        self.assertAlmostEqual(loan.installment_amount, 85000.0, places=2)

    def test_installment_amount_recomputes_when_loan_amount_changes(self):
        loan = self._create_loan(loan_amount=1200.0, term=6)
        loan._onchange_loan_amount_recompute_installment()
        first = loan.installment_amount
        loan.loan_amount = 2400.0
        loan._onchange_loan_amount_recompute_installment()
        self.assertGreater(loan.installment_amount, first)

    def test_installment_amount_inverse_calculation_recomputes_term(self):
        loan = self._create_loan(loan_amount=1200.0, term=6)
        loan._onchange_loan_amount_recompute_installment()
        # Échéance doublée -> moins d'échéances nécessaires pour rembourser le même capital.
        loan.installment_amount = loan.installment_amount * 2
        loan._onchange_installment_amount_recompute_terms()
        self.assertLess(loan.term, 6)

    def test_installment_amount_inverse_denominator_non_positive_leaves_term_unchanged(self):
        # Échéance trop faible pour couvrir même l'intérêt d'une seule période (produit par
        # défaut : 12%/an, mensuel -> ~12 Ar d'intérêt par période sur 1200 Ar de capital) :
        # denominator <= 0, ne doit rien changer plutôt que planter ou produire un term absurde.
        loan = self._create_loan(loan_amount=1200.0, term=6)
        original_term = loan.term
        loan.installment_amount = 5.0
        loan._onchange_installment_amount_recompute_terms()
        self.assertEqual(loan.term, original_term)

    def test_no_recompute_once_loan_is_active(self):
        loan = self._activate_loan(loan_amount=1200.0, term=6)
        self.assertEqual(loan.state, 'active')
        loan.installment_amount = 999999.0  # écriture directe, hors onchange
        loan._onchange_installment_amount_recompute_terms()
        self.assertEqual(loan.term, 6)  # inchangé : le crédit actif n'est plus dans les états éditables

    def test_action_start_enquete_computes_installment_amount_when_missing(self):
        # Crédit "importé" (création directe via create(), sans passer par le formulaire) :
        # installment_amount reste vide puisque l'onchange ne s'exécute jamais hors client web -
        # filet de sécurité du bouton "Démarrer l'enquête" (Lot D).
        loan = self._create_loan(loan_amount=1200.0, term=6)
        self.assertFalse(loan.installment_amount)
        loan.action_start_enquete()
        self.assertTrue(loan.installment_amount)

    def test_action_start_enquete_does_not_override_existing_installment_amount(self):
        loan = self._create_loan(loan_amount=1200.0, term=6)
        loan.installment_amount = 250.0
        loan.action_start_enquete()
        self.assertEqual(loan.installment_amount, 250.0)


class TestLoanInstallmentSchedulePreview(MicrofinanceCommon):
    """_build_installment_commands, réutilisée par action_generate_schedule (bouton) et par les
    onchange A/B (rafraîchissement d'installment_ids intégré directement dans
    _onchange_loan_amount_recompute_installment / _onchange_installment_amount_recompute_terms,
    plutôt qu'un onchange séparé sur les mêmes champs - cf. incident signalé par Micka : deux
    onchange indépendants déclenchés par le même champ modifié n'ont pas d'ordre d'exécution
    garanti par Odoo, ce qui pouvait laisser le tableau affiché sur l'ancien `term`) - vérifie
    que tous ces chemins produisent exactement le même résultat."""

    def test_build_installment_commands_matches_action_generate_schedule(self):
        self.product.interest_rate = 36.0
        self.product.max_amount = 1000000.0
        self.product.installment_rounding_unit = 1000.0
        loan = self._create_loan(loan_amount=700000.0, term=11)
        commands = loan._build_installment_commands()
        loan.action_generate_schedule()
        installments = loan.installment_ids.sorted('sequence')
        self.assertEqual(len(commands), len(installments))
        for command, installment in zip(commands, installments):
            vals = command[2]
            self.assertEqual(vals['sequence'], installment.sequence)
            self.assertEqual(vals['due_date'], installment.due_date)
            self.assertAlmostEqual(vals['principal_amount'], installment.principal_amount, places=2)
            self.assertAlmostEqual(vals['interest_amount'], installment.interest_amount, places=2)

    def test_onchange_refreshes_installment_ids_preview(self):
        loan = self._create_loan(loan_amount=1200.0, term=6)
        self.assertFalse(loan.installment_ids)
        loan._onchange_loan_amount_recompute_installment()
        self.assertEqual(len(loan.installment_ids), 6)

    def test_onchange_preview_does_not_refresh_once_loan_is_active(self):
        loan = self._activate_loan(loan_amount=1200.0, term=6)
        installment_ids_before = loan.installment_ids.ids
        loan._onchange_loan_amount_recompute_installment()
        self.assertEqual(loan.installment_ids.ids, installment_ids_before)

    def test_onchange_installment_amount_refreshes_schedule_with_updated_term(self):
        # Reproduit l'incident signalé par Micka : modifier installment_amount recalcule term
        # (Lot B) - le tableau installment_ids doit alors refléter ce NOUVEAU term, pas rester
        # sur l'ancien (c'était le bug : un onchange séparé se déclenchait avec l'ancien term).
        loan = self._create_loan(loan_amount=1200.0, term=6)
        loan._onchange_loan_amount_recompute_installment()
        self.assertEqual(len(loan.installment_ids), 6)

        loan.installment_amount = loan.installment_amount * 2  # -> moins d'échéances
        loan._onchange_installment_amount_recompute_terms()
        self.assertLess(loan.term, 6)
        self.assertEqual(len(loan.installment_ids), loan.term)

    def test_build_installment_commands_empty_without_repayment_frequency(self):
        loan = self._create_loan(loan_amount=1200.0, term=6)
        loan.repayment_frequency_id = False
        self.assertEqual(loan._build_installment_commands(), [])
