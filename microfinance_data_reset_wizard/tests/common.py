# -*- coding: utf-8 -*-
from odoo import fields

from odoo.addons.microfinance_savings_management.tests.common import SavingsCommon


class MicrofinanceDataResetCommon(SavingsCommon):
    """Base commune pour les tests du RAZ microfinance : hérite de SavingsCommon
    (elle-même dérivée de MicrofinanceCommon) pour disposer d'une société de test
    déjà équipée (comptes, journaux, produit de crédit, produit d'épargne)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Wizard = cls.env['microfinance.data.reset.wizard'].sudo()

    def setUp(self):
        super().setUp()
        # Le wizard appelle cr.commit()/cr.rollback() directement (nécessaire en
        # production : chaque étape est une requête HTTP séparée, committée par lot
        # pour rester reprenable). Sous TransactionCase, tous les tests partagent un
        # même curseur isolé par un SAVEPOINT test_N nommé (odoo/tests/common.py) : un
        # vrai COMMIT/ROLLBACK sur ce curseur détruirait ce savepoint et casserait
        # tous les tests suivants de la classe. On neutralise donc commit/rollback au
        # niveau du curseur de test (idiome standard Odoo pour tester du code qui
        # committe explicitement) — cr.savepoint() reste un vrai savepoint SQL
        # (ROLLBACK TO SAVEPOINT direct, pas via cr.rollback()), donc le dry-run du
        # wizard continue à annuler réellement ses suppressions.
        # Important : on préserve flush()/clear() (ce que fait la vraie implémentation
        # de Cursor.commit()/rollback() avant le COMMIT/ROLLBACK réel) — un no-op nu
        # laisse des écritures ORM non flushées, ce qui a provoqué un blocage silencieux
        # (le curseur reste "idle in transaction" côté Postgres, en attente d'un état
        # jamais réellement écrit) lors des premiers essais de ce fichier de tests.
        cr = self.env.cr

        def _fake_commit():
            cr.flush()

        def _fake_rollback():
            cr.clear()

        cr.commit = _fake_commit
        cr.rollback = _fake_rollback

    def _make_wizard(self, companies, **kwargs):
        vals = {'company_ids': [(6, 0, companies.ids)]}
        vals.update(kwargs)
        return self.Wizard.create(vals)

    def _create_full_dataset(self, partner=None, product=None, savings_product=None, payment_journal=None):
        """Crée un jeu de données transactionnel complet pour un test RAZ : crédit actif
        avec échéancier, un remboursement posté, une visite de recouvrement et un compte
        d'épargne actif avec une transaction — un représentant de chaque bloc du wizard."""
        partner = partner or self.partner
        product = product or self.product
        payment_journal = payment_journal or self.payment_journal
        loan = self._activate_loan(partner_id=partner.id, product_id=product.id)
        installment = loan.installment_ids.sorted('sequence')[0]
        payment = self.env['microfinance.loan.payment'].create({
            'loan_id': loan.id,
            'amount': installment.principal_amount + installment.interest_amount,
            'payment_date': fields.Date.today(),
            'journal_id': payment_journal.id,
        })
        payment.action_post()
        visit = self.env['microfinance.collection.visit'].create({
            'loan_id': loan.id,
            'status': 'planned',
        })
        account = self._create_active_account(
            opening_amount=300.0, partner_id=partner.id,
            product_id=(savings_product or self.savings_product).id,
        )
        return loan, payment, visit, account

    def _setup_second_company(self, code='Z1'):
        """Crée une deuxième agence CEFOR complète (comptes, journaux, produit crédit
        et épargne), isolée de la société de test principale, pour les tests
        d'isolation multi-agence."""
        company = self.env['res.company'].create({'name': 'Agence RAZ Test %s' % code, 'agency_code': code})
        loan_account = self.env['account.account'].create({
            'name': 'Prêts clients %s' % code, 'code': '%sPRET' % code,
            'account_type': 'asset_current', 'company_id': company.id,
        })
        interest_account = self.env['account.account'].create({
            'name': 'Intérêts %s' % code, 'code': '%sINT' % code,
            'account_type': 'income', 'company_id': company.id,
        })
        penalty_account = self.env['account.account'].create({
            'name': 'Pénalités %s' % code, 'code': '%sPEN' % code,
            'account_type': 'income_other', 'company_id': company.id,
        })
        bank_account = self.env['account.account'].create({
            'name': 'Caisse %s' % code, 'code': '%sCASH' % code,
            'account_type': 'asset_cash', 'company_id': company.id,
        })
        disbursement_journal = self.env['account.journal'].create({
            'name': 'Décaissement %s' % code, 'code': '%sDEC' % code,
            'type': 'cash', 'company_id': company.id, 'default_account_id': bank_account.id,
        })
        payment_journal = self.env['account.journal'].create({
            'name': 'Remboursement %s' % code, 'code': '%sREM' % code,
            'type': 'cash', 'company_id': company.id, 'default_account_id': bank_account.id,
        })
        product = self.env['microfinance.loan.product'].create({
            'name': 'Produit %s' % code, 'code': 'P%s' % code,
            'company_id': company.id,
            'min_amount': 100.0, 'max_amount': 100000.0, 'min_term': 1, 'max_term': 36,
            'interest_rate': 12.0, 'interest_method': 'flat', 'repayment_frequency_mode': 'fixed',
            'repayment_frequency_id': self.env.ref('microfinance_loan_management.repayment_frequency_monthly').id,
            'disbursement_journal_id': disbursement_journal.id,
            'payment_journal_id': payment_journal.id,
            'account_principal_individuel_id': loan_account.id,
            'account_principal_groupe_id': loan_account.id,
            'account_interets_recus_individuel_id': interest_account.id,
            'account_interets_recus_groupe_id': interest_account.id,
            'account_penalites_id': penalty_account.id,
        })
        savings_deposit_account = self.env['account.account'].create({
            'name': 'Passif épargne %s' % code, 'code': '%sSAV' % code,
            'account_type': 'liability_current', 'company_id': company.id,
        })
        savings_interest_account = self.env['account.account'].create({
            'name': 'Charge intérêts épargne %s' % code, 'code': '%sSAVINT' % code,
            'account_type': 'expense', 'company_id': company.id,
        })
        savings_fee_account = self.env['account.account'].create({
            'name': 'Frais épargne %s' % code, 'code': '%sSAVFEE' % code,
            'account_type': 'income_other', 'company_id': company.id,
        })
        savings_product = self.env['microfinance.savings.product'].create({
            'name': 'Épargne %s' % code, 'code': 'SAV%s' % code, 'product_type': 'voluntary',
            'interest_rate': 6.0, 'balance_method': 'min_balance', 'capitalization_frequency': 'monthly',
            'min_opening_amount': 0.0, 'min_balance': 50.0,
            'account_epargne_individuel_id': savings_deposit_account.id,
            'account_epargne_groupe_id': savings_deposit_account.id,
            'account_epargne_entreprise_id': savings_deposit_account.id,
            'account_interet_paye_individuel_id': savings_interest_account.id,
            'account_commission_id': savings_fee_account.id,
            'deposit_journal_id': disbursement_journal.id,
            'withdrawal_journal_id': payment_journal.id,
        })
        partner = self.env['res.partner'].create({'name': 'Client Agence %s' % code})
        return company, product, savings_product, payment_journal, partner
