# -*- coding: utf-8 -*-
"""Tests du moteur de paie malgache (IRSA, plafond CNAPS/OSTIE mutualisé).

Les règles hr.salary.rule IRSA/CNAPS_SAL/OSTIE_SAL/CNAPS_PAT/OSTIE_PAT
officielles ne sont pas versionnées dans ce module (elles sont configurées
directement dans la base cible) et ne doivent pas être modifiées ici. Ces
tests créent donc leurs propres règles locales, reproduisant le barème
officiel malgache (source: DGI, barème IRSA 2024/2025 à 5 tranches +
minimum de perception de 3 000 Ar), uniquement pour valider le mécanisme
(plafonnement CNAPS/OSTIE via get_cnaps_ceiling(), plancher IRSA). Ces
enregistrements sont créés dans une transaction de test qui est annulée à
la fin de chaque test : aucune donnée réelle n'est modifiée.
"""
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

# Barème IRSA 2024/2025 (DGI Madagascar) : base arrondie à la centaine
# inférieure, tranches à 0/5/10/15/20/25%, réduction de 2 000 Ar par
# personne à charge, minimum de perception de 3 000 Ar dès que la base
# imposable dépasse 350 000 Ar.
IRSA_AMOUNT_PYTHON_COMPUTE = """
base = BASIC - CNAPS_SAL - OSTIE_SAL
base = int(base // 100) * 100
dependents = employee.dependent_count or 0
if base <= 350000:
    result = 0.0
else:
    irsa = (
        min(max(0, base - 350000), 50000) * 0.05
        + min(max(0, base - 400000), 100000) * 0.10
        + min(max(0, base - 500000), 100000) * 0.15
        + min(max(0, base - 600000), 3400000) * 0.20
        + max(0, base - 4000000) * 0.25
        - 2000 * dependents
    )
    result = max(3000, irsa)
"""


@tagged('post_install', '-at_install')
class TestHrPayrollMg(TransactionCase):
    """Vérifie l'IRSA (tranches + plancher) et le plafond CNAPS/OSTIE."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'Société Test MG',
            'sme_amount': 262680,
            'cnaps_ceiling_multiplier': 8,
        })
        category_basic = cls.env.ref('hr_payroll_community.BASIC')
        category_ded = cls.env.ref('hr_payroll_community.DED')
        category_comp = cls.env.ref('hr_payroll_community.COMP')

        cls.rule_basic = cls.env['hr.salary.rule'].create({
            'name': 'Salaire de base',
            'code': 'BASIC',
            'sequence': 1,
            'category_id': category_basic.id,
            'company_id': cls.company.id,
            'amount_select': 'code',
            'amount_python_compute': 'result = contract.wage',
        })
        cls.rule_cnaps_sal = cls.env['hr.salary.rule'].create({
            'name': 'CNAPS salarial',
            'code': 'CNAPS_SAL',
            'sequence': 10,
            'category_id': category_ded.id,
            'company_id': cls.company.id,
            'amount_select': 'code',
            'amount_python_compute':
                'result = round(contract.get_cnaps_ceiling(BASIC) * 0.01)',
        })
        cls.rule_ostie_sal = cls.env['hr.salary.rule'].create({
            'name': 'OSTIE salarial',
            'code': 'OSTIE_SAL',
            'sequence': 11,
            'category_id': category_ded.id,
            'company_id': cls.company.id,
            'amount_select': 'code',
            'amount_python_compute':
                'result = round(contract.get_cnaps_ceiling(BASIC) * 0.01)',
        })
        cls.rule_cnaps_pat = cls.env['hr.salary.rule'].create({
            'name': 'CNAPS patronal',
            'code': 'CNAPS_PAT',
            'sequence': 12,
            'category_id': category_comp.id,
            'company_id': cls.company.id,
            'amount_select': 'code',
            'amount_python_compute':
                'result = round(contract.get_cnaps_ceiling(BASIC) * 0.13)',
        })
        cls.rule_ostie_pat = cls.env['hr.salary.rule'].create({
            'name': 'OSTIE patronal',
            'code': 'OSTIE_PAT',
            'sequence': 13,
            'category_id': category_comp.id,
            'company_id': cls.company.id,
            'amount_select': 'code',
            'amount_python_compute':
                'result = round(contract.get_cnaps_ceiling(BASIC) * 0.05)',
        })
        cls.rule_irsa = cls.env['hr.salary.rule'].create({
            'name': 'IRSA',
            'code': 'IRSA',
            'sequence': 20,
            'category_id': category_ded.id,
            'company_id': cls.company.id,
            'amount_select': 'code',
            'amount_python_compute': IRSA_AMOUNT_PYTHON_COMPUTE,
        })
        cls.structure = cls.env['hr.payroll.structure'].create({
            'name': 'Structure Test MG',
            'code': 'TESTMG',
            'company_id': cls.company.id,
            'rule_ids': [(6, 0, [
                cls.rule_basic.id, cls.rule_cnaps_sal.id,
                cls.rule_ostie_sal.id, cls.rule_cnaps_pat.id,
                cls.rule_ostie_pat.id, cls.rule_irsa.id,
            ])],
        })
        cls.calendar = cls.env['resource.calendar'].create({
            'name': 'Calendrier Test MG',
            'company_id': cls.company.id,
        })
        # Un salarié avec une personne à charge, comme utilisé par les
        # exemples de calcul ci-dessous.
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Salarié Test MG',
            'company_id': cls.company.id,
            'dependent_count': 1,
        })

    def _compute_payslip(self, wage):
        """Crée un contrat au salaire donné et calcule son bulletin"""
        contract = self.env['hr.contract'].create({
            'name': 'Contrat Test MG',
            'employee_id': self.employee.id,
            'company_id': self.company.id,
            'resource_calendar_id': self.calendar.id,
            'struct_id': self.structure.id,
            'wage': wage,
            'date_start': '2024-01-01',
            'state': 'open',
        })
        payslip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'contract_id': contract.id,
            'struct_id': self.structure.id,
            'date_from': '2024-01-01',
            'date_to': '2024-01-31',
            'company_id': self.company.id,
        })
        payslip.action_compute_sheet()
        return payslip

    def test_irsa_nominal(self):
        """Brut 800 000 Ar : IRSA ≈ 62 300, CNAPS+OSTIE salarial = 16 000"""
        payslip = self._compute_payslip(800000)
        self.assertAlmostEqual(
            payslip.get_salary_line_total('IRSA'), 62300, delta=1)
        cnaps_ostie_sal = (payslip.get_salary_line_total('CNAPS_SAL')
                          + payslip.get_salary_line_total('OSTIE_SAL'))
        self.assertAlmostEqual(cnaps_ostie_sal, 16000, delta=1)

    def test_cnaps_ceiling(self):
        """Brut > plafond (2 101 440 Ar) : CNAPS/OSTIE salarial plafonnés
        à 21 014 Ar chacun"""
        payslip = self._compute_payslip(2500000)
        self.assertAlmostEqual(
            payslip.get_salary_line_total('CNAPS_SAL'), 21014, delta=1)
        self.assertAlmostEqual(
            payslip.get_salary_line_total('OSTIE_SAL'), 21014, delta=1)

    def test_irsa_floor(self):
        """Bas salaire (au-dessus du seuil d'exonération) : IRSA au
        plancher de 3 000 Ar"""
        payslip = self._compute_payslip(360000)
        self.assertAlmostEqual(
            payslip.get_salary_line_total('IRSA'), 3000, delta=1)
