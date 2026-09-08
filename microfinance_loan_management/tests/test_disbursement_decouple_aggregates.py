# -*- coding: utf-8 -*-
"""Sous-lot C du découplage activation / décaissement (docs_dev/guichet_caisse/
AUDIT_decaissement.md) : les agrégats de portefeuille (provisions, PAR, KPI dashboard,
totaux fonds bailleur) ne doivent plus compter un crédit 'active' tant que
disbursement_date est vide, et doivent le compter dès qu'il est décaissé."""
from odoo import fields

from .common import MicrofinanceCommon


class _NoFundMixin:
    def setUp(self):
        super().setUp()
        # Neutralise les fonds bailleurs actifs (cf. test_guichet_backend_lists) : sinon
        # action_activate() lève « Un fonds de crédit rotatif actif existe » sur une base
        # réelle. TransactionCase => rollback, aucune donnée réelle touchée.
        self.env['microfinance.fond.credit'].sudo().search([('active', '=', True)]).write({'active': False})


class TestDecoupleProvisionAndPar(_NoFundMixin, MicrofinanceCommon):

    def setUp(self):
        super().setUp()
        self.env['microfinance.provision.rule'].search(
            [('company_id', '=', self.env.company.id)]).unlink()
        Rule = self.env['microfinance.provision.rule']
        Rule.create({'min_days': 0, 'max_days': 30, 'provision_rate': 0.0})
        Rule.create({'min_days': 31, 'max_days': 0, 'provision_rate': 100.0})

    def _make_overdue(self, loan, days=45):
        first = loan.installment_ids.sorted('sequence')[0]
        first.due_date = fields.Date.subtract(fields.Date.context_today(loan), days=days)
        return first

    def test_provision_zero_while_active_not_disbursed_then_computed_after_disbursement(self):
        loan = self._activate_loan_without_disbursement(loan_amount=1000.0, term=4)
        self._make_overdue(loan)
        loan._compute_provision()
        self.assertEqual(loan.provision_amount, 0.0,
                         "Aucune provision tant que le crédit n'est pas décaissé.")

        loan.action_process_disbursement()
        self._make_overdue(loan)
        loan._compute_provision()
        self.assertGreater(loan.provision_amount, 0.0,
                           "Provision calculée une fois le crédit décaissé et en retard.")

    def test_par_buckets_ignores_active_not_disbursed(self):
        Loan = self.env['microfinance.loan']
        before = Loan.get_par_buckets(self.env.company.id)['values']

        loan = self._activate_loan_without_disbursement(loan_amount=1000.0, term=4)
        self._make_overdue(loan)
        while_not_disbursed = Loan.get_par_buckets(self.env.company.id)['values']
        self.assertEqual(while_not_disbursed, before,
                         "Un crédit non décaissé ne change rien au PAR.")

        loan.action_process_disbursement()
        self._make_overdue(loan)
        after = Loan.get_par_buckets(self.env.company.id)['values']
        self.assertNotEqual(after, before,
                            "Une fois décaissé et en retard, le crédit pèse dans le PAR.")


class TestDecoupleDashboardModel(_NoFundMixin, MicrofinanceCommon):

    def test_dashboard_kpis_exclude_active_not_disbursed(self):
        Dashboard = self.env['microfinance.dashboard']
        before = Dashboard.new({})
        before._compute_dashboard()
        base_count = before.active_loan_count
        base_disbursed = before.disbursed_amount

        loan = self._activate_loan_without_disbursement(loan_amount=1500.0, term=4)
        mid = Dashboard.new({})
        mid._compute_dashboard()
        self.assertEqual(mid.active_loan_count, base_count,
                         "Crédit activé non décaissé : pas compté dans « Crédits actifs ».")
        self.assertAlmostEqual(mid.disbursed_amount, base_disbursed, places=2,
                               msg="Pas de montant décaissé tant que rien n'est sorti.")

        loan.action_process_disbursement()
        after = Dashboard.new({})
        after._compute_dashboard()
        self.assertEqual(after.active_loan_count, base_count + 1)
        self.assertAlmostEqual(after.disbursed_amount, base_disbursed + 1500.0, places=2)


class TestDecoupleFondTotals(_NoFundMixin, MicrofinanceCommon):
    # _NoFundMixin désactive les AUTRES fonds actifs (base réelle) ; le seul fonds actif
    # pendant le test est celui créé par _fond_with_contribution, rattaché explicitement au
    # crédit — action_activate() passe donc la garde _check_fond_disponibilite.

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.bailleur = cls.env['microfinance.bailleur.fonds'].create({'name': 'Bailleur découplage'})
        cls.fond_account = cls.env['account.account'].create({
            'name': 'Dette bailleur découplage', 'code': 'TFONDDC',
            'account_type': 'liability_current', 'company_id': cls.env.company.id,
        })

    def _fond_with_contribution(self, amount=10000.0):
        fond = self.env['microfinance.fond.credit'].create({
            'name': 'Fonds découplage', 'bailleur_id': self.bailleur.id,
            'date_debut': '2020-01-01', 'account_id': self.fond_account.id, 'passer_gl': False,
        })
        self.env['microfinance.fond.contribution'].create({
            'fond_id': fond.id, 'type_mouvement': 'depot', 'amount': amount,
            'mode_paiement': 'especes', 'journal_id': self.disbursement_journal.id,
        }).action_post()
        return fond

    def test_total_decaisse_only_counts_disbursed_loans(self):
        fond = self._fond_with_contribution()
        # fond_credit_id rattaché AVANT l'activation : un fonds actif existe pour l'agence,
        # action_activate() (via _check_fond_disponibilite) l'exige.
        loan = self._approve_loan(loan_amount=2000.0, term=4)
        loan.fond_credit_id = fond.id
        loan.action_activate()
        self.assertFalse(loan.disbursement_date)

        fond.invalidate_recordset(['total_decaisse'])
        self.assertEqual(fond.total_decaisse, 0.0,
                         "Crédit 'active' non décaissé : hors total décaissé du fonds.")

        loan.action_process_disbursement()
        fond.invalidate_recordset(['total_decaisse'])
        self.assertAlmostEqual(fond.total_decaisse, 2000.0, places=2)
