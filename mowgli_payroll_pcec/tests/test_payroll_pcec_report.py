# -*- coding: utf-8 -*-
"""Tests du bulletin de paie paysage dupliqué (2 copies/page).

Mêmes hypothèses que test_payroll_pcec.py : nécessite les données réelles
de la société 'CEFOR Isotry' et de la structure 'BASE' (copie jetable de
MOWGLI, jamais la production). TransactionCase -> rollback en fin de test.
"""
import re
import subprocess

from odoo.tests.common import TransactionCase, tagged
from odoo.addons.mowgli_payroll_pcec.tests.common import MowgliSmeTestMixin

RULE_CODES = (
    'BASIC', 'Travel', 'GROSS', 'CNAPS', 'OSTIE', 'NETIMP', 'IRSA', 'NET',
)


@tagged('post_install', '-at_install')
class TestPayrollPcecReport(MowgliSmeTestMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].search(
            [('name', '=', 'CEFOR Isotry')], limit=1)
        cls.structure = cls.env['hr.payroll.structure'].search(
            [('code', '=', 'BASE')], limit=1)
        if cls.company and cls.structure:
            cls.env['hr.salary.rule']._mowgli_setup_payroll_rules()
        cls.report = cls.env.ref(
            'hr_payroll_community.hr_payslip_new_report_action',
            raise_if_not_found=False)

    def setUp(self):
        super().setUp()
        self._mowgli_add_test_sme()
        if not self.company or not self.structure:
            self.skipTest(
                "Société CEFOR Isotry ou structure BASE absente de cette "
                "base : ces tests nécessitent les données réelles de "
                "MOWGLI (ou une copie jetable).")

    def _make_payslip(self, wage, travel_allowance=0, children=0):
        employee = self.env['hr.employee'].create({
            'name': 'Employé de test MOWGLI',
            'company_id': self.company.id,
            'children': children,
        })
        contract = self.env['hr.contract'].create({
            'name': 'Contrat de test MOWGLI',
            'employee_id': employee.id,
            'company_id': self.company.id,
            'wage': wage,
            'travel_allowance': travel_allowance,
            'state': 'open',
            'struct_id': self.structure.id,
            'date_start': '2026-01-01',
        })
        payslip = self.env['hr.payslip'].create({
            'employee_id': employee.id,
            'contract_id': contract.id,
            'struct_id': self.structure.id,
            'date_from': '2026-01-01',
            'date_to': '2026-01-31',
        })
        payslip.action_compute_sheet()
        return payslip

    def test_paperformat_landscape_a4_sur_action(self):
        self.assertTrue(self.report, "Action de rapport introuvable")
        paperformat = self.report.paperformat_id
        self.assertTrue(paperformat, "Aucun paperformat lié à l'action")
        self.assertEqual(paperformat.format, 'A4')
        self.assertEqual(paperformat.orientation, 'Landscape')

    def test_rendu_html_bulletin_duplique(self):
        payslip = self._make_payslip(500000, travel_allowance=150000)
        net_line = payslip.line_ids.filtered(lambda l: l.code == 'NET')
        self.assertTrue(net_line, "Ligne NET absente")
        self.assertAlmostEqual(net_line.total, 602100)

        html, _report_type = self.env['ir.actions.report']._render_qweb_html(
            'mowgli_payroll_pcec.report_payslip_duplicate', payslip.ids)
        html = html.decode() if isinstance(html, bytes) else html

        self.assertEqual(html.count('NET À PAYER'), 2)
        self.assertEqual(html.count("Signature de l'employeur"), 2)
        self.assertEqual(html.count('Signature du salarié'), 2)

        # Deux copies : on isole chacune pour vérifier que chaque code y
        # apparaît (certains noms de règle sont identiques à leur code,
        # ex. OSTIE/IRSA, donc un simple comptage global serait ambigu).
        copies = html.split('mowgli_payslip_copy')
        self.assertEqual(
            len(copies), 3,
            "Le rendu ne contient pas exactement deux copies du bulletin")
        for copy_html in copies[1:]:
            for code in RULE_CODES:
                self.assertIn(
                    '>%s<' % code, copy_html,
                    "Code %s absent d'une des deux copies" % code)

        texte_lettres = self.company.currency_id.amount_to_text(
            net_line.total).capitalize()
        self.assertEqual(html.count(texte_lettres), 2)

    def test_rendu_pdf_une_page(self):
        try:
            subprocess.run(
                ['wkhtmltopdf', '--version'],
                capture_output=True, check=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            self.skipTest("wkhtmltopdf non disponible sur cette machine")

        try:
            import pypdf
        except ImportError:
            self.skipTest("pypdf non installé : impossible de compter les "
                           "pages du PDF généré")

        payslip = self._make_payslip(500000, travel_allowance=150000)
        # force_report_rendering : en mode test, _render_qweb_pdf retombe
        # sur le rendu HTML par défaut (pas assez de workers pour
        # wkhtmltopdf) ; on veut ici vraiment générer le PDF.
        pdf_content, _report_type = (
            self.env['ir.actions.report']
            .with_context(force_report_rendering=True)
            ._render_qweb_pdf(
                'mowgli_payroll_pcec.report_payslip_duplicate', payslip.ids))

        self.assertTrue(pdf_content.startswith(b'%PDF'))
        reader = pypdf.PdfReader(__import__('io').BytesIO(pdf_content))
        self.assertEqual(
            len(reader.pages), 1,
            "Le bulletin dupliqué doit tenir sur une seule page paysage")

    def test_sans_ligne_net_pas_de_bloc(self):
        payslip = self._make_payslip(500000, travel_allowance=150000)
        payslip.line_ids.filtered(lambda l: l.code == 'NET').unlink()

        html, _report_type = self.env['ir.actions.report']._render_qweb_html(
            'mowgli_payroll_pcec.report_payslip_duplicate', payslip.ids)
        html = html.decode() if isinstance(html, bytes) else html

        self.assertEqual(html.count('NET À PAYER'), 0)
        self.assertEqual(html.count('Arrêté en lettres'), 0)
