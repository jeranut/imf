# -*- coding: utf-8 -*-
"""Lot 1 — Dashboard Portefeuille par agent de crédit.

Données forgées (SEFOR ne contient qu'un agent / une agence avec dossiers) : 2 agences,
3 agents, contrôle serveur du scope, PAR par agent (exclusif + cumulatif), agrégats mensuels,
panneau échéances, snapshot, non-régression de get_par_buckets.
"""
import base64
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError

from .common import MicrofinanceCommon

G = 'microfinance_loan_management.group_microfinance_'


class TestAgentPortfolioDashboard(MicrofinanceCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # action_activate lève si un fonds de crédit actif existe ; on n'active pas de crédit
        # ici (forge directe) mais on neutralise par cohérence avec les autres suites.
        cls.env['microfinance.fond.credit'].sudo().search([('active', '=', True)]).write({'active': False})
        cls.company_a = cls.env.company

        # --- Agence B : comptes, journaux, produit ---
        cls.company_b = cls.env['res.company'].create({'name': 'Agence B dash (test)', 'agency_code': 'DB1'})

        def _acc(name, code, kind, company):
            return cls.env['account.account'].create({
                'name': name, 'code': code, 'account_type': kind, 'company_id': company.id,
            })

        b_loan = _acc('Prêts B', 'BDPRET', 'asset_current', cls.company_b)
        b_loan_grp = _acc('Prêts B grp', 'BDPRTG', 'asset_current', cls.company_b)
        b_int = _acc('Intérêts B', 'BDINT', 'income', cls.company_b)
        b_int_grp = _acc('Intérêts B grp', 'BDINTG', 'income', cls.company_b)
        b_pen = _acc('Pénalités B', 'BDPEN', 'income_other', cls.company_b)
        b_bank = _acc('Caisse B', 'BDCASH', 'asset_cash', cls.company_b)
        b_disb_journal = cls.env['account.journal'].create({
            'name': 'Caisse décaissement B', 'code': 'BDDEC', 'type': 'cash',
            'company_id': cls.company_b.id, 'default_account_id': b_bank.id,
        })
        b_pay_journal = cls.env['account.journal'].create({
            'name': 'Caisse remboursement B', 'code': 'BDREM', 'type': 'cash',
            'company_id': cls.company_b.id, 'default_account_id': b_bank.id,
        })
        cls.product_b = cls.env['microfinance.loan.product'].with_company(cls.company_b).create({
            'name': 'Produit B', 'code': 'PTESTB', 'min_amount': 100.0, 'max_amount': 100000.0,
            'min_term': 1, 'max_term': 36, 'interest_rate': 12.0, 'interest_method': 'flat',
            'installment_rounding_unit': 0, 'repayment_frequency_mode': 'fixed',
            'repayment_frequency_id': cls.env.ref('microfinance_loan_management.repayment_frequency_monthly').id,
            'company_id': cls.company_b.id,
            'disbursement_journal_id': b_disb_journal.id, 'payment_journal_id': b_pay_journal.id,
            'account_principal_individuel_id': b_loan.id, 'account_principal_groupe_id': b_loan_grp.id,
            'account_interets_recus_individuel_id': b_int.id, 'account_interets_recus_groupe_id': b_int_grp.id,
            'account_penalites_id': b_pen.id,
        })
        cls.partner_b = cls.env['res.partner'].create({
            'name': 'Client B dash', 'microfinance_partner_type': 'client', 'company_id': cls.company_b.id,
        })

        # --- Utilisateurs ---
        def _user(login, company, groups, companies=None):
            return cls.env['res.users'].create({
                'name': login, 'login': login, 'company_id': company.id,
                'company_ids': [(6, 0, companies or [company.id])],
                'groups_id': [(6, 0, [cls.env.ref('base.group_user').id]
                              + [cls.env.ref(G + g).id for g in groups])],
            })

        cls.agent_a1 = _user('dash_agent_a1', cls.company_a, ['user'])
        cls.agent_a2 = _user('dash_agent_a2', cls.company_a, ['user'])
        cls.agent_b1 = _user('dash_agent_b1', cls.company_b, ['user'])
        cls.manager_a = _user('dash_manager_a', cls.company_a, ['manager'])
        cls.auditor_ab = _user('dash_auditor_ab', cls.company_a, ['auditor'],
                               companies=[cls.company_a.id, cls.company_b.id])

        cls.Loan = cls.env['microfinance.loan']

        # --- Portefeuille forgé ---
        # Agent A1 : 1 crédit à jour + 1 crédit en retard 45j
        cls.l_a1_ok = cls._forge(cls, cls.agent_a1, cls.company_a, amount=1000.0)
        cls.l_a1_late = cls._forge(cls, cls.agent_a1, cls.company_a, amount=2000.0, overdue_days=45)
        # Agent A2 : 1 crédit en retard 100j
        cls.l_a2_late = cls._forge(cls, cls.agent_a2, cls.company_a, amount=3000.0, overdue_days=100)
        # Agent B1 : 1 crédit à jour dans l'agence B
        cls.l_b1_ok = cls._forge(cls, cls.agent_b1, cls.company_b, amount=5000.0,
                                 partner=cls.partner_b, product=cls.product_b)
        # Bruit à exclure : sans officer_id, et non décaissé
        cls.l_no_officer = cls._forge(cls, None, cls.company_a, amount=9999.0)
        cls.l_not_disbursed = cls._forge(cls, cls.agent_a1, cls.company_a, amount=8888.0, disbursed=False)

    def _forge(self, officer, company, amount=1000.0, overdue_days=0, state='active',
               disbursed=True, partner=None, product=None):
        loan = self.env['microfinance.loan'].with_company(company).create({
            'partner_id': (partner or self.partner).id,
            'product_id': (product or self.product).id,
            'loan_amount': amount, 'term': 6,
            'officer_id': officer.id if officer else False,
            'company_id': company.id,
            'signed_contract': base64.b64encode(b'x'), 'signed_contract_filename': 'c.pdf',
        })
        # L'échéancier n'est généré qu'au write() sur un état éditable ; on le force ici tant
        # que le crédit est 'draft'.
        loan.action_generate_schedule()
        if overdue_days:
            first = loan.installment_ids.sorted('sequence')[:1]
            first.due_date = fields.Date.today() - timedelta(days=overdue_days)
            loan.max_days_overdue = overdue_days  # simule le rafraîchissement par le cron quotidien
        write_vals = {'state': state}
        if disbursed:
            write_vals['disbursement_date'] = fields.Date.today()
        loan.write(write_vals)
        return loan

    # ------------------------------------------------------------------ scope

    def test_scope_agent_sees_only_himself(self):
        agents = self.Loan.with_user(self.agent_a1).get_available_agents()
        self.assertEqual([a['officer_id'] for a in agents], [self.agent_a1.id])

    def test_scope_manager_sees_all_agents_of_his_agency_only(self):
        # Assertions par inclusion : SEFOR contient des crédits pré-existants (officer =
        # Administrator, agence 1) qui remontent aussi ; l'invariant testé est « les agents de
        # mon agence oui, ceux d'une autre agence non ».
        agents = self.Loan.with_user(self.manager_a).get_available_agents()
        ids = {a['officer_id'] for a in agents}
        self.assertIn(self.agent_a1.id, ids)
        self.assertIn(self.agent_a2.id, ids)
        self.assertNotIn(self.agent_b1.id, ids)
        self.assertEqual({a['company_id'] for a in agents}, {self.company_a.id})

    def test_scope_auditor_sees_multiple_agencies(self):
        agents = self.Loan.with_user(self.auditor_ab).get_available_agents()
        ids = {a['officer_id'] for a in agents}
        companies = {a['company_id'] for a in agents}
        self.assertIn(self.agent_a1.id, ids)
        self.assertIn(self.agent_b1.id, ids)
        self.assertEqual(companies, {self.company_a.id, self.company_b.id})

    def test_agent_forcing_a_colleague_officer_id_is_blocked(self):
        with self.assertRaises(AccessError):
            self.Loan.with_user(self.agent_a1).get_agent_portfolio_kpis(officer_id_filter=self.agent_a2.id)

    def test_manager_forcing_foreign_agency_agent_is_blocked(self):
        with self.assertRaises(AccessError):
            self.Loan.with_user(self.manager_a).get_agent_portfolio_kpis(officer_id_filter=self.agent_b1.id)

    # ------------------------------------------------------------------ KPI

    def test_kpis_agent_scope_and_exclusions(self):
        kpis = self.Loan.with_user(self.agent_a1).get_agent_portfolio_kpis()
        # 2 crédits décaissés actifs (le non-décaissé et celui d'A2 exclus)
        self.assertEqual(kpis['nb_dossiers_actifs'], 2)
        self.assertEqual(kpis['nb_dossiers_en_retard'], 1)
        self.assertAlmostEqual(kpis['encours'], self.l_a1_ok.balance_total + self.l_a1_late.balance_total, places=2)

    def test_no_officer_loan_excluded_everywhere(self):
        kpis = self.Loan.with_user(self.manager_a).get_agent_portfolio_kpis()
        # l_no_officer (9999) ne doit pas gonfler l'encours agence
        table = self.Loan.with_user(self.manager_a).get_agent_portfolio_table(limit=100)
        self.assertFalse(any(r['id'] == self.l_no_officer.id for r in table['rows']))
        self.assertFalse(any(r['id'] == self.l_not_disbursed.id for r in table['rows']))

    # ------------------------------------------------------------------ PAR

    def test_cumulative_par_is_monotonic_decreasing(self):
        res = self.Loan.with_user(self.manager_a).get_cumulative_par_by_agent()
        self.assertTrue(res)
        for row in res:
            v = row['values']
            self.assertGreaterEqual(v[0], v[1])
            self.assertGreaterEqual(v[1], v[2])
            self.assertGreaterEqual(v[2], v[3])

    def test_par_exclusive_vs_cumulative_same_base(self):
        # Agent A1 : encours 3000 (1000 ok + 2000 late@45j). PAR exclusif 31-60 = 2000/3000.
        excl = self.Loan.with_user(self.agent_a1).get_par_buckets_by_agent()[0]
        cumul = self.Loan.with_user(self.agent_a1).get_cumulative_par_by_agent()[0]
        # tranche 31-60 (index 1) = 2000/3000*100
        self.assertAlmostEqual(excl['values'][1], 2000.0 / 3000.0 * 100.0, places=2)
        # PAR30 cumulatif (index 0, seuil 30) = 2000/3000*100 (le crédit à 45j compte)
        self.assertAlmostEqual(cumul['values'][0], 2000.0 / 3000.0 * 100.0, places=2)
        # PAR60 = 0 (45 < 60)
        self.assertAlmostEqual(cumul['values'][1], 0.0, places=2)

    def test_get_par_buckets_global_unchanged(self):
        # Non-régression : la méthode globale existante fonctionne toujours et ne dépend pas
        # du nouveau champ max_days_overdue (elle rappelle _get_max_overdue_days()).
        res = self.Loan.get_par_buckets(self.company_a.id)
        self.assertIn('labels', res)
        self.assertIn('values', res)
        self.assertEqual(len(res['values']), 4)

    # ------------------------------------------------------------------ mensuel

    def test_monthly_kpis_disbursement_this_month(self):
        kpis = self.Loan.with_user(self.agent_a1).get_agent_monthly_kpis()
        # les 2 crédits décaissés d'A1 le sont aujourd'hui (donc ce mois)
        self.assertEqual(kpis['nb_credits_decaisses'], 2)
        self.assertAlmostEqual(kpis['montant_decaisse'], 3000.0, places=2)

    # ------------------------------------------------------------------ échéances

    def test_due_dates_panel_excludes_non_disbursed_preview_loan(self):
        # Force une échéance "aujourd'hui" sur le crédit NON décaissé d'A1.
        inst = self.l_not_disbursed.installment_ids.sorted('sequence')[:1]
        inst.write({'due_date': fields.Date.today()})
        panel = self.Loan.with_user(self.agent_a1).get_agent_due_dates_panel()
        # rien ne doit remonter : le crédit n'est pas décaissé
        self.assertEqual(panel['today']['montant_attendu'], 0.0)

    # ------------------------------------------------------------------ snapshot

    def test_snapshot_cron_creates_rows_and_history_reads_them(self):
        self.Loan.cron_snapshot_portfolio_par()
        Snap = self.env['microfinance.portfolio.snapshot']
        rows = Snap.search([('officer_id', '=', self.agent_a1.id), ('company_id', '=', self.company_a.id)])
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows.par30, 2000.0 / 3000.0 * 100.0, places=2)
        # ré-exécution = upsert, pas de doublon
        self.Loan.cron_snapshot_portfolio_par()
        self.assertEqual(
            Snap.search_count([('officer_id', '=', self.agent_a1.id), ('company_id', '=', self.company_a.id)]), 1)
        hist = self.Loan.with_user(self.agent_a1).get_par_history_by_agent()
        self.assertTrue(hist['has_data'])
        self.assertEqual(len(hist['labels']), 1)

    def test_history_empty_before_any_cron_run(self):
        hist = self.Loan.with_user(self.agent_a2).get_par_history_by_agent()
        self.assertFalse(hist['has_data'])
        self.assertEqual(hist['labels'], [])

    # ------------------------------------------------------------------ champs related

    def test_officer_id_related_stored_on_installment_and_payment(self):
        self.assertEqual(self.l_a1_late.installment_ids[0].officer_id, self.agent_a1)
        self.assertTrue(self.env['microfinance.loan.payment']._fields['officer_id'].store)
        self.assertTrue(self.env['microfinance.loan.installment']._fields['officer_id'].store)

    def test_max_days_overdue_refreshed_by_daily_cron(self):
        loan = self._forge(self.agent_a1, self.company_a, amount=1500.0)
        first = loan.installment_ids.sorted('sequence')[:1]
        first.write({'due_date': fields.Date.today() - timedelta(days=20)})
        loan.max_days_overdue = 0  # simulate stale
        self.Loan.cron_update_overdue_and_penalties()
        loan.invalidate_recordset(['max_days_overdue'])
        self.assertEqual(loan.max_days_overdue, 20)
