# -*- coding: utf-8 -*-
"""Tests d'intégration Lot 2 (retenue sur bulletin). Comme
mowgli_payroll_pcec/tests/test_payroll_pcec.py, ces tests supposent la présence des données
réelles de production (société 'CEFOR Isotry', structure BASE avec BASIC/GROSS/CNAPS/OSTIE/
NETIMP/IRSA/NET, + la règle LOAN posée par ce module) : à exécuter sur une copie jetable de
MOWGLI, jamais sur la production. TransactionCase : rollback en fin de chaque test."""
import base64
from datetime import timedelta

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestMicrofinancePayrollSalaryDeduction(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].search([('name', '=', 'CEFOR Isotry')], limit=1)
        cls.structure = cls.env['hr.payroll.structure'].search([('code', '=', 'BASE')], limit=1)

    def setUp(self):
        super().setUp()
        if not self.company or not self.structure or not self.structure.rule_ids.filtered(
            lambda r: r.code == 'LOAN'
        ):
            self.skipTest(
                "Société CEFOR Isotry, structure BASE ou règle LOAN absente de cette base : "
                "ces tests nécessitent les données réelles de MOWGLI (ou une copie jetable) "
                "avec microfinance_payroll_loan installé.")
        # Neutralise les fonds bailleurs actifs réels (sinon action_activate() bloque), même
        # mécanisme que MicrofinanceNoFundMixin côté microfinance_loan_management.
        self.env['microfinance.fond.credit'].sudo().search([('active', '=', True)]).write({'active': False})

        general_journal = self.env['account.journal'].search([
            ('company_id', '=', self.company.id), ('type', '=', 'general'), ('code', '=', 'OD'),
        ], limit=1)
        self.company.write({'payroll_journal_id': general_journal.id})

        cash_account = self.env['account.account'].create({
            'name': 'Caisse test paie', 'code': 'TPAYCASH',
            'account_type': 'asset_cash', 'company_id': self.company.id,
        })
        self.loan_journal = self.env['account.journal'].create({
            'name': 'Caisse test paie', 'code': 'TPAYCRE', 'type': 'cash',
            'company_id': self.company.id, 'default_account_id': cash_account.id,
        })
        self.principal_account = self.env['account.account'].create({
            'name': 'Prêts clients test paie', 'code': 'TPAYPRET',
            'account_type': 'asset_current', 'company_id': self.company.id,
        })
        self.interest_account = self.env['account.account'].create({
            'name': 'Intérêts test paie', 'code': 'TPAYINT',
            'account_type': 'income', 'company_id': self.company.id,
        })
        monthly = self.env.ref('microfinance_loan_management.repayment_frequency_monthly')
        self.product = self.env['microfinance.loan.product'].create({
            'name': 'Produit paie test', 'code': 'PPAYTEST',
            'min_amount': 100.0, 'max_amount': 10000000.0,
            'min_term': 1, 'max_term': 36,
            'interest_rate': 0.0, 'interest_method': 'flat',
            'installment_rounding_unit': 0,
            'repayment_frequency_mode': 'fixed', 'repayment_frequency_id': monthly.id,
            'disbursement_journal_id': self.loan_journal.id,
            'payment_journal_id': self.loan_journal.id,
            'account_principal_individuel_id': self.principal_account.id,
            'account_principal_groupe_id': self.principal_account.id,
            'account_interets_recus_individuel_id': self.interest_account.id,
            'account_interets_recus_groupe_id': self.interest_account.id,
            'company_id': self.company.id,
            'employee_authorized': True,
        })
        self.client_partner = self.env['res.partner'].create({
            'name': 'Client Salarié Test Paie', 'microfinance_partner_type': 'client',
            'company_id': self.company.id,
        })
        self.employee = self.env['hr.employee'].create({
            'name': 'Salarié Test Prêt', 'company_id': self.company.id,
        })
        self.employee.microfinance_partner_id = self.client_partner.id
        self.contract = self.env['hr.contract'].create({
            'name': 'Contrat Salarié Test Prêt', 'employee_id': self.employee.id,
            'company_id': self.company.id, 'wage': 1000000.0, 'state': 'open',
            'struct_id': self.structure.id, 'date_start': '2026-01-01',
        })
        self.employee.contract_id = self.contract.id

    def _create_loan(self, **kwargs):
        vals = {
            'partner_id': self.client_partner.id,
            'product_id': self.product.id,
            'loan_amount': 600000.0,
            'term': 6,
            'signed_contract': base64.b64encode(b'test signed contract'),
            'signed_contract_filename': 'contrat_signe_test.pdf',
        }
        vals.update(kwargs)
        return self.env['microfinance.loan'].create(vals)

    def _activate_loan(self, **kwargs):
        loan = self._create_loan(**kwargs)
        loan.action_generate_schedule()
        loan.action_start_enquete()
        loan.action_ca_review()
        loan.action_cdag_review()
        loan.action_view_applications()
        loan.application_ids.write({'committee_first_decision': 'accepted'})
        loan.action_approve()
        loan._activate_with_auto_confirm()
        loan.action_process_disbursement()
        self._rebase_due_dates_to_today(loan)
        return loan

    def _rebase_due_dates_to_today(self, loan):
        """Décale l'échéancier généré (ancré sur la date d'activation réelle, donc dans le
        futur par rapport à aujourd'hui) pour que la 1ère échéance tombe aujourd'hui : sans
        cela, account.move._post() diffère silencieusement la comptabilisation d'un bulletin
        daté dans le futur (move.state reste 'draft', aucune exception), ce qui est un
        comportement standard d'Odoo sans rapport avec la retenue sur salaire elle-même."""
        installments = loan.installment_ids.sorted('due_date')
        if not installments:
            return
        shift = fields.Date.today() - installments[0].due_date
        for installment in installments:
            installment.due_date = installment.due_date + shift

    def _make_payslip(self, date_from, date_to):
        return self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'contract_id': self.contract.id,
            'struct_id': self.structure.id,
            'date_from': date_from,
            'date_to': date_to,
        })

    def _line_total(self, payslip, code):
        line = payslip.line_ids.filtered(lambda l: l.code == code)
        return line.total if line else 0.0

    def _account_totals(self, move):
        totals = {}
        for line in move.line_ids:
            entry = totals.setdefault(line.account_id.code, [0.0, 0.0])
            entry[0] += line.debit
            entry[1] += line.credit
        return totals

    def test_loan_deduction_amounts(self):
        loan = self._activate_loan()
        first_due = loan.installment_ids.sorted('due_date')[0].due_date
        payslip = self._make_payslip(first_due.replace(day=1), first_due)
        payslip.action_compute_sheet()
        self.assertAlmostEqual(self._line_total(payslip, 'LOAN'), -100000.0)
        self.assertAlmostEqual(self._line_total(payslip, 'NETIMP'), 980000.0)
        self.assertAlmostEqual(self._line_total(payslip, 'IRSA'), -103500.0)
        self.assertAlmostEqual(self._line_total(payslip, 'NET'), 776500.0)

    def test_month_without_installment_no_loan_line(self):
        loan = self._activate_loan()
        first_due = loan.installment_ids.sorted('due_date')[0].due_date
        early_to = first_due - timedelta(days=50)
        early_from = early_to - timedelta(days=29)
        payslip = self._make_payslip(early_from, early_to)
        payslip.action_compute_sheet()
        self.assertAlmostEqual(self._line_total(payslip, 'LOAN'), 0.0)
        self.assertAlmostEqual(self._line_total(payslip, 'NET'), 876500.0)

    def test_undisbursed_or_draft_loan_never_deducted(self):
        draft_loan = self._create_loan(loan_amount=60000.0, term=1)
        self.assertEqual(draft_loan.state, 'draft')

        undisbursed = self._create_loan(loan_amount=60000.0, term=1)
        undisbursed.action_generate_schedule()
        undisbursed.action_start_enquete()
        undisbursed.action_ca_review()
        undisbursed.action_cdag_review()
        undisbursed.action_view_applications()
        undisbursed.application_ids.write({'committee_first_decision': 'accepted'})
        undisbursed.action_approve()
        undisbursed._activate_with_auto_confirm()  # actif, mais disbursement_date vide
        self.assertTrue(undisbursed.salary_deduction)
        self.assertFalse(undisbursed.disbursement_date)

        payslip = self._make_payslip('2026-02-01', '2026-02-28')
        payslip.action_compute_sheet()
        self.assertAlmostEqual(self._line_total(payslip, 'LOAN'), 0.0)

    def test_other_company_loan_never_deducted(self):
        other_company = self.env['res.company'].search(
            [('id', '!=', self.company.id), ('agency_code', '!=', False)], limit=1)
        if not other_company:
            self.skipTest("Pas de seconde agence disponible sur cette base pour ce test.")
        other_partner = self.client_partner.copy({
            'name': 'Client Autre Agence Test Paie', 'company_id': other_company.id,
        })
        self.employee.microfinance_partner_id = other_partner.id
        other_product = self.product.copy({
            'code': 'PPAYTEST2', 'company_id': other_company.id,
        })
        other_loan = self._create_loan(
            partner_id=other_partner.id, product_id=other_product.id,
            loan_amount=60000.0, term=1, company_id=other_company.id,
        )
        self.assertEqual(other_loan.company_id, other_company)

        payslip = self._make_payslip('2026-02-01', '2026-02-28')
        payslip.action_compute_sheet()
        self.assertAlmostEqual(self._line_total(payslip, 'LOAN'), 0.0)

    def test_validation_creates_repayment_and_balances(self):
        loan = self._activate_loan()
        first_due = loan.installment_ids.sorted('due_date')[0].due_date
        payslip = self._make_payslip(first_due.replace(day=1), first_due)
        payslip.action_payslip_verify()
        payslip.action_payslip_done()

        self.assertAlmostEqual(loan.balance_total, 500000.0)

        move = payslip.move_id
        self.assertEqual(move.state, 'posted')
        totals = self._account_totals(move)
        self.assertAlmostEqual(totals['652100'][0], 1000000.0)
        self.assertAlmostEqual(
            totals['315000'][1], 10000 + 10000 + 103500 + 776500 + 100000)
        self.assertAlmostEqual(sum(t[0] for t in totals.values()), sum(t[1] for t in totals.values()))

        payment = self.env['microfinance.loan.payment'].sudo().search([
            ('payslip_id', '=', payslip.id), ('loan_id', '=', loan.id),
        ])
        self.assertEqual(len(payment), 1)
        self.assertAlmostEqual(payment.amount, 100000.0)
        self.assertEqual(payment.state, 'posted')

        repay_totals = self._account_totals(payment.move_id)
        self.assertAlmostEqual(repay_totals['315000'][0], 100000.0)
        self.assertAlmostEqual(repay_totals['TPAYPRET'][1], 100000.0)

        net_transit_bulletin = totals['315000'][1] - totals['315000'][0]
        net_transit_remboursement = repay_totals['315000'][1] - repay_totals['315000'][0]
        self.assertAlmostEqual(
            net_transit_bulletin + net_transit_remboursement,
            10000 + 10000 + 103500 + 776500,
            msg="Le transit (315) doit revenir à zéro sur la part retenue.",
        )

    def test_insufficient_net_caps_and_carries_over(self):
        loan = self._activate_loan()
        first_due = loan.installment_ids.sorted('due_date')[0].due_date
        self.contract.wage = 50000.0  # net avant pret (46 000) sous le plafond 100 000
        payslip = self._make_payslip(first_due.replace(day=1), first_due)
        payslip.action_payslip_verify()
        payslip.action_payslip_done()

        retained = abs(self._line_total(payslip, 'LOAN'))
        self.assertGreater(retained, 0.0)
        self.assertLess(retained, 100000.0)

        installment = loan.installment_ids.sorted('due_date')[0]
        self.assertGreater(installment.residual_amount, 0.0)
        if len(loan.installment_ids) > 1:
            second_due = loan.installment_ids.sorted('due_date')[1].due_date
            carried = sum(loan.installment_ids.filtered(
                lambda i: i.due_date <= second_due and i.residual_amount > 0.01
            ).mapped('residual_amount'))
            self.assertAlmostEqual(carried, installment.residual_amount + 100000.0)

    def test_last_payslip_closes_loan(self):
        loan = self._activate_loan(loan_amount=100000.0, term=1)
        due_date = loan.installment_ids[0].due_date
        payslip = self._make_payslip(due_date.replace(day=1), due_date)
        payslip.action_payslip_verify()
        payslip.action_payslip_done()
        self.assertEqual(loan.state, 'closed')
        self.assertAlmostEqual(loan.balance_total, 0.0)

    def test_cancel_payslip_reverses_payment(self):
        loan = self._activate_loan()
        first_due = loan.installment_ids.sorted('due_date')[0].due_date
        payslip = self._make_payslip(first_due.replace(day=1), first_due)
        payslip.action_payslip_verify()
        payslip.action_payslip_done()
        payment = self.env['microfinance.loan.payment'].sudo().search([
            ('payslip_id', '=', payslip.id),
        ])
        self.assertEqual(payment.state, 'posted')

        payslip.action_payslip_cancel()
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'cancelled')
        self.assertTrue(payment.reversal_move_id)
        first_installment = loan.installment_ids.sorted('due_date')[0]
        self.assertAlmostEqual(first_installment.residual_amount, 100000.0)

    def test_recompute_draft_does_not_create_payment(self):
        loan = self._activate_loan()
        first_due = loan.installment_ids.sorted('due_date')[0].due_date
        payslip = self._make_payslip(first_due.replace(day=1), first_due)
        payslip.action_payslip_verify()
        payslip.action_compute_sheet()
        count = self.env['microfinance.loan.payment'].sudo().search_count([
            ('payslip_id', '=', payslip.id),
        ])
        self.assertEqual(count, 0, "Un recalcul en brouillon/attente ne doit rien créer.")

    def test_revalidate_after_cancel_does_not_double_active_payment(self):
        loan = self._activate_loan()
        first_due = loan.installment_ids.sorted('due_date')[0].due_date
        payslip = self._make_payslip(first_due.replace(day=1), first_due)
        payslip.action_payslip_verify()
        payslip.action_payslip_done()
        payslip.action_payslip_draft()
        payslip.action_payslip_verify()
        payslip.action_payslip_done()

        payments = self.env['microfinance.loan.payment'].sudo().search([
            ('payslip_id', '=', payslip.id),
        ])
        posted = payments.filtered(lambda p: p.state == 'posted')
        self.assertEqual(len(posted), 1, "Une seule retenue active à la fois pour ce bulletin.")
        self.assertAlmostEqual(posted.amount, 100000.0)

    def test_manual_payment_creation_still_blocked(self):
        # En tant que superutilisateur (par défaut dans TransactionCase), les droits
        # ir.model.access.csv ne s'appliquent pas : on se place explicitement dans la peau
        # d'un caissier (droits réels les plus proches d'un utilisateur paie) pour vérifier
        # que la création manuelle hors guichet reste bloquée malgré l'exception étroite de
        # ce module (D).
        loan = self._activate_loan()
        cashier = self.env['res.users'].create({
            'name': 'Caissier Test Paie',
            'login': 'caissier_test_paie@example.com',
            'email': 'caissier_test_paie@example.com',
            'company_id': self.company.id,
            'company_ids': [(4, self.company.id)],
            'groups_id': [(4, self.env.ref('microfinance_loan_management.group_microfinance_cashier').id)],
        })
        from odoo.exceptions import AccessError
        with self.assertRaises(AccessError):
            self.env['microfinance.loan.payment'].with_user(cashier).create({
                'loan_id': loan.id,
                'amount': 1000.0,
                'journal_id': self.loan_journal.id,
            })
