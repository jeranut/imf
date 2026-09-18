# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged('post_install_l10n', '-at_install', 'post_install')
class TestResCompanyEcartCaisseAccounts(TransactionCase):
    """Les deux comptes d'attente écart de caisse (microfinance_account_ecart_caisse_deficit_id
    / excedent_id) doivent se pré-remplir automatiquement dès que le chart PCEC (mg_pcec) est
    chargé sur la société, exactement comme les champs account_xxx_id de microfinance.loan.product
    / microfinance.savings.product (_pcec_default). Chargement explicite du template requis :
    cf. docstring de plan_compta_pcec/tests/test_chart.py (le CSV n'est parsé qu'à l'appel de
    try_loading, jamais à la seule installation du module)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        mg_country = cls.env.ref('base.mg')
        cls.company = cls.env['res.company'].create({
            'name': 'CEFOR Test Écart Caisse',
            'country_id': mg_country.id,
            'currency_id': cls.env.ref('base.MGA').id,
            'agency_code': 'ZZ',
        })
        cls.env['account.chart.template'].with_company(cls.company).try_loading(
            'mg_pcec', cls.company, install_demo=False,
        )

    def test_deficit_account_auto_filled_on_pcec_company(self):
        """microfinance_account_ecart_caisse_deficit_id doit pointer vers le compte PCEC 324000
        sans aucune action manuelle."""
        company = self.company.with_context(force_company=self.company.id)
        deficit_account = company.microfinance_account_ecart_caisse_deficit_id
        self.assertTrue(
            deficit_account,
            'Le compte d\'attente écart de caisse (déficit) doit être pré-rempli automatiquement',
        )
        self.assertEqual(deficit_account.code, '324000')
        self.assertEqual(deficit_account.account_type, 'asset_current')

    def test_excedent_account_auto_filled_on_pcec_company(self):
        """microfinance_account_ecart_caisse_excedent_id doit pointer vers le compte PCEC 329100
        sans aucune action manuelle."""
        company = self.company.with_context(force_company=self.company.id)
        excedent_account = company.microfinance_account_ecart_caisse_excedent_id
        self.assertTrue(
            excedent_account,
            'Le compte d\'attente écart de caisse (excédent) doit être pré-rempli automatiquement',
        )
        self.assertEqual(excedent_account.code, '329100')
        self.assertEqual(excedent_account.account_type, 'liability_current')
