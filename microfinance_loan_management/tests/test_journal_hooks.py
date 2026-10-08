# -*- coding: utf-8 -*-
from odoo.addons.microfinance_loan_management import hooks
from odoo.exceptions import ValidationError

from .common import MicrofinanceCommon


class TestJournalHooks(MicrofinanceCommon):
    """Garde-fou anti-régression du bug corrigé en 17.0.1.5.0 (docs_dev/gestion_caisse/AUDIT.md
    §1.3) : CRE/EPG étaient créés en type 'general' alors qu'ils sont utilisés comme valeur par
    défaut de champs Many2one account.journal dont le domaine de vue exige
    ('type', 'in', ('bank', 'cash')), et qui ne seraient donc pas sélectionnables tels quels."""

    def test_create_journals_treasury_structure(self):
        # Structure cible : un journal = un endroit où se trouve l'argent. CRE, EPG et BQxx
        # n'existent plus ; les journaux de trésorerie sont de type bank/cash.
        company = self.env['res.company'].create({'name': 'Agence hook journaux (test)', 'agency_code': 'JH1'})
        hooks._create_journals(self.env, company)
        journals = self.env['account.journal'].search([('company_id', '=', company.id)])
        codes = set(journals.mapped('code'))
        for code in ('CAI', 'BMCR', 'BNCR', 'BMEP', 'BNEP', 'MVO', 'BMOP', 'BNOP', 'VIR', 'OD', 'AN'):
            self.assertIn(code, codes)
        for code in ('CRE', 'EPG', 'BQOP', 'BQEP', 'BQCR', 'FDBM', 'FDBN', 'TRANS', 'TRANSIT'):
            self.assertNotIn(code, codes)
        for code in ('CAI', 'BMCR', 'BNCR', 'BMEP', 'BNEP', 'MVO', 'BMOP', 'BNOP'):
            self.assertIn(journals.filtered(lambda j: j.code == code).type, ('bank', 'cash'))

    def test_create_journals_od_stays_general(self):
        # OD (Opérations diverses) n'est jamais utilisé comme défaut d'un champ journal du
        # produit crédit/épargne : il reste 'general', réservé aux écritures de radiation/
        # provision (recherche dynamique du journal 'general' de la société).
        company = self.env['res.company'].create({'name': 'Agence hook journaux OD (test)', 'agency_code': 'JH2'})
        hooks._create_journals(self.env, company)
        od = self.env['account.journal'].search([
            ('company_id', '=', company.id), ('code', '=', 'OD'),
        ])
        self.assertEqual(od.type, 'general')

    def test_create_journals_idempotent(self):
        # _create_journals ne recrée pas un journal déjà présent (même code + société) : appelé
        # deux fois, le nombre de journaux créés ne double pas.
        company = self.env['res.company'].create({'name': 'Agence hook journaux idempotence (test)', 'agency_code': 'JH3'})
        hooks._create_journals(self.env, company)
        count_after_first_call = self.env['account.journal'].search_count([('company_id', '=', company.id)])
        hooks._create_journals(self.env, company)
        count_after_second_call = self.env['account.journal'].search_count([('company_id', '=', company.id)])
        self.assertEqual(count_after_first_call, count_after_second_call)

    def test_loan_product_journal_defaults_match_view_domain(self):
        # Les défauts calculés (_journal_default) doivent retourner un journal satisfaisant le
        # domaine de vue déclaré sur le champ, une fois les journaux correctement typés.
        company = self.env['res.company'].create({'name': 'Agence défauts journal produit (test)', 'agency_code': 'JH4'})
        hooks._create_journals(self.env, company)
        product = self.env['microfinance.loan.product'].with_company(company).new({})
        for field_name in ('disbursement_journal_id', 'payment_journal_id', 'fee_journal_id'):
            journal = product[field_name]
            self.assertTrue(journal, "Le défaut de %s n'a pas trouvé le journal CAI" % field_name)
            self.assertIn(journal.type, ('bank', 'cash'))


