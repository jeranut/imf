# -*- coding: utf-8 -*-
"""Reprise de portefeuille : import nominal, simulation, doublon, règle inter-agences, concordance, absence d'écriture
comptable et de mouvement de caisse, absence dans « Décaissements en attente », visibilité au dashboard."""
import base64
import io
import random
from datetime import date, timedelta

import xlsxwriter

import math

from odoo.tools.misc import format_amount
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase

from odoo.addons.microfinance_loan_management.models import microfinance_opening_xlsx as xlsx
from odoo.addons.microfinance_loan_management.tests.common import MicrofinanceNoFundMixin

CLIENTS = ['Référence client', 'Nom', 'CIN', 'Téléphone', 'Agent de crédit', 'Type (individuel / société)']
CREDITS = ['Référence client', 'Produit de crédit', 'Principal initial', 'Principal restant', 'Date de décaissement',
           'Périodicité', "Nombre d'échéances restantes", 'Date de la prochaine échéance', 'Agent de crédit']
EPARGNE = ['Référence client', "Produit d'épargne", "Solde d'ouverture"]


def _workbook(sheets):
    """sheets : {nom: (en-têtes, lignes)}. Les textes sont écrits en cellules texte, les nombres en nombres."""
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    for name, (headers, rows) in sheets.items():
        sheet = workbook.add_worksheet(name)
        sheet.write_row(0, 0, headers)
        for number, row in enumerate(rows, start=1):
            for col, value in enumerate(row):
                if isinstance(value, (int, float)):
                    sheet.write_number(number, col, value)
                elif value is not None:
                    sheet.write_string(number, col, value)
    workbook.close()
    return base64.b64encode(output.getvalue())


