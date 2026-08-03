# -*- coding: utf-8 -*-
from odoo.addons.microfinance_loan_management.hooks import (
    _cleanup_existing_financial_lines,
    _load_financial_reference_data,
)

from .common import MicrofinanceCommon


class TestFinancialReferenceDataLoading(MicrofinanceCommon):
    """Chargement des désignations par défaut (3 catalogues) et des fréquences configurables
    (Section V — refonte 2026-07-20) : cf. hooks._load_financial_reference_data."""

    def test_loading_designations_and_frequencies(self):
        _load_financial_reference_data(self.env)
        Income = self.env['microfinance.financial.designation.income']
        ActivityExpense = self.env['microfinance.financial.designation.activity.expense']
        FamilyExpense = self.env['microfinance.financial.designation.family.expense']
        Frequency = self.env['microfinance.financial.frequency']
        self.assertEqual(Income.search_count([]), 7)
        self.assertEqual(ActivityExpense.search_count([]), 7)
        self.assertEqual(FamilyExpense.search_count([]), 21)
        self.assertEqual(Frequency.search_count([]), 3)
        self.assertEqual(
            set(Frequency.search([]).mapped('name')),
            {'Quotidien', 'Hebdomadaire', 'Mensuel'},
        )

        # Idempotent : un second appel ne doit rien dupliquer.
        _load_financial_reference_data(self.env)
        self.assertEqual(Income.search_count([]), 7)
        self.assertEqual(Frequency.search_count([]), 3)


class TestFinancialLinesPrefill(MicrofinanceCommon):
    """Pré-remplissage automatique des lignes financières à la création du dossier : une ligne
    par désignation configurée, pour chacune des 3 catégories × 2 situations."""

    def setUp(self):
        super().setUp()
        _load_financial_reference_data(self.env)

    def _create_application(self, **kwargs):
        vals = {'partner_id': self.partner.id, 'loan_product_id': self.product.id}
        vals.update(kwargs)
        return self.env['microfinance.loan.application'].create(vals)

    def test_six_tables_prefilled_with_configured_designations(self):
        application = self._create_application()
        lines = application.income_line_ids
        self.assertEqual(
            len(lines.filtered(lambda l: l.category == 'family_income' and l.situation == 'current')), 7)
        self.assertEqual(
            len(lines.filtered(lambda l: l.category == 'family_income' and l.situation == 'forecast')), 7)
        self.assertEqual(
            len(lines.filtered(lambda l: l.category == 'activity_expense' and l.situation == 'current')), 7)
        self.assertEqual(
            len(lines.filtered(lambda l: l.category == 'activity_expense' and l.situation == 'forecast')), 7)
        self.assertEqual(
            len(lines.filtered(lambda l: l.category == 'family_expense' and l.situation == 'current')), 21)
        self.assertEqual(
            len(lines.filtered(lambda l: l.category == 'family_expense' and l.situation == 'forecast')), 21)
        self.assertEqual(len(lines), 70)

    def test_prefill_not_duplicated_when_called_twice(self):
        application = self._create_application()
        application._ensure_default_financial_lines()
        self.assertEqual(len(application.income_line_ids), 70)

    def test_prefill_uses_active_designations_only(self):
        inactive_designation = self.env['microfinance.financial.designation.activity.expense'].search([], limit=1)
        inactive_designation.active = False
        application = self._create_application()
        self.assertEqual(
            len(application.income_line_ids.filtered(
                lambda l: l.category == 'activity_expense' and l.situation == 'current')),
            6,
        )
        self.assertFalse(application.income_line_ids.filtered(
            lambda l: l.activity_expense_designation_id == inactive_designation))

    def test_cleanup_existing_financial_lines_removes_empty_duplicates_and_recreates_missing(self):
        application = self._create_application()
        monthly = self.env.ref('microfinance_loan_management.financial_frequency_monthly')
        activity_line = application.income_line_ids.filtered(
            lambda l: l.category == 'activity_expense' and l.situation == 'forecast')[:1]
        activity_line.amount = 10000
        shared_designation = activity_line.activity_expense_designation_id
        duplicate = activity_line.copy({'amount': 25000})
        empty = self.env['microfinance.loan.application.income.line'].create({
            'application_id': application.id,
            'category': 'activity_expense',
            'situation': 'forecast',
            'frequency_id': monthly.id,
        })
        removed_expected = application.income_line_ids.filtered(
            lambda l: l.category == 'family_expense' and l.situation == 'current')[:1]
        removed_designation = removed_expected.family_expense_designation_id
        removed_expected.unlink()

        _cleanup_existing_financial_lines(self.env)
        application.invalidate_recordset()

        activity_forecast = application.income_line_ids.filtered(
            lambda l: l.category == 'activity_expense' and l.situation == 'forecast')
        self.assertEqual(len(activity_forecast), 7)
        self.assertFalse(empty.exists())
        # L'une des deux lignes en doublon (activity_line ou duplicate, selon le départage de
        # _financial_line_keep_key) a été supprimée — une seule doit subsister pour cette
        # désignation partagée, peu importe laquelle exactement.
        self.assertEqual(
            len(activity_forecast.filtered(
                lambda l: l.activity_expense_designation_id == shared_designation)),
            1,
        )
        self.assertEqual(
            len(application.income_line_ids.filtered(
                lambda l: l.category == 'family_expense'
                and l.situation == 'current'
                and l.family_expense_designation_id == removed_designation)),
            1,
        )

    def test_read_never_creates_lines(self):
        # read() ne doit jamais déclencher _ensure_default_financial_lines() (retiré : une
        # lecture peut être appelée plusieurs fois/en parallèle par le client web, ce qui a
        # provoqué une duplication massive constatée en usage réel — cf. correctif 2026-07-20).
        application = self._create_application()
        application.income_line_ids.unlink()
        application.read(['name', 'income_line_ids'])
        application.invalidate_recordset()
        self.assertFalse(application.income_line_ids)


