# -*- coding: utf-8 -*-
import unittest

from .common import MicrofinanceCommon


class TestApplicationWorkflow(MicrofinanceCommon):
    """Workflow global du dossier d'instruction (microfinance.loan.application) :
    transitions d'état, numérotation, éligibilité de rang > 1."""

    def _create_application(self, **kwargs):
        vals = {'partner_id': self.partner.id, 'loan_product_id': self.product.id}
        vals.update(kwargs)
        return self.env['microfinance.loan.application'].create(vals)

    def test_numbering_derived_from_client_permanent_account_number(self):
        # name n'est plus une séquence propre au dossier : il reprend le numéro de compte
        # permanent du client (cf. correctif numérotation) — deux dossiers du même client
        # partagent donc la même référence, contrairement à l'ancien comportement.
        app1 = self._create_application()
        app2 = self._create_application()
        self.assertTrue(app1.name)
        self.assertTrue(app1.name.startswith('%s/' % self.env.company.agency_code))
        self.assertEqual(app1.name, self.partner.microfinance_account_number)
        self.assertEqual(app1.name, app2.name)

    @unittest.skip(
        "TODO(fusion): couverture de _check_previous_loan_requirements() sans point "
        "d'accroche depuis la simplification du cycle de microfinance.loan.application "
        "(committee/ca_review/cdag_review retirés, cf. restructuration du workflow de "
        "microfinance.loan) — même TODO que _check_committee_eligibility() dans le "
        "modèle. À réactiver et réécrire une fois le rattachement tranché avec Micka "
        "(probablement sur microfinance.loan.action_ca_review()), pas à réinventer ici."
    )
    def test_previous_loan_requirement_triggered_on_rank_greater_than_one(self):
        # Ancien scénario (avant simplification) : un dossier de rang > 1 amené jusqu'à
        # l'état 'committee' avec une impression insuffisante sur le dossier précédent
        # devait lever un UserError via _check_committee_eligibility(). Plus aucune étape
        # du cycle actuel (draft/visite/contre_visite/fait) ne déclenche ce contrôle.
        pass
