# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError
from odoo.tests import Form

from .common import MicrofinanceCommon, MicrofinanceNoFundMixin


class TestCashierAccess(MicrofinanceNoFundMixin, MicrofinanceCommon):
    """Lot 7 (audit gestion_caisse) : vérifie empiriquement si l'absence d'accès de
    group_microfinance_cashier à microfinance.loan.product casse un flux réel du caissier,
    avant de décider s'il faut modifier ir.model.access.csv."""

    def _cashier_user(self):
        return self.env['res.users'].create({
            'name': 'Caissier accès test', 'login': 'cashier_access_test',
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('microfinance_loan_management.group_microfinance_cashier').id,
            ])],
        })

    def test_cashier_cannot_create_payment_form_from_loan(self):
        # Rendu obsolète par AUDIT_anomalies_ampitatafika_ambanidia_20260921.md §3 : un caissier
        # pouvait auparavant enregistrer un remboursement en dehors de toute session de caisse
        # via ce formulaire (bouton "Enregistrer remboursement"/menu "Analyse paiements"), sans
        # jamais créer de microfinance.caisse.mouvement, donc invisible du solde/ticket de
        # session. group_microfinance_cashier n'a plus create/write sur ce modèle
        # (ir.model.access.csv) : seul le guichet caisse (sudo scopé, cf.
        # microfinance_caisse_mouvement.py) peut encore créer un remboursement pour ce rôle.
        loan = self._activate_loan(loan_amount=900.0, term=3)
        cashier = self._cashier_user()
        with self.assertRaises(AccessError):
            with Form(self.env['microfinance.loan.payment'].with_user(cashier)) as payment_form:
                payment_form.loan_id = loan
            payment_form.save()