class TestBackfillCashJournalId(MicrofinanceCommon):
    """Backfill de res.company.cash_journal_id (restriction du journal de session de caisse
    guichet, cf. models/res_company.py et migrations/17.0.1.14.0) à partir du journal de code
    'CAI' déjà provisionné sur l'agence."""

    def test_backfill_sets_cash_journal_from_cai_journal(self):
        company = self.env['res.company'].create({
            'name': 'Agence backfill avec CAI (test)', 'agency_code': 'BF1',
        })
        cai = self.env['account.journal'].create({
            'name': 'Caisse', 'code': 'CAI', 'type': 'cash', 'company_id': company.id,
        })
        backfilled, missing = hooks._backfill_cash_journal_id(self.env)
        self.assertIn(company.name, backfilled)
        self.assertNotIn(company.name, missing)
        self.assertEqual(company.cash_journal_id, cai)

    def test_backfill_reports_missing_cai_journal_without_error(self):
        # Les agences pas encore provisionnées (pas de journal CAI) ne doivent pas faire
        # planter le script : elles sont seulement journalisées comme "missing", cash_journal_id
        # reste vide.
        company = self.env['res.company'].create({
            'name': 'Agence backfill sans CAI (test)', 'agency_code': 'BF2',
        })
        backfilled, missing = hooks._backfill_cash_journal_id(self.env)
        self.assertNotIn(company.name, backfilled)
        self.assertIn(company.name, missing)
        self.assertFalse(company.cash_journal_id)

    def test_backfill_does_not_overwrite_existing_cash_journal_id(self):
        company = self.env['res.company'].create({
            'name': 'Agence backfill déjà configurée (test)', 'agency_code': 'BF3',
        })
        self.env['account.journal'].create({
            'name': 'Caisse', 'code': 'CAI', 'type': 'cash', 'company_id': company.id,
        })
        already_set = self.env['account.journal'].create({
            'name': 'Caisse déjà choisie', 'code': 'BF3C', 'type': 'cash', 'company_id': company.id,
        })
        company.cash_journal_id = already_set.id
        backfilled, missing = hooks._backfill_cash_journal_id(self.env)
        self.assertNotIn(company.name, backfilled)
        self.assertNotIn(company.name, missing)
        self.assertEqual(company.cash_journal_id, already_set)

    def test_backfill_idempotent(self):
        company = self.env['res.company'].create({
            'name': 'Agence backfill idempotence (test)', 'agency_code': 'BF4',
        })
        cai = self.env['account.journal'].create({
            'name': 'Caisse', 'code': 'CAI', 'type': 'cash', 'company_id': company.id,
        })
        hooks._backfill_cash_journal_id(self.env)
        self.assertEqual(company.cash_journal_id, cai)
        backfilled_again, missing_again = hooks._backfill_cash_journal_id(self.env)
        self.assertNotIn(company.name, backfilled_again)
        self.assertNotIn(company.name, missing_again)
        self.assertEqual(company.cash_journal_id, cai)


class TestOperatingJournal(MicrofinanceCommon):
    """Journal bancaire d'exploitation (res.company.microfinance_operating_journal_id) et
    journaux de fonds réservés à la société mère."""

    def _company(self, name, code):
        return self.env['res.company'].create({'name': name, 'agency_code': code})

    def test_default_is_bmop_on_new_company(self):
        company = self._company('Agence exploitation défaut (test)', 'OP1')
        hooks._create_journals(self.env, company)
        hooks._set_default_operating_journal(self.env, company)
        self.assertEqual(company.microfinance_operating_journal_id.code, 'BMOP')

    def test_default_does_not_overwrite_existing_choice(self):
        company = self._company('Agence exploitation choix (test)', 'OP2')
        hooks._create_journals(self.env, company)
        bnop = self.env['account.journal'].search([('company_id', '=', company.id), ('code', '=', 'BNOP')])
        company.microfinance_operating_journal_id = bnop
        hooks._set_default_operating_journal(self.env, company)
        self.assertEqual(company.microfinance_operating_journal_id, bnop)

    def test_constraint_refuses_fund_journals(self):
        company = self._company('Agence exploitation fonds (test)', 'OP3')
        for code in ('FDBM', 'FDBN'):
            fund = self.env['account.journal'].create({
                'name': 'Fonds %s' % code, 'code': code, 'type': 'bank', 'company_id': company.id})
            with self.assertRaises(ValidationError):
                company.microfinance_operating_journal_id = fund

    def test_constraint_refuses_non_bank_journal(self):
        company = self._company('Agence exploitation non bancaire (test)', 'OP4')
        hooks._create_journals(self.env, company)
        cai = self.env['account.journal'].search([('company_id', '=', company.id), ('code', '=', 'CAI')])
        with self.assertRaises(ValidationError):
            company.microfinance_operating_journal_id = cai

    def test_credit_journal_gives_warning_not_error(self):
        company = self._company('Agence exploitation avertissement (test)', 'OP5')
        hooks._create_journals(self.env, company)
        bmcr = self.env['account.journal'].search([('company_id', '=', company.id), ('code', '=', 'BMCR')])
        company.microfinance_operating_journal_id = bmcr  # accepté
        self.assertEqual(company.microfinance_operating_journal_id, bmcr)
        self.assertIn('warning', self.env['res.company']._operating_journal_warning(bmcr))
        bmop = self.env['account.journal'].search([('company_id', '=', company.id), ('code', '=', 'BMOP')])
        self.assertFalse(self.env['res.company']._operating_journal_warning(bmop))

    def test_replay_does_not_recreate_archived_journal(self):
        company = self._company('Agence rejeu hook (test)', 'OP6')
        hooks._create_journals(self.env, company)
        bmcr = self.env['account.journal'].search([('company_id', '=', company.id), ('code', '=', 'BMCR')])
        bmcr.active = False
        hooks._create_journals(self.env, company)  # ne doit ni lever d'erreur ni recréer
        all_bmcr = self.env['account.journal'].with_context(active_test=False).search([
            ('company_id', '=', company.id), ('code', '=', 'BMCR')])
        self.assertEqual(all_bmcr, bmcr)
        self.assertFalse(all_bmcr.active)

    def test_fund_journals_only_on_parent_company(self):
        parent = self._company('Siège fonds (test)', 'OP7')
        agency = self._company('Agence sans fonds (test)', 'OP8')
        self.env['ir.config_parameter'].sudo().set_param('microfinance.parent_company_id', str(parent.id))
        hooks._create_journals(self.env, parent)
        hooks._create_journals(self.env, agency)
        Journal = self.env['account.journal']
        self.assertEqual(Journal.search_count([('company_id', '=', parent.id), ('code', 'in', ('FDBM', 'FDBN'))]), 2)
        self.assertEqual(Journal.search_count([('company_id', '=', agency.id), ('code', 'in', ('FDBM', 'FDBN'))]), 0)

    def test_payroll_journal_follows_operating_journal(self):
        company = self._company('Agence paie (test)', 'OP9')
        hooks._create_journals(self.env, company)
        Journal = self.env['account.journal']
        bmop = Journal.search([('company_id', '=', company.id), ('code', '=', 'BMOP')])
        bnop = Journal.search([('company_id', '=', company.id), ('code', '=', 'BNOP')])
        company.microfinance_operating_journal_id = bmop
        self.assertEqual(company.payroll_journal_id, bmop)
        company.microfinance_operating_journal_id = bnop
        self.assertEqual(company.payroll_journal_id, bnop)


