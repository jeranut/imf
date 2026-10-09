# -*- coding: utf-8 -*-
import random
import tempfile

from lxml import etree

from odoo.exceptions import AccessError, UserError, ValidationError

from odoo.addons.microfinance_loan_management.client_officer_backfill import (
    PARAM_DRY_RUN, backfill_client_officer, is_dry_run,
)

from .common import MicrofinanceCommon, MicrofinanceNoFundMixin

FORBIDDEN = "La création d'un client se fait uniquement depuis le portefeuille de l'agent de crédit."


class TestClientsPortefeuille(MicrofinanceNoFundMixin, MicrofinanceCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        mod = 'microfinance_loan_management.'
        agent_groups = cls.env.ref('base.group_user') | cls.env.ref(mod + 'group_microfinance_user') \
            | cls.env.ref('base.group_partner_manager')
        cls.company_a = cls.env['res.company'].create({'name': 'Agence A portefeuille (test)', 'agency_code': 'Y1'})
        cls.company_b = cls.env['res.company'].create({'name': 'Agence B portefeuille (test)', 'agency_code': 'Y2'})

        def user(login, company, groups, companies=None):
            return cls.env['res.users'].create({
                'name': login, 'login': login, 'company_id': company.id,
                'company_ids': [(6, 0, (companies or company).ids)], 'groups_id': [(6, 0, groups.ids)],
            })
        cls.agent_a = user('agent_a_pf_test', cls.company_a, agent_groups)
        cls.agent_a2 = user('agent_a2_pf_test', cls.company_a, agent_groups)
        cls.agent_b = user('agent_b_pf_test', cls.company_b, agent_groups)
        cls.sans_portefeuille = user('sans_pf_test', cls.company_a, agent_groups)
        cls.auditor = user('auditeur_pf_test', cls.company_a,
                           cls.env.ref('base.group_user') | cls.env.ref(mod + 'group_microfinance_auditor'),
                           companies=cls.company_a | cls.company_b)
        Portfolio = cls.env['microfinance.portfolio']
        for agent, company in ((cls.agent_a, cls.company_a), (cls.agent_a2, cls.company_a), (cls.agent_b, cls.company_b)):
            Portfolio.create({'agent_id': agent.id, 'company_id': company.id})

        cls.client_a1 = cls._client(cls.company_a, cls.agent_a)
        cls.client_a2 = cls._client(cls.company_a, cls.agent_a2)
        cls.client_a3 = cls._client(cls.company_a)
        cls.client_b = cls._client(cls.company_b, cls.agent_b)

    @classmethod
    def _unique_cin(cls):
        Partner = cls.env['res.partner'].with_context(active_test=False)
        while True:
            cin = ''.join(str(random.randint(0, 9)) for _ in range(12))
            if not Partner.search_count([('microfinance_id_number', '=', cin)]):
                return cin

    @classmethod
    def _client_vals(cls, company, **extra):
        vals = {
            'name': 'Client PF %s' % cls._unique_cin(), 'company_id': company.id,
            'microfinance_partner_type': 'client', 'microfinance_client_type': 'individual',
            'microfinance_id_type': 'cin', 'microfinance_id_number': cls._unique_cin(),
        }
        vals.update(extra)
        return vals

    @classmethod
    def _client(cls, company, officer=None):
        extra = {'microfinance_officer_id': officer.id} if officer else {}
        return cls.env['res.partner'].with_company(company).with_context(
            microfinance_context=True, allow_microfinance_partner_create=True,
        ).create(cls._client_vals(company, **extra))

    # --- Garde serveur create/write ---
    def test_create_client_sans_flag_bloque(self):
        Partner = self.env['res.partner'].with_company(self.company_a).with_context(microfinance_context=True)
        with self.assertRaises(UserError) as ctx:
            Partner.create(self._client_vals(self.company_a))
        self.assertEqual(ctx.exception.args[0], FORBIDDEN)

    def test_create_client_type_par_defaut_de_contexte_bloque(self):
        Partner = self.env['res.partner'].with_company(self.company_a).with_context(
            microfinance_context=True, default_microfinance_partner_type='client')
        vals = self._client_vals(self.company_a)
        vals.pop('microfinance_partner_type')
        with self.assertRaises(UserError):
            Partner.create(vals)

    def test_create_client_avec_flag_ok(self):
        partner = self.env['res.partner'].with_company(self.company_a).with_context(
            microfinance_context=True, allow_microfinance_partner_create=True,
        ).create(self._client_vals(self.company_a))
        self.assertEqual(partner.microfinance_partner_type, 'client')
        self.assertTrue(partner.microfinance_account_number)

    def test_conjoint_et_garant_type_vide_creables(self):
        Partner = self.env['res.partner'].with_company(self.company_a).with_context(microfinance_context=True)
        spouse = Partner.create({'name': 'Conjoint PF', 'company_id': self.company_a.id})
        guarantor = Partner.create({'name': 'Garant PF', 'company_id': self.company_a.id})
        self.assertFalse(spouse.microfinance_partner_type)
        self.assertFalse(guarantor.microfinance_partner_type)

    def test_write_garant_vers_client_sans_flag_bloque(self):
        Partner = self.env['res.partner'].with_company(self.company_a).with_context(microfinance_context=True)
        guarantor = Partner.create({'name': 'Garant PF bascule', 'company_id': self.company_a.id})
        with self.assertRaises(UserError):
            guarantor.write({'microfinance_partner_type': 'client'})
        guarantor.with_context(allow_microfinance_partner_create=True).write({
            'microfinance_partner_type': 'client', 'microfinance_id_type': 'cin',
            'microfinance_id_number': self._unique_cin(),
        })
        self.assertEqual(guarantor.microfinance_partner_type, 'client')

    def test_write_client_existant_non_bloque(self):
        self.client_a1.with_context(microfinance_context=True).write({
            'microfinance_partner_type': 'client', 'phone': '0340000001'})
        self.assertEqual(self.client_a1.phone, '0340000001')

    def test_creation_hors_contexte_microfinance_inchangee(self):
        partner = self.env['res.partner'].create({
            'name': 'Contact EAT PF', 'microfinance_partner_type': 'client'})
        self.assertEqual(partner.microfinance_partner_type, 'client')

    def test_blocage_inter_agences_toujours_actif_avec_flag(self):
        cin = self._unique_cin()
        client_b = self.env['res.partner'].with_company(self.company_b).with_context(
            microfinance_context=True, allow_microfinance_partner_create=True,
        ).create(self._client_vals(self.company_b, microfinance_id_number=cin))
        loan =self._create_loan(partner_id=client_b.id, company_id=self.company_b.id)
        loan.sudo().write({'state': 'active'})
        with self.assertRaises(ValidationError) as ctx:
            self.env['res.partner'].with_company(self.company_a).with_context(
                microfinance_context=True, allow_microfinance_partner_create=True,
            ).create(self._client_vals(self.company_a, microfinance_id_number=cin))
        self.assertIn('Agence B portefeuille (test)', str(ctx.exception))

    # --- Vues de l'action Clients ---
    def test_vues_action_clients_sans_creation(self):
        action = self.env.ref('microfinance_loan_management.action_microfinance_client')
        views = {v.view_mode: v.view_id for v in action.view_ids}
        self.assertEqual(set(views), {'tree', 'form', 'kanban'})
        Partner = self.env['res.partner'].with_context(microfinance_context=True)
        for view_type, view in views.items():
            arch = etree.fromstring(Partner.get_view(view.id, view_type)['arch'])
            self.assertEqual(arch.get('create'), 'false', view_type)
            if view_type == 'form':
                self.assertEqual(arch.get('duplicate'), 'false')
                self.assertTrue(arch.xpath("//field[@name='microfinance_officer_id']"))
                self.assertTrue(arch.xpath("//page[@name='microfinance_credits']"),
                                "L'extension microfinance de la fiche doit toujours s'appliquer.")
                if 'microfinance_savings_count' in Partner._fields:
                    self.assertTrue(arch.xpath("//field[@name='microfinance_savings_count']"),
                                    "L'extension épargne de la fiche doit toujours s'appliquer.")
            else:
                self.assertEqual(arch.get('import'), 'false', view_type)

    def test_vues_de_base_inchangees(self):
        Partner = self.env['res.partner']
        for view_type in ('tree', 'form', 'kanban'):
            arch = etree.fromstring(Partner.get_view(False, view_type)['arch'])
            self.assertNotEqual(arch.get('create'), 'false', view_type)

    # --- Chemin légitime « Nouveau client » de Mon portefeuille ---
    def test_nouveau_client_portefeuille_agent_pose_cote_serveur(self):
        Loan = self.env['microfinance.loan'].with_user(self.agent_a).with_company(self.company_a)
        action = Loan.with_context(default_microfinance_officer_id=self.agent_b.id).get_portfolio_new_client_action()
        context = action['context']
        self.assertEqual(context['default_microfinance_officer_id'], self.agent_a.id,
                         "Un id d'agent forgé côté client doit être ignoré.")
        self.assertTrue(context['allow_microfinance_partner_create'])
        self.assertEqual(action['views'][0][0], self.env.ref(
            'microfinance_loan_management.view_microfinance_client_form_clients_menu').id)

        vals = self._client_vals(self.company_a)
        vals.pop('microfinance_partner_type')
        partner = self.env['res.partner'].with_user(self.agent_a).with_company(self.company_a) \
            .with_context(**context).create(vals)
        self.assertEqual(partner.microfinance_partner_type, 'client')
        self.assertEqual(partner.microfinance_officer_id, self.agent_a)
        self.assertEqual(partner.company_id, self.company_a)

    def test_nouveau_client_portefeuille_agent_force_refuse(self):
        context = self.env['microfinance.loan'].with_user(self.agent_a).with_company(
            self.company_a).get_portfolio_new_client_action()['context']
        Partner = self.env['res.partner'].with_user(self.agent_a).with_company(self.company_a).with_context(**context)
        with self.assertRaises(UserError):
            Partner.create(self._client_vals(self.company_a, microfinance_officer_id=self.agent_b.id))

    def test_nouveau_client_sans_portefeuille_refuse(self):
        with self.assertRaises(UserError):
            self.env['microfinance.loan'].with_user(self.sans_portefeuille).with_company(
                self.company_a).get_portfolio_new_client_action()

    # --- Panneau de recherche ---
    def _panel_officers(self, user, companies):
        result = self.env['res.partner'].with_user(user).with_context(
            allowed_company_ids=companies.ids, microfinance_context=True,
        ).search_panel_select_range(
            'microfinance_officer_id', search_domain=[('microfinance_partner_type', '=', 'client')],
            enable_counters=True, hierarchize=False)
        return {value['id']: value['__count'] for value in result['values']}

    def test_searchpanel_agent_ne_voit_que_son_agence(self):
        officers = self._panel_officers(self.agent_a, self.company_a)
        self.assertEqual(officers.get(self.agent_a.id), 1)
        self.assertEqual(officers.get(self.agent_a2.id), 1)
        self.assertNotIn(self.agent_b.id, officers)

    def test_searchpanel_auditeur_voit_toutes_les_agences(self):
        officers = self._panel_officers(self.auditor, self.company_a | self.company_b)
        for agent in (self.agent_a, self.agent_a2, self.agent_b):
            self.assertEqual(officers.get(agent.id), 1)

    def test_search_view_panneau_et_filtre_sans_portefeuille(self):
        view = self.env.ref('microfinance_loan_management.view_microfinance_client_search')
        arch = etree.fromstring(self.env['res.partner'].get_view(view.id, 'search')['arch'])
        panel = [f.get('name') for f in arch.xpath('//searchpanel/field')]
        self.assertEqual(panel[:4], ['company_id', 'microfinance_officer_id',
                                      'microfinance_marital_status', 'microfinance_commune_id'])
        officer_panel = arch.xpath("//searchpanel/field[@name='microfinance_officer_id']")[0]
        self.assertEqual(officer_panel.get('select'), 'one')
        self.assertEqual(officer_panel.get('hierarchize'), '0',
                         "res.users hérite parent_id de res.partner : sans hierarchize=0 le panneau plante.")
        no_portfolio = arch.xpath("//filter[@name='no_portfolio']")
        self.assertEqual(no_portfolio[0].get('string'), 'Sans portefeuille')
        found = self.env['res.partner'].search([
            ('company_id', '=', self.company_a.id), ('microfinance_officer_id', '=', False),
            ('microfinance_partner_type', '=', 'client')])
        self.assertEqual(found, self.client_a3)

    # --- Ouverture de la fiche client existante ---
    def _client_form_view_id(self):
        return self.env.ref('microfinance_loan_management.view_microfinance_client_form_clients_menu').id

    def test_action_ouvrir_fiche_client(self):
        action = self.client_a1.with_user(self.agent_a).with_company(self.company_a) \
            .action_open_microfinance_client_form()
        self.assertEqual(action['res_id'], self.client_a1.id)
        self.assertEqual(action['views'], [(self._client_form_view_id(), 'form')])
        self.assertTrue(action['context']['microfinance_context'])
        self.assertNotIn('allow_microfinance_partner_create', action['context'],
                         "Ouvrir une fiche existante ne doit jamais autoriser la création.")

    def test_action_ouvrir_fiche_client_autre_agence_refusee(self):
        with self.assertRaises(AccessError):
            self.client_b.with_user(self.agent_a).with_company(self.company_a) \
                .action_open_microfinance_client_form()

    def test_clic_many2one_sous_contexte_microfinance_ouvre_la_fiche_client(self):
        action = self.client_a1.with_context(
            microfinance_context=True, allow_microfinance_partner_create=True).get_formview_action()
        self.assertEqual(action['views'], [(self._client_form_view_id(), 'form')])
        self.assertNotIn('allow_microfinance_partner_create', action['context'])

    def test_clic_many2one_hors_contexte_inchange(self):
        action = self.env['res.partner'].browse(self.client_a1.id).get_formview_action()
        self.assertNotEqual(action['views'][0][0], self._client_form_view_id())
        guarantor = self.env['res.partner'].create({'name': 'Garant PF clic'})
        action = guarantor.with_context(microfinance_context=True).get_formview_action()
        self.assertNotEqual(action['views'][0][0], self._client_form_view_id(),
                            "Un contact non client garde la fiche standard.")

    def test_sections_microfinance_conditionnees_au_contexte(self):
        arch = etree.fromstring(self.env['res.partner'].get_view(self._client_form_view_id(), 'form')['arch'])
        for field_name in ('microfinance_id_type', 'microfinance_marital_status', 'microfinance_spouse_id'):
            field = arch.xpath("//field[@name='%s']" % field_name)[0]
            conditions = [node.get('invisible') or '' for node in [field] + list(field.iterancestors())]
            self.assertTrue(any("context.get('microfinance_context')" in c for c in conditions), field_name)

    def test_many2one_partner_des_vues_microfinance_propagent_le_contexte(self):
        refs = [
            ('microfinance.loan', 'microfinance_loan_management.view_microfinance_loan_form', 'partner_id'),
            ('microfinance.loan', 'microfinance_loan_management.view_microfinance_loan_form', 'co_borrower_id'),
            ('microfinance.loan.application', 'microfinance_loan_management.view_microfinance_loan_application_form', 'partner_id'),
            ('microfinance.loan.account', 'microfinance_loan_management.view_microfinance_loan_account_form', 'partner_id'),
            ('microfinance.loan.installment', 'microfinance_loan_management.view_microfinance_installment_form', 'partner_id'),
            ('microfinance.loan.payment', 'microfinance_loan_management.view_microfinance_payment_form', 'partner_id'),
        ]
        for model, xmlid, field_name in refs:
            arch = etree.fromstring(self.env[model].get_view(self.env.ref(xmlid).id, 'form')['arch'])
            field = arch.xpath("//field[@name='%s']" % field_name)[0]
            self.assertIn("'microfinance_context': True", field.get('context') or '', '%s.%s' % (model, field_name))

    # --- Migration : rattachement client -> agent ---
    def _loan_for(self, partner, officer):
        return self._create_loan(partner_id=partner.id, officer_id=officer.id)

    def _backfill_fixture(self):
        company = self.env.company
        self.env['microfinance.portfolio'].create({'agent_id': self.agent_a.id, 'company_id': company.id})
        ok = self._client(company)
        multi = self._client(company)
        none = self._client(company)
        other_agency = self._client(company)
        self._loan_for(ok, self.agent_a)
        self._loan_for(ok, self.agent_a)
        self._loan_for(multi, self.agent_a)
        self._loan_for(multi, self.agent_a2)
        self._loan_for(other_agency, self.agent_a)
        other_agency.write({'company_id': self.company_b.id})
        return ok, multi, none, other_agency

    def _status(self, rows, partner):
        return next((row['statut'] for row in rows if row['partner_id'] == partner.id), None)

    def test_backfill_dry_run_par_defaut(self):
        self.env['ir.config_parameter'].sudo().search([('key', '=', PARAM_DRY_RUN)]).unlink()
        self.assertTrue(is_dry_run(self.env))
        self.assertEqual(self.env['ir.config_parameter'].sudo().get_param(PARAM_DRY_RUN), 'True')
        ok, multi, none, other_agency = self._backfill_fixture()
        rows = backfill_client_officer(self.env, log_dir=tempfile.mkdtemp())
        self.assertEqual(self._status(rows, ok), 'A_POSER')
        self.assertFalse(ok.microfinance_officer_id, "Le dry-run ne doit rien écrire.")
        self.assertEqual(self._status(rows, multi), 'AMBIGU_AGENTS')
        self.assertEqual(self._status(rows, none), 'SANS_CREDIT')
        self.assertEqual(self._status(rows, other_agency), 'AMBIGU_AGENCES')

    def test_backfill_reel_idempotent(self):
        ok, multi, none, other_agency = self._backfill_fixture()
        log_dir = tempfile.mkdtemp()
        rows = backfill_client_officer(self.env, dry_run=False, log_dir=log_dir)
        self.assertEqual(self._status(rows, ok), 'POSE')
        self.assertEqual(ok.microfinance_officer_id, self.agent_a)
        for partner in (multi, none, other_agency):
            self.assertFalse(partner.microfinance_officer_id, "Un cas ambigu n'est jamais deviné.")
        rows = backfill_client_officer(self.env, dry_run=False, log_dir=log_dir)
        self.assertIsNone(self._status(rows, ok), "Un client déjà rattaché n'est plus relu.")
        self.assertEqual(self._status(rows, multi), 'AMBIGU_AGENTS')
        self.assertEqual(ok.microfinance_officer_id, self.agent_a)
