# -*- coding: utf-8 -*-
from odoo.addons.microfinance_loan_management import hooks

from .common import MicrofinanceCommon


class TestJournalHooks(MicrofinanceCommon):
    """Garde-fou anti-régression du bug corrigé en 17.0.1.5.0 (docs_dev/gestion_caisse/AUDIT.md
    §1.3) : CRE/EPG étaient créés en type 'general' alors qu'ils sont utilisés comme valeur par
    défaut de champs Many2one account.journal dont le domaine de vue exige
    ('type', 'in', ('bank', 'cash')), et qui ne seraient donc pas sélectionnables tels quels."""

    def test_create_journals_cre_epg_are_cash_not_general(self):
        company = self.env['res.company'].create({'name': 'Agence hook journaux (test)', 'agency_code': 'JH1'})
        hooks._create_journals(self.env, company)
        journals = self.env['account.journal'].search([
            ('company_id', '=', company.id), ('code', 'in', ('CRE', 'EPG')),
        ])
        self.assertEqual(len(journals), 2)
        for journal in journals:
            self.assertIn(
                journal.type, ('bank', 'cash'),
                "%s doit être de type bank/cash, pas %s" % (journal.code, journal.type),
            )

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
            self.assertTrue(journal, "Le défaut de %s n'a pas trouvé le journal CRE" % field_name)
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
