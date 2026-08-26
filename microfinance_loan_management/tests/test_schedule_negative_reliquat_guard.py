# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError

from .common import MicrofinanceCommon


class TestScheduleNegativeReliquatGuard(MicrofinanceCommon):
    """Garde-fou contre le reliquat négatif de dernière tranche (effet de bord de l'arrondi
    `ceiling`, Lot 1) : quand le nombre d'échéances est élevé par rapport au montant du crédit,
    le surplus d'arrondi cumulé sur les `n-1` premières tranches (chacune arrondie au multiple
    SUPÉRIEUR de `installment_rounding_unit`) peut dépasser le total dû, rendant la dernière
    tranche - qui absorbe le reliquat exact - négative. Constaté réellement sur IS/001076 (30
    échéances hebdomadaires, cible 21 000 Ar, reliquat -5 153,85 Ar), cf.
    docs_dev/garde_fou_reliquat_negatif/AUDIT.md pour la dérivation et le recensement complets.
    """

    def setUp(self):
        super().setUp()
        self.env['microfinance.fond.credit'].sudo().search([]).write({'active': False})
        self.product.max_amount = 1000000.0
        self.product.installment_rounding_unit = 1000.0
        self.product.repayment_frequency_id = self.env.ref(
            'microfinance_loan_management.repayment_frequency_weekly'
        ).id

    def test_bm_case_raises_before_any_write(self):
        """Reproduction exacte du cas constaté : 603 846,15 Ar dus, 30 échéances hebdomadaires,
        unité d'arrondi 1000 Ar - reliquat attendu -5 153,85 Ar. `interest_rate=0` isole le
        calcul (total_due == loan_amount) sans changer la mécanique de reliquat, qui ne dépend
        que de total_due/n/unit."""
        self.product.interest_rate = 0.0
        loan = self._create_loan(loan_amount=603846.15, term=30)
        installments_before = loan.installment_ids
        with self.assertRaises(ValidationError):
            loan.action_generate_schedule()
        # Rien n'a été écrit : la ValidationError doit être levée avant toute écriture, pas
        # après une persistance partielle.
        self.assertEqual(loan.installment_ids, installments_before)

    def test_non_regression_reference_case_weekly_still_passes(self):
        """Cas de référence IS/000289 (déjà validé Lot 1) : reste positif, ne doit pas
        déclencher le garde-fou - non-régression explicite demandée."""
        self.product.interest_rate = 36.0
        loan = self._create_loan(loan_amount=500000.0, term=24)
        loan.action_generate_schedule()
        self.assertEqual(len(loan.installment_ids), 24)
        last = loan.installment_ids.sorted('sequence')[-1]
        self.assertGreaterEqual(last.principal_amount + last.interest_amount, 0.0)

    def test_non_regression_reference_case_monthly_still_passes(self):
        """Cas de référence IS/01913 (déjà validé Lot 1, mensuel) : reste positif, ne doit pas
        déclencher le garde-fou."""
        self.product.interest_rate = 36.0
        self.product.repayment_frequency_id = self.env.ref(
            'microfinance_loan_management.repayment_frequency_monthly'
        ).id
        loan = self._create_loan(loan_amount=700000.0, term=11)
        loan.action_generate_schedule()
        self.assertEqual(len(loan.installment_ids), 11)

    def test_write_trigger_also_blocked(self):
        """Le garde-fou doit aussi bloquer la régénération automatique déclenchée par write()
        (Lot précédent, _SCHEDULE_TRIGGER_FIELDS) une fois un échéancier déjà existant - pas
        seulement le premier appel explicite au bouton "Générer échéancier"."""
        self.product.interest_rate = 0.0
        loan = self._create_loan(loan_amount=500000.0, term=10)
        loan.action_generate_schedule()
        self.assertTrue(loan.installment_ids)
        with self.assertRaises(ValidationError):
            loan.write({'loan_amount': 603846.15, 'term': 30})
