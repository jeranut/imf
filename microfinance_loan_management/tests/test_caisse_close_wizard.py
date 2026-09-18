# -*- coding: utf-8 -*-
"""Assistant de clôture de session en 3 temps (Comptage -> Récapitulatif -> Écart) : tests
structurels ici (pré-remplissage du comptage, absence garantie du théorique/écart avant le
temps 3, navigation entre wizards, bouton d'ouverture). Le flux complet jusqu'à
action_confirm_close (comptage, écart, verrou concurrentiel, rollback, écriture d'écart en
attente) exige un vrai microfinance.caisse.mouvement pour produire un théorique non nul : ce
modèle est ajouté par microfinance_savings_management, un module dépendant de celui-ci, chargé
- et donc disponible pour ses propres tests - APRÈS microfinance_loan_management dans l'ordre
d'installation. Ces tests end-to-end vivent donc dans
microfinance_savings_management/tests/test_caisse_close_wizard_confirm.py (cf.
AUDIT_session_zigzag / AUDIT_session_close_3temps)."""
from odoo import fields
from odoo.exceptions import UserError

from .common import MicrofinanceCommon


class TestCaisseCloseSessionWizard(MicrofinanceCommon):

    def setUp(self):
        super().setUp()
        # Neutralise les coupures existantes (données par défaut + éventuelles) pour un jeu de
        # dénominations maîtrisé : le wizard pré-remplit une ligne par coupure active de la
        # devise de la session.
        self.env['microfinance.caisse.denomination'].search([]).write({'active': False})
        currency = self.env.company.currency_id
        self.d1000 = self.env['microfinance.caisse.denomination'].create({
            'name': 'Wizard test 1000', 'value': 1000.0, 'currency_id': currency.id,
        })
        self.d500 = self.env['microfinance.caisse.denomination'].create({
            'name': 'Wizard test 500', 'value': 500.0, 'currency_id': currency.id,
        })
        self.d100 = self.env['microfinance.caisse.denomination'].create({
            'name': 'Wizard test 100', 'value': 100.0, 'currency_id': currency.id,
        })

    def _open_session(self, date=None):
        session = self.env['microfinance.caisse.session'].create({
            'journal_id': self.disbursement_journal.id,
            'date': date or fields.Date.today(),
        })
        session.action_open_session()
        return session

    def _wizard1(self, session):
        return self.env['microfinance.caisse.close.session.wizard'].with_context(
            default_session_id=session.id).create({})

    def _set_quantities(self, wizard, mapping):
        for line in wizard.line_ids:
            if line.denomination_id in mapping:
                line.quantity = mapping[line.denomination_id]

    # --- Temps 1 : pré-remplissage ---

    def test_wizard_prefills_lines_from_active_denominations(self):
        session = self._open_session()
        wizard = self._wizard1(session)
        self.assertEqual(len(wizard.line_ids), 3)
        self.assertEqual(set(wizard.line_ids.mapped('denomination_id')),
                         {self.d1000, self.d500, self.d100})

    def test_archived_denomination_not_offered(self):
        self.d100.active = False
        session = self._open_session()
        wizard = self._wizard1(session)
        self.assertEqual(len(wizard.line_ids), 2)

    # --- Robustesse à un payload line_ids incomplet envoyé par le client ---
    # (cf. AUDIT_denomination_id_manquant : un utilisateur a rencontré une ValidationError
    # "denomination_id requis" au clic sur "Confirmer le comptage", alors que default_get()
    # le renseigne correctement à l'ouverture. create() ne fait plus confiance aux commandes
    # line_ids telles quelles : il les reconstruit toujours depuis le référentiel des
    # dénominations, en ne retenant du payload que les quantités saisies.)

    def test_create_reconstructs_lines_when_denomination_id_missing_from_payload(self):
        session = self._open_session()
        # Simule le payload défectueux : une commande CREATE par coupure, mais sans
        # denomination_id (exactement le symptôme observé), avec des quantités saisies sur
        # certaines lignes. L'ordre correspond à celui de _order sur le modèle de dénomination
        # ('currency_id, value desc') : d1000, d500, d100.
        wizard = self.env['microfinance.caisse.close.session.wizard'].with_context(
            default_session_id=session.id).create({
                'session_id': session.id,
                'line_ids': [
                    (0, 0, {'quantity': 2}),   # devrait retomber sur d1000 (position 0)
                    (0, 0, {'quantity': 0}),   # d500
                    (0, 0, {'quantity': 5}),   # d100
                ],
            })
        self.assertEqual(len(wizard.line_ids), 3)
        self.assertTrue(all(wizard.line_ids.mapped('denomination_id')))
        self.assertEqual(set(wizard.line_ids.mapped('denomination_id')),
                          {self.d1000, self.d500, self.d100})
        line_by_denom = {line.denomination_id: line.quantity for line in wizard.line_ids}
        self.assertEqual(line_by_denom[self.d1000], 2)
        self.assertEqual(line_by_denom[self.d100], 5)
        self.assertEqual(wizard.counted_total, 2 * 1000.0 + 5 * 100.0)

    def test_create_preserves_quantities_by_denomination_id_when_present(self):
        session = self._open_session()
        wizard = self.env['microfinance.caisse.close.session.wizard'].with_context(
            default_session_id=session.id).create({
                'session_id': session.id,
                'line_ids': [
                    (0, 0, {'denomination_id': self.d500.id, 'quantity': 3}),
                    (0, 0, {'denomination_id': self.d1000.id, 'quantity': 1}),
                    (0, 0, {'denomination_id': self.d100.id, 'quantity': 0}),
                ],
            })
        line_by_denom = {line.denomination_id: line.quantity for line in wizard.line_ids}
        self.assertEqual(line_by_denom[self.d500], 3)
        self.assertEqual(line_by_denom[self.d1000], 1)

    def test_confirm_count_succeeds_with_malformed_line_payload(self):
        # Reproduit le scénario bout en bout du bug rapporté : le clic sur "Confirmer le
        # comptage" ne doit plus jamais lever de ValidationError, même si le payload de
        # sauvegarde du formulaire arrive sans denomination_id sur certaines lignes.
        session = self._open_session()
        wizard = self.env['microfinance.caisse.close.session.wizard'].with_context(
            default_session_id=session.id).create({
                'session_id': session.id,
                'line_ids': [(0, 0, {'quantity': 1}), (0, 0, {'quantity': 0}), (0, 0, {'quantity': 0})],
            })
        action = wizard.action_confirm_count()  # ne doit pas lever
        self.assertEqual(action['res_model'], 'microfinance.caisse.close.session.recap.wizard')

    # --- Garantie structurelle : théorique/écart absents avant le temps 3 ---

    def test_step1_wizard_has_no_theoretical_or_variance_field(self):
        # Garantie qu'aucune valeur calculée ne peut fuiter avant le temps 3 : le théorique et
        # l'écart n'existent tout simplement pas sur ce modèle. variance_comment, lui, existe
        # bien ici (depuis le correctif de persistance du brouillon, cf.
        # AUDIT_ecart_cloture_session.md) : il ne s'agit pas d'une valeur calculée pouvant
        # fuiter, seulement du texte déjà saisi par l'utilisateur, porté d'un temps à l'autre et
        # vers le brouillon persistant.
        Wizard = self.env['microfinance.caisse.close.session.wizard']
        self.assertNotIn('theoretical_total', Wizard._fields)
        self.assertNotIn('variance', Wizard._fields)

    def test_step2_recap_wizard_has_no_theoretical_or_variance_field(self):
        Recap = self.env['microfinance.caisse.close.session.recap.wizard']
        self.assertNotIn('theoretical_total', Recap._fields)
        self.assertNotIn('variance', Recap._fields)
        self.assertNotIn('variance_comment', Recap._fields)

    # --- Navigation temps 1 -> temps 2 ---

    def test_confirm_count_opens_recap_with_complete_act_window(self):
        session = self._open_session()
        wizard = self._wizard1(session)
        self._set_quantities(wizard, {self.d1000: 2})
        action = wizard.action_confirm_count()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'microfinance.caisse.close.session.recap.wizard')
        self.assertIn('views', action)
        self.assertTrue(action['views'])
        recap = self.env['microfinance.caisse.close.session.recap.wizard'].browse(action['res_id'])
        self.assertEqual(recap.source_wizard_id, wizard)
        self.assertEqual(recap.counted_total, 2000.0)
        self.assertEqual(len(recap.line_ids), 3)

    def test_confirm_count_blocked_when_session_not_open(self):
        session = self._open_session()
        session.action_close_session()
        wizard = self.env['microfinance.caisse.close.session.wizard'].create({
            'session_id': session.id,
        })
        with self.assertRaises(UserError):
            wizard.action_confirm_count()

    # --- Retour temps 2 -> temps 1 : quantités conservées ---

    def test_recap_action_back_reopens_same_step1_wizard(self):
        session = self._open_session()
        wizard = self._wizard1(session)
        self._set_quantities(wizard, {self.d1000: 1, self.d500: 1})
        recap = self.env['microfinance.caisse.close.session.recap.wizard'].browse(
            wizard.action_confirm_count()['res_id'])
        action = recap.action_back()
        self.assertEqual(action['res_model'], 'microfinance.caisse.close.session.wizard')
        self.assertEqual(action['res_id'], wizard.id)
        self.assertIn('views', action)
        self.assertTrue(action['views'])
        reopened = self.env['microfinance.caisse.close.session.wizard'].browse(action['res_id'])
        self.assertEqual(reopened.counted_total, 1500.0)

    # --- Bouton d'ouverture (session.action_open_close_wizard) ---

    def test_action_open_close_wizard_returns_action(self):
        session = self._open_session()
        action = session.action_open_close_wizard()
        self.assertEqual(action['res_model'], 'microfinance.caisse.close.session.wizard')
        self.assertEqual(action['context']['default_session_id'], session.id)

    def test_action_open_close_wizard_returns_complete_act_window(self):
        # Ce dict est construit à la main et transmis BRUT au client OWL (orm.call + doAction()
        # depuis le bouton "Fermer la caisse" de l'en-tête guichet, pas un bouton type="object"
        # de vue qui passerait par l'enrichissement serveur de ir.actions.act_window.read()) :
        # 'views' doit donc être explicitement présent et non vide, sinon
        # _preprocessAction() plante côté client sur action.views.map()
        # (cf. AUDIT_session_close_action_views).
        session = self._open_session()
        action = session.action_open_close_wizard()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertIn('views', action)
        self.assertTrue(action['views'])
        self.assertEqual(action['views'], [[False, 'form']])

    def test_action_open_close_wizard_blocked_when_not_open(self):
        session = self.env['microfinance.caisse.session'].create({
            'journal_id': self.disbursement_journal.id,
        })
        with self.assertRaises(UserError):
            session.action_open_close_wizard()

    # --- Brouillon persistant : reprise après fermeture de la fenêtre avant confirmation ---
    # (cf. docs_dev/guichet_caisse/AUDIT_ecart_cloture_session.md) - le comptage et le motif ne
    # doivent plus être perdus si l'utilisateur quitte le wizard avant "Confirmer la clôture".

    def test_confirm_count_saves_draft_reopening_wizard_restores_quantities(self):
        session = self._open_session()
        wizard = self._wizard1(session)
        self._set_quantities(wizard, {self.d1000: 2, self.d500: 1})
        wizard.action_confirm_count()  # billetage partiel -> temps 2, fenêtre "fermée" ensuite

        reopened = self._wizard1(session)  # réouverture de "Fermer la caisse" sur la session
        self.assertTrue(reopened.is_recovered_draft)
        line_by_denom = {line.denomination_id: line.quantity for line in reopened.line_ids}
        self.assertEqual(line_by_denom[self.d1000], 2)
        self.assertEqual(line_by_denom[self.d500], 1)

    def test_reopen_without_draft_is_not_flagged_as_recovered(self):
        session = self._open_session()
        wizard = self._wizard1(session)
        self.assertFalse(wizard.is_recovered_draft)

    def test_variance_wizard_back_saves_comment_into_draft(self):
        session = self._open_session()
        wizard = self._wizard1(session)
        self._set_quantities(wizard, {self.d1000: 1})
        recap = self.env['microfinance.caisse.close.session.recap.wizard'].browse(
            wizard.action_confirm_count()['res_id'])
        variance = self.env['microfinance.caisse.close.session.variance.wizard'].browse(
            recap.action_confirm_recap()['res_id'])
        variance.variance_comment = 'Erreur de rendu monnaie chez un client.'
        variance.action_back()  # quitte le temps 3 sans cliquer "Confirmer la clôture"

        reopened = self._wizard1(session)
        self.assertTrue(reopened.is_recovered_draft)
        self.assertEqual(reopened.variance_comment, 'Erreur de rendu monnaie chez un client.')
        self.assertEqual(
            {line.denomination_id: line.quantity for line in reopened.line_ids}[self.d1000], 1)

    def test_draft_is_a_single_record_per_session_across_transitions(self):
        session = self._open_session()
        wizard = self._wizard1(session)
        self._set_quantities(wizard, {self.d1000: 1})
        wizard.action_confirm_count()
        reopened = self._wizard1(session)
        self._set_quantities(reopened, {self.d1000: 3, self.d100: 4})
        reopened.action_confirm_count()

        Brouillon = self.env['microfinance.caisse.comptage.brouillon']
        drafts = Brouillon.search([('session_id', '=', session.id)])
        self.assertEqual(len(drafts), 1)
        line_by_denom = {line.denomination_id: line.quantity for line in drafts.line_ids}
        self.assertEqual(line_by_denom[self.d1000], 3)
        self.assertEqual(line_by_denom[self.d100], 4)
