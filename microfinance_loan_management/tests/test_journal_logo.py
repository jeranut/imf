# -*- coding: utf-8 -*-
"""Logo du journal : vignette sur la carte kanban du tableau de bord (image par la route d'Odoo, icône de repli)."""
import base64
import io
import json
from unittest.mock import patch

from PIL import Image

from odoo.exceptions import AccessError

from ..models.account_journal import MICROFINANCE_USAGES
from ..models.res_company import ResCompany
from .test_fond_liaison import TestFondLiaison


def _png(size):
    out = io.BytesIO()
    Image.new('RGB', (size, size), (200, 30, 30)).save(out, 'PNG')
    return base64.b64encode(out.getvalue())


class TestJournalLogo(TestFondLiaison):

    KANBAN = 'account.account_journal_dashboard_kanban_view'

    @classmethod
    def setUpClass(cls):
        with patch.object(ResCompany, '_get_microfinance_parent', lambda self: self.browse()):
            super().setUpClass()
        cls.finance_user = cls._user('logo_finance', 'microfinance_loan_management.group_microfinance_finance')
        cls.chief = cls._user('logo_chief', 'microfinance_loan_management.group_microfinance_gestionnaire')
        cls.manager = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'logo_mgr', 'login': 'logo_mgr', 'company_id': cls.agency.id,
            'company_ids': [(6, 0, [cls.agency.id])],
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id, cls.env.ref('account.group_account_manager').id])]})

    @classmethod
    def _user(cls, login, group):
        return cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'company_id': cls.agency.id, 'company_ids': [(6, 0, [cls.agency.id])],
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id, cls.env.ref(group).id])]})

    def _journals_of_every_kind(self):
        Journal = self.env['account.journal']
        made = Journal
        for i, (usage, _label) in enumerate(MICROFINANCE_USAGES):
            made |= Journal.create({'name': 'U %s' % usage, 'code': 'ZU%d' % i, 'type': 'bank',
                                    'company_id': self.agency.id, 'microfinance_usage': usage})
        for i, jtype in enumerate(('bank', 'cash', 'sale', 'purchase', 'general')):
            made |= Journal.create({'name': 'T %s' % jtype, 'code': 'ZT%d' % i, 'type': jtype,
                                    'company_id': self.agency.id})
        for code in ('AN', 'VIR', 'TRANS'):
            made |= Journal.create({'name': 'G %s' % code, 'code': 'ZG' + code[:2], 'type': 'general',
                                    'company_id': self.agency.id})
        return made

    def test_kanban_view_loads_with_and_without_logo_for_every_usage_and_type(self):
        journals = self._journals_of_every_kind()
        spec = {name: {} for name in ('name', 'type', 'code', 'microfinance_usage', 'mf_logo', 'write_date',
                                      'kanban_dashboard')}
        domain = [('id', 'in', journals.ids)]
        rows = self.env['account.journal'].web_search_read(domain, spec)['records']
        self.assertEqual(len(rows), len(journals))
        self.assertFalse(any(r['mf_logo'] for r in rows))
        journals[:1].mf_logo = _png(64)
        rows = self.env['account.journal'].web_search_read(domain, spec)['records']
        self.assertEqual(sum(1 for r in rows if r['mf_logo']), 1)
        view = self.env['account.journal'].get_view(self.env.ref(self.KANBAN).id, 'kanban')
        arch = view['arch']
        self.assertIn('kanban_image(', arch)
        self.assertIn('mf_logo', arch)
        self.assertIn('fa-university', arch)
        self.assertNotIn('data:image', arch)
        self.assertIn('alt', arch)

    def test_form_view_has_the_logo_field_for_the_account_manager_only(self):
        manager_view = self.env['account.journal'].with_user(self.manager).get_view(
            self.env.ref('account.view_account_journal_form').id, 'form')
        self.assertIn('mf_logo', manager_view['arch'])
        finance_view = self.env['account.journal'].with_user(self.finance_user).get_view(
            self.env.ref('account.view_account_journal_form').id, 'form')
        self.assertNotIn('mf_logo', finance_view['arch'])

    def test_big_image_is_reduced_to_256(self):
        self.ag_journal.mf_logo = _png(2000)
        image = Image.open(io.BytesIO(base64.b64decode(self.ag_journal.mf_logo)))
        self.assertLessEqual(max(image.size), 256)

    def test_non_manager_cannot_write_logo_but_reads_it(self):
        self.ag_journal.mf_logo = _png(64)
        journal = self.ag_journal.with_user(self.finance_user)
        with self.assertRaises(AccessError):
            journal.write({'mf_logo': _png(32)})
        self.assertTrue(journal.mf_logo)
        row = journal.web_read({'name': {}, 'mf_logo': {}, 'write_date': {}})[0]
        self.assertTrue(row['mf_logo'])
        self.ag_journal.with_user(self.manager).mf_logo = _png(32)  # le gestionnaire comptable peut

    def test_branch_head_sees_only_cards_of_own_company(self):
        journals = self.env['account.journal'].with_user(self.chief).with_context(
            allowed_company_ids=[self.agency.id]).search([('show_on_dashboard', '=', True)])
        self.assertTrue(journals)
        self.assertEqual(journals.company_id, self.agency)
        self.assertNotIn(self.fdbm, journals)

    def test_dashboard_data_and_buttons_are_identical_with_and_without_logo(self):
        journals = self._journals_of_every_kind() | self.ag_journal
        Journal = self.env['account.journal'].with_user(self.manager)
        before = {j.id: Journal.browse(j.id).kanban_dashboard for j in journals}
        journals.write({'mf_logo': _png(64)})
        journals.invalidate_recordset(['kanban_dashboard'])
        after = {j.id: Journal.browse(j.id).kanban_dashboard for j in journals}
        self.assertEqual(before, after)
        for raw in after.values():
            self.assertNotIn('data:image', raw)
            self.assertNotIn('mf_logo', json.dumps(json.loads(raw)))
