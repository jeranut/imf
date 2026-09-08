# -*- coding: utf-8 -*-
import base64

from odoo.tests.common import TransactionCase


class MicrofinanceCommon(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company = cls.env.company
        company.agency_code = 'T0'
        cls.loan_account = cls.env['account.account'].create({
            'name': 'Prêts clients test',
            'code': 'TPRET',
            'account_type': 'asset_current',
            'company_id': company.id,
        })
        cls.loan_account_groupe = cls.env['account.account'].create({
            'name': 'Prêts clients groupe test',
            'code': 'TPRETG',
            'account_type': 'asset_current',
            'company_id': company.id,
        })
        cls.interest_account = cls.env['account.account'].create({
            'name': 'Produits intérêts test',
            'code': 'TINT',
            'account_type': 'income',
            'company_id': company.id,
        })
        cls.interest_account_groupe = cls.env['account.account'].create({
            'name': 'Produits intérêts groupe test',
            'code': 'TINTG',
            'account_type': 'income',
            'company_id': company.id,
        })
        cls.penalty_account = cls.env['account.account'].create({
            'name': 'Produits pénalités test',
            'code': 'TPEN',
            'account_type': 'income_other',
            'company_id': company.id,
        })
        cls.bank_account = cls.env['account.account'].create({
            'name': 'Caisse test',
            'code': 'TCASH',
            'account_type': 'asset_cash',
            'company_id': company.id,
        })
        cls.disbursement_journal = cls.env['account.journal'].create({
            'name': 'Caisse décaissement test',
            'code': 'TDEC',
            'type': 'cash',
            'company_id': company.id,
            'default_account_id': cls.bank_account.id,
        })
        cls.payment_journal = cls.env['account.journal'].create({
            'name': 'Caisse remboursement test',
            'code': 'TREM',
            'type': 'cash',
            'company_id': company.id,
            'default_account_id': cls.bank_account.id,
        })
        # microfinance_partner_type='client' déclenche l'attribution du numéro de compte
        # permanent (microfinance_account_number), dont dérive maintenant la référence des
        # dossiers d'instruction (microfinance.loan.application.name, related) — sans ce
        # marquage, name resterait vide sur tous les dossiers créés dans les tests.
        cls.partner = cls.env['res.partner'].create({
            'name': 'Client Test Microfinance', 'microfinance_partner_type': 'client',
        })
        cls.product = cls.env['microfinance.loan.product'].create({
            'name': 'Produit Test',
            'code': 'PTEST',
            'min_amount': 100.0,
            'max_amount': 100000.0,
            'min_term': 1,
            'max_term': 36,
            'interest_rate': 12.0,
            'interest_method': 'flat',
            # Arrondi de la cible par tranche (installment_rounding_unit, défaut modèle = 1000 Ar)
            # désactivé sur ce produit de test générique : les montants de crédit utilisés dans la
            # majorité des tests de la suite (souvent quelques centaines/milliers d'Ar) sont sans
            # rapport avec la granularité réelle CEFOR, et l'arrondi par défaut y créerait des
            # distorsions massives (cible qui tombe à 0, échéances à 0 rejetées par les
            # remboursements, etc.) sans rapport avec ce que ces tests vérifient réellement. Les
            # tests dédiés à l'arrondi (test_interest_first_schedule.py) l'activent explicitement.
            'installment_rounding_unit': 0,
            'repayment_frequency_mode': 'fixed',
            'repayment_frequency_id': cls.env.ref('microfinance_loan_management.repayment_frequency_monthly').id,
            'disbursement_journal_id': cls.disbursement_journal.id,
            'payment_journal_id': cls.payment_journal.id,
            'account_principal_individuel_id': cls.loan_account.id,
            'account_principal_groupe_id': cls.loan_account_groupe.id,
            'account_interets_recus_individuel_id': cls.interest_account.id,
            'account_interets_recus_groupe_id': cls.interest_account_groupe.id,
            'account_penalites_id': cls.penalty_account.id,
        })

    def _set_product_policy(self, policy):
        self.env['ir.config_parameter'].sudo().set_param(
            'microfinance_loan_management.microfinance_product_policy', policy)

    def _create_loan(self, **kwargs):
        vals = {
            'partner_id': self.partner.id,
            'product_id': self.product.id,
            'loan_amount': 1200.0,
            'term': 6,
            # Contrat signé factice : action_disburse() l'exige désormais comme
            # prérequis d'activation (cf. microfinance.loan.action_disburse). Sans
            # rapport avec ce que testent les appelants ; surchargeable via kwargs
            # (ex. signed_contract=False) si un test veut en vérifier l'absence.
            'signed_contract': base64.b64encode(b'test signed contract'),
            'signed_contract_filename': 'contrat_signe_test.pdf',
        }
        vals.update(kwargs)
        return self.env['microfinance.loan'].create(vals)

    def _approve_loan(self, **kwargs):
        """Amène un crédit jusqu'à l'état 'approved' (sans activation ni décaissement)."""
        loan = self._create_loan(**kwargs)
        loan.action_generate_schedule()
        loan.action_start_enquete()
        loan.action_ca_review()
        loan.action_cdag_review()
        # Comité d'octroi accepté (filet de sécurité action_approve, docs_dev/blocage_
        # approbation_comite_octroi/) : ce helper sert des tests sans rapport avec le comité
        # lui-même, on prend donc le chemin "accepté" le plus direct plutôt que de forcer chaque
        # appelant à le faire.
        loan.action_view_applications()
        loan.application_ids.write({'committee_first_decision': 'accepted'})
        loan.action_approve()
        return loan

    def _activate_loan_without_disbursement(self, **kwargs):
        """Crédit 'active' mais PAS encore décaissé (disbursement_date vide) — état transitoire
        introduit par le découplage activation / décaissement (docs_dev/guichet_caisse/
        AUDIT_decaissement.md). Pour les tests qui vérifient explicitement ce cas ; ne pas
        détourner _activate_loan, qui doit continuer à produire un crédit réellement décaissé."""
        loan = self._approve_loan(**kwargs)
        loan.action_activate()
        return loan

    def _activate_loan(self, **kwargs):
        loan = self._activate_loan_without_disbursement(**kwargs)
        loan.action_process_disbursement()
        return loan


class MicrofinanceNoFundMixin:
    """À mixer AVANT MicrofinanceCommon dans les classes de test qui activent un crédit sans
    fond_credit_id : neutralise les fonds bailleurs actifs de la base réelle (SEFOR), sinon
    action_activate() lève « Un fonds de crédit rotatif actif existe pour cette agence ».
    TransactionCase => rollback, aucune donnée réelle touchée. Même mécanisme que le
    _NoFundMixin local de test_disbursement_decouple_aggregates."""

    def setUp(self):
        super().setUp()
        self.env['microfinance.fond.credit'].sudo().search([('active', '=', True)]).write({'active': False})
