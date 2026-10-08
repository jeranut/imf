# -*- coding: utf-8 -*-
from odoo.exceptions import UserError

from .common import MicrofinanceDataResetCommon


class TestMicrofinanceFondCreditPurgeWizard(MicrofinanceDataResetCommon):
    """Toutes les exécutions "réelles" portent sur des agences de test isolées
    (jamais self.env.company, cf. commentaire de TestMicrofinanceDataResetWizard) —
    self.company_a est la société ciblée par la purge, self.company_b sert à vérifier
    qu'une société HORS PÉRIMÈTRE n'est jamais touchée (exigence explicite de la
    demande initiale)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.PurgeWizard = cls.env['microfinance.fond.credit.purge.wizard'].sudo()
        cls.bailleur = cls.env['microfinance.bailleur.fonds'].create({'name': 'Bailleur Test Purge'})

    def setUp(self):
        super().setUp()
        self.company_a, self.product_a, _sp_a, _pj_a, self.partner_a = self._setup_second_company('PA')
        self.company_b, self.product_b, _sp_b, _pj_b, self.partner_b = self._setup_second_company('PB')
        self.account_a = self._create_liability_account(self.company_a, 'PAFONDGL')
        self.account_b = self._create_liability_account(self.company_b, 'PBFONDGL')

    def _create_liability_account(self, company, code):
        return self.env['account.account'].create({
            'name': 'Dette bailleur %s' % code, 'code': code,
            'account_type': 'liability_current', 'company_id': company.id,
        })

    def _create_fond(self, company, account, **kwargs):
        vals = {
            'name': 'Fonds %s' % company.name,
            'bailleur_id': self.bailleur.id,
            'company_id': company.id,
            'date_debut': '2020-01-01',
            'account_id': account.id,
            'passer_gl': False,  # pas d'écriture comptable à générer : hors périmètre de ce test
        }
        vals.update(kwargs)
        return self.env['microfinance.fond.credit'].create(vals)

    def _make_purge_wizard(self, companies, **kwargs):
        vals = {'company_ids': [(6, 0, companies.ids)]}
        vals.update(kwargs)
        return self.PurgeWizard.create(vals)

    # 1. Isolation : purge ciblant company_a ne touche jamais un fonds de company_b.
    def test_purge_does_not_affect_out_of_scope_company(self):
        fond_a = self._create_fond(self.company_a, self.account_a)
        fond_b = self._create_fond(self.company_b, self.account_b)

        wizard = self._make_purge_wizard(self.company_a)
        self.env['ir.config_parameter'].sudo().set_param(
            'microfinance.fond_credit_purge_apply', 'True')
        wizard.i_confirm = True
        wizard.confirm_text = 'SUPPRIMER'
        wizard.action_run_execute()

        self.assertNotIn('ERREUR', wizard.log)
        self.assertFalse(fond_a.exists(), "Le fonds de la société ciblée doit être supprimé.")
        self.assertTrue(fond_b.exists(), "Le fonds d'une société HORS PÉRIMÈTRE ne doit jamais être touché.")
        self.assertEqual(fond_b.company_id, self.company_b)

    # 2. Dry-run : rollback effectif, rien n'est supprimé (ni dans, ni hors périmètre).
    def test_dry_run_rolls_back(self):
        fond_a = self._create_fond(self.company_a, self.account_a)
        wizard = self._make_purge_wizard(self.company_a)
        wizard.action_run_dry_run()

        self.assertNotIn('ERREUR', wizard.log)
        self.assertTrue(fond_a.exists())
        self.assertIn('fonds supprimé', wizard.log)

    # 3. Exécution réelle refusée sans le paramètre système (dry-run par défaut).
    def test_execute_blocked_without_system_parameter(self):
        self._create_fond(self.company_a, self.account_a)
        self.env['ir.config_parameter'].sudo().set_param('microfinance.fond_credit_purge_apply', 'False')
        wizard = self._make_purge_wizard(self.company_a, i_confirm=True, confirm_text='SUPPRIMER')
        with self.assertRaises(UserError):
            wizard.action_run_execute()

    # 4. Fonds bloqué par des contributions (ondelete='restrict') : purgé en cascade
    #    avec le fonds, sans jamais toucher l'account.move déjà posté.
    def test_purge_cascades_contributions_without_touching_posted_move(self):
        fond_a = self._create_fond(self.company_a, self.account_a, passer_gl=True)
        bank = self.env['res.bank'].create({'name': 'Banque PA (test)'})
        self.env['account.journal'].create({
            'name': 'Fonds PA', 'code': 'PABQ', 'type': 'bank', 'company_id': self.company_a.id,
            'default_account_id': self.account_a.id,
            'microfinance_usage': 'fund', 'microfinance_bank_id': bank.id,
        })
        fond_a.bank_id = bank
        contribution = self.env['microfinance.fond.contribution'].create({
            'fond_id': fond_a.id, 'type_mouvement': 'depot', 'amount': 1000.0,
            'mode_paiement': 'virement',
        })
        contribution.action_post()
        move = contribution.move_id
        self.assertTrue(move and move.state == 'posted')

        wizard = self._make_purge_wizard(self.company_a)
        self.env['ir.config_parameter'].sudo().set_param('microfinance.fond_credit_purge_apply', 'True')
        wizard.i_confirm = True
        wizard.confirm_text = 'SUPPRIMER'
        wizard.action_run_execute()

        self.assertNotIn('ERREUR', wizard.log)
        self.assertFalse(fond_a.exists())
        self.assertFalse(contribution.exists())
        self.assertTrue(move.exists(), "L'écriture comptable postée ne doit jamais être supprimée.")
        self.assertEqual(move.state, 'posted')

    # 5. Fonds référencé par un crédit non décaissé : bloqué par défaut (action 'stop').
    def test_fund_with_non_disbursed_loan_blocked_by_default(self):
        fond_a = self._create_fond(self.company_a, self.account_a)
        loan = self.env['microfinance.loan'].create({
            'partner_id': self.partner_a.id, 'product_id': self.product_a.id,
            'company_id': self.company_a.id, 'loan_amount': 1000.0, 'term': 6,
            'fond_credit_id': fond_a.id,
        })
        wizard = self._make_purge_wizard(self.company_a)
        self.env['ir.config_parameter'].sudo().set_param('microfinance.fond_credit_purge_apply', 'True')
        wizard.i_confirm = True
        wizard.confirm_text = 'SUPPRIMER'
        wizard.action_run_execute()

        self.assertNotIn('ERREUR', wizard.log)
        self.assertTrue(fond_a.exists(), "Un fonds référencé par un crédit non décaissé reste bloqué par défaut.")
        self.assertTrue(loan.exists())
        self.assertEqual(loan.fond_credit_id, fond_a)

    # 6. Fonds référencé par un crédit décaissé : jamais touché, quelle que soit l'option.
    def test_fund_with_disbursed_loan_never_purged(self):
        fond_a = self._create_fond(self.company_a, self.account_a)
        loan = self.env['microfinance.loan'].create({
            'partner_id': self.partner_a.id, 'product_id': self.product_a.id,
            'company_id': self.company_a.id, 'loan_amount': 1000.0, 'term': 6,
            'fond_credit_id': fond_a.id,
        })
        # disbursement_date est readonly=True côté champ (jamais écrit hors action_disburse) :
        # write direct légitime uniquement en test, pour simuler un crédit déjà décaissé sans
        # dérouler tout le circuit d'approbation/activation, hors sujet ici.
        loan.disbursement_date = '2024-01-01'

        wizard = self._make_purge_wizard(self.company_a, blocking_loan_action='delete_test_loan')
        self.env['ir.config_parameter'].sudo().set_param('microfinance.fond_credit_purge_apply', 'True')
        wizard.i_confirm = True
        wizard.confirm_text = 'SUPPRIMER'
        wizard.action_run_execute()

        self.assertNotIn('ERREUR', wizard.log)
        self.assertTrue(fond_a.exists(), "Un fonds avec un crédit DÉCAISSÉ ne doit jamais être supprimé.")
        self.assertTrue(loan.exists())

    # 7. Cas du fonds 360 (MOWGLI) : fonds multi-agences avec allocation d'agence ET répartition
    #    de portefeuille validée (microfinance.portfolio.allocation.fond_id, ondelete='restrict').
    #    Avant correctif : ForeignKeyViolation à la suppression du fonds.
    def _create_fond_with_portfolio_allocation(self):
        fond = self._create_fond(
            self.company_a, self.account_a, scope='multi_company', company_id=False)
        allocation = self.env['microfinance.fond.allocation'].sudo().with_context(
            fond_partage_technique=True, microfinance_skip_parent_check=True).create({
                'fond_id': fond.id, 'company_id': self.company_a.id, 'amount_allocated': 1000.0,
            })
        portfolio = self.env['microfinance.portfolio'].sudo().create({
            'agent_id': self.env.user.id, 'company_id': self.company_a.id,
        })
        repartition = self.env['microfinance.portfolio.allocation'].sudo().create({
            'fond_id': fond.id, 'company_id': self.company_a.id, 'base_amount': 1000.0,
            'line_ids': [(0, 0, {'portfolio_id': portfolio.id, 'percent': 100.0, 'amount': 1000.0})],
        })
        repartition.action_validate()
        self.assertEqual(repartition.state, 'validated')
        self.assertEqual(portfolio.amount_allocated, 1000.0)
        return fond, allocation, portfolio, repartition

    def test_purge_fund_with_validated_portfolio_allocation(self):
        fond, allocation, portfolio, repartition = self._create_fond_with_portfolio_allocation()
        line = repartition.line_ids
        self.assertEqual(len(line), 1)

        wizard = self._make_purge_wizard(self.company_a)
        self.env['ir.config_parameter'].sudo().set_param('microfinance.fond_credit_purge_apply', 'True')
        wizard.i_confirm = True
        wizard.confirm_text = 'SUPPRIMER'
        wizard.action_run_execute()

        self.assertNotIn('ERREUR', wizard.log)
        self.assertFalse(fond.exists(), "Le fonds avec répartition de portefeuille doit être purgé.")
        self.assertFalse(repartition.exists())
        self.assertFalse(line.exists())
        self.assertFalse(allocation.exists())
        # La répartition validée a été annulée avant suppression : le portefeuille est restitué.
        self.assertEqual(portfolio.amount_allocated, 0.0)
        self.assertIn('1 répartition(s) de portefeuille supprimée(s)', wizard.log)
        self.assertIn('1 annulée(s) au préalable', wizard.log)

    # 8. Dry-run : détail par modèle (y compris les répartitions de portefeuille), rien supprimé.
    def test_dry_run_lists_counts_per_model_and_rolls_back(self):
        fond, allocation, portfolio, repartition = self._create_fond_with_portfolio_allocation()

        wizard = self._make_purge_wizard(self.company_a)
        wizard.action_run_dry_run()

        self.assertNotIn('ERREUR', wizard.log)
        self.assertIn('0 contribution(s), 1 répartition(s) de portefeuille (dont 1 validée(s) à annuler) '
                      'avec 1 ligne(s), 0 partage(s), 1 allocation(s) d\'agence', wizard.log)
        self.assertIn('fonds supprimé', wizard.log)
        # Rollback effectif.
        self.assertTrue(fond.exists())
        self.assertTrue(repartition.exists())
        self.assertTrue(allocation.exists())
        self.assertEqual(portfolio.amount_allocated, 1000.0)
        self.assertEqual(repartition.state, 'validated')
