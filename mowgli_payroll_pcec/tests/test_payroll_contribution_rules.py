# -*- coding: utf-8 -*-
"""Paramètres datés, base cotisable plafonnée/plancher, CNAPS/OSTIE/IRSA lus
dans les paramètres, parts patronales CNAPS_ER/OSTIE_ER (catégorie COMP).
Suppose les données réelles de MOWGLI (copie jetable). Rollback automatique."""
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from .common import MowgliSmeTestMixin

LINES = ('GROSS', 'CNAPS', 'OSTIE', 'NETIMP', 'IRSA', 'NET', 'CNAPS_ER', 'OSTIE_ER')


@tagged('post_install', '-at_install')
class TestPayrollContributionRules(MowgliSmeTestMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].search(
            [('name', 'in', ['AGENCE ANALAKELY', 'CEFOR Isotry'])], limit=1)
        cls.structure = cls.env['hr.payroll.structure'].search(
            [('code', '=', 'BASE')], limit=1)
        if cls.company and cls.structure:
            cls.env['hr.salary.rule']._mowgli_setup_payroll_rules()

    def setUp(self):
        super().setUp()
        if not self.company or not self.structure:
            self.skipTest("Données MOWGLI absentes de cette base.")
        self._mowgli_add_test_sme(250000.0)

    def _slip(self, wage, children=0, date_from='2026-09-01', date_to='2026-09-30'):
        employee = self.env['hr.employee'].create({
            'name': 'Employé cotisations', 'company_id': self.company.id,
            'children': children})
        contract = self.env['hr.contract'].create({
            'name': 'Contrat cotisations', 'employee_id': employee.id,
            'company_id': self.company.id, 'wage': wage, 'state': 'open',
            'struct_id': self.structure.id, 'date_start': '2026-01-01'})
        slip = self.env['hr.payslip'].create({
            'employee_id': employee.id, 'contract_id': contract.id,
            'struct_id': self.structure.id, 'company_id': self.company.id,
            'date_from': date_from, 'date_to': date_to})
        slip.action_compute_sheet()
        return slip

    def _totals(self, slip):
        return {l.code: l.total for l in slip.line_ids}

    def _check(self, slip, expected):
        totals = self._totals(slip)
        self.assertEqual({k: totals.get(k) for k in LINES}, dict(zip(LINES, expected)))

    # --- cas du fichier (SME 250 000, plafond 2 000 000, PLANCHER 1) ----------
    # Recalcul manuel (IRSA : 5 % de 350 001 à 400 000, 10 % jusqu'à 500 000,
    # 15 % jusqu'à 600 000, 20 % jusqu'à 4 000 000, 25 % au-delà, -2 000/enfant,
    # minimum 3 000) :
    #  Rabe 475 000 : base 475 000 ; sal. 4 750 + 4 750 ; NETIMP 465 500 ;
    #    IRSA = 50 000 x 5 % + 65 500 x 10 % = 2 500 + 6 550 = 9 050 ;
    #    NET = 475 000 - 4 750 - 4 750 - 9 050 = 456 450 ; ER 13 % = 61 750, 5 % = 23 750.
    #  John Doe 395 000 : 3 950 + 3 950 ; NETIMP 387 100 ;
    #    IRSA = 37 100 x 5 % = 1 855, - 3 x 2 000 < 0 -> minimum 3 000 ;
    #    NET = 395 000 - 7 900 - 3 000 = 384 100 ; ER 51 350 et 19 750.
    #  Ritchie Rich 5 000 000 : base plafonnée 2 000 000 ; sal. 20 000 + 20 000 ;
    #    NETIMP 4 960 000 ; IRSA = 2 500 + 10 000 + 15 000 + 3 400 000 x 20 %
    #    + 960 000 x 25 % - 2 x 2 000 = 27 500 + 680 000 + 240 000 - 4 000 = 943 500 ;
    #    NET = 5 000 000 - 40 000 - 943 500 = 4 016 500 ; ER 260 000 et 100 000.
    def test_cas_fichier_rakoto(self):
        self._check(self._slip(700000, 1), (700000, -7000, -7000, 686000, -42700, 643300, 91000, 35000))

    def test_cas_fichier_rabe(self):
        self._check(self._slip(475000, 0), (475000, -4750, -4750, 465500, -9050, 456450, 61750, 23750))

    def test_cas_fichier_john_doe(self):
        self._check(self._slip(395000, 3), (395000, -3950, -3950, 387100, -3000, 384100, 51350, 19750))

    def test_cas_fichier_ritchie_rich(self):
        self._check(self._slip(5000000, 2), (5000000, -20000, -20000, 4960000, -943500, 4016500, 260000, 100000))

    # --- valeurs par défaut, octobre 2026 (SME 315 000, plafond 2 520 000) ------
    def test_defaut_ritchie_rich(self):
        slip = self._slip(5000000, 2, '2026-10-01', '2026-10-31')
        self._check(slip, (5000000, -25200, -25200, 4949600, -940900, 4008700, 327600, 126000))

    def test_defaut_plancher_actif(self):
        slip = self._slip(200000, 0, '2026-10-01', '2026-10-31')
        self._check(slip, (200000, -3150, -3150, 193700, -3000, 190700, 40950, 15750))

    def test_defaut_plancher_inactif(self):
        self.env['mowgli.payroll.param'].create({
            'code': 'PLANCHER', 'value': 0.0, 'date_from': '2026-10-01',
            'company_id': self.company.id})
        slip = self._slip(200000, 0, '2026-10-01', '2026-10-31')
        self._check(slip, (200000, -2000, -2000, 196000, -3000, 193000, 26000, 10000))

    # --- base cotisable --------------------------------------------------------
    def test_base_cotisable(self):
        slip = self._slip(700000)
        for brut, base in ((700000, 700000), (5000000, 2000000), (200000, 250000),
                           (2000000, 2000000), (2000001, 2000000)):
            self.assertEqual(slip._mowgli_contribution_base(brut), base)
        self.env['mowgli.payroll.param'].create({
            'code': 'PLANCHER', 'value': 0.0, 'date_from': '2026-01-02',
            'company_id': self.company.id})
        self.assertEqual(slip._mowgli_contribution_base(200000), 200000)

    def test_brut_nul_aucune_ligne_patronale(self):
        totals = self._totals(self._slip(0))
        self.assertNotIn('CNAPS_ER', totals)
        self.assertNotIn('OSTIE_ER', totals)

    def test_montant_non_rond_arrondi_devise(self):
        slip = self._slip(1234567, 0, '2026-10-01', '2026-10-31')
        currency = self.company.currency_id
        totals = self._totals(slip)
        self.assertAlmostEqual(currency.round(totals['CNAPS_ER']), 160493.71, places=2)
        self.assertAlmostEqual(currency.round(totals['OSTIE_ER']), 61728.35, places=2)

    # --- paramètres datés ---------------------------------------------------------
    def test_sme_non_defini_avant_la_date(self):
        with self.assertRaisesRegex(UserError, "SME non défini"):
            self._slip(700000, 0, '2025-12-01', '2025-12-31')
        self.env['mowgli.payroll.param'].sudo().search(
            [('code', '=', 'SME')]).unlink()
        with self.assertRaisesRegex(UserError, "SME non défini"):
            self._slip(700000, 0, '2026-08-01', '2026-08-31')

    def test_sme_date_avant_et_apres(self):
        Param = self.env['mowgli.payroll.param']
        self.assertEqual(Param._get_value('SME', '2026-09-30', self.company), 250000.0)
        self.assertEqual(Param._get_value('SME', '2026-10-01', self.company), 315000.0)
        Param.create({'code': 'SME', 'value': 400000.0, 'date_from': '2026-10-01',
                      'company_id': self.company.id})
        self.assertEqual(Param._get_value('SME', '2026-10-31', self.company), 400000.0)

    def test_semis_idempotents_sans_ecrasement(self):
        Param = self.env['mowgli.payroll.param']
        line = Param.search([('code', '=', 'CNAPS_ER'), ('company_id', '=', False)],
                            order='date_from', limit=1)
        line.value = 0.14
        count = Param.search_count([])
        Param._seed_defaults()
        Param._seed_defaults()
        self.assertEqual(Param.search_count([]), count)
        self.assertAlmostEqual(line.value, 0.14)

    # --- règles ----------------------------------------------------------------
    def test_regles_patronales_et_rejeu(self):
        Rule = self.env['hr.salary.rule']
        before = self.structure.rule_ids.mapped('code')
        Rule._mowgli_setup_payroll_rules()
        Rule._microfinance_payroll_setup_loan_rule() if hasattr(
            Rule, '_microfinance_payroll_setup_loan_rule') else None
        Rule._mowgli_setup_payroll_rules()
        after = self.structure.rule_ids.mapped('code')
        self.assertLessEqual(set(before), set(after))
        self.assertEqual(len(after), len(set(after)))
        for code in ('CNAPS_ER', 'OSTIE_ER'):
            rule = self.structure.rule_ids.filtered(lambda r: r.code == code)
            self.assertEqual(len(rule), 1)
            self.assertEqual(rule.category_id.code, 'COMP')
            self.assertFalse(rule.appears_on_payslip)
            self.assertGreater(rule.sequence, self.structure.rule_ids.filtered(
                lambda r: r.code == 'OSTIE').sequence)
            self.assertLess(rule.sequence, self.structure.rule_ids.filtered(
                lambda r: r.code == 'NETIMP').sequence)
        gross = self.structure.rule_ids.filtered(lambda r: r.code == 'GROSS')
        self.assertNotIn('COMP', gross.amount_python_compute)
        net = self.structure.rule_ids.filtered(lambda r: r.code == 'NET')
        self.assertNotIn('COMP', net.amount_python_compute)

    def test_synchro_ne_cree_aucun_compte_patronal(self):
        Rule = self.env['hr.salary.rule'].sudo()
        company = self.env['res.company'].with_context(active_test=False).search(
            [('chart_template', '!=', False), ('id', '!=', self.company.id)], limit=1)
        if not company:
            self.skipTest("Pas de seconde société avec plan.")
        rules = self.structure.sudo().rule_ids
        rows = Rule._mowgli_complete_company_accounts(rules, company, apply=False)
        self.assertFalse([r for r in rows if r['regle'] in ('CNAPS_ER', 'OSTIE_ER')])
        self.assertIn('CNAPS_ER', rules.mapped('code'))
        self.assertIn('OSTIE_ER', rules.mapped('code'))

    def test_aucun_fmfp(self):
        self.assertFalse(self.env['hr.salary.rule'].with_context(active_test=False).search_count(
            [('code', 'ilike', 'FMFP')]))
        self.assertFalse(self.env['mowgli.payroll.param'].search_count(
            [('code', 'ilike', 'FMFP')]))