class TestFinancialMonthlyAmountComputation(MicrofinanceCommon):
    """monthly_amount = amount × frequency_id.multiplier (plus de saisie directe du montant
    mensuel) — multiplicateurs configurables librement (Configuration > Financement)."""

    def setUp(self):
        super().setUp()
        _load_financial_reference_data(self.env)

    def _create_application(self, **kwargs):
        vals = {'partner_id': self.partner.id, 'loan_product_id': self.product.id}
        vals.update(kwargs)
        return self.env['microfinance.loan.application'].create(vals)

    def _first_line(self, application, category, situation='current'):
        return application.income_line_ids.filtered(
            lambda l: l.category == category and l.situation == situation)[:1]

    def test_daily_multiplier(self):
        application = self._create_application()
        line = self._first_line(application, 'family_income')
        line.write({
            'amount': 10000,
            'frequency_id': self.env.ref('microfinance_loan_management.financial_frequency_daily').id,
        })
        self.assertEqual(line.monthly_amount, 300000)

    def test_weekly_multiplier(self):
        application = self._create_application()
        line = self._first_line(application, 'family_income')
        line.write({
            'amount': 170000,
            'frequency_id': self.env.ref('microfinance_loan_management.financial_frequency_weekly').id,
        })
        self.assertEqual(line.monthly_amount, 680000)

    def test_monthly_multiplier(self):
        application = self._create_application()
        line = self._first_line(application, 'family_income')
        line.write({
            'amount': 250000,
            'frequency_id': self.env.ref('microfinance_loan_management.financial_frequency_monthly').id,
        })
        self.assertEqual(line.monthly_amount, 250000)

    def test_multiplier_freely_editable_in_configuration(self):
        # Le multiplicateur reste libre (pas figé en dur) : modifiable depuis Configuration.
        application = self._create_application()
        weekly = self.env.ref('microfinance_loan_management.financial_frequency_weekly')
        weekly.multiplier = 5
        line = self._first_line(application, 'family_income')
        line.write({'amount': 100000, 'frequency_id': weekly.id})
        self.assertEqual(line.monthly_amount, 500000)


