# -*- coding: utf-8 -*-
from odoo.addons.microfinance_loan_management import hooks

from .common import MicrofinanceCommon


class TestJournalHooks(MicrofinanceCommon):
    """Garde-fou anti-régression du bug corrigé en 17.0.1.5.0 (docs_dev/gestion_caisse/AUDIT.md
    §1.3) : CRE/EPG étaient créés en type 'general' alors qu'ils sont utilisés comme valeur par
    défaut de champs Many2one account.journal dont le domaine de vue exige
    ('type', 'in', ('bank', 'cash')), et qui ne seraient donc pas sélectionnables tels quels."""

    def test_create_journals_cre_epg_are_cash_not_general(self):
        company = self.env['res.company'].create({'name': 'Agence hook journaux (test)'})
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
        company = self.env['res.company'].create({'name': 'Agence hook journaux OD (test)'})
        hooks._create_journals(self.env, company)
        od = self.env['account.journal'].search([
            ('company_id', '=', company.id), ('code', '=', 'OD'),
        ])
        self.assertEqual(od.type, 'general')

    def test_create_journals_idempotent(self):
        # _create_journals ne recrée pas un journal déjà présent (même code + société) : appelé
        # deux fois, le nombre de journaux créés ne double pas.
        company = self.env['res.company'].create({'name': 'Agence hook journaux idempotence (test)'})
        hooks._create_journals(self.env, company)
        count_after_first_call = self.env['account.journal'].search_count([('company_id', '=', company.id)])
        hooks._create_journals(self.env, company)
        count_after_second_call = self.env['account.journal'].search_count([('company_id', '=', company.id)])
        self.assertEqual(count_after_first_call, count_after_second_call)

    def test_loan_product_journal_defaults_match_view_domain(self):
        # Les défauts calculés (_journal_default) doivent retourner un journal satisfaisant le
        # domaine de vue déclaré sur le champ, une fois les journaux correctement typés.
        company = self.env['res.company'].create({'name': 'Agence défauts journal produit (test)'})
        hooks._create_journals(self.env, company)
        product = self.env['microfinance.loan.product'].with_company(company).new({})
        for field_name in ('disbursement_journal_id', 'payment_journal_id', 'fee_journal_id'):
            journal = product[field_name]
            self.assertTrue(journal, "Le défaut de %s n'a pas trouvé le journal CRE" % field_name)
            self.assertIn(journal.type, ('bank', 'cash'))
