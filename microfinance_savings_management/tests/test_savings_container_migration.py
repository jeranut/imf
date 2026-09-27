# -*- coding: utf-8 -*-
import csv
import os
import shutil
import tempfile


from odoo.addons.microfinance_loan_management.tests.common import MicrofinanceNoFundMixin
from odoo.addons.microfinance_savings_management.container_migration import (
    OLD_TYPE_I_SEQUENCE_CODE,
    PARAM_DRY_RUN,
    SHARED_ACCOUNT_NUMBER_SEQUENCE_CODE,
    align_savings_number_sequences,
    is_dry_run,
    list_savings_duplicates,
    rename_misnumbered_containers,
)

from .common import SavingsCommon


class TestSavingsContainerMigration(MicrofinanceNoFundMixin, SavingsCommon):
    """Migration 17.0.1.5.0 : renommage des conteneurs de l'ancien format AGENCE/IC/<numéro du
    compte crédit> (Option A, 21/09) vers AGENCE/I/<numéro de compte permanent> (correctif du
    2026-09-24, docs_dev/epargne_auto/AUDIT_doublons_creation_client.md §13). La base de test est
    une copie de données réelles : on ne raisonne donc QUE sur les lignes créées par le test."""

    def setUp(self):
        super().setUp()
        self.log_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.log_dir, ignore_errors=True)

    def _misnumbered_container(self, cin):
        """Simule un conteneur encore au format Option A (AGENCE/IC/<N>) : on part d'un client
        conforme au nouveau format, puis on renomme son conteneur en arrière vers l'ancien nom."""
        partner = self._create_context_client(cin)
        container = self.env['microfinance.savings.account'].search([
            ('partner_id', '=', partner.id), ('is_container', '=', True)])
        target = container.name
        agency, suffix = target.split('/I/', 1)
        old = '%s/IC/%s' % (agency, suffix)
        container.write({'name': old})
        return partner, container, old, target

    def _run(self, container, dry_run):
        rows = rename_misnumbered_containers(self.env, dry_run=dry_run, log_dir=self.log_dir)
        return [r for r in rows if r['id'] == container.id]

    def test_dry_run_changes_nothing_but_lists_and_traces(self):
        _partner, container, old, target = self._misnumbered_container('822000000001')
        rows = self._run(container, dry_run=True)
        self.assertEqual(container.name, old)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['ancien_nom'], rows[0]['nouveau_nom'], rows[0]['statut']),
                         (old, target, 'A_RENOMMER'))
        files = [f for f in os.listdir(self.log_dir) if f.startswith('renommage_conteneurs_epargne') and f.endswith('_dryrun.csv')]
        self.assertEqual(len(files), 1)
        with open(os.path.join(self.log_dir, files[0]), encoding='utf-8') as handle:
            traced = [r for r in csv.DictReader(handle, delimiter=';') if r['id'] == str(container.id)]
        self.assertEqual(len(traced), 1)
        self.assertEqual(traced[0]['nouveau_nom'], target)
        self.assertTrue(traced[0]['credit_lie'])

    def test_real_run_renames_container_then_second_run_is_noop(self):
        _partner, container, old, target = self._misnumbered_container('822000000002')
        rows = self._run(container, dry_run=False)
        self.assertEqual([r['statut'] for r in rows], ['RENOMME'])
        self.assertEqual(container.name, target)
        self.assertEqual(self._run(container, dry_run=False), [])  # idempotent

    def test_existing_target_name_is_reported_not_renamed(self):
        partner, container, old, target = self._misnumbered_container('822000000003')
        squatter = self._create_account(partner_id=partner.id, name=target)
        rows = self._run(container, dry_run=False)
        self.assertEqual([r['statut'] for r in rows], ['IGNORE_NOM_EXISTANT'])
        self.assertEqual(container.name, old)
        self.assertEqual(squatter.name, target)

    def test_old_name_cited_in_free_text_blocks_rename(self):
        partner, container, old, _target = self._misnumbered_container('822000000004')
        partner.message_post(body='Rapprochement avec le compte %s' % old)
        rows = self._run(container, dry_run=False)
        self.assertEqual([r['statut'] for r in rows], ['IGNORE_REFERENCES_TEXTE'])
        self.assertIn('mail.message.body', rows[0]['detail'])
        self.assertEqual(container.name, old)

    def test_dry_run_is_default_and_only_explicit_false_enables_real_run(self):
        params = self.env['ir.config_parameter'].sudo()
        params.search([('key', '=', PARAM_DRY_RUN)]).unlink()
        self.assertTrue(is_dry_run(self.env))
        self.assertEqual(params.get_param(PARAM_DRY_RUN), 'True')  # créé à True
        params.set_param(PARAM_DRY_RUN, 'False')
        self.assertFalse(is_dry_run(self.env))
        params.set_param(PARAM_DRY_RUN, '')
        self.assertTrue(is_dry_run(self.env))

    def test_two_runs_never_overwrite_each_others_trace(self):
        # Régression constatée au déploiement du 21/09 : deux exécutions dans la même seconde
        # écrasaient le CSV de la première (nom de fichier identique).
        _partner, container, _old, _target = self._misnumbered_container('822000000005')
        self._run(container, dry_run=True)
        self._run(container, dry_run=True)
        files = [f for f in os.listdir(self.log_dir) if f.startswith('renommage_conteneurs_epargne')]
        self.assertEqual(len(files), 2)
        for name in files:
            with open(os.path.join(self.log_dir, name), encoding='utf-8') as handle:
                self.assertIn(str(container.id), handle.read())


