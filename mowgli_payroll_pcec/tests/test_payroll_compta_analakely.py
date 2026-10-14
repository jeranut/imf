# -*- coding: utf-8 -*-
"""Comptabilité de la paie pour AGENCE ANALAKELY : écritures réelles (S1, S2),
comportement sans comptes (S4) et script d'alignement des comptes. Suppose les
données réelles de MOWGLI (copie jetable). TransactionCase : rollback."""
from odoo.tests.common import TransactionCase, tagged

from .common import MowgliSmeTestMixin

MANAGER = 'hr_payroll_community.group_hr_payroll_community_manager'


@tagged('post_install', '-at_install')
class TestPayrollComptaAnalakely(MowgliSmeTestMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].search(
            [('name', '=', 'AGENCE ANALAKELY')], limit=1)
        cls.structure = cls.env['hr.payroll.structure'].search(
            [('code', '=', 'BASE')], limit=1)

    def setUp(self):
        super().setUp()
        if not self.company or not self.structure:
            self.skipTest("AGENCE ANALAKELY ou structure BASE absente.")
        self.Account = self.env['account.account'].sudo()
        self._mowgli_legacy_accounts(self.company)
        journal = self.env['account.journal'].search(
            [('company_id', '=', self.company.id), ('type', '=', 'general')],
            limit=1)
        self.company.write({'hr_payroll_entries': True,
                            'payroll_journal_id': journal.id})
        self.user = self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'paie_analakely', 'login': 'paie_analakely',
                'email': 'paie_analakely@example.com',
                'company_id': self.company.id,
                'company_ids': [(6, 0, self.company.ids)],
                'groups_id': [(6, 0, [
                    self.env.ref('base.group_user').id,
                    self.env.ref(MANAGER).id,
                    self.env.ref('account.group_account_invoice').id])]})

    def _slip(self, company=None, **allowances):
        company = company or self.company
        employee = self.env['hr.employee'].create(
            {'name': 'Salarié compta', 'company_id': company.id})
        contract = self.env['hr.contract'].create(dict({
            'name': 'Contrat compta', 'employee_id': employee.id,
            'company_id': company.id, 'wage': 750000,
            'travel_allowance': 150000, 'state': 'open',
            'struct_id': self.structure.id, 'date_start': '2026-01-01',
        }, **allowances))
        slip = self.env['hr.payslip'].with_user(
            self.user if company == self.company else self.env.user
        ).with_company(company).create({
                'employee_id': employee.id, 'contract_id': contract.id,
                'struct_id': self.structure.id, 'company_id': company.id,
                'date_from': '2026-10-01', 'date_to': '2026-10-10'})
        slip.action_compute_sheet()
        slip.action_payslip_verify()
        slip.action_payslip_done()
        return slip

    def _by_account(self, move):
        totals = {}
        for line in move.line_ids:
            entry = totals.setdefault(line.account_id.code, [0.0, 0.0])
            entry[0] += line.debit
            entry[1] += line.credit
        return totals

    def _check_move(self, slip, gross, credits):
        move = slip.move_id
        self.assertEqual(move.state, 'posted')
        totals = self._by_account(move)
        self.assertEqual(set(totals), {'652100', '315000'},
                         "Aucune ligne sur GROSS/NETIMP ni compte inattendu")
        self.assertAlmostEqual(totals['652100'][0], gross)
        self.assertAlmostEqual(totals['652100'][1], 0.0)
        self.assertAlmostEqual(totals['315000'][1], sum(credits))
        self.assertAlmostEqual(totals['315000'][0], 0.0)
        self.assertAlmostEqual(sum(t[0] for t in totals.values()),
                               sum(t[1] for t in totals.values()))
        return totals

    def test_s1_salaire_et_transport(self):
        slip = self._slip()
        self.assertEqual(
            {l.code: l.total for l in slip.line_ids if l.code in (
                'GROSS', 'CNAPS', 'OSTIE', 'IRSA', 'NET')},
            {'GROSS': 900000, 'CNAPS': -9000, 'OSTIE': -9000,
             'IRSA': -83900, 'NET': 798100})
        self._check_move(slip, 900000, [9000, 9000, 83900, 798100])

    def test_s2_avec_logement_et_repas(self):
        slip = self._slip(hra=50000, meal_allowance=30000)
        self.assertEqual(
            {l.code: l.total for l in slip.line_ids if l.code in (
                'GROSS', 'CNAPS', 'OSTIE', 'IRSA', 'NET')},
            {'GROSS': 980000, 'CNAPS': -9800, 'OSTIE': -9800,
             'IRSA': -99580, 'NET': 860820})
        self._check_move(slip, 980000, [9800, 9800, 99580, 860820])

    def test_s4_societe_sans_comptes_aucune_ecriture(self):
        """Comportement actuel (non corrigé) : sans comptes sur les règles,
        la validation réussit mais ne génère AUCUNE écriture."""
        other = self.env['res.company'].search(
            [('id', '!=', self.company.id), ('chart_template', '!=', False)],
            limit=1)
        if not other:
            self.skipTest("Pas de seconde société avec plan.")
        for rule in self.structure.rule_ids.sudo():
            rule.with_company(other).write(
                {'debit_account_id': False, 'credit_account_id': False})
        other.write({'hr_payroll_entries': True,
                     'payroll_journal_id': self.env['account.journal'].search(
                         [('company_id', '=', other.id)], limit=1).id})
        slip = self._slip(company=other)
        self.assertEqual(slip.state, 'done')
        self.assertFalse(slip.move_id)

    # --- script d'alignement ------------------------------------------
    def _rule(self, code):
        return self.structure.rule_ids.filtered(lambda r: r.code == code)

    def test_align_rejeu_zero_ecriture(self):
        Rule = self.env['hr.salary.rule']
        Rule._mowgli_align_company_accounts(self.company)
        props = self.env['ir.property'].sudo().search(
            [('res_id', 'like', 'hr.salary.rule,%')])
        stamps = dict(props.mapped(lambda p: (p.id, p.write_date)))
        rows = Rule._mowgli_align_company_accounts(self.company)
        self.assertFalse([r for r in rows if r['statut'] == 'ecrit'])
        props.invalidate_recordset()
        self.assertEqual(
            stamps, dict(props.mapped(lambda p: (p.id, p.write_date))))

    def test_align_corrige_une_regle_mal_configuree(self):
        Rule = self.env['hr.salary.rule']
        basic = self._rule('BASIC').sudo().with_company(self.company)
        wrong = self.Account.search([
            ('code', '=', '315000'), ('company_id', '=', self.company.id)],
            limit=1)
        basic.write({'debit_account_id': wrong.id})
        rows = Rule._mowgli_align_company_accounts(self.company)
        done = [r for r in rows if r['statut'] == 'ecrit']
        self.assertIn(('BASIC', 'debit', '315000', '652100'),
                      [(r['regle'], r['role'], r['avant'], r['apres']) for r in done])
        self.assertEqual(basic.debit_account_id.code, '652100')

    def test_align_compte_absent_signale_sans_creation(self):
        Rule = self.env['hr.salary.rule']
        account = self.Account.search([
            ('code', '=', '652100'), ('company_id', '=', self.company.id)],
            limit=1)
        count = self.Account.search_count([])
        account.write({'code': 'ZZ6521'})
        rows = Rule._mowgli_align_company_accounts(self.company)
        missing = [r for r in rows if r['statut'] == 'compte_absent']
        self.assertTrue(missing)
        self.assertTrue(all(r['cible'] == '652100' for r in missing))
        self.assertEqual(self.Account.search_count([]), count)
