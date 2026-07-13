# -*- coding: utf-8 -*-
import base64

from .common import MicrofinanceCommon

ONE_PIXEL_PNG = base64.b64encode(
    base64.b64decode(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
    )
)


class TestDashboardCompanyHeader(MicrofinanceCommon):

    def test_subtitle_with_full_address(self):
        company = self.env.company
        company.write({'street': 'Lot II M 12', 'street2': 'Bis', 'city': 'Antananarivo'})
        self.assertEqual(
            company._get_microfinance_dashboard_subtitle(),
            '%s — Lot II M 12, Bis, Antananarivo' % company.name,
        )

    def test_subtitle_with_partial_address_no_orphan_separators(self):
        company = self.env.company
        company.write({'street': False, 'street2': False, 'city': 'Antananarivo'})
        self.assertEqual(company._get_microfinance_dashboard_subtitle(), '%s — Antananarivo' % company.name)
        self.assertNotIn(',', company._get_microfinance_dashboard_subtitle())

        company.write({'street': 'Lot II M 12', 'city': False})
        self.assertEqual(company._get_microfinance_dashboard_subtitle(), '%s — Lot II M 12' % company.name)

    def test_subtitle_falls_back_to_name_without_any_address(self):
        company = self.env.company
        company.write({'street': False, 'street2': False, 'city': False})
        self.assertEqual(company._get_microfinance_dashboard_subtitle(), company.name)
        self.assertNotIn('—', company._get_microfinance_dashboard_subtitle())

    def test_uses_default_logo_by_default(self):
        company = self.env['res.company'].create({'name': 'Agence sans logo (test)', 'agency_code': 'Z4'})
        self.assertTrue(company.uses_default_logo, 'Une société sans logo personnalisé doit rester sur le repli visuel')

    def test_custom_logo_disables_default_flag(self):
        company = self.env['res.company'].create({'name': 'Agence avec logo (test)', 'agency_code': 'Z5'})
        company.logo = ONE_PIXEL_PNG
        self.assertFalse(company.uses_default_logo, "Un logo personnalisé doit désactiver le repli visuel")