class TestSavingsDuplicatesListing(MicrofinanceNoFundMixin, SavingsCommon):
    """list_savings_duplicates : liste (jamais de fusion, jamais d'écriture sur un compte) les
    clients ayant un conteneur ET au moins un compte réel pour la même société - typiquement
    l'ancien « compte principal » de l'Option A. Colonne ``decision`` vide, à remplir par Micka."""

    def setUp(self):
        super().setUp()
        self.log_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.log_dir, ignore_errors=True)

    def test_client_with_only_a_container_is_not_listed(self):
        # Base de test = copie de données réelles : on ne raisonne donc QUE sur les lignes de
        # NOTRE partenaire (d'autres clients réels peuvent légitimement déjà apparaître dans la
        # liste, ex. le cas ELIO constaté sur MOWGLI - c'est le comportement attendu, pas une
        # régression).
        partner = self._create_context_client('823000000001')
        rows = list_savings_duplicates(self.env, log_dir=self.log_dir)
        self.assertFalse([r for r in rows if r['partner_id'] == partner.id])

    def test_client_with_container_and_one_real_account_is_listed_with_empty_decision(self):
        partner = self._create_context_client('823000000002')
        account = self._create_account(partner_id=partner.id)
        rows = list_savings_duplicates(self.env, log_dir=self.log_dir)
        matching = [r for r in rows if r['partner_id'] == partner.id]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]['compte_id'], account.id)
        self.assertEqual(matching[0]['decision'], '')

    def test_listing_never_writes_to_any_account(self):
        partner = self._create_context_client('823000000003')
        account = self._create_account(partner_id=partner.id)
        container = self.env['microfinance.savings.account'].search([
            ('partner_id', '=', partner.id), ('is_container', '=', True)])
        names_before = (container.name, account.name)
        list_savings_duplicates(self.env, log_dir=self.log_dir)
        self.assertEqual((container.name, account.name), names_before)

    def test_listing_writes_a_csv_with_decision_column(self):
        partner = self._create_context_client('823000000004')
        self._create_account(partner_id=partner.id)
        list_savings_duplicates(self.env, log_dir=self.log_dir)
        files = [f for f in os.listdir(self.log_dir) if f.startswith('doublons_comptes_epargne')]
        self.assertEqual(len(files), 1)
        with open(os.path.join(self.log_dir, files[0]), encoding='utf-8') as handle:
            header = next(csv.reader(handle, delimiter=';'))
        self.assertIn('decision', header)


