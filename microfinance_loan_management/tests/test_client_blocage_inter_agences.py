# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError

from .common import MicrofinanceCommon, MicrofinanceNoFundMixin

CIN_BLOQUE = '123456789012'
CIN_LIBRE = '210987654321'


class TestClientBlocageInterAgences(MicrofinanceNoFundMixin, MicrofinanceCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        groups = cls.env.ref('base.group_user') | cls.env.ref(
            'microfinance_loan_management.group_microfinance_user') | cls.env.ref('base.group_partner_manager')
        cls.company_a = cls.env.company
        cls.company_b = cls.env['res.company'].create({'name': 'Agence B blocage (test)', 'agency_code': 'Z2'})
        cls.user_a = cls.env['res.users'].create({
            'name': 'Agent Agence A (blocage)', 'login': 'agent_a_blocage_test',
            'company_id': cls.company_a.id, 'company_ids': [(6, 0, [cls.company_a.id])],
            'groups_id': [(6, 0, groups.ids)],
        })
        cls.user_b = cls.env['res.users'].create({
            'name': 'Agent Agence B (blocage)', 'login': 'agent_b_blocage_test',
            'company_id': cls.company_b.id, 'company_ids': [(6, 0, [cls.company_b.id])],
            'groups_id': [(6, 0, groups.ids)],
        })

    def _new_client(self, user, company, cin, name, microfinance_context=True):
        Partner = self.env['res.partner'].with_user(user).with_company(company)
        if microfinance_context:
            Partner = Partner.with_context(microfinance_context=True, allow_microfinance_partner_create=True)
        return Partner.create({
            'name': name,
            'company_id': company.id,
            'microfinance_partner_type': 'client',
            'microfinance_id_type': 'cin',
            'microfinance_id_number': cin,
        })

    def _loan_agence_b(self, cin=CIN_BLOQUE, state='active'):
        """Crédit d'un client de l'agence B (même CIN), dans l'état demandé."""
        partner_b = self._new_client(self.user_b, self.company_b, cin, 'Client Agence B')
        loan_b = self._create_loan(partner_id=partner_b.id, company_id=self.company_b.id)
        loan_b.sudo().write({'state': state})
        return loan_b

    def _assert_blocage(self, callable_):
        with self.assertRaises(ValidationError) as ctx:
            callable_()
        self.assertIn('Agence B blocage (test)', str(ctx.exception))
        return str(ctx.exception)

    # --- Création du client ---
    def test_creation_client_bloquee_si_pret_actif_autre_agence(self):
        self._loan_agence_b()
        self._assert_blocage(lambda: self._new_client(self.user_a, self.company_a, CIN_BLOQUE, 'Client A'))

    def test_creation_client_bloquee_si_pret_defaut_autre_agence(self):
        self._loan_agence_b(state='defaulted')
        self._assert_blocage(lambda: self._new_client(self.user_a, self.company_a, CIN_BLOQUE, 'Client A'))

    def test_creation_client_ok_sans_pret(self):
        client = self._new_client(self.user_a, self.company_a, CIN_LIBRE, 'Client A')
        self.assertTrue(client)

    def test_creation_client_ok_si_pret_autre_agence_non_en_cours(self):
        for index, state in enumerate(('draft', 'approved', 'closed', 'cancelled', 'written_off')):
            with self.subTest(state=state):
                cin = '30000000000%d' % index
                self._loan_agence_b(cin=cin, state=state)
                client = self._new_client(self.user_a, self.company_a, cin, 'Client A %s' % state)
                self.assertTrue(client)

    def test_creation_client_ok_sans_microfinance_context(self):
        self._loan_agence_b()
        client = self._new_client(
            self.user_a, self.company_a, CIN_BLOQUE, 'Contact EAT', microfinance_context=False)
        self.assertTrue(client)

    # --- CIN obligatoire pour un client particulier (contexte microfinance) ---
    def _create_client_vals(self, **extra):
        vals = {'name': 'Client sans CIN', 'company_id': self.company_a.id, 'microfinance_partner_type': 'client'}
        vals.update(extra)
        return vals

    def test_cin_obligatoire_client_particulier(self):
        Partner = self.env['res.partner'].with_user(self.user_a).with_context(microfinance_context=True, allow_microfinance_partner_create=True)
        with self.assertRaisesRegex(ValidationError, 'CIN est obligatoire'):
            Partner.create(self._create_client_vals())

    def test_piece_obligatoire_autre_type_de_piece(self):
        # Passeport / autre : le numéro de la pièce est exigé, pas un CIN.
        Partner = self.env['res.partner'].with_user(self.user_a).with_context(microfinance_context=True, allow_microfinance_partner_create=True)
        for id_type in ('passport', 'other'):
            with self.subTest(id_type=id_type):
                with self.assertRaisesRegex(ValidationError, "numéro de la pièce d'identité est obligatoire"):
                    Partner.create(self._create_client_vals(microfinance_id_type=id_type))
                client = Partner.create(self._create_client_vals(
                    microfinance_id_type=id_type, microfinance_id_number='AB123456'))
                self.assertEqual(client.microfinance_id_number, 'AB123456')

    def test_cin_non_obligatoire_hors_microfinance_context(self):
        Partner = self.env['res.partner'].with_user(self.user_a)
        self.assertTrue(Partner.create(self._create_client_vals()))

    def test_cin_non_obligatoire_pour_non_client_ou_societe(self):
        Partner = self.env['res.partner'].with_user(self.user_a).with_context(microfinance_context=True, allow_microfinance_partner_create=True)
        garant = Partner.create({'name': 'Garant', 'company_id': self.company_a.id})
        societe = Partner.create(self._create_client_vals(
            name='Société cliente', microfinance_client_type='company'))
        self.assertTrue(garant and societe)

    def test_creation_client_cin_saisi_via_affichage_bloquee(self):
        self._loan_agence_b()
        Partner = self.env['res.partner'].with_user(self.user_a).with_context(microfinance_context=True, allow_microfinance_partner_create=True)
        self._assert_blocage(lambda: Partner.create({
            'name': 'Client A', 'company_id': self.company_a.id, 'microfinance_partner_type': 'client',
            'microfinance_id_type': 'cin', 'microfinance_id_number_display': '123 456 789 012',
        }))

    def test_write_cin_vers_cin_bloque(self):
        self._loan_agence_b()
        client = self._new_client(self.user_a, self.company_a, CIN_LIBRE, 'Client A')
        self._assert_blocage(lambda: client.with_user(self.user_a).with_context(
            microfinance_context=True).write({'microfinance_id_number': CIN_BLOQUE}))

    def test_write_cin_vers_cin_bloque_sans_microfinance_context_ok(self):
        self._loan_agence_b()
        client = self._new_client(self.user_a, self.company_a, CIN_LIBRE, 'Client A')
        client.with_user(self.user_a).with_context(microfinance_context=False).write(
            {'microfinance_id_number': CIN_BLOQUE})
        self.assertEqual(client.microfinance_id_number, CIN_BLOQUE)

    def test_write_champ_sans_rapport_ne_bloque_pas(self):
        client = self._new_client(self.user_a, self.company_a, CIN_BLOQUE, 'Client A')
        self._loan_agence_b()
        client.with_user(self.user_a).with_context(microfinance_context=True, allow_microfinance_partner_create=True).write({'name': 'Client A renommé'})
        self.assertEqual(client.name, 'Client A renommé')

    # --- Dossier de crédit, pour un client créé AVANT le prêt de l'autre agence ---
    def _client_a_existant(self):
        return self._new_client(self.user_a, self.company_a, CIN_BLOQUE, 'Client A existant')

    def test_credit_bloque_a_la_creation(self):
        client_a = self._client_a_existant()
        self._loan_agence_b()
        self._assert_blocage(lambda: self._create_loan(partner_id=client_a.id))

    def test_credit_bloque_a_l_approbation(self):
        client_a = self._client_a_existant()
        loan_a = self._create_loan(partner_id=client_a.id)
        loan_a.action_generate_schedule()
        loan_a.action_start_enquete()
        loan_a.action_ca_review()
        loan_a.action_cdag_review()
        loan_a.action_view_applications()
        loan_a.application_ids.write({'committee_first_decision': 'accepted'})
        self._loan_agence_b()
        self._assert_blocage(loan_a.action_approve)
        self.assertEqual(loan_a.state, 'avis_cdag')

    def test_credit_bloque_a_l_activation(self):
        client_a = self._client_a_existant()
        loan_a = self._approve_loan(partner_id=client_a.id)
        self._loan_agence_b()
        self._assert_blocage(loan_a.action_activate)
        self.assertEqual(loan_a.state, 'approved')

    def test_credit_bloque_au_decaissement(self):
        client_a = self._client_a_existant()
        loan_b = self._loan_agence_b(state='draft')
        loan_a = self._activate_loan_without_disbursement(partner_id=client_a.id)
        loan_b.sudo().write({'state': 'active'})
        self._assert_blocage(loan_a.action_process_disbursement)
        self.assertFalse(loan_a.disbursement_date)

    def test_credit_ok_si_pret_autre_agence_solde(self):
        client_a = self._client_a_existant()
        self._loan_agence_b(state='closed')
        loan_a = self._activate_loan(partner_id=client_a.id)
        self.assertTrue(loan_a.disbursement_date)

    # --- Même agence : comportement inchangé ---
    def test_pret_actif_meme_agence_ne_bloque_pas(self):
        client_a = self._client_a_existant()
        premier = self._activate_loan(partner_id=client_a.id)
        second = self._create_loan(partner_id=client_a.id)
        self.assertEqual(premier.state, 'active')
        self.assertEqual(second.get_loan_rank_for_partner(), 2)
        second._check_no_active_loan_elsewhere()

    # --- Confidentialité du message ---
    def test_message_ne_revele_que_le_nom_de_l_agence(self):
        client_a = self._client_a_existant()
        loan_b = self._loan_agence_b()
        message = self._assert_blocage(lambda: self._create_loan(partner_id=client_a.id))
        self.assertNotIn(loan_b.name, message)
        self.assertNotIn(loan_b.partner_id.name, message)
        self.assertNotIn(CIN_BLOQUE, message)
        self.assertNotIn('1200', message)
        self.assertIn('solder', message)
        self.assertIn('transfert de compte', message)

    # --- N° CIN saisi via le champ affiché (microfinance_id_number_display, calculé non stocké) ---
    CIN_ESPACES = '101 981 092 052'
    CIN_CHIFFRES = '101981092052'

    def _partner_model(self, user=None):
        return self.env['res.partner'].with_user(user or self.user_a).with_context(microfinance_context=True, allow_microfinance_partner_create=True)

    def test_cin_avec_espaces_creation_via_affichage(self):
        client = self._partner_model().create(self._create_client_vals(
            microfinance_id_type='cin', microfinance_id_number_display=self.CIN_ESPACES))
        self.assertEqual(client.microfinance_id_number, self.CIN_CHIFFRES)
        self.assertEqual(client.microfinance_id_number_display, self.CIN_ESPACES)

    def test_cin_avec_espaces_creation_via_champ_stocke(self):
        client = self._partner_model().create(self._create_client_vals(
            microfinance_id_type='cin', microfinance_id_number=self.CIN_ESPACES))
        self.assertEqual(client.microfinance_id_number_display, self.CIN_ESPACES)

    def test_modification_client_existant_type_et_cin_saisis_ensemble(self):
        # Cas du formulaire : fiche existante sans pièce, l'agent choisit CIN et saisit le numéro.
        ancien = self.env['res.partner'].create(self._create_client_vals(name='Ancien client'))
        ancien.with_user(self.user_a).with_context(microfinance_context=True, allow_microfinance_partner_create=True).write({
            'microfinance_id_type': 'cin', 'microfinance_id_number_display': self.CIN_ESPACES,
        })
        self.assertEqual(ancien.microfinance_id_number, self.CIN_CHIFFRES)

    def test_modification_passeport_vers_cin_via_affichage(self):
        client = self._partner_model().create(self._create_client_vals(
            microfinance_id_type='passport', microfinance_id_number='AB123456'))
        client.write({'microfinance_id_type': 'cin', 'microfinance_id_number_display': self.CIN_ESPACES})
        self.assertEqual(client.microfinance_id_number, self.CIN_CHIFFRES)

    def test_modification_adresse_sans_toucher_au_cin(self):
        client = self._partner_model().create(self._create_client_vals(
            microfinance_id_type='cin', microfinance_id_number_display=self.CIN_ESPACES))
        client.write({'street': '12 rue des Tests', 'city': 'Antananarivo'})
        client.write({'street': '13 rue des Tests', 'microfinance_id_number_display': self.CIN_ESPACES})
        self.assertEqual(client.street, '13 rue des Tests')
        self.assertEqual(client.microfinance_id_number, self.CIN_CHIFFRES)

    def test_client_type_cin_sans_numero_refuse(self):
        Partner = self._partner_model()
        with self.assertRaisesRegex(ValidationError, 'CIN est obligatoire'):
            Partner.create(self._create_client_vals(microfinance_id_type='cin'))
        with self.assertRaisesRegex(ValidationError, 'CIN est obligatoire'):
            Partner.create(self._create_client_vals(
                microfinance_id_type='cin', microfinance_id_number_display=''))
        client = Partner.create(self._create_client_vals(
            microfinance_id_type='cin', microfinance_id_number_display=self.CIN_ESPACES))
        with self.assertRaisesRegex(ValidationError, 'CIN est obligatoire'):
            client.write({'microfinance_id_number_display': ''})
        with self.assertRaisesRegex(ValidationError, 'CIN est obligatoire'):
            client.write({'microfinance_id_number_display': '   '})

    def test_societe_et_contact_non_client_sans_cin_ok(self):
        Partner = self._partner_model()
        societe = Partner.create(self._create_client_vals(
            name='Société cliente', microfinance_client_type='company', is_company=True))
        contact = Partner.create({'name': 'Contact adresse', 'company_id': self.company_a.id, 'type': 'other'})
        garant = Partner.create({
            'name': 'Garant', 'company_id': self.company_a.id, 'microfinance_id_type': 'cin',
            'microfinance_id_number_display': '',
        })
        societe.write({'street': 'Zone industrielle'})
        contact.write({'street': 'Autre adresse'})
        self.assertTrue(societe and contact and garant)

    # --- Blocage inter-agences : même CIN, avec ou sans espaces ---
    def test_blocage_inter_agences_cin_normalise(self):
        cases = (
            ('stocke sans espaces / demande avec espaces', self.CIN_CHIFFRES, self.CIN_ESPACES),
            ('stocke avec espaces / demande sans espaces', self.CIN_ESPACES, self.CIN_CHIFFRES),
        )
        for index, (label, cin_b, cin_a) in enumerate(cases):
            with self.subTest(label):
                # CIN distincts d'un cas à l'autre (unicité globale) : dernier chiffre décalé.
                shift = lambda cin: cin[:-1] + str(index)
                self._loan_agence_b(cin=shift(cin_b))
                self._assert_blocage(lambda: self._new_client(
                    self.user_a, self.company_a, shift(cin_a), 'Client A %s' % index))

    def test_blocage_inter_agences_creation_via_affichage_avec_espaces(self):
        self._loan_agence_b(cin=self.CIN_CHIFFRES)
        self._assert_blocage(lambda: self._partner_model().create(self._create_client_vals(
            microfinance_id_type='cin', microfinance_id_number_display=self.CIN_ESPACES)))

    def test_blocage_inter_agences_modification_cin_via_affichage(self):
        self._loan_agence_b(cin=self.CIN_CHIFFRES)
        client = self._new_client(self.user_a, self.company_a, CIN_LIBRE, 'Client A')
        self._assert_blocage(lambda: client.with_user(self.user_a).with_context(
            microfinance_context=True).write({'microfinance_id_number_display': self.CIN_ESPACES}))

    def test_credit_bloque_cin_saisi_avec_espaces(self):
        client_a = self._new_client(self.user_a, self.company_a, self.CIN_ESPACES, 'Client A espaces')
        self._loan_agence_b(cin=self.CIN_CHIFFRES)
        self._assert_blocage(lambda: self._create_loan(partner_id=client_a.id))

    def test_client_sans_credit_en_cours_autorise(self):
        client_a = self._new_client(self.user_a, self.company_a, self.CIN_ESPACES, 'Client A libre')
        loan_a = self._create_loan(partner_id=client_a.id)
        self.assertTrue(loan_a)
        loan_a._check_no_active_loan_elsewhere()
