from odoo.tests import TransactionCase, tagged


@tagged('post_install_l10n', '-at_install', 'post_install')
class TestMgReports(TransactionCase):
    """Smoke tests for softeam_l10n_mg_reports."""

    def test_module_installed(self):
        module = self.env['ir.module.module'].search([
            ('name', '=', 'softeam_l10n_mg_reports'),
        ])
        self.assertTrue(module)
        self.assertEqual(module.state, 'installed')

    def test_tax_report_loaded(self):
        report = self.env.ref(
            'softeam_l10n_mg_reports.tax_report',
            raise_if_not_found=False,
        )
        self.assertTrue(report, 'Madagascar tax report should be loaded')
        self.assertEqual(report.country_id.code, 'MG')
        self.assertGreater(
            len(report.line_ids), 3,
            'Tax report should have at least 4 sections (A/B/C/D)',
        )

    def test_balance_sheet_loaded(self):
        report = self.env.ref(
            'softeam_l10n_mg_reports.balance_sheet',
            raise_if_not_found=False,
        )
        self.assertTrue(report, 'Madagascar balance sheet should be loaded')
        self.assertEqual(report.country_id.code, 'MG')

    def test_income_statement_loaded(self):
        report = self.env.ref(
            'softeam_l10n_mg_reports.income_statement_nature',
            raise_if_not_found=False,
        )
        self.assertTrue(report, 'Madagascar income statement should be loaded')
        self.assertEqual(report.country_id.code, 'MG')

    def test_reports_country_filter(self):
        """All Madagascar reports should be filtered by country=MG."""
        reports = self.env['account.report'].search([
            ('country_id.code', '=', 'MG'),
        ])
        self.assertGreaterEqual(
            len(reports), 3,
            'Expected at least 3 Madagascar reports (TVA, Bilan, CR)',
        )