class TestSavingsSequenceAlignment(MicrofinanceNoFundMixin, SavingsCommon):
    """align_savings_number_sequences (Option B, docs_dev/epargne_auto/
    AUDIT_doublons_creation_client.md §15) : la séquence des comptes réels de type I et celle du
    numéro de compte permanent sont fusionnées dans le code (même code de séquence ir.sequence) -
    cette fonction avance une fois le plancher partagé au-delà du plus avancé des deux anciens
    compteurs, pour ne pas recréer de collision avec l'historique."""

    def setUp(self):
        super().setUp()
        self.log_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.log_dir, ignore_errors=True)
        self.Sequence = self.env['ir.sequence'].sudo().with_context(active_test=False)

    def _set_sequence_next(self, code, next_value):
        seq = self.Sequence.search([('code', '=', code), ('company_id', '=', self.env.company.id)], limit=1)
        if not seq:
            seq = self.Sequence.create({
                'name': '%s (%s)' % (code, self.env.company.name), 'code': code,
                'company_id': self.env.company.id, 'padding': 6, 'number_increment': 1,
            })
        seq.write({'number_next': next_value})
        return seq

    def test_dry_run_reports_the_gap_without_changing_anything(self):
        self._set_sequence_next(OLD_TYPE_I_SEQUENCE_CODE, 628)
        self._set_sequence_next(SHARED_ACCOUNT_NUMBER_SEQUENCE_CODE, 523)
        rows = align_savings_number_sequences(self.env, dry_run=True, log_dir=self.log_dir)
        matching = [r for r in rows if r['societe'] == self.env.company.name]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]['statut'], 'A_ALIGNER')
        self.assertEqual(matching[0]['nouveau_prochain_compte_permanent'], 628)
        shared = self.Sequence.search([
            ('code', '=', SHARED_ACCOUNT_NUMBER_SEQUENCE_CODE), ('company_id', '=', self.env.company.id)])
        self.assertEqual(shared.number_next_actual, 523)  # inchangé

    def test_real_run_advances_shared_sequence_and_deactivates_old_one(self):
        self._set_sequence_next(OLD_TYPE_I_SEQUENCE_CODE, 628)
        self._set_sequence_next(SHARED_ACCOUNT_NUMBER_SEQUENCE_CODE, 523)
        rows = align_savings_number_sequences(self.env, dry_run=False, log_dir=self.log_dir)
        matching = [r for r in rows if r['societe'] == self.env.company.name]
        self.assertEqual(matching[0]['statut'], 'ALIGNE')
        shared = self.Sequence.search([
            ('code', '=', SHARED_ACCOUNT_NUMBER_SEQUENCE_CODE), ('company_id', '=', self.env.company.id)])
        self.assertEqual(shared.number_next_actual, 628)
        old = self.Sequence.search([
            ('code', '=', OLD_TYPE_I_SEQUENCE_CODE), ('company_id', '=', self.env.company.id)])
        self.assertFalse(old.active)
        self.assertIn('OBSOL', old.name)

    def test_already_aligned_is_a_noop(self):
        self._set_sequence_next(OLD_TYPE_I_SEQUENCE_CODE, 100)
        self._set_sequence_next(SHARED_ACCOUNT_NUMBER_SEQUENCE_CODE, 500)
        rows = align_savings_number_sequences(self.env, dry_run=False, log_dir=self.log_dir)
        matching = [r for r in rows if r['societe'] == self.env.company.name]
        self.assertEqual(matching[0]['statut'], 'DEJA_ALIGNE')
        shared = self.Sequence.search([
            ('code', '=', SHARED_ACCOUNT_NUMBER_SEQUENCE_CODE), ('company_id', '=', self.env.company.id)])
        self.assertEqual(shared.number_next_actual, 500)  # inchangé, jamais reculé

    def test_second_real_run_is_idempotent(self):
        self._set_sequence_next(OLD_TYPE_I_SEQUENCE_CODE, 628)
        self._set_sequence_next(SHARED_ACCOUNT_NUMBER_SEQUENCE_CODE, 523)
        align_savings_number_sequences(self.env, dry_run=False, log_dir=self.log_dir)
        rows_second = align_savings_number_sequences(self.env, dry_run=False, log_dir=self.log_dir)
        matching = [r for r in rows_second if r['societe'] == self.env.company.name]
        self.assertEqual(matching[0]['statut'], 'DEJA_ALIGNE')

    def test_new_real_account_after_alignment_never_collides_with_old_one(self):
        # Reproduit le blocage constaté sur MOWGLI : un compte réel historique occupe déjà
        # AGENCE/I/<N> pour un N que le compteur compte permanent n'a pas encore atteint.
        self._create_account(name='%s/I/000628' % self.env.company.agency_code)
        self._set_sequence_next(OLD_TYPE_I_SEQUENCE_CODE, 629)
        self._set_sequence_next(SHARED_ACCOUNT_NUMBER_SEQUENCE_CODE, 523)
        align_savings_number_sequences(self.env, dry_run=False, log_dir=self.log_dir)
        partner = self._create_context_client('824000000001')
        container = self.env['microfinance.savings.account'].search([
            ('partner_id', '=', partner.id), ('is_container', '=', True)])
        self.assertEqual(len(container), 1)  # aucune ValidationError
