# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError

from .common import MicrofinanceCommon


class TestLockedDossierFields(MicrofinanceCommon):
    """Verrouillage des champs "Calcul crédit" (`loan_amount`, `term`, `product_id`,
    `interest_rate`, `installment_amount`) dès qu'un crédit atteint `avis_ca`/`avis_cdag` (et
    tous les états suivants) - Lot 1, cf. docs_dev/verrouillage_calcul_credit/AUDIT.md. Le
    filet réel est l'override de `write()` (`_check_locked_dossier_fields`), pas seulement le
    `readonly` de vue (contournable par API/import) - ces tests appellent `write()` directement,
    pas via `Form()`, pour vérifier ce filet serveur."""

    def setUp(self):
        super().setUp()
        self.env['microfinance.fond.credit'].sudo().search([]).write({'active': False})
        self.product2 = self.product.copy({'code': 'PTEST2', 'name': 'Produit Test 2'})

    def _loan_in_avis_ca(self):
        loan = self._create_loan(loan_amount=1200.0, term=6)
        loan.action_generate_schedule()
        loan.action_start_enquete()
        loan.action_ca_review()
        return loan

    def test_locked_fields_blocked_in_avis_ca(self):
        loan = self._loan_in_avis_ca()
        for vals in (
            {'loan_amount': 2000.0},
            {'term': 10},
            {'product_id': self.product2.id},
            {'interest_rate': 20.0},
            {'installment_amount': 999.0},
        ):
            with self.assertRaises(ValidationError):
                loan.write(vals)

    def test_locked_fields_blocked_in_avis_cdag_and_approved(self):
        loan = self._loan_in_avis_ca()
        loan.action_cdag_review()
        with self.assertRaises(ValidationError):
            loan.write({'loan_amount': 2000.0})
        loan.action_approve()
        with self.assertRaises(ValidationError):
            loan.write({'term': 10})

    def test_propagate_avis_still_works_in_avis_ca(self):
        """L'écriture système de _propagate_avis_to_loan() (déclenchée par une modification du
        bloc Avis CA) ne doit pas être bloquée par son propre verrou."""
        loan = self._loan_in_avis_ca()
        loan.write({'avis_ca_amount': 1800.0, 'avis_ca_term': 9})
        self.assertEqual(loan.loan_amount, 1800.0)
        self.assertEqual(loan.term, 9)

    def test_schedule_regeneration_still_works_in_approved(self):
        """Non-régression : _EDITABLE_SCHEDULE_STATES et action_generate_schedule() (qui
        n'écrit que installment_ids, jamais les 5 champs verrouillés) continuent de fonctionner
        normalement en 'approved'."""
        loan = self._loan_in_avis_ca()
        loan.action_cdag_review()
        loan.action_approve()
        self.assertEqual(loan.state, 'approved')
        loan.action_generate_schedule()
        self.assertTrue(loan.installment_ids)

    def test_locked_fields_still_editable_before_avis(self):
        """Un crédit encore en draft/enquete (avant tout avis) reste librement modifiable sur
        les 5 champs."""
        loan = self._create_loan(loan_amount=1200.0, term=6)
        loan.write({
            'loan_amount': 1500.0, 'term': 8, 'interest_rate': 20.0,
            'product_id': self.product2.id,
        })
        self.assertEqual(loan.loan_amount, 1500.0)
        self.assertEqual(loan.term, 8)
        self.assertEqual(loan.interest_rate, 20.0)
        self.assertEqual(loan.product_id, self.product2)

        loan.action_generate_schedule()
        loan.action_start_enquete()
        loan.write({'installment_amount': loan.installment_amount})  # état 'enquete', pas verrouillé
