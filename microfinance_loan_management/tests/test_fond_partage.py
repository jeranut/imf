# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import Form

from .test_fond_bailleur import TestFondBailleurCommon


class TestFondPartageBase(TestFondBailleurCommon):
    """Base commune : société courante = agence A ; société B = agence B ; la mère est désignée
    (ou non) par chaque test via _set_parent()."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company
        cls.company_b = cls.env['res.company'].create({'name': 'Agence B partage (test)', 'agency_code': 'Y1'})
        cls.company_c = cls.env['res.company'].create({'name': 'Agence C partage (test)', 'agency_code': 'Y2'})

    def _set_parent(self, company):
        self.env['ir.config_parameter'].sudo().set_param(
            'microfinance.parent_company_id', company.id if company else False)

    def _create_shared_fond(self, **kwargs):
        # passer_gl faux par défaut : ces tests portent sur les allocations, pas sur la comptabilité (les
        # écritures de partage sont couvertes par test_fond_liaison.py).
        vals = {'name': 'Fonds partagé test', 'scope': 'multi_company', 'company_id': False, 'passer_gl': False}
        vals.update(kwargs)
        return self._create_fond(**vals)


class TestFondMultiScopeCreate(TestFondPartageBase):

    def test_multi_company_create_ignores_default_company(self):
        fond = self._create_shared_fond(company_id=self.env.company.id)
        self.assertEqual(fond.scope, 'multi_company')
        self.assertFalse(fond.company_id)


class TestFondParentCompanySetting(TestFondPartageBase):

    def test_no_parent_configured_by_default(self):
        self._set_parent(False)
        self.assertFalse(self.env['res.company']._get_microfinance_parent())
        self.assertFalse(self.company_a.is_microfinance_parent)
        # aucune restriction sans mère
        self.env['res.company']._check_microfinance_parent_only()

    def test_parent_helper_and_flag(self):
        self._set_parent(self.company_b)
        self.assertEqual(self.env['res.company']._get_microfinance_parent(), self.company_b)
        self.assertTrue(self.company_b.is_microfinance_parent)
        self.assertFalse(self.company_a.is_microfinance_parent)

    def test_settings_field_reads_and_writes_parameter(self):
        settings = self.env['res.config.settings'].create({'microfinance_parent_company_id': self.company_b.id})
        settings.execute()
        self.assertEqual(self.env['res.company']._get_microfinance_parent(), self.company_b)
        settings = self.env['res.config.settings'].create({})
        self.assertEqual(settings.microfinance_parent_company_id, self.company_b)

    def test_check_parent_only_blocks_agency(self):
        self._set_parent(self.company_b)
        with self.assertRaises(UserError):
            self.env['res.company']._check_microfinance_parent_only()
        self.env['res.company'].with_company(self.company_b)._check_microfinance_parent_only()


class TestFondAllocation(TestFondPartageBase):

    def _allocation(self, fond, company, amount):
        return self.env['microfinance.fond.allocation'].sudo().with_context(
            fond_partage_technique=True).create({
                'fond_id': fond.id, 'company_id': company.id, 'amount_allocated': amount})

    def test_direct_create_write_unlink_refused(self):
        fond = self._create_shared_fond()
        with self.assertRaises(UserError):
            self.env['microfinance.fond.allocation'].create({
                'fond_id': fond.id, 'company_id': self.company_a.id, 'amount_allocated': 10.0})
        alloc = self._allocation(fond, self.company_a, 100.0)
        # le recordset garde le contexte technique de sa création : on le retire explicitement
        alloc = alloc.with_context(fond_partage_technique=False)
        with self.assertRaises(UserError):
            alloc.write({'amount_allocated': 200.0})
        with self.assertRaises(UserError):
            alloc.unlink()

    def test_unique_per_fond_and_company(self):
        fond = self._create_shared_fond()
        self._allocation(fond, self.company_a, 100.0)
        with self.assertRaises(Exception), self.cr.savepoint():
            self._allocation(fond, self.company_a, 50.0)

    def test_solde_is_allocated_minus_used_principal(self):
        fond = self._create_shared_fond(verification_disponibilite='never')
        alloc = self._allocation(fond, self.company_a, 5000.0)
        self.assertEqual(alloc.solde_disponible, 5000.0)
        loan = self._approve_loan(loan_amount=1000.0, term=3, fond_credit_id=fond.id)
        self.assertEqual(alloc.montant_utilise, 1000.0)
        self.assertEqual(alloc.solde_disponible, 4000.0)
        loan.action_disburse()
        self.assertEqual(alloc.solde_disponible, 4000.0)

    def test_company_rule_isolates_agencies(self):
        fond = self._create_shared_fond()
        alloc_a = self._allocation(fond, self.company_a, 100.0)
        alloc_b = self._allocation(fond, self.company_b, 200.0)
        user_b = self.env['res.users'].create({
            'name': 'Agent B partage (test)', 'login': 'agent_b_partage_test',
            'company_id': self.company_b.id, 'company_ids': [(6, 0, [self.company_b.id])],
            'groups_id': [(6, 0, [self.env.ref('microfinance_loan_management.group_microfinance_user').id])],
        })
        visible = self.env['microfinance.fond.allocation'].with_user(user_b).with_company(self.company_b).search([])
        self.assertEqual(visible, alloc_b)
        self.assertNotIn(alloc_a, visible)


class TestFondPartage(TestFondPartageBase):

    def _fond_with_contribution(self, amount=9000.0):
        fond = self._create_shared_fond(verification_disponibilite='at_disbursement')
        self._create_contribution(fond, amount=amount).action_post()
        return fond

    def _partage(self, fond, base=None, percents=None):
        partage = self.env['microfinance.fond.partage'].create({
            'fond_id': fond.id, 'base_amount': base or fond.reste_partageable})
        if percents:
            for line in partage.line_ids:
                line.percent = percents.get(line.company_id, 0.0)
        return partage

    def test_default_lines_cover_all_agencies_including_parent(self):
        fond = self._fond_with_contribution()
        self._set_parent(self.company_a)
        partage = self._partage(fond)
        companies = partage.line_ids.mapped('company_id')
        self.assertIn(self.company_a, companies)
        self.assertIn(self.company_b, companies)
        self.assertEqual(companies, self.env['res.company'].search([('agency_code', '!=', False)]))
        self.assertEqual(partage.company_id, self.company_a)

    def test_reste_partageable_and_onchange_prefill(self):
        fond = self._fond_with_contribution(9000.0)
        self.assertEqual(fond.reste_partageable, 9000.0)
        with Form(self.env['microfinance.fond.partage']) as form:
            form.fond_id = fond
            self.assertEqual(form.base_amount, 9000.0)

    def test_percent_to_amount_and_amount_to_percent(self):
        fond = self._fond_with_contribution(1000.0)
        partage = self._partage(fond, 1000.0)
        line = partage.line_ids[0]
        line.percent = 25.0
        self.assertEqual(line.amount, 250.0)
        line.amount = 400.0
        self.assertAlmostEqual(line.percent, 40.0, places=4)
        # la base change : le pourcentage reste la référence
        partage.base_amount = 500.0
        self.assertAlmostEqual(line.percent, 40.0, places=4)
        self.assertEqual(line.amount, 200.0)

    def test_total_amount_cannot_exceed_base(self):
        fond = self._fond_with_contribution(1000.0)
        partage = self._partage(fond, 1000.0)
        partage.line_ids[0].amount = 800.0
        with self.assertRaises(ValidationError):
            partage.line_ids[1].amount = 300.0

    def test_partager_egalement_refused_without_base(self):
        fond = self._fond_with_contribution(1000.0)
        partage = self._partage(fond, 1000.0)
        self.cr.execute("UPDATE microfinance_fond_partage SET base_amount = 0 WHERE id = %s", [partage.id])
        partage.invalidate_recordset()
        with self.assertRaises(UserError):
            partage.action_partager_egalement()

    def test_validate_requires_100_percent(self):
        fond = self._fond_with_contribution(1000.0)
        partage = self._partage(fond, 1000.0)
        partage.line_ids[0].percent = 50.0
        with self.assertRaises(UserError):
            partage.action_validate()

    def test_validate_creates_allocations_including_parent_and_is_cumulative(self):
        self._set_parent(self.company_a)
        fond = self._fond_with_contribution(9000.0)
        partage = self._partage(fond, 6000.0)
        partage.line_ids.filtered(lambda l: l.company_id == self.company_a).percent = 50.0
        partage.line_ids.filtered(lambda l: l.company_id == self.company_b).percent = 30.0
        partage.line_ids.filtered(lambda l: l.company_id == self.company_c).percent = 20.0
        partage.action_validate()
        self.assertEqual(partage.state, 'validated')
        alloc = {a.company_id: a.amount_allocated for a in fond.allocation_ids}
        self.assertEqual(alloc[self.company_a], 3000.0)
        self.assertEqual(alloc[self.company_b], 1800.0)
        self.assertEqual(alloc[self.company_c], 1200.0)
        self.assertEqual(fond.reste_partageable, 3000.0)
        # second partage cumulatif sur la même base restante
        partage2 = self._partage(fond, 3000.0)
        partage2.line_ids.filtered(lambda l: l.company_id == self.company_b).percent = 100.0
        partage2.action_validate()
        self.assertEqual(
            fond.allocation_ids.filtered(lambda a: a.company_id == self.company_b).amount_allocated, 4800.0)
        self.assertEqual(fond.reste_partageable, 0.0)

    def test_base_cannot_exceed_reste_partageable(self):
        fond = self._fond_with_contribution(1000.0)
        partage = self._partage(fond, 5000.0)
        partage.line_ids[0].percent = 100.0
        with self.assertRaises(UserError):
            partage.action_validate()

    def test_validated_partage_is_locked(self):
        fond = self._fond_with_contribution(1000.0)
        partage = self._partage(fond, 1000.0)
        partage.line_ids[0].percent = 100.0
        partage.action_validate()
        with self.assertRaises(UserError):
            partage.base_amount = 500.0
        with self.assertRaises(UserError):
            partage.line_ids[0].percent = 10.0
        with self.assertRaises(UserError):
            partage.unlink()

    def test_cancel_validated_refused_if_agency_used_funds(self):
        fond = self._fond_with_contribution(9000.0)
        fond.verification_disponibilite = 'at_disbursement'
        partage = self._partage(fond, 5000.0)
        line_a = partage.line_ids.filtered(lambda l: l.company_id == self.company_a)
        line_a.percent = 100.0
        partage.action_validate()
        loan = self._approve_loan(loan_amount=1000.0, term=3, fond_credit_id=fond.id)
        self.assertEqual(loan.company_id, self.company_a)
        alloc = fond.allocation_ids.filtered(lambda a: a.company_id == self.company_a)
        self.assertEqual(alloc.montant_utilise, 1000.0)
        # 5000 - 5000 = 0 < 1000 utilisé : refus explicite
        with self.assertRaises(UserError) as ctx:
            partage.action_cancel()
        self.assertIn(self.company_a.name, str(ctx.exception))
        self.assertEqual(partage.state, 'validated')

    def test_cancel_validated_ok_when_unused_removes_allocation(self):
        fond = self._fond_with_contribution(1000.0)
        partage = self._partage(fond, 1000.0)
        partage.line_ids.filtered(lambda l: l.company_id == self.company_b).percent = 100.0
        partage.action_validate()
        self.assertTrue(fond.allocation_ids)
        partage.action_cancel()
        self.assertEqual(partage.state, 'cancelled')
        self.assertFalse(fond.allocation_ids)
        self.assertEqual(fond.reste_partageable, 1000.0)

    def test_only_parent_can_create_and_validate(self):
        fond = self._fond_with_contribution(1000.0)
        self._set_parent(self.company_b)
        with self.assertRaises(UserError):
            self.env['microfinance.fond.partage'].create({'fond_id': fond.id, 'base_amount': 1000.0})
        partage = self.env['microfinance.fond.partage'].with_company(self.company_b).create(
            {'fond_id': fond.id, 'base_amount': 1000.0})
        self.assertEqual(partage.company_id, self.company_b)
        with self.assertRaises(UserError):
            partage.with_company(self.company_a).action_validate()

    def test_agencies_do_not_see_partages(self):
        fond = self._fond_with_contribution(1000.0)
        self._set_parent(self.company_b)
        partage = self.env['microfinance.fond.partage'].with_company(self.company_b).create(
            {'fond_id': fond.id, 'base_amount': 1000.0})
        user_a = self.env['res.users'].create({
            'name': 'Manager A partage (test)', 'login': 'manager_a_partage_test',
            'company_id': self.company_a.id, 'company_ids': [(6, 0, [self.company_a.id])],
            'groups_id': [(6, 0, [self.env.ref('microfinance_loan_management.group_microfinance_manager').id])],
        })
        seen = self.env['microfinance.fond.partage'].with_user(user_a).with_company(self.company_a).search([])
        self.assertNotIn(partage, seen)


class TestFondParentOnlyGuards(TestFondPartageBase):

    def test_no_parent_no_restriction(self):
        self._set_parent(False)
        bailleur = self.env['microfinance.bailleur.fonds'].with_company(self.company_b).create({'name': 'B libre'})
        fond = self.env['microfinance.fond.credit'].with_company(self.company_b).create({
            'name': 'F libre', 'bailleur_id': bailleur.id, 'scope': 'multi_company', 'company_id': False,
            'account_id': self.fond_account.id, 'date_debut': '2020-01-01'})
        fond.write({'name': 'F libre 2'})
        fond.unlink()

    def test_agency_cannot_create_or_edit_bailleur(self):
        self._set_parent(self.company_b)
        with self.assertRaises(UserError) as ctx:
            self.env['microfinance.bailleur.fonds'].create({'name': 'Interdit'})
        self.assertIn(self.company_b.name, str(ctx.exception))
        with self.assertRaises(UserError):
            self.bailleur.write({'code': 'X'})
        with self.assertRaises(UserError):
            self.bailleur.unlink()
        # la mère peut
        self.bailleur.with_company(self.company_b).write({'code': 'OK'})
        self.env['microfinance.bailleur.fonds'].with_company(self.company_b).create({'name': 'Autorisé'})

    def test_agency_cannot_create_or_delete_fond(self):
        self._set_parent(self.company_b)
        with self.assertRaises(UserError):
            self._create_fond()
        fond = self.env['microfinance.fond.credit'].with_company(self.company_b).create({
            'name': 'F mère', 'bailleur_id': self.bailleur.id, 'scope': 'multi_company', 'company_id': False,
            'account_id': self.fond_account.id, 'date_debut': '2020-01-01'})
        with self.assertRaises(UserError):
            fond.with_company(self.company_a).write({'name': 'renommé'})
        with self.assertRaises(UserError):
            fond.with_company(self.company_a).unlink()
        fond.with_company(self.company_b).write({'name': 'renommé mère'})

    def test_legacy_single_company_fond_still_writable_by_its_agency(self):
        fond = self._create_fond()  # créé sans mère, agence A, legacy
        self._set_parent(self.company_b)
        fond.with_company(self.company_a).write({'name': 'legacy renommé'})
        self.assertEqual(fond.name, 'legacy renommé')

    def test_contribution_on_shared_fond_only_from_parent(self):
        fond = self._create_shared_fond()
        self._set_parent(self.company_b)
        with self.assertRaises(UserError):
            self._create_contribution(fond)
        contrib = self.env['microfinance.fond.contribution'].with_company(self.company_b).create({
            'fond_id': fond.id, 'type_mouvement': 'depot', 'amount': 1000.0,
            'mode_paiement': 'virement'})
        self.assertEqual(contrib.saisie_company_id, self.company_b)
        with self.assertRaises(UserError):
            contrib.with_company(self.company_a).action_post()

    def test_contribution_on_legacy_fond_unaffected(self):
        fond = self._create_fond()
        self._set_parent(self.company_b)
        contrib = self._create_contribution(fond)
        contrib.action_post()
        self.assertEqual(fond.total_contributions, 1000.0)


class TestFondMotherBase(TestFondPartageBase):
    """Helpers : fonds partagé alimenté et partagé par la société mère (société B)."""

    def _mother_shared_fond(self, contribution=9000.0, shares=None):
        """Fonds partagé alimenté et partagé par la mère (société B). shares : {company: montant}."""
        self._set_parent(self.company_b)
        Fond = self.env['microfinance.fond.credit'].with_company(self.company_b)
        fond = Fond.create({
            'name': 'Fonds mère', 'bailleur_id': self.bailleur.id, 'scope': 'multi_company',
            'company_id': False, 'date_debut': '2020-01-01', 'passer_gl': False,
            'verification_disponibilite': 'at_disbursement'})
        self.env['microfinance.fond.contribution'].with_company(self.company_b).create({
            'fond_id': fond.id, 'type_mouvement': 'depot', 'amount': contribution,
            'mode_paiement': 'virement'}).action_post()
        if shares:
            base = sum(shares.values())
            partage = self.env['microfinance.fond.partage'].with_company(self.company_b).create(
                {'fond_id': fond.id, 'base_amount': base})
            for line in partage.line_ids:
                line.amount = shares.get(line.company_id, 0.0)
            partage.with_company(self.company_b).action_validate()
        return fond

    def _loan_domain_fonds(self, company):
        from odoo import fields
        from odoo.tools.safe_eval import safe_eval
        field = self.env['microfinance.loan']._fields['fond_credit_id']
        domain = safe_eval(field.domain, {'company_id': company.id, 'context_today': lambda: fields.Date.today()})
        return self.env['microfinance.fond.credit'].search(domain)



class TestFondAllocationConsumption(TestFondMotherBase):
    """Consommation par les crédits : plafond = allocation de l'agence du crédit ; fonds existants
    (sans allocation) inchangés."""

    def test_fond_created_with_parent_requires_allocation(self):
        fond = self._mother_shared_fond()
        self.assertTrue(fond.allocation_required)
        self._set_parent(False)
        self.assertFalse(self._create_shared_fond(name='Legacy').allocation_required)

    def test_disbursement_capped_by_agency_allocation(self):
        fond = self._mother_shared_fond(9000.0, {self.company_a: 2000.0, self.company_b: 7000.0})
        self.assertEqual(fond.solde_disponible, 9000.0)  # le solde global aurait tout permis
        loan1 = self._approve_loan(loan_amount=1000.0, term=3, fond_credit_id=fond.id)
        loan1.action_disburse()
        alloc = fond.allocation_ids.filtered(lambda a: a.company_id == self.company_a)
        self.assertEqual(alloc.solde_disponible, 1000.0)
        loan2 = self._approve_loan(loan_amount=1500.0, term=3, fond_credit_id=fond.id)
        with self.assertRaises(UserError) as ctx:
            loan2.action_disburse()
        self.assertIn('Solde insuffisant', str(ctx.exception))

    def test_disbursement_within_allocation_ok(self):
        fond = self._mother_shared_fond(9000.0, {self.company_a: 2000.0, self.company_b: 7000.0})
        loan = self._approve_loan(loan_amount=2000.0, term=3, fond_credit_id=fond.id)
        loan.action_disburse()
        self.assertEqual(loan.state, 'active')

    def test_agency_without_allocation_cannot_use_shared_fond(self):
        fond = self._mother_shared_fond(9000.0, {self.company_b: 9000.0})
        self.assertNotIn(fond, self._loan_domain_fonds(self.company_a))
        self.assertIn(fond, self._loan_domain_fonds(self.company_b))
        loan = self._approve_loan(loan_amount=1000.0, term=3, fond_credit_id=fond.id)
        with self.assertRaises(UserError) as ctx:
            loan.action_disburse()
        self.assertIn('aucune allocation', str(ctx.exception))

    def test_has_active_fond_follows_allocation(self):
        # isole le cas : la copie de base peut contenir d'autres fonds actifs de l'agence A
        self.env['microfinance.fond.credit'].search([]).write({'active': False})
        fond = self._mother_shared_fond(9000.0, {self.company_b: 9000.0})
        loan = self._create_loan()
        self.assertFalse(loan.has_active_fond)
        fond2 = self._mother_shared_fond(9000.0, {self.company_a: 4000.0, self.company_b: 5000.0})
        loan.invalidate_recordset(['has_active_fond'])
        self.assertTrue(loan.has_active_fond)
        self.assertIn(fond, self._loan_domain_fonds(self.company_b))
        self.assertNotIn(fond, self._loan_domain_fonds(self.company_a))
        self.assertIn(fond2, self._loan_domain_fonds(self.company_a))

    def test_legacy_shared_fond_without_allocation_keeps_global_balance(self):
        self._set_parent(False)
        fond = self._create_shared_fond(verification_disponibilite='at_disbursement')
        self._create_contribution(fond, amount=5000.0).action_post()
        self.assertFalse(fond.allocation_required)
        self.assertIn(fond, self._loan_domain_fonds(self.company_a))
        loan = self._approve_loan(loan_amount=1000.0, term=3, fond_credit_id=fond.id)
        loan.action_disburse()
        self.assertEqual(fond.solde_disponible, 4000.0)

    def test_company_default_fond_domain_uses_allocation(self):
        fond = self._mother_shared_fond(9000.0, {self.company_b: 9000.0})
        from odoo import fields
        from odoo.tools.safe_eval import safe_eval
        field = self.env['res.company']._fields['microfinance_fond_credit_default_id']
        ctx = {'id': self.company_a.id, 'context_today': lambda: fields.Date.today()}
        self.assertNotIn(fond, self.env['microfinance.fond.credit'].search(safe_eval(field.domain, ctx)))
        ctx['id'] = self.company_b.id
        self.assertIn(fond, self.env['microfinance.fond.credit'].search(safe_eval(field.domain, ctx)))


class TestFondPartageDashboardAndAccess(TestFondMotherBase):
    """Dashboard sur allocations, et lecture par une agence sans AccessError."""

    def test_dashboard_kpi_uses_agency_allocation(self):
        self.env['microfinance.fond.credit'].search([]).write({'active': False})
        fond = self._mother_shared_fond(9000.0, {self.company_a: 2000.0, self.company_b: 7000.0})
        Fond = self.env['microfinance.fond.credit']
        self.assertEqual(Fond.get_dashboard_kpi(self.company_a.id), {'total': 2000.0, 'count': 1})
        self.assertEqual(Fond.get_dashboard_kpi(self.company_b.id), {'total': 7000.0, 'count': 1})
        # company_c n'a aucune allocation : le fonds ne compte pas pour elle
        self.assertEqual(Fond.get_dashboard_kpi(self.company_c.id), {'total': 0.0, 'count': 0})
        chart = Fond.get_single_company_chart(self.company_a.id)
        self.assertEqual(chart['labels'], [fond.name])
        self.assertEqual(chart['values'], [2000.0])

    def test_multi_chart_exposes_allocations(self):
        self.env['microfinance.fond.credit'].search([]).write({'active': False})
        self._mother_shared_fond(9000.0, {self.company_a: 2000.0, self.company_b: 7000.0})
        chart = self.env['microfinance.fond.credit'].get_multi_company_usage_chart()
        by_label = dict(zip(chart['labels'], chart['allocations']))
        self.assertEqual(by_label[self.company_a.name], 2000.0)
        self.assertEqual(by_label[self.company_b.name], 7000.0)

    def test_agency_user_reads_shared_fond_and_only_its_allocation(self):
        fond = self._mother_shared_fond(9000.0, {self.company_a: 2000.0, self.company_b: 7000.0})
        user_a = self.env['res.users'].create({
            'name': 'Agent A partage (test)', 'login': 'agent_a_partage_test',
            'company_id': self.company_a.id, 'company_ids': [(6, 0, [self.company_a.id])],
            'groups_id': [(6, 0, [self.env.ref('microfinance_loan_management.group_microfinance_user').id])],
        })
        # env neuf : `fond` porte le contexte de la société mère (allowed_company_ids) invalide pour user_a
        fond_a = self.env['microfinance.fond.credit'].browse(fond.id).with_user(user_a).with_company(self.company_a)
        self.assertEqual(fond_a.name, fond.name)  # pas d'AccessError (rapport échéancier, formulaire prêt)
        self.assertEqual(fond_a.allocation_ids.mapped('company_id'), self.company_a)
        self.assertEqual(fond_a.allocation_ids.solde_disponible, 2000.0)
        self.assertEqual(fond_a.solde_disponible, 9000.0)
        # aucun accès en écriture direct aux allocations ni aux partages
        # le garde-fou technique (UserError) passe avant le contrôle d'accès ; les deux refusent
        with self.assertRaises(UserError):
            fond_a.allocation_ids.write({'amount_allocated': 1.0})
        # côté ACL : aucune permission d'écriture sur le modèle pour ce groupe
        self.assertFalse(self.env['microfinance.fond.allocation'].with_user(user_a).check_access_rights('write', raise_exception=False))
        # un simple agent n'a aucun droit sur les partages
        with self.assertRaises(AccessError):
            self.env['microfinance.fond.partage'].with_user(user_a).with_company(self.company_a).search([])


class TestFondPartageRebalance(TestFondPartageBase):
    """« Partager également » et équilibrage automatique de la liste éditable (onchange parent)."""

    def _partage(self, base=1000.0):
        fond = self._create_shared_fond()
        self._create_contribution(fond, amount=max(base, 1.0)).action_post()
        return self.env['microfinance.fond.partage'].create({'fond_id': fond.id, 'base_amount': base})

    def _line(self, partage, company):
        return partage.line_ids.filtered(lambda l: l.company_id == company)

    def _set_shares(self, partage, shares):
        """shares : {company: percent}, les autres lignes à 0 (écritures Python directes)."""
        for line in partage.line_ids:
            line.percent = shares.get(line.company_id, 0.0)

    def _edit(self, partage, company, **values):
        """Édite une ligne dans le formulaire (déclenche l'onchange parent à la sortie de la ligne)."""
        index = list(partage.line_ids.ids).index(self._line(partage, company).id)
        with Form(partage) as form:
            with form.line_ids.edit(index) as line:
                for name, value in values.items():
                    setattr(line, name, value)
        partage.invalidate_recordset()

    def _assert_balanced(self, partage, base):
        self.assertAlmostEqual(partage.total_percent, 100.0, places=3)
        self.assertAlmostEqual(partage.total_amount, base, places=2)
        for line in partage.line_ids:
            self.assertGreaterEqual(line.percent, 0.0)
            self.assertGreaterEqual(line.amount, 0.0)
            self.assertEqual((line.percent_ref, line.amount_ref), (line.percent, line.amount))

    def test_partager_egalement_on_11_lines_puts_remainder_on_last(self):
        base = 10000000.0
        partage = self._partage(base)
        partage.line_ids[11:].unlink()
        self.assertEqual(len(partage.line_ids), 11)
        partage.action_partager_egalement()
        lines = partage.line_ids
        self._assert_balanced(partage, base)
        self.assertEqual(partage.total_percent, 100.0)
        self.assertEqual(partage.total_amount, base)
        first = lines[0]
        for line in lines[:-1]:
            self.assertEqual((line.percent, line.amount), (first.percent, first.amount))
        self.assertAlmostEqual(lines[-1].amount, base - first.amount * 10, places=2)
        self.assertAlmostEqual(lines[-1].percent, 100.0 - first.percent * 10, places=4)

    def test_partager_egalement_validates(self):
        partage = self._partage(1000.0)
        partage.action_partager_egalement()
        partage.action_validate()
        self.assertEqual(partage.state, 'validated')
        self.assertAlmostEqual(sum(partage.fond_id.allocation_ids.mapped('amount_allocated')), 1000.0, places=2)

    def test_edit_percent_rebalances_others_proportionally(self):
        partage = self._partage(1000.0)
        a, b, c = self.company_a, self.company_b, self.company_c
        self._set_shares(partage, {a: 50.0, b: 30.0, c: 20.0})
        self._edit(partage, a, percent=70.0)
        self.assertEqual(self._line(partage, a).percent, 70.0)  # valeur saisie conservée
        self.assertEqual(self._line(partage, a).amount, 700.0)
        self.assertAlmostEqual(self._line(partage, b).percent, 18.0, places=3)
        self.assertAlmostEqual(self._line(partage, c).percent, 12.0, places=3)
        self.assertAlmostEqual(self._line(partage, b).amount, 180.0, places=2)
        self._assert_balanced(partage, 1000.0)

    def test_edit_amount_recomputes_percent_and_rebalances(self):
        partage = self._partage(1000.0)
        a, b, c = self.company_a, self.company_b, self.company_c
        self._set_shares(partage, {a: 50.0, b: 30.0, c: 20.0})
        self._edit(partage, a, amount=250.0)
        self.assertEqual(self._line(partage, a).amount, 250.0)  # valeur saisie conservée
        self.assertAlmostEqual(self._line(partage, a).percent, 25.0, places=3)
        self.assertAlmostEqual(self._line(partage, b).amount, 450.0, places=2)
        self.assertAlmostEqual(self._line(partage, c).amount, 300.0, places=2)
        self._assert_balanced(partage, 1000.0)

    def test_value_above_100_is_capped_and_others_zero(self):
        partage = self._partage(1000.0)
        self._set_shares(partage, {self.company_a: 50.0, self.company_b: 50.0})
        self._edit(partage, self.company_a, percent=150.0)
        self.assertEqual(self._line(partage, self.company_a).percent, 100.0)
        self.assertEqual(self._line(partage, self.company_a).amount, 1000.0)
        others = partage.line_ids - self._line(partage, self.company_a)
        self.assertFalse(any(others.mapped('percent')) or any(others.mapped('amount')))
        self._assert_balanced(partage, 1000.0)

    def test_amount_above_base_is_capped(self):
        partage = self._partage(1000.0)
        self._set_shares(partage, {self.company_a: 50.0, self.company_b: 50.0})
        self._edit(partage, self.company_a, amount=5000.0)
        self.assertEqual(self._line(partage, self.company_a).amount, 1000.0)
        self.assertEqual(self._line(partage, self.company_a).percent, 100.0)
        self._assert_balanced(partage, 1000.0)

    def test_negative_value_becomes_zero(self):
        partage = self._partage(1000.0)
        self._set_shares(partage, {self.company_a: 50.0, self.company_b: 30.0, self.company_c: 20.0})
        self._edit(partage, self.company_a, percent=-5.0)
        self.assertEqual(self._line(partage, self.company_a).percent, 0.0)
        self.assertAlmostEqual(self._line(partage, self.company_b).percent, 60.0, places=3)
        self.assertAlmostEqual(self._line(partage, self.company_c).percent, 40.0, places=3)
        self._assert_balanced(partage, 1000.0)

    def test_others_all_zero_are_redistributed_equally(self):
        partage = self._partage(1000.0)
        self._set_shares(partage, {self.company_a: 100.0})
        self._edit(partage, self.company_a, percent=40.0)
        others = partage.line_ids - self._line(partage, self.company_a)
        expected = 60.0 / len(others)
        for line in others[:-1]:
            self.assertAlmostEqual(line.percent, expected, places=3)
        self._assert_balanced(partage, 1000.0)

    def test_base_zero_computes_in_percent_only(self):
        partage = self._partage(1000.0)
        self._set_shares(partage, {self.company_a: 100.0})
        self.cr.execute("UPDATE microfinance_fond_partage SET base_amount = 0 WHERE id = %s", [partage.id])
        self.cr.execute("UPDATE microfinance_fond_partage_line SET amount = 0, amount_ref = 0 WHERE partage_id = %s", [partage.id])
        partage.invalidate_recordset()
        partage.line_ids.invalidate_recordset()
        self._edit(partage, self.company_a, percent=40.0)
        self.assertEqual(self._line(partage, self.company_a).percent, 40.0)
        self.assertAlmostEqual(partage.total_percent, 100.0, places=3)
        self.assertEqual(partage.total_amount, 0.0)

    def test_changing_base_keeps_percent_and_realigns_refs(self):
        partage = self._partage(1000.0)
        self._set_shares(partage, {self.company_a: 60.0, self.company_b: 40.0})
        partage.base_amount = 500.0
        self.assertEqual(self._line(partage, self.company_a).amount, 300.0)
        self.assertEqual(self._line(partage, self.company_a).percent, 60.0)
        self._assert_balanced(partage, 500.0)

    def test_lines_read_only_after_validation(self):
        partage = self._partage(1000.0)
        partage.action_partager_egalement()
        partage.action_validate()
        with self.assertRaises(UserError):
            self._line(partage, self.company_a).percent = 5.0