class TestOpeningReprise(MicrofinanceNoFundMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({'name': 'Agence RP (test)', 'agency_code': 'RP1'})
        cls.other = cls.env['res.company'].create({'name': 'Agence RP 2 (test)', 'agency_code': 'RP2'})
        cls.today = date.today()
        cls.opening_date = cls.today
        mod = 'microfinance_loan_management.'
        groups = cls.env.ref('base.group_user') | cls.env.ref(mod + 'group_microfinance_user')
        cls.agent = cls._user('agent_rp_test', groups)
        cls.agent_sans_pf = cls._user('agent_sans_pf_rp_test', groups)
        cls.finance = cls._user('finance_rp_test', groups | cls.env.ref(mod + 'group_microfinance_finance'))
        cls.auditor = cls._user('auditeur_rp_test', cls.env.ref('base.group_user') | cls.env.ref(mod + 'group_microfinance_auditor'))
        cls.env['microfinance.portfolio'].create({'agent_id': cls.agent.id, 'company_id': cls.company.id})
        # comptes et produits de la société de test
        cls.principal = cls._account(cls.company, 'RP203001', 'asset_current')
        cls.interest = cls._account(cls.company, 'RP707301', 'income')
        cls.penalty = cls._account(cls.company, 'RP749001', 'income_other')
        cls.bank = cls._account(cls.company, 'RP101000', 'asset_cash')
        cls.capital = cls._account(cls.company, 'RP563000', 'equity')
        cls.savings_acc = cls._account(cls.company, 'RP213001', 'liability_current')
        cls.savings_acc_co = cls._account(cls.company, 'RP213003', 'liability_current')
        cls.savings_acc_g = cls._account(cls.company, 'RP213002', 'liability_current')
        cls.savings_interest = cls._account(cls.company, 'RP607301', 'expense')
        cls.journal = cls.env['account.journal'].create({
            'name': 'Caisse RP', 'code': 'RPC', 'type': 'cash', 'company_id': cls.company.id,
            'default_account_id': cls.bank.id})
        cls.an = cls.env['account.journal'].create({'name': 'AN RP', 'code': 'AN', 'type': 'general',
                                                    'company_id': cls.company.id})
        cls.product = cls.env['microfinance.loan.product'].create({
            'name': 'Produit RP', 'code': 'PRP', 'company_id': cls.company.id, 'min_amount': 100.0, 'max_amount': 100000.0,
            'min_term': 1, 'max_term': 36, 'interest_rate': 12.0, 'interest_method': 'flat', 'installment_rounding_unit': 0,
            'repayment_frequency_mode': 'fixed',
            'repayment_frequency_id': cls.env.ref('microfinance_loan_management.repayment_frequency_monthly').id,
            'disbursement_journal_id': cls.journal.id, 'payment_journal_id': cls.journal.id,
            'account_principal_individuel_id': cls.principal.id, 'account_principal_groupe_id': cls.principal.id,
            'account_interets_recus_individuel_id': cls.interest.id, 'account_interets_recus_groupe_id': cls.interest.id,
            'account_penalites_id': cls.penalty.id})
        cls.savings_product = cls.env['microfinance.savings.product'].create({
            'name': 'Épargne RP', 'code': 'SRP', 'company_id': cls.company.id, 'product_type': 'voluntary',
            'interest_rate': 0.0, 'min_opening_amount': 0.0, 'min_balance': 0.0,
            'account_epargne_individuel_id': cls.savings_acc.id, 'account_epargne_groupe_id': cls.savings_acc_g.id,
            'account_epargne_entreprise_id': cls.savings_acc_co.id,
            'account_interet_paye_individuel_id': cls.savings_interest.id,
            'deposit_journal_id': cls.journal.id, 'withdrawal_journal_id': cls.journal.id})
        cls.env['ir.config_parameter'].sudo().set_param('microfinance.reprise_credit_codes', 'RP203001')
        cls.env['ir.config_parameter'].sudo().set_param('microfinance.reprise_savings_codes', 'RP213001,RP213002,RP213003')

    @classmethod
    def _user(cls, login, groups):
        return cls.env['res.users'].create({
            'name': login, 'login': login, 'email': login + '@rp.test', 'company_id': cls.company.id,
            'company_ids': [(6, 0, (cls.company | cls.other).ids)], 'groups_id': [(6, 0, groups.ids)]})

    @classmethod
    def _account(cls, company, code, account_type):
        return cls.env['account.account'].create({'code': code, 'name': 'Test ' + code, 'account_type': account_type,
                                                  'company_id': company.id})

    def setUp(self):
        super().setUp()
        self.balance = self.env['microfinance.opening.balance'].create({'company_id': self.company.id, 'date': self.opening_date})

    # ------------------------------------------------------------------ outils
    def _cin(self):
        Partner = self.env['res.partner'].with_context(active_test=False)
        while True:
            cin = '99' + ''.join(str(random.randint(0, 9)) for _ in range(10))
            if not Partner.search_count([('microfinance_id_number', '=', cin)]):
                return cin

    def _due(self, days=7):
        return (self.opening_date + timedelta(days=days)).strftime('%d/%m/%Y')

    def _file(self, clients=None, credits=None, savings=None):
        sheets = {}
        if clients is not None:
            sheets['Clients'] = (CLIENTS, clients)
        if credits is not None:
            sheets['Crédits'] = (CREDITS, credits)
        if savings is not None:
            sheets['Épargne'] = (EPARGNE, savings)
        return _workbook(sheets)

    def _client_row(self, ref='CLI-A', cin=None, agent=None, ctype='individuel'):
        return [ref, 'Client ' + ref, cin or self._cin(), '0340000000', (agent or self.agent).name, ctype]

    def _credit_row(self, ref='CLI-A', initial=5000000.0, remaining=1000000.0, count=4, due=None, product=None, agent=None):
        return [ref, (product or self.product).name, initial, remaining, '01/06/%s' % self.today.year, '', count,
                due or self._due(), (agent or self.agent).name]

    def _run(self, file, dry_run=False, user=None):
        wizard = self.env['microfinance.opening.reprise'].with_user(user or self.finance).create({
            'balance_id': self.balance.id, 'file': file, 'filename': 'reprise.xlsx', 'dry_run': dry_run})
        wizard.action_import()
        return wizard

    def _moves(self):
        return self.env['account.move'].sudo().search_count([('company_id', '=', self.company.id)])

    def _partner(self, ref):
        return self.env['res.partner'].with_context(active_test=False).search([
            ('company_id', '=', self.company.id), ('microfinance_internal_reference', '=', ref)])

    def _full_file(self):
        return self._file(
            clients=[self._client_row('CLI-A'), self._client_row('CLI-B')],
            credits=[self._credit_row('CLI-A', 5000000.0, 1000000.0, 4), self._credit_row('CLI-B', 2500000.0, 2000000.0, 3)],
            savings=[['CLI-A', self.savings_product.name, 250000.0], ['CLI-B', self.savings_product.name, 150000.0]])

    # ------------------------------------------------------------------ tests
    def test_import_nominal(self):
        moves = self._moves()
        wizard = self._run(self._full_file())
        self.assertFalse(wizard.has_errors, wizard.report)
        loans = self.env['microfinance.loan'].search([('opening_balance_id', '=', self.balance.id)])
        self.assertEqual(len(loans), 2)
        for loan in loans:
            self.assertEqual((loan.state, bool(loan.disbursement_date)), ('active', True))
            self.assertEqual(loan.officer_id, self.agent)
            self.assertAlmostEqual(sum(loan.installment_ids.mapped('principal_amount')), loan._get_principal_outstanding())
            self.assertEqual(sum(loan.installment_ids.mapped('interest_amount')), 0)
            self.assertFalse(loan.disbursement_move_id or loan.fee_receivable_move_id or loan.fee_move_id
                             or loan.fee_sent_to_cashier)
            self.assertGreaterEqual(min(loan.installment_ids.mapped('due_date')), self.opening_date)
        by_ref = {l.partner_id.microfinance_internal_reference: l for l in loans}
        self.assertEqual(by_ref['CLI-A'].balance_total, 1000000.0)
        self.assertEqual(by_ref['CLI-B'].balance_total, 2000000.0)
        # même conteneur que le compte crédit (nom dérivé du n° permanent du client)
        holder = self.env['microfinance.savings.holder.account'].search([('partner_id', '=', by_ref['CLI-A'].partner_id.id)])
        self.assertEqual(holder.name, 'CE/' + by_ref['CLI-A'].loan_account_id.name)
        self.assertEqual(sum(holder.mapped('balance_total')), 250000.0)
        # d'autres échéances sans intérêt : produit au-delà des limites du catalogue accepté (D3)
        self.assertGreater(by_ref['CLI-B'].loan_amount, self.product.max_amount)
        # aucune écriture comptable, aucun mouvement de caisse, aucun solde d'épargne avec pièce
        self.assertEqual(self._moves(), moves)
        txns = self.env['microfinance.savings.transaction'].search([('opening_balance_id', '=', self.balance.id)])
        self.assertEqual(len(txns), 2)
        self.assertFalse(txns.mapped('move_id'))
        self.assertFalse(self.env['microfinance.caisse.mouvement'].search_count([('partner_id', 'in', txns.partner_id.ids)]))
        self.assertTrue(all(a.state == 'active' for a in txns.account_id))

    def test_simulation_ne_cree_rien(self):
        partners = self.env['res.partner'].search_count([])
        wizard = self._run(self._full_file(), dry_run=True)
        self.assertFalse(wizard.has_errors, wizard.report)
        self.assertIn('Simulation réussie', wizard.report)
        self.assertEqual(self.env['res.partner'].search_count([]), partners)
        self.assertFalse(self.env['microfinance.loan'].search_count([('opening_balance_id', '=', self.balance.id)]))
        self.assertFalse(self.env['microfinance.savings.transaction'].search_count([('opening_balance_id', '=', self.balance.id)]))

    def test_relancer_ne_duplique_rien(self):
        file = self._full_file()
        self._run(file)
        counts = (self.env['res.partner'].search_count([]),
                  self.env['microfinance.loan'].search_count([]),
                  self.env['microfinance.savings.account'].search_count([]),
                  self.env['microfinance.savings.transaction'].search_count([]))
        wizard = self._run(file)
        self.assertFalse(wizard.has_errors, wizard.report)
        self.assertEqual(counts, (self.env['res.partner'].search_count([]),
                                  self.env['microfinance.loan'].search_count([]),
                                  self.env['microfinance.savings.account'].search_count([]),
                                  self.env['microfinance.savings.transaction'].search_count([])))

    def test_doublons_dans_le_fichier(self):
        cin = self._cin()
        wizard = self._run(self._file(clients=[self._client_row('CLI-A', cin), self._client_row('CLI-A'),
                                               self._client_row('CLI-C', cin)]))
        self.assertTrue(wizard.has_errors)
        self.assertIn('en double', wizard.report)
        self.assertFalse(self._partner('CLI-A') | self._partner('CLI-C'))

    def test_erreurs_ligne_par_ligne_et_tout_ou_rien(self):
        wizard = self._run(self._file(
            clients=[self._client_row('CLI-A'), self._client_row('CLI-B', agent=self.agent_sans_pf), self._client_row('CLI-D')],
            credits=[self._credit_row('CLI-A', initial=100.0, remaining=500.0), self._credit_row('CLI-Z'),
                     self._credit_row('CLI-A'), self._credit_row('CLI-D', due='01/01/2000')],
            savings=[['CLI-D', 'Produit fantôme', 10.0]]))
        self.assertTrue(wizard.has_errors)
        report = wizard.report
        for expected in ("portefeuille actif", 'client inconnu', 'principal restant', 'Produit fantôme',
                         'antérieure', 'un seul crédit'):
            self.assertIn(expected, report)
        # tout ou rien : le client valide CLI-A n'est pas créé non plus
        self.assertFalse(self._partner('CLI-A'))

    def test_cin_invalide_et_produit_inconnu(self):
        credit = self._credit_row('CLI-B')
        credit[1] = 'Produit inconnu'
        wizard = self._run(self._file(clients=[self._client_row('CLI-A', cin='123'), self._client_row('CLI-B')],
                                      credits=[credit]))
        self.assertIn('12 chiffres', wizard.report)
        self.assertIn('produit de crédit inconnu', wizard.report)

    def test_cin_deja_utilise_dans_une_autre_societe(self):
        cin = self._cin()
        self.env['res.partner'].with_company(self.other).with_context(
            microfinance_context=True, allow_microfinance_partner_create=True).create({
                'name': 'Autre agence', 'company_id': self.other.id, 'microfinance_partner_type': 'client',
                'microfinance_client_type': 'individual', 'microfinance_id_type': 'cin', 'microfinance_id_number': cin})
        wizard = self._run(self._file(clients=[self._client_row('CLI-A', cin)]))
        self.assertTrue(wizard.has_errors)
        self.assertIn('déjà utilisé', wizard.report)

    def test_regle_inter_agences(self):
        cin = self._cin()
        other_partner = self.env['res.partner'].with_company(self.other).with_context(
            microfinance_context=True, allow_microfinance_partner_create=True).create({
                'name': 'Client autre agence', 'company_id': self.other.id, 'microfinance_partner_type': 'client',
                'microfinance_client_type': 'individual', 'microfinance_id_type': 'cin', 'microfinance_id_number': cin})
        self.env['microfinance.loan'].with_context(mf_reprise_skip_product_limits=True).create({
            'partner_id': other_partner.id, 'product_id': self.product.id, 'company_id': self.other.id,
            'loan_amount': 1000.0, 'term': 2, 'repayment_frequency_id': self.product.repayment_frequency_id.id,
            'state': 'active', 'fee_paid': True, 'disbursement_date': self.today})
        wizard = self._run(self._file(clients=[self._client_row('CLI-A', cin)]))
        self.assertTrue(wizard.has_errors)
        self.assertIn('autre agence', wizard.report)
        self.assertFalse(self._partner('CLI-A'))

    def test_pas_dans_decaissements_en_attente_et_visible_au_dashboard(self):
        self._run(self._full_file())
        Loan = self.env['microfinance.loan']
        self.assertFalse(Loan.get_pending_disbursements(self.company.id))
        kpis = Loan.with_user(self.agent).with_context(allowed_company_ids=[self.company.id]).get_agent_portfolio_kpis(
            officer_id_filter=self.agent.id)
        self.assertEqual(kpis['nb_dossiers_actifs'], 2)
        self.assertEqual(kpis['encours'], 3000000.0)

    def test_concordance_ecart_puis_ok(self):
        self._run(self._full_file())
        self.env['microfinance.opening.balance.line'].create([
            {'balance_id': self.balance.id, 'account_id': self.principal.id, 'debit': 3500000.0},
            {'balance_id': self.balance.id, 'account_id': self.savings_acc.id, 'credit': 400000.0},
            {'balance_id': self.balance.id, 'account_id': self.capital.id, 'credit': 3100000.0}])
        with self.assertRaises(UserError) as error:
            self.balance.action_validate()
        self.assertIn('RP203001', error.exception.args[0])
        self.assertIn('500000', error.exception.args[0])
        self.assertIn('Écart', self.balance.reprise_concordance_html)
        self.balance.line_ids.filtered(lambda l: l.account_id == self.principal).debit = 3000000.0
        self.balance.line_ids.filtered(lambda l: l.account_id == self.capital).credit = 2600000.0
        self.balance.action_validate()
        self.assertEqual(self.balance.state, 'validated')

    def test_validation_sans_reprise_avertit_sans_bloquer(self):
        self.env['microfinance.opening.balance.line'].create([
            {'balance_id': self.balance.id, 'account_id': self.principal.id, 'debit': 100.0},
            {'balance_id': self.balance.id, 'account_id': self.capital.id, 'credit': 100.0}])
        self.balance.action_validate()
        self.assertEqual(self.balance.state, 'validated')
        self.assertTrue(any('aucune reprise' in (m.body or '') for m in self.balance.message_ids))

    def test_droits(self):
        # le profil auditeur peut simuler mais pas importer
        file = self._full_file()
        wizard = self._run(file, dry_run=True, user=self.auditor)
        self.assertFalse(wizard.has_errors, wizard.report)
        with self.assertRaises(AccessError):
            self._run(file, dry_run=False, user=self.auditor)

    def test_montant_ouverture_verrouille(self):
        self._run(self._full_file())
        txn = self.env['microfinance.savings.transaction'].search([('opening_balance_id', '=', self.balance.id)], limit=1)
        with self.assertRaises(ValidationError):
            txn.write({'amount': 1.0})

    def test_lecteur_excel_dates_serie_et_texte(self):
        self.assertEqual(xlsx.to_date(46000.0), date(1899, 12, 30) + timedelta(days=46000))
        self.assertEqual(xlsx.to_date('15/10/2026'), date(2026, 10, 15))
        self.assertEqual(xlsx.to_date('2026-10-15'), date(2026, 10, 15))
        self.assertIsNone(xlsx.to_date(''))
        with self.assertRaises(ValueError):
            xlsx.to_date('pas une date')
        sheets = xlsx.read_sheets(base64.b64decode(self._full_file()))
        self.assertEqual(list(sheets), ['Clients', 'Crédits', 'Épargne'])

    def test_gabarit_telechargeable(self):
        content = self.env['microfinance.opening.reprise']._template_workbook()
        sheets = xlsx.read_sheets(content)
        self.assertEqual(list(sheets), ['Clients', 'Crédits', 'Épargne', "Mode d'emploi"])

    def test_concordance_sans_zero_negatif_et_montants_formates_comme_les_lignes(self):
        self._run(self._full_file())
        # lignes à zéro sur les autres comptes d'épargne (modèle chargé) : l'inversion de signe donnait -0.0
        self.env['microfinance.opening.balance.line'].create([
            {'balance_id': self.balance.id, 'account_id': self.savings_acc_g.id},
            {'balance_id': self.balance.id, 'account_id': self.savings_acc_co.id},
            {'balance_id': self.balance.id, 'account_id': self.principal.id, 'debit': 3000000.0},
            {'balance_id': self.balance.id, 'account_id': self.savings_acc.id, 'credit': 400000.0}])
        lines = self.balance._reprise_concordance()
        self.assertGreaterEqual(len(lines), 4)
        for line in lines:
            for key in ('balance', 'detail', 'gap'):
                self.assertEqual(math.copysign(1.0, line[key]), 1.0, "%s %s" % (line['account'].code, key))
        html = self.balance.reprise_concordance_html
        self.assertNotIn('-0', html)
        currency = self.company.currency_id
        self.assertIn(format_amount(self.env, 3000000.0, currency), html)  # même moteur que les montants des lignes
        lang = self.env['res.lang'].search([('code', '=', 'fr_FR')], limit=1)
        if lang and lang.active:
            html_fr = self.balance.with_context(lang='fr_FR').reprise_concordance_html
            self.assertIn(format_amount(self.env['res.partner'].with_context(lang='fr_FR').env, 3000000.0, currency), html_fr)