class TestPaymentAccountsByJournalType(MicrofinanceCommon):
    """139100/139500 (établissements de crédit) sont réservés aux journaux bancaires ; un journal de
    caisse a pour compte de paiement son compte par défaut (101000)."""

    def _company_with_accounts(self, name, code):
        company = self.env['res.company'].create({'name': name, 'agency_code': code})
        Account = self.env['account.account']
        accounts = {}
        for acode, atype, rec in (
                ('101000', 'asset_cash', False), ('139100', 'asset_current', True),
                ('139500', 'liability_current', True), ('201000', 'asset_receivable', True),
                ('401000', 'liability_payable', True)):
            accounts[acode] = Account.create({
                'code': acode, 'name': 'Test %s' % acode, 'account_type': atype,
                'reconcile': rec, 'company_id': company.id})
        return company, accounts

    def test_cash_journal_has_default_account_as_payment_account_bank_has_139(self):
        company, accounts = self._company_with_accounts('Agence comptes paiement (test)', 'PA1')
        hooks._create_journals(self.env, company)
        Journal = self.env['account.journal']
        cai = Journal.search([('company_id', '=', company.id), ('code', '=', 'CAI')])
        for line in cai.inbound_payment_method_line_ids | cai.outbound_payment_method_line_ids:
            self.assertEqual(line.payment_account_id, accounts['101000'])
        bmop = Journal.search([('company_id', '=', company.id), ('code', '=', 'BMOP')])
        self.assertEqual(bmop.inbound_payment_method_line_ids.payment_account_id, accounts['139100'])
        self.assertEqual(bmop.outbound_payment_method_line_ids.payment_account_id, accounts['139500'])

    def test_replay_does_not_recreate_archived_journal_or_transit(self):
        company, _accounts = self._company_with_accounts('Agence rejeu sans TRANS (test)', 'PA2')
        hooks._create_journals(self.env, company)
        Journal = self.env['account.journal'].with_context(active_test=False)
        self.assertFalse(Journal.search([('company_id', '=', company.id), ('code', 'in', ('TRANS', 'TRANSIT'))]))
        cai = Journal.search([('company_id', '=', company.id), ('code', '=', 'CAI')])
        cai.active = False
        count = Journal.search_count([('company_id', '=', company.id)])
        hooks._create_journals(self.env, company)
        self.assertEqual(Journal.search_count([('company_id', '=', company.id)]), count)

    def test_cash_payment_in_and_out_lands_on_101000_and_is_matched(self):
        company, accounts = self._company_with_accounts('Agence paiement espèces (test)', 'PA3')
        hooks._create_journals(self.env, company)
        cai = self.env['account.journal'].search([('company_id', '=', company.id), ('code', '=', 'CAI')])
        partner = self.env['res.partner'].create({'name': 'Client paiement espèces (test)'})
        for payment_type, partner_type, destination in (
                ('inbound', 'customer', accounts['201000']), ('outbound', 'supplier', accounts['401000'])):
            lines = (cai.inbound_payment_method_line_ids if payment_type == 'inbound'
                     else cai.outbound_payment_method_line_ids)
            payment = self.env['account.payment'].with_company(company).create({
                'payment_type': payment_type, 'partner_type': partner_type, 'partner_id': partner.id,
                'amount': 1000.0, 'journal_id': cai.id, 'payment_method_line_id': lines[:1].id,
                'destination_account_id': destination.id,
            })
            payment.action_post()
            liquidity = payment.move_id.line_ids.filtered(lambda l: l.account_id == payment.outstanding_account_id)
            self.assertEqual(payment.state, 'posted')
            self.assertEqual(liquidity.account_id, accounts['101000'], payment_type)
            self.assertTrue(payment.is_matched, "Un paiement en espèces doit être rapproché d'emblée (%s)" % payment_type)
            self.assertFalse(payment.move_id.line_ids.filtered(lambda l: l.account_id.code in ('139100', '139500')))