class TestFinancialSafetyMargin(MicrofinanceCommon):
    """La majoration (+X%) s'applique uniquement au sous-total des dépenses familiales, jamais
    aux dépenses d'activité — point de vérification confirmé avec Micka (audit Section V)."""

    def setUp(self):
        super().setUp()
        _load_financial_reference_data(self.env)

    def _create_application(self, **kwargs):
        vals = {'partner_id': self.partner.id, 'loan_product_id': self.product.id}
        vals.update(kwargs)
        return self.env['microfinance.loan.application'].create(vals)

    def test_margin_applied_to_family_expense_only(self):
        application = self._create_application(safety_margin_current=5.0)
        monthly = self.env.ref('microfinance_loan_management.financial_frequency_monthly')
        family_line = application.income_line_ids.filtered(
            lambda l: l.category == 'family_expense' and l.situation == 'current')[:1]
        family_line.write({'amount': 100000, 'frequency_id': monthly.id})
        activity_line = application.income_line_ids.filtered(
            lambda l: l.category == 'activity_expense' and l.situation == 'current')[:1]
        activity_line.write({'amount': 100000, 'frequency_id': monthly.id})

        self.assertEqual(application.total_family_expense_current, 105000)
        self.assertEqual(application.total_activity_expense_current, 100000)


class TestFinancialCapacityCalculation(MicrofinanceCommon):
    """Capacité de remboursement mensuelle/hebdomadaire — exemple chiffré de la fiche papier
    CEFOR (revenu 840 000, dépenses activités 44 200, dépenses familiales majorées 581 910
    → capacité attendue 213 890 mensuel / 53 472,5 hebdomadaire, soit ÷4 exactement)."""

    def setUp(self):
        super().setUp()
        _load_financial_reference_data(self.env)

    def _create_application(self, **kwargs):
        vals = {'partner_id': self.partner.id, 'loan_product_id': self.product.id}
        vals.update(kwargs)
        return self.env['microfinance.loan.application'].create(vals)

    def test_paper_example_monthly_and_weekly_capacity(self):
        application = self._create_application(safety_margin_current=5.0)
        monthly = self.env.ref('microfinance_loan_management.financial_frequency_monthly')

        income_line = application.income_line_ids.filtered(
            lambda l: l.category == 'family_income' and l.situation == 'current')[:1]
        income_line.write({'amount': 840000, 'frequency_id': monthly.id})

        activity_line = application.income_line_ids.filtered(
            lambda l: l.category == 'activity_expense' and l.situation == 'current')[:1]
        activity_line.write({'amount': 44200, 'frequency_id': monthly.id})

        family_line = application.income_line_ids.filtered(
            lambda l: l.category == 'family_expense' and l.situation == 'current')[:1]
        family_line.write({'amount': 554200, 'frequency_id': monthly.id})  # ×1.05 = 581 910

        self.assertEqual(application.total_family_expense_current, 581910)
        self.assertEqual(application.repayment_capacity_monthly_current, 213890)
        self.assertEqual(application.repayment_capacity_weekly_current, 53472.5)


class TestIncomeGrowthBlock(MicrofinanceCommon):
    """Bloc Accroissement du revenu : radio Oui/Non (défaut Non), montants Avant/Actuel visibles
    uniquement si Oui."""

    def _create_application(self, **kwargs):
        vals = {'partner_id': self.partner.id, 'loan_product_id': self.product.id}
        vals.update(kwargs)
        return self.env['microfinance.loan.application'].create(vals)

    def test_default_is_no(self):
        application = self._create_application()
        self.assertEqual(application.income_growth_occurred, 'no')

    def test_amounts_stored_when_yes(self):
        application = self._create_application(
            income_growth_occurred='yes', income_growth_before=300000, income_growth_after=450000)
        self.assertEqual(application.income_growth_before, 300000)
        self.assertEqual(application.income_growth_after, 450000)
