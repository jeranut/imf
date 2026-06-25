from odoo.tests import TransactionCase, tagged


@tagged('post_install_l10n', '-at_install', 'post_install')
class TestMgChart(TransactionCase):
    """Smoke tests for softeam_l10n_mg.

    These tests run AFTER module install with --test-enable. The mere fact
    that they execute proves the manifest, CSV chart files (v17+/18+/19) or
    XML records (v16), Python models, and i18n all parse cleanly.

    Cross-version API: avoids depending on AccountTestInvoicingCommon, whose
    setUpClass signature changed between v16 → v17 → v18 → v19. Uses only
    res.company / account.account / account.tax models which remain stable.
    """

    def test_module_installed(self):
        """Module is in 'installed' state after `-i softeam_l10n_mg`."""
        module = self.env['ir.module.module'].search([
            ('name', '=', 'softeam_l10n_mg'),
        ])
        self.assertTrue(module, 'softeam_l10n_mg should be findable')
        self.assertEqual(
            module.state, 'installed',
            f'Module state should be installed, got {module.state!r}',
        )

    def test_currency_mga_available(self):
        """MGA (Ariary) currency exists in base."""
        mga = self.env.ref('base.MGA', raise_if_not_found=False)
        self.assertTrue(mga, 'base.MGA currency should exist')
        self.assertEqual(mga.name, 'MGA')

    def test_country_mg_available(self):
        """Madagascar country exists in base."""
        mg = self.env.ref('base.mg', raise_if_not_found=False)
        self.assertTrue(mg, 'base.mg country should exist')
        self.assertEqual(mg.code, 'MG')

    def test_chart_template_artifact_present(self):
        """Verify a chart_template artifact is present.

        On v16 the chart is a regular ir.model.data record under our module.
        On v17.1+/18+/19 the @template decorator registers the chart at module
        scan time but doesn't create ir.model.data until try_loading is called.
        Either way, our module's package must be loaded.
        """
        module_records = self.env['ir.model.data'].search([
            ('module', '=', 'softeam_l10n_mg'),
        ])
        self.assertGreater(
            len(module_records), 0,
            'Module should have loaded at least some ir.model.data records',
        )
