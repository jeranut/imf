# -*- coding: utf-8 -*-
"""Journal CSOC, registre des cotisations, compte 652500. Suppose les données
réelles de MOWGLI (copie jetable). TransactionCase : rollback automatique."""
from unittest.mock import patch

from odoo import fields
from odoo.addons.mowgli_payroll_pcec.tests.common import MowgliSmeTestMixin
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestContributions(MowgliSmeTestMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].search(
            [('name', 'in', ['AGENCE ANALAKELY', 'CEFOR Isotry'])], limit=1)
        cls.structure = cls.env['hr.payroll.structure'].search(
            [('code', '=', 'BASE')], limit=1)

    def setUp(self):
        super().setUp()
        if not self.company or not self.structure:
            self.skipTest("Données MOWGLI absentes de cette base.")
        # Société active = société du bulletin (la note de crédit copiée prend la société active).
        self.env = self.env(context=dict(
            self.env.context, allowed_company_ids=[self.company.id]))
        self._mowgli_add_test_sme(250000.0)
        self._mowgli_legacy_accounts(self.company)
        self.Account = self.env['account.account'].sudo()
        self.Contribution = self.env['mowgli.payroll.contribution']
        self.Contribution._setup_all()
        journal = self.env['account.journal'].search(
            [('company_id', '=', self.company.id), ('type', '=', 'general'),
             ('code', '!=', 'CSOC')], limit=1)
        self.company.write({'hr_payroll_entries': True,
                            'payroll_journal_id': journal.id})

    def _slip(self, wage=700000, children=1, date_from='2026-09-01',
              date_to='2026-09-30', validate=True):
        employee = self.env['hr.employee'].create({
            'name': 'Rakoto test', 'company_id': self.company.id,
            'children': children})
        contract = self.env['hr.contract'].create({
            'name': 'Contrat test', 'employee_id': employee.id,
            'company_id': self.company.id, 'wage': wage, 'state': 'open',
            'struct_id': self.structure.id, 'date_start': '2026-01-01'})
        slip = self.env['hr.payslip'].create({
            'name': 'Bulletin test cotisations',
            'employee_id': employee.id, 'contract_id': contract.id,
            'struct_id': self.structure.id, 'company_id': self.company.id,
            'date_from': date_from, 'date_to': date_to})
        if validate:
            slip.action_payslip_verify()
            slip.action_payslip_done()
        return slip

    def _by_account(self, moves):
        totals = {}
        for line in moves.line_ids:
            entry = totals.setdefault(line.account_id.code, [0.0, 0.0])
            entry[0] += line.debit
            entry[1] += line.credit
        return totals

    def _csoc_moves(self, slip):
        move = slip.mowgli_csoc_move_id
        return move | move.reversal_move_id

    # --- cas Rakoto ------------------------------------------------------
    def test_rakoto_ecritures_et_registre(self):
        slip = self._slip()
        main = self._by_account(slip.move_id)
        self.assertEqual(main, {'652100': [700000.0, 0.0], '315000': [0.0, 700000.0]})
        csoc = slip.mowgli_csoc_move_id
        self.assertEqual(csoc.journal_id.code, 'CSOC')
        self.assertEqual(self._by_account(csoc),
                         {'652500': [126000.0, 0.0], '315000': [0.0, 126000.0]})
        self.assertEqual(sum(csoc.line_ids.mapped('debit')), sum(csoc.line_ids.mapped('credit')))
        rows = {r.rule_code: r for r in slip.mowgli_contribution_ids}
        self.assertEqual({k: (v.organisme, v.nature, v.montant) for k, v in rows.items()}, {
            'CNAPS': ('cnaps', 'salarie', 7000.0), 'OSTIE': ('ostie', 'salarie', 7000.0),
            'IRSA': ('irsa', 'impot', 42700.0),
            'CNAPS_ER': ('cnaps', 'patronal', 91000.0),
            'OSTIE_ER': ('ostie', 'patronal', 35000.0)})
        self.assertEqual(rows['CNAPS_ER'].base, 700000.0)
        self.assertAlmostEqual(rows['CNAPS_ER'].taux, 0.13)
        self.assertEqual(rows['CNAPS_ER'].move_id, csoc)
        self.assertEqual({r.state for r in rows.values()}, {'a_verser'})
        # net inchangé : les parts patronales ne touchent pas le salarié
        self.assertEqual({l.code: l.total for l in slip.line_ids}['NET'], 643300.0)

    def test_pivot_mois_organisme(self):
        self._slip()
        groups = self.Contribution.read_group(
            [('mois', '=', '2026-09'), ('company_id', '=', self.company.id)],
            ['montant:sum'], ['mois', 'organisme'], lazy=False)
        totals = {g['organisme']: g['montant'] for g in groups}
        self.assertEqual(totals['cnaps'], 7000 + 91000)
        self.assertEqual(totals['ostie'], 7000 + 35000)
        self.assertEqual(totals['irsa'], 42700)

    # --- arrondi ---------------------------------------------------------
    def test_montants_arrondis_registre_egal_ecriture(self):
        slip = self._slip(1234567, 0, '2026-10-01', '2026-10-31')
        rows = {r.rule_code: r.montant for r in slip.mowgli_contribution_ids}
        self.assertAlmostEqual(rows['CNAPS_ER'], 160493.71, places=2)
        self.assertAlmostEqual(rows['OSTIE_ER'], 61728.35, places=2)
        csoc = slip.mowgli_csoc_move_id
        debit = sum(csoc.line_ids.mapped('debit'))
        self.assertEqual(debit, sum(csoc.line_ids.mapped('credit')))
        self.assertEqual(debit, rows['CNAPS_ER'] + rows['OSTIE_ER'])
        self.assertEqual(len(csoc.line_ids), 4, "aucune ligne d'ajustement")

    # --- annulation, brouillon, revalidation ---------------------------------
    def test_annulation_extourne_et_vide_le_registre(self):
        slip = self._slip()
        csoc = slip.mowgli_csoc_move_id
        slip.action_payslip_cancel()
        self.assertFalse(slip.mowgli_csoc_move_id)
        self.assertFalse(self.Contribution.search([('payslip_id', '=', slip.id)]))
        self.assertTrue(csoc.reversal_move_id)
        net = self._by_account(csoc | csoc.reversal_move_id)
        self.assertEqual(net['652500'][0], net['652500'][1])
        self.assertEqual(net['315000'][0], net['315000'][1])

    def test_double_validation_sans_doublon(self):
        slip = self._slip()
        move = slip.mowgli_csoc_move_id
        slip._mowgli_register_contributions()
        slip._mowgli_post_csoc()
        self.assertEqual(len(slip.mowgli_contribution_ids), 5)
        self.assertEqual(slip.mowgli_csoc_move_id, move)
        slip.action_payslip_draft()
        self.assertFalse(slip.mowgli_contribution_ids)
        slip.action_payslip_verify()
        slip.action_payslip_done()
        self.assertEqual(len(slip.mowgli_contribution_ids), 5)
        active = self.env['account.move'].search([
            ('journal_id.code', '=', 'CSOC'), ('company_id', '=', self.company.id),
            ('ref', 'like', slip.name), ('reversed_entry_id', '=', False),
            ('reversal_move_id', '=', False)])
        self.assertEqual(active, slip.mowgli_csoc_move_id)
        self.assertEqual(slip.mowgli_csoc_move_id.state, 'posted')

    def test_cotisation_declaree_bloque_annulation(self):
        slip = self._slip()
        wizard = self.env['mowgli.payroll.contribution.wizard'].with_context(
            active_ids=slip.mowgli_contribution_ids.ids).create(
            {'target_state': 'declare', 'reference': 'DECL-2026-09'})
        wizard.action_apply()
        self.assertEqual({r.state for r in slip.mowgli_contribution_ids}, {'declare'})
        with self.assertRaises(UserError), self.env.cr.savepoint():
            slip.action_payslip_cancel()
        wizard = self.env['mowgli.payroll.contribution.wizard'].with_context(
            active_ids=slip.mowgli_contribution_ids.ids).create(
            {'target_state': 'verse', 'payment_date': '2026-10-15'})
        wizard.action_apply()
        self.assertEqual({r.state for r in slip.mowgli_contribution_ids}, {'verse'})
        self.assertEqual(slip.mowgli_contribution_ids[0].payment_date,
                         fields.Date.to_date('2026-10-15'))

    def test_periode_verrouillee_bloque_extourne(self):
        slip = self._slip()
        # La date de verrouillage se règle de façon différente selon les bases
        # (contrôles de base_accounting_kit) : on simule la lecture du verrou.
        with patch.object(type(self.env['res.company']), '_get_user_fiscal_lock_date',
                          return_value=fields.Date.today()):
            with self.assertRaisesRegex(UserError, "verrouillée"), self.env.cr.savepoint():
                slip.action_payslip_cancel()

    # --- refund ------------------------------------------------------------
    def test_refund_registre_net_zero_et_csoc_inverse(self):
        slip = self._slip()
        slip.action_refund_sheet()
        refund = self.env['hr.payslip'].search(
            [('credit_note', '=', True), ('employee_id', '=', slip.employee_id.id)])
        self.assertEqual(len(refund), 1)
        rows = refund.mowgli_contribution_ids
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(r.montant < 0 for r in rows))
        total = sum((slip | refund).mapped('mowgli_contribution_ids.montant'))
        self.assertEqual(total, 0.0)
        moves = slip.mowgli_csoc_move_id | refund.mowgli_csoc_move_id
        self.assertEqual(self._by_account(refund.mowgli_csoc_move_id),
                         {'652500': [0.0, 126000.0], '315000': [126000.0, 0.0]})
        net = self._by_account(moves)
        self.assertEqual(net['652500'][0] - net['652500'][1], 0.0)
        self.assertEqual(net['315000'][0] - net['315000'][1], 0.0)
        for line in moves.line_ids:
            self.assertGreaterEqual(line.debit, 0.0)
            self.assertGreaterEqual(line.credit, 0.0)

    # --- comptes ------------------------------------------------------------
    def test_compte_introuvable_user_error_sans_ecriture(self):
        slip = self._slip(validate=False)
        slip.action_payslip_verify()
        account = self.Account.search(
            [('code', '=', '652500'), ('company_id', '=', self.company.id)], limit=1)
        account.code = 'ZZ6525'
        with self.assertRaisesRegex(UserError, "652500"), self.env.cr.savepoint():
            slip.action_payslip_done()
        slip.invalidate_recordset()
        self.assertEqual(slip.state, 'verify')
        self.assertFalse(slip.mowgli_csoc_move_id)
        self.assertFalse(self.Contribution.search([('payslip_id', '=', slip.id)]))

    def test_creation_652500_seulement_si_absent(self):
        account = self.Account.search(
            [('code', '=', '652500'), ('company_id', '=', self.company.id)])
        self.assertEqual(len(account), 1)
        account.name = 'Nom modifié'
        self.Contribution._setup_all()
        self.assertEqual(account.name, 'Nom modifié', "jamais de renommage")
        # Compte « absent » : son code est libéré (on ne supprime pas un compte
        # qui peut porter des écritures réelles).
        account.code = 'ZZ6525'
        created = self.Contribution._setup_all()
        self.assertIn(self.company.name, created)
        new = self.Account.search(
            [('code', '=', '652500'), ('company_id', '=', self.company.id)])
        self.assertEqual(len(new), 1)
        self.assertNotEqual(new, account)
        self.assertEqual(new.account_type, 'expense')
        self.assertFalse(new.reconcile)
        self.assertEqual(new.name, 'Cotisations aux organismes sociaux')
        self.assertNotIn(self.company.name, self.Contribution._setup_all())
        self.assertEqual(self.Account.search_count(
            [('code', '=', '652500'), ('company_id', '=', self.company.id)]), 1)
        self.assertEqual(self.env['account.journal'].search_count([
            ('code', '=', 'CSOC'), ('company_id', '=', self.company.id)]), 1)

    def test_aucun_fmfp_dans_le_registre(self):
        field = self.Contribution._fields['organisme']
        self.assertEqual([k for k, __ in field.selection], ['cnaps', 'ostie', 'irsa'])
