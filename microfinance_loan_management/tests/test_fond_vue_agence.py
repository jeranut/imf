# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError

from .test_fond_origine import TestFondOrigine
from .test_fond_liaison import TestFondLiaison


class TestFondVueAgence(TestFondLiaison):
    """Montants d'un fonds partagé vus par une agence : alloué / en transit / reçu en banque, part de l'agence
    seulement (jamais le total du fonds), siège = total et ventilation."""

    _auto_fond = TestFondOrigine._auto_fond
    _deposit = TestFondOrigine._deposit
    _shared = TestFondOrigine._shared

    DEPOSIT = 100000.0

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        group_ids = [cls.env.ref('base.group_user').id, cls.env.ref('microfinance_loan_management.group_microfinance_manager').id]
        both = [cls.hq.id, cls.agency.id]
        cls.user_hq = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Utilisateur siège (test)', 'login': 'vue_agence_hq', 'company_id': cls.hq.id,
            'company_ids': [(6, 0, both)], 'groups_id': [(6, 0, group_ids)]})
        cls.user_agency = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Utilisateur agence (test)', 'login': 'vue_agence_ag', 'company_id': cls.agency.id,
            'company_ids': [(6, 0, [cls.agency.id])], 'groups_id': [(6, 0, group_ids)]})

    def _as_agency(self, records):
        return records.with_user(self.user_agency).with_company(self.agency)

    def _as_hq(self, records):
        return records.with_user(self.user_hq).with_company(self.hq)

    def _allocation(self, fond, company):
        allocation = self.env['microfinance.fond.allocation'].sudo().search(
            [('fond_id', '=', fond.id), ('company_id', '=', company.id)])
        allocation.invalidate_recordset()
        return allocation

    # (1) l'agence voit sa part, jamais le total
    def test_agency_sees_its_share_never_the_total(self):
        fond, partage = self._shared(500.0, 300.0)
        values = self._as_agency(fond).read(['total_contributions', 'solde_disponible', 'reste_partageable'])[0]
        self.assertEqual(values['total_contributions'], 300.0)
        self.assertEqual(values['solde_disponible'], 300.0)
        self.assertEqual(values['reste_partageable'], 0.0)
        row = self._as_agency(self.env['microfinance.fond.credit']).search_read(
            [('id', '=', fond.id)], ['total_contributions'])[0]
        self.assertEqual(row['total_contributions'], 300.0)
        self.assertNotEqual(row['total_contributions'], self.DEPOSIT)

    def test_agency_cannot_aggregate_or_export_consolidated_totals(self):
        fond, partage = self._shared(500.0, 300.0)
        model = self._as_agency(self.env['microfinance.fond.credit'])
        with self.assertRaises(AccessError):
            model._read_group([], [], ['total_contributions:sum'])
        with self.assertRaises(AccessError):
            model.browse(fond.id).export_data(['total_contributions'])

    def test_stored_totals_stay_consolidated(self):
        fond, partage = self._shared(500.0, 300.0)
        self.assertEqual(fond.total_contributions, self.DEPOSIT)

    # (2) le siège voit le total et la ventilation
    def test_hq_sees_total_and_breakdown(self):
        fond, partage = self._shared(500.0, 300.0)
        hq_fond = self._as_hq(fond)
        self.assertEqual(hq_fond.read(['total_contributions'])[0]['total_contributions'], self.DEPOSIT)
        breakdown = hq_fond.allocation_ids
        self.assertEqual(set(breakdown.mapped('company_id')), {self.hq, self.agency})
        self.assertEqual(sorted(breakdown.mapped('amount_allocated')), [300.0, 500.0])

    # (3) après le partage : en transit = part, reçu = 0
    def test_after_sharing_share_is_in_transit(self):
        fond, partage = self._shared(500.0, 300.0)
        allocation = self._allocation(fond, self.agency)
        self.assertEqual((allocation.amount_allocated, allocation.amount_in_transit,
                          allocation.amount_received, allocation.amount_not_received), (300.0, 300.0, 0.0, 0.0))
        agency_fond = self._as_agency(fond)
        self.assertEqual((agency_fond.agency_allocated, agency_fond.agency_in_transit, agency_fond.agency_received),
                         (300.0, 300.0, 0.0))

    # (4) après lettrage de la ligne 139100 avec un relevé : transit = 0, reçu = part
    def test_after_bank_reconciliation_share_is_received(self):
        fond, partage = self._shared(500.0, 300.0)
        mirror = self._moves(partage).filtered(lambda m: m.microfinance_partage_side == 'agency')
        self._reconcile(mirror, self.ag_in, self._statement(self.ag_journal, 300.0, self.ag_in))
        allocation = self._allocation(fond, self.agency)
        self.assertEqual((allocation.amount_in_transit, allocation.amount_received), (0.0, 300.0))

    def test_unreconciled_move_is_not_counted_as_received_by_another_reconciliation(self):
        # extourne lettrée avec la pièce (annulation) ≠ relevé : jamais comptée comme reçue
        fond, partage = self._shared(500.0, 300.0)
        allocation = self._allocation(fond, self.agency)
        self.assertEqual(allocation.amount_received, 0.0)

    def test_share_without_agency_move_is_not_received(self):
        fond = self._auto_fond()
        self._deposit(fond, 100000.0)
        partage = self.env['microfinance.fond.partage'].create({'fond_id': fond.id, 'base_amount': 200.0})
        partage.line_ids.filtered(lambda l: l.company_id == self.agency2).write({'amount': 200.0})
        partage.action_validate()  # agence 2 non configurée : côté siège seul
        allocation = self._allocation(fond, self.agency2)
        self.assertEqual((allocation.amount_allocated, allocation.amount_in_transit, allocation.amount_not_received),
                         (200.0, 0.0, 200.0))

    # (5) 301010 au passif de l'agence : bilan équilibré
    def test_liaison_account_becomes_liability_and_balance_sheet_stays_balanced(self):
        fond, partage = self._shared(500.0, 300.0)
        self.ag_liaison.account_type = 'liability_current'  # ce que fait le script de données, sans toucher aux pièces
        self.assertEqual(self._balance(self.ag_liaison), -300.0)
        report = self.env.ref('base_accounting_kit.account_financial_report_balancesheet0')
        wizard = self.env['financial.report'].with_company(self.agency).new({
            'account_report_id': report.id, 'date_to': '2099-12-31', 'target_move': 'posted', 'company_id': self.agency.id})
        data = {'date_from': False, 'date_to': '2099-12-31', 'enable_filter': False, 'debit_credit': False,
                'account_report_id': [report.id, report.name], 'target_move': 'posted', 'journal_ids': [],
                'view_format': 'vertical', 'company_id': [self.agency.id, self.agency.name],
                'filter_cmp': 'filter_no', 'date_from_cmp': False, 'date_to_cmp': False}
        data['used_context'] = wizard._build_contexts({'form': data})
        lines = wizard.get_account_lines(data)
        by_id = {line['r_id']: line['balance'] for line in lines if line['type'] == 'report'}
        assets = by_id[self.env.ref('base_accounting_kit.account_financial_report_assets0').id]
        liabilities = by_id[self.env.ref('base_accounting_kit.account_financial_report_liabilitysum0').id]
        self.assertEqual(assets, 300.0)
        self.assertEqual(liabilities, 300.0)  # passif affiché en positif
        self.assertEqual(assets - liabilities, 0.0)

    # (6) une agence ne lit pas les allocations des autres
    def test_agency_cannot_read_other_agencies_allocations(self):
        fond, partage = self._shared(500.0, 300.0)
        visible = self._as_agency(self.env['microfinance.fond.allocation']).search([('fond_id', '=', fond.id)])
        self.assertEqual(visible.mapped('company_id'), self.agency)
        self.assertEqual(visible.amount_allocated, 300.0)

    def test_agency_cannot_read_the_total_deposit_contribution(self):
        fond, partage = self._shared(500.0, 300.0)
        contributions = self.env['microfinance.fond.contribution']
        self.assertEqual(self._as_agency(contributions).search_count([('fond_id', '=', fond.id)]), 0)
        self.assertEqual(self._as_hq(contributions).search_count([('fond_id', '=', fond.id)]), 1)

    # contrôle de disponibilité : inchangé par défaut, sur le reçu en banque si la société l'active
    def test_disbursement_base_is_allocation_by_default_and_received_when_enabled(self):
        fond, partage = self._shared(500.0, 300.0)
        allocation = self._allocation(fond, self.agency)
        self.assertFalse(self.agency.microfinance_fond_require_received)
        self.assertEqual(allocation._available_for_disbursement(), 300.0)
        self.agency.microfinance_fond_require_received = True
        allocation.invalidate_recordset()
        self.assertEqual(allocation._available_for_disbursement(), 0.0)  # encore en transit
        mirror = self._moves(partage).filtered(lambda m: m.microfinance_partage_side == 'agency')
        self._reconcile(mirror, self.ag_in, self._statement(self.ag_journal, 300.0, self.ag_in))
        allocation.invalidate_recordset()
        self.assertEqual(allocation._available_for_disbursement(), 300.0)

    # tuile du tableau de bord
    def test_dashboard_tile_shows_the_three_amounts(self):
        fond, partage = self._shared(500.0, 300.0)
        amounts = self.env['microfinance.fond.credit']._get_agency_fund_amounts(self.agency.id)
        self.assertEqual((amounts['allocated'], amounts['in_transit'], amounts['received']), (300.0, 300.0, 0.0))
