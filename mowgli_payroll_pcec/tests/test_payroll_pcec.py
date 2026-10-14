# -*- coding: utf-8 -*-
"""Tests d'intégration pour la structure BASE (CEFOR Isotry).

Ces tests supposent la présence des données réelles de production
(société 'CEFOR Isotry', structure BASE avec les règles BASIC, Travel,
GROSS, CNAPS, OSTIE, IRSA, NET). Ils sont donc à exécuter sur une copie
jetable de la base MOWGLI, jamais sur la base de production elle-même.
TransactionCase place chaque test dans une transaction annulée (rollback)
à la fin : aucune donnée créée par ces tests n'est conservée.
"""
from odoo.tests.common import TransactionCase, tagged
from odoo.addons.mowgli_payroll_pcec.tests.common import MowgliSmeTestMixin


@tagged('post_install', '-at_install')
class TestPayrollPcec(MowgliSmeTestMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].search(
            [('name', '=', 'CEFOR Isotry')], limit=1)
        cls.structure = cls.env['hr.payroll.structure'].search(
            [('code', '=', 'BASE')], limit=1)
        if cls.company and cls.structure:
            cls.env['hr.salary.rule']._mowgli_setup_payroll_rules()

    def setUp(self):
        super().setUp()
        self._mowgli_add_test_sme()
        if not self.company or not self.structure:
            self.skipTest(
                "Société CEFOR Isotry ou structure BASE absente de cette "
                "base : ces tests nécessitent les données réelles de "
                "MOWGLI (ou une copie jetable).")

    def _make_payslip(self, wage, children=0):
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

    def _line_total(self, payslip, code):
        line = payslip.line_ids.filtered(lambda l: l.code == code)
        self.assertTrue(line, "Ligne %s absente du bulletin" % code)
        return line.total

    def test_cas_1_000_000_sans_enfant(self):
        payslip = self._make_payslip(1000000)
        self.assertAlmostEqual(self._line_total(payslip, 'GROSS'), 1000000)
        self.assertAlmostEqual(self._line_total(payslip, 'CNAPS'), -10000)
        self.assertAlmostEqual(self._line_total(payslip, 'OSTIE'), -10000)
        self.assertAlmostEqual(self._line_total(payslip, 'NETIMP'), 980000)
        self.assertAlmostEqual(self._line_total(payslip, 'IRSA'), -103500)
        self.assertAlmostEqual(self._line_total(payslip, 'NET'), 876500)

    def test_cas_2_enfants(self):
        payslip = self._make_payslip(1000000, children=2)
        self.assertAlmostEqual(self._line_total(payslip, 'IRSA'), -99500)

    def test_cas_minimum_irsa(self):
        payslip = self._make_payslip(300000)
        self.assertAlmostEqual(self._line_total(payslip, 'IRSA'), -3000)

    def test_ecriture_comptable_validation(self):
        """Configure temporairement des comptes/journal (annulés par le
        rollback de fin de test) pour vérifier l'écriture générée à la
        validation. Comptes PCEC utilisés : 652100 (le plus proche de
        6521 Rémunérations du personnel dans le plan Odoo actuel, cf.
        rapport d'audit - écart de libellé connu et non corrigé ici) en
        débit, 315000 (Créditeurs divers, conforme au PCEC) en crédit."""
        self.company.write({'hr_payroll_entries': True})
        journal = self.env['account.journal'].search(
            [('company_id', '=', self.company.id), ('type', '=', 'general')],
            limit=1)
        self.company.write({'payroll_journal_id': journal.id})

        debit_account = self.env['account.account'].search(
            [('code', '=', '652100'), ('company_id', '=', self.company.id)],
            limit=1)
        credit_account = self.env['account.account'].search(
            [('code', '=', '315000'), ('company_id', '=', self.company.id)],
            limit=1)
        self.assertTrue(debit_account and credit_account,
                        "Comptes 652100/315000 absents du plan de la "
                        "société de test")

        rules = {r.code: r for r in self.structure.rule_ids}
        rules['BASIC'].write({'debit_account_id': debit_account.id})
        for code in ('CNAPS', 'OSTIE', 'IRSA', 'NET'):
            rules[code].write({'credit_account_id': credit_account.id})

        payslip = self._make_payslip(1000000)
        payslip.action_payslip_verify()
        payslip.action_payslip_done()

        move = payslip.move_id
        self.assertTrue(move, "Aucune écriture comptable générée")
        self.assertEqual(move.state, 'posted')

        total_debit = sum(move.line_ids.mapped('debit'))
        total_credit = sum(move.line_ids.mapped('credit'))
        self.assertAlmostEqual(total_debit, total_credit,
                               msg="Écriture non équilibrée")
        self.assertAlmostEqual(total_debit, 1000000)

        debit_lines = move.line_ids.filtered(lambda l: l.debit)
        credit_lines = move.line_ids.filtered(lambda l: l.credit)
        # Une seule ligne de débit (BASIC -> 652100) et une seule ligne de
        # crédit car CNAPS/OSTIE/IRSA/NET pointent tous vers 315000 et sont
        # fusionnés par _prepare_account_move_line_vals (cf. point 10 du
        # rapport d'audit : pas de lignes séparées par règle).
        self.assertEqual(len(debit_lines), 1)
        self.assertEqual(debit_lines.account_id.code, '652100')
        self.assertAlmostEqual(debit_lines.debit, 1000000)

        self.assertEqual(len(credit_lines), 1)
        self.assertEqual(credit_lines.account_id.code, '315000')
        self.assertAlmostEqual(
            credit_lines.credit, 10000 + 10000 + 103500 + 876500)
