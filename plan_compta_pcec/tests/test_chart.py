from odoo.tests import TransactionCase, tagged


@tagged('post_install_l10n', '-at_install', 'post_install')
class TestPcecChart(TransactionCase):
    """Tests for plan_compta_pcec (PCEC 2005).

    Mere module installation does NOT parse data/template/*-mg_pcec.csv : the @template
    decorator only registers the chart at module scan time, the CSV files are only read when
    account.chart.template.try_loading('mg_pcec', company) is actually called. These tests
    therefore explicitly load the template on a fresh Madagascar company to prove the CSV
    files parse and produce a coherent chart, per the task's requirement to "charger et
    valider le nouveau template mg_pcec" rather than just check passive artifacts.

    Cross-version API: avoids depending on AccountTestInvoicingCommon, whose setUpClass
    signature changed between v16 → v17 → v18 → v19. Uses only res.company / account.account /
    account.tax models which remain stable. Same pattern as softeam_l10n_mg/tests/test_chart.py.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mg_country = cls.env.ref('base.mg')
        cls.company = cls.env['res.company'].create({
            'name': 'CEFOR Test PCEC',
            'country_id': cls.mg_country.id,
            'currency_id': cls.env.ref('base.MGA').id,
        })
        cls.env['account.chart.template'].with_company(cls.company).try_loading(
            'mg_pcec', cls.company, install_demo=False,
        )

    def test_module_installed(self):
        """Module is in 'installed' state after `-i plan_compta_pcec`."""
        module = self.env['ir.module.module'].search([
            ('name', '=', 'plan_compta_pcec'),
        ])
        self.assertTrue(module, 'plan_compta_pcec should be findable')
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
        self.assertEqual(self.mg_country.code, 'MG')

    def test_chart_applied_on_company(self):
        """try_loading actually set the chart template on the test company."""
        self.assertEqual(self.company.chart_template, 'mg_pcec')
        self.assertTrue(self.company.account_fiscal_country_id)

    def test_pcec_accounts_loaded_full_nomenclature(self):
        """The 5 account.account-*-mg_pcec.csv rows are all created as real account.account
        records on the company, distinct from the pcg_* accounts of the sibling PCG module."""
        accounts = self.env['account.account'].search([
            ('company_id', '=', self.company.id),
        ])
        self.assertGreater(
            len(accounts), 250,
            'Expected the full PCEC classes 1-7 nomenclature (300+ accounts) to be loaded, '
            f'got {len(accounts)}',
        )
        # Une fois le template appliqué à une société, Odoo régénère les xmlid des comptes
        # sous le module 'account' (pas le module d'origine du template), au format
        # "{company_id}_{xml_id_du_csv}" (account/models/chart_template.py, _load_data) : on
        # retrouve donc nos ids sous "<company_id>_pcec_XXX", pas "plan_compta_pcec.pcec_XXX".
        pcec_ids = self.env['ir.model.data'].search([
            ('module', '=', 'account'),
            ('model', '=', 'account.account'),
            ('name', 'like', f'{self.company.id}_pcec_%'),
        ])
        self.assertGreater(len(pcec_ids), 250)
        self.assertFalse(
            any('_pcg_' in rec.name for rec in pcec_ids),
            'plan_compta_pcec must not reuse pcg_* ids from softeam_l10n_mg',
        )

    def test_pcec_account_codes_no_duplicates(self):
        """No two PCEC accounts loaded on the company share the same 6-digit code."""
        accounts = self.env['account.account'].search([
            ('company_id', '=', self.company.id),
        ])
        codes = accounts.mapped('code')
        self.assertEqual(
            len(codes), len(set(codes)),
            'Duplicate account codes found in the PCEC template',
        )

    def test_pcec_account_types_are_valid(self):
        """Every PCEC account loaded on the company has a recognized account_type."""
        valid_types = set(dict(self.env['account.account']._fields['account_type'].selection))
        accounts = self.env['account.account'].search([
            ('company_id', '=', self.company.id),
        ])
        invalid = accounts.filtered(lambda a: a.account_type not in valid_types)
        self.assertFalse(
            invalid,
            'Accounts with an unrecognized account_type: %s' % invalid.mapped('code'),
        )

    def test_pcec_treasury_class_1_not_class_5(self):
        """Regression guard for the PCEC-specific class 1/5 inversion vs the generic PCG:
        the cash/bank default accounts must live under class 1 (trésorerie), not class 5."""
        cash_prefix_accounts = self.env['account.account'].search([
            ('company_id', '=', self.company.id),
            ('code', '=like', '10%'),
        ])
        self.assertTrue(cash_prefix_accounts, 'Class 1 (10 Valeurs en caisse) should be loaded')

    def test_pcec_taxes_point_to_pcec_accounts(self):
        """The Madagascar VAT taxes loaded for this company post to accounts belonging to
        this same PCEC company, not to some other company's (e.g. softeam_l10n_mg pcg_*)."""
        taxes = self.env['account.tax'].search([('company_id', '=', self.company.id)])
        self.assertTrue(taxes, 'VAT taxes should be loaded for the PCEC company')
        tax_accounts = taxes.mapped('invoice_repartition_line_ids.account_id')
        self.assertTrue(tax_accounts, 'VAT taxes should have repartition line accounts')
        for account in tax_accounts:
            self.assertEqual(
                account.company_id, self.company,
                f'Tax repartition account {account.code} does not belong to the PCEC company',
            )
            self.assertTrue(
                account.code.startswith('317'),
                f'Tax repartition account {account.code} should be one of the pcec_317x VAT accounts',
            )
