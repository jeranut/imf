# -*- coding: utf-8 -*-
"""Traces détaillées du chatter (mf.trace) : contenu, confidentialité, robustesse, performance, et surtout aucune
différence comptable avec ou sans trace.

Deux scénarios : fonds d'exploitation partagé à deux agences (fixtures de test_fond_partage_exploitation) et relevé
bancaire sur un fonds de crédit multi-agences (fixtures de test_bank_statement_paper). Les classes parentes sont
importées par leur module pour ne pas être rejouées ici ; leurs propres tests sont neutralisés."""
import logging
from contextlib import closing
from unittest.mock import patch

from odoo import Command
from odoo.tools import html2plaintext

from . import test_bank_statement_paper as paper
from . import test_fond_partage_exploitation as expl

MF = 'microfinance_loan_management.'
LOGGER = 'odoo.addons.microfinance_loan_management.models.mf_trace'
AR = ' Ar'
M100_TEST, M40_TEST, M30_TEST = 100000000.0, 40000000.0, 30000000.0


def _drop_inherited_tests(cls, parent):
    for name in dir(parent):
        if name.startswith('test_') and name not in cls.__dict__ and callable(getattr(parent, name)):
            setattr(cls, name, None)


class TraceHelpers:
    def traces(self, record):
        record = record.sudo()
        return record.message_ids.filtered(lambda m: 'o_mf_trace' in (m.body or '')).sorted('id')

    def plain(self, message):
        return html2plaintext(message.body).replace('\u00a0', ' ')

    def text(self, record):
        return '\n'.join(self.plain(m) for m in self.traces(record))

    def with_title(self, record, fragment):
        return self.traces(record).filtered(lambda m: fragment in self.plain(m).split('\n')[0])

    def neutral_trace(self):
        return patch.object(type(self.env['mf.trace']), 'mf_trace_batch', lambda self, entries: False)


class TestMfTraceExploitation(TraceHelpers, expl.TestFondPartageExploitation):
    """Contribution et partage d'un fonds d'exploitation à deux agences ; lettrage ; fonds ; robustesse."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.acc_ag1 = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Comptable agence 1 (trace)', 'login': 'trace_acc_ag1', 'company_id': cls.ag1.id,
            'company_ids': [(6, 0, [cls.ag1.id])],
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id, cls.env.ref('account.group_account_manager').id])]})

    # ------------------------------------------------------------------ contribution
    def test_contribution_validation_is_traced_on_contribution_fund_and_move(self):
        fond = self._create_fond(name='Exploitation trace', destination='exploitation', nature='subvention',
                                 bank_id=self.bmoi.id, account_id=False)
        contrib = self._create_contribution(fond, amount=M100_TEST, reference_paiement='VIR-TRACE')
        followers = contrib.message_partner_ids
        mails = self.env['mail.mail'].sudo().search_count([])
        contrib.action_post()
        move = contrib.move_id
        text = self.text(contrib)
        self.assertEqual(len(self.with_title(contrib, 'Contribution validée')), 1)
        for expected in ('100 000 000' + AR, 'BMOPT', 'VIR-TRACE', move.name, 'Virement'):
            self.assertIn(expected, text)
        body = self.traces(contrib).body
        self.assertIn('data-oe-model="account.move"', body)
        self.assertIn('data-oe-id="%s"' % move.id, body)
        self.assertEqual(len(self.with_title(fond, 'Contribution validée')), 1)
        self.assertIn('100 000 000' + AR, self.text(fond))
        created = self.with_title(move, 'Créée par la contribution')
        self.assertEqual(len(created), 1)
        self.assertIn(self.hq_in.code, self.plain(created))
        # note interne : ni notification, ni e-mail, ni abonné
        for message in self.traces(contrib) | self.traces(fond) | created:
            self.assertEqual((message.message_type, message.subtype_id), ('comment', self.env.ref('mail.mt_note')))
            self.assertTrue(message.is_internal)
            self.assertFalse(message.notification_ids)
        self.assertEqual(self.env['mail.mail'].sudo().search_count([]), mails)
        self.assertEqual(contrib.message_partner_ids, followers)

    def test_trace_tool_posts_an_internal_note_without_follower_or_mail(self):
        fond = self._fond()
        followers, mails = fond.message_partner_ids, self.env['mail.mail'].sudo().search_count([])
        self.assertTrue(self.env['mf.trace'].mf_trace(
            fond, 'Titre <b>court</b>', [('Montant', '1 000 Ar'), ('Vide', False), ('Zéro', 0)], [fond]))
        message = self.traces(fond)[-1]
        self.assertIn('Titre &lt;b&gt;court&lt;/b&gt;', message.body)   # le texte est échappé
        self.assertIn('Zéro', self.plain(message))
        self.assertNotIn('Vide', self.plain(message))
        self.assertIn('data-oe-model="microfinance.fond.credit"', message.body)
        self.assertEqual((message.message_type, message.subtype_id.id, message.is_internal),
                         ('comment', self.env.ref('mail.mt_note').id, True))
        self.assertFalse(message.notification_ids)
        self.assertEqual((fond.message_partner_ids, self.env['mail.mail'].sudo().search_count([])), (followers, mails))

    def test_contribution_cancellation_is_traced(self):
        fond = self._fond()
        contrib = fond.contribution_ids
        contrib.action_cancel()
        reversal = self.env['account.move'].sudo().search([('reversed_entry_id', '=', contrib.move_id.id)])
        self.assertEqual(len(self.with_title(contrib, 'Contribution annulée')), 1)
        self.assertEqual(len(self.with_title(fond, 'Contribution annulée')), 1)
        self.assertEqual(len(self.with_title(contrib.move_id, 'Extournée')), 1)
        self.assertEqual(len(self.with_title(reversal, "Créée par l'annulation")), 1)
        # l'extourne tracée par l'annulation n'ajoute pas de trace de lettrage
        self.assertFalse(self.with_title(contrib.move_id, 'lettrée'))

    # ------------------------------------------------------------------ partage à deux agences
    def test_two_agencies_share_is_traced_everywhere_and_each_agency_sees_only_its_part(self):
        fond = self._fond()
        partage = self._validated(fond=fond)
        self.assertEqual(len(self.with_title(partage, 'Partage validé')), 1)
        self.assertEqual(len(self.with_title(fond, 'Partage validé')), 1)
        ptext = self.text(partage)
        for company, amount in ((self.ag1, '40 000 000'), (self.ag2, '30 000 000')):
            self.assertIn(company.name, ptext)
            self.assertIn(amount, ptext)
            hq_move, ag_move = self._hq_move(partage, company), self._ag_move(partage, company)
            self.assertEqual(len(self.with_title(hq_move, 'Créée par le partage')), 1)
            self.assertIn(ag_move.name, self.text(hq_move))
            self.assertEqual(len(self.with_title(ag_move, 'Créée par le partage')), 1)
        # côté agence : sa part seulement, ni l'autre agence ni le total
        a1 = self.text(self._ag_move(partage, self.ag1))
        a2 = self.text(self._ag_move(partage, self.ag2))
        self.assertIn('40 000 000', a1)
        self.assertNotIn('30 000 000', a1)
        self.assertNotIn('70 000 000', a1)
        self.assertNotIn(self.ag2.name, a1)
        self.assertIn('30 000 000', a2)
        self.assertNotIn('40 000 000', a2)
        self.assertNotIn('70 000 000', a2)
        self.assertNotIn(self.ag1.name, a2)
        self.assertNotIn(self.hq.name, a1 + a2)

    def test_agency_user_reads_no_message_of_another_company(self):
        partage = self._validated()
        Message = self.env['mail.message'].with_user(self.acc_ag1).with_company(self.ag1)

        def readable(move):
            return Message.search([('model', '=', 'account.move'), ('res_id', '=', move.id)])

        own = readable(self._ag_move(partage, self.ag1))
        self.assertTrue(own.filtered(lambda m: 'o_mf_trace' in m.body))
        self.assertFalse(readable(self._hq_move(partage, self.ag1)))
        self.assertFalse(readable(self._ag_move(partage, self.ag2)))
        self.assertFalse(Message.search([('model', '=', 'microfinance.fond.partage'), ('res_id', '=', partage.id)]))

    def test_share_cancellation_is_traced_on_both_sides(self):
        partage = self._validated()
        partage.action_cancel()
        self.assertEqual(len(self.with_title(partage, 'Partage annulé')), 1)
        self.assertEqual(len(self.with_title(partage.fond_id, 'Partage annulé')), 1)
        for company in (self.ag1, self.ag2):
            for move in (self._hq_move(partage, company), self._ag_move(partage, company)):
                self.assertEqual(len(self.with_title(move, 'Extournée')), 1)
        reversals = self.env['account.move'].sudo().search([('reversed_entry_id', 'in', self._moves(partage).ids)])
        self.assertEqual(len(reversals), 4)
        for reversal in reversals:
            self.assertEqual(len(self.with_title(reversal, "Créée par l'annulation du partage")), 1)
        agency_reversal = reversals.filtered(lambda m: m.company_id == self.ag1 and m.microfinance_partage_side == 'agency')
        self.assertNotIn('30 000 000', self.text(agency_reversal))

    # ------------------------------------------------------------------ lettrage / délettrage
    def test_reconciliation_and_unreconciliation_leave_one_message_per_piece(self):
        fond = self._fond()
        move = fond.contribution_ids.move_id
        statement = self._statement(self.bmop, M100_TEST, self.hq_in)
        self._reconcile(move, self.hq_in, statement)
        for piece in (move, statement.move_id):
            self.assertEqual(len(self.with_title(piece, 'Pièce lettrée')), 1)
        self.assertIn(self.hq_in.code, self.text(move))
        self.assertIn('100 000 000' + AR, self.text(move))
        (move.line_ids | statement.move_id.line_ids).filtered(lambda l: l.account_id == self.hq_in).remove_move_reconcile()
        for piece in (move, statement.move_id):
            self.assertEqual(len(self.with_title(piece, 'Pièce délettrée')), 1)

    def test_reconciling_non_ampaly_entries_leaves_no_message(self):
        other = self._acc(self.hq, 'T999001H', 'asset_current', True)
        entry = self.env['account.move'].create({
            'move_type': 'entry', 'journal_id': self.bmop.id, 'date': '2026-10-02',
            'line_ids': [Command.create({'account_id': other.id, 'debit': 5.0, 'credit': 0.0}),
                         Command.create({'account_id': self.hq_suspense.id, 'debit': 0.0, 'credit': 5.0})]})
        entry.action_post()
        back = self.env['account.move'].create({
            'move_type': 'entry', 'journal_id': self.bmop.id, 'date': '2026-10-02',
            'line_ids': [Command.create({'account_id': other.id, 'debit': 0.0, 'credit': 5.0}),
                         Command.create({'account_id': self.hq_suspense.id, 'debit': 5.0, 'credit': 0.0})]})
        back.action_post()
        (entry | back).line_ids.filtered(lambda l: l.account_id == other).reconcile()
        self.assertFalse(self.traces(entry) | self.traces(back))

    # ------------------------------------------------------------------ fonds
    def test_fund_creation_and_changes_are_traced(self):
        fond = self._create_fond(name='Fonds trace', destination='exploitation', nature='subvention',
                                 bank_id=self.bmoi.id, account_id=False)
        created = self.with_title(fond, 'Fonds créé')
        self.assertEqual(len(created), 1)
        self.assertIn('Fonds trace', self.plain(created))
        fond.write({'bank_id': self.bni.id})
        self.assertIn(self.bmoi.name + ' → ' + self.bni.name, self.text(fond))
        self.assertFalse(fond.account_id)
        fond.write({'nature': 'avance'})
        self.assertTrue(fond.account_id)
        changed = self.with_title(fond, "compte d'origine créé")
        self.assertEqual(len(changed), 1)
        self.assertIn('Subvention non remboursable → Avance remboursable', self.plain(changed))
        self.assertIn(fond.account_id.code, self.plain(changed))
        fond.write({'origine': 'public'})
        self.assertIn('Privé → Public', self.text(fond))

    # ------------------------------------------------------------------ identique à avant
    def _scenario(self):
        fond = self._fond(post=False)
        contrib = fond.contribution_ids
        results = [contrib.action_post()]
        partage = self._partage(fond, {self.ag1: M40_TEST, self.ag2: M30_TEST})
        results.append(partage.action_validate())
        shot = [self._shot(contrib, partage)]
        results.append(partage.action_cancel())
        results.append(contrib.action_cancel())
        shot.append(self._shot(contrib, partage))
        accounts = [self.hq_out, self.hq_in]
        for company, ag in self.agencies.items():
            accounts += [ag['in'], ag['out'], company.microfinance_liaison_hq_account_id,
                         company.microfinance_liaison_agency_account_id]
        return results, shot, [round(self._balance(a), 2) for a in accounts]

    def _shot(self, contrib, partage):
        Move = self.env['account.move'].sudo()
        moves = contrib.move_id | Move.search([('microfinance_fond_partage_id', '=', partage.id)])
        moves |= Move.search([('reversed_entry_id', 'in', moves.ids)])
        return {
            'states': (contrib.state, partage.state, partage.base_amount, partage.fond_id.reste_partageable),
            'moves': sorted((m.company_id.id, m.journal_id.code, m.state, m.microfinance_partage_side or '',
                             bool(m.reversed_entry_id), tuple(sorted((l.account_id.code, l.debit, l.credit) for l in m.line_ids)))
                            for m in moves)}

    def test_scenarios_are_identical_with_and_without_traces(self):
        with closing(self.cr.savepoint()):
            with self.neutral_trace():
                without = self._scenario()
        with closing(self.cr.savepoint()):
            with_traces = self._scenario()
        self.assertEqual(with_traces, without)
        self.assertTrue(without[1][0]['moves'])

    # ------------------------------------------------------------------ robustesse
    def test_trace_failure_never_blocks_the_operation_and_leaves_a_warning(self):
        fond = self._create_fond(name='Fonds robuste', destination='exploitation', nature='subvention',
                                 bank_id=self.bmoi.id, account_id=False)
        contrib = self._create_contribution(fond, amount=M100_TEST, reference_paiement='VIR-KO')
        def boom_batch(self, entries):
            raise RuntimeError('boom')

        with patch.object(type(self.env['mf.trace']), 'mf_trace_batch', boom_batch), self.assertLogs(LOGGER, level=logging.WARNING) as logs:
            contrib.action_post()
        self.assertEqual(contrib.state, 'posted')
        self.assertEqual(contrib.move_id.state, 'posted')
        self.assertTrue(any(str(contrib.id) in line for line in logs.output))
        # une erreur à l'écriture du message elle-même : journalisée aussi, opération intacte
        other = self._create_contribution(fond, amount=M30_TEST, reference_paiement='VIR-KO2')
        with patch.object(type(self.env['microfinance.fond.contribution']), '_message_log_batch',
                          side_effect=RuntimeError('boom')), self.assertLogs(LOGGER, level=logging.WARNING):
            other.action_post()
        self.assertEqual(other.state, 'posted')
        self.assertTrue(other.move_id)
        self.assertFalse(self.traces(other))
        # la base reste utilisable après l'échec (savepoint propre)
        self.assertTrue(self.env['microfinance.fond.contribution'].search_count([('id', '=', other.id)]))


_drop_inherited_tests(TestMfTraceExploitation, expl.TestFondPartageExploitation)


class TestMfTraceStatement(TraceHelpers, paper.TestBankStatementPaper):
    """Relevé papier sur un fonds de crédit multi-agences : création, validation, traitement, annulation, réouverture."""

    def _statement_to_treat(self):
        fond, partage = self._shared(500.0, 300.0)
        mirror = self._mirror_line(partage)
        stmt = self._mf_statement(self.ag_journal, 0.0, 300.0, [{
            'name': 'Virement BMOI', 'amount_in': 300.0, 'reference': 'VIR-9', 'treatment': 'reconcile',
            'target_line_id': mirror.id}], user=self.user_agency)
        return fond, partage, mirror, stmt

    def test_statement_lifecycle_is_traced(self):
        fond, partage, mirror, stmt = self._statement_to_treat()
        self.assertEqual(len(self.with_title(stmt, 'Relevé créé')), 1)
        self.assertIn(self.ag_journal.display_name, self.text(stmt))
        stmt.action_mf_validate()
        validated = self.with_title(stmt, 'Relevé validé')
        self.assertEqual(len(validated), 1)
        self.assertIn('300' + AR, self.plain(validated))
        entry = stmt.mf_entry_ids
        entry.action_treat()
        st_move = entry.statement_line_id.move_id
        synthesis = self.with_title(stmt, 'ligne(s) du relevé traitée')
        self.assertEqual(len(synthesis), 1)
        self.assertIn('Virement BMOI', self.plain(synthesis))
        reconciled = self.with_title(mirror.move_id, 'Rapprochée avec la ligne')
        self.assertEqual(len(reconciled), 1)
        self.assertIn(self.user_agency.name, self.plain(reconciled))
        self.assertIn('Virement BMOI', self.plain(reconciled))
        self.assertEqual(len(self.with_title(st_move, 'Créée par la ligne')), 1)
        # le lettrage fait par le relevé n'est pas tracé deux fois
        self.assertFalse(self.with_title(mirror.move_id, 'Pièce lettrée'))
        self.assertFalse(self.with_title(st_move, 'Pièce lettrée'))
        # annulation du rapprochement, puis réouverture avec motif
        entry.with_user(self.user_accountant)._cancel_treatment('Mauvais rapprochement')
        self.assertEqual(len(self.with_title(stmt, 'Traitement annulé')), 1)
        self.assertEqual(len(self.with_title(mirror.move_id, 'Rapprochement annulé')), 1)
        self.assertEqual(len(self.with_title(st_move, 'Extournée')), 1)
        self.assertFalse(self.with_title(mirror.move_id, 'Pièce délettrée'))
        self.assertIn('Mauvais rapprochement', self.text(stmt))
        stmt.with_user(self.user_accountant)._mf_reopen('Erreur de saisie')
        reopened = self.with_title(stmt, 'Relevé rouvert')
        self.assertEqual(len(reopened), 1)
        self.assertIn('Erreur de saisie', self.plain(reopened))

    def test_multi_company_fund_thread_carries_no_amount(self):
        fond, partage, mirror, stmt = self._statement_to_treat()
        self.assertTrue(self.traces(fond))
        self.assertNotIn(AR, self.text(fond))
        # la pièce miroir de l'agence ne cite ni le siège ni la part gardée
        agency_text = self.text(self._moves(partage).filtered(lambda m: m.microfinance_partage_side == 'agency'))
        self.assertIn('300' + AR, agency_text)
        self.assertNotIn('500' + AR, agency_text)
        self.assertNotIn('800' + AR, agency_text)

    def test_a_statement_of_200_lines_leaves_one_summary_message(self):
        fees = self._acc(self.agency, 'T627000Z', 'expense', False)
        stmt = self._mf_statement(self.ag_journal, 0.0, -200.0, [
            {'name': 'Frais %s' % i, 'amount_out': 1.0, 'treatment': 'new', 'account_id': fees.id} for i in range(200)])
        stmt.mf_entry_ids.action_treat()
        self.assertEqual(set(stmt.mf_entry_ids.mapped('state')), {'done'})
        self.assertEqual(len(self.with_title(stmt, 'ligne(s) du relevé traitée')), 1)
        self.assertIn('200 ligne(s)', self.text(stmt))
        self.assertEqual(len(self.traces(stmt)), 2)   # création + une seule synthèse de traitement

    def test_statement_scenarios_are_identical_with_and_without_traces(self):
        def scenario():
            fond, partage, mirror, stmt = self._statement_to_treat()
            validated = stmt.action_mf_validate()
            entry = stmt.mf_entry_ids
            treated = entry.action_treat()
            moves = entry.statement_line_id.move_id
            shot = (validated, treated, entry.state, mirror.reconciled,
                    sorted((l.account_id.code, l.debit, l.credit) for l in moves.line_ids),
                    self._allocation(fond, self.agency).amount_received)
            entry.with_user(self.user_accountant)._cancel_treatment('x')
            return shot, entry.state, mirror.reconciled, self._allocation(fond, self.agency).amount_in_transit

        with closing(self.cr.savepoint()):
            with self.neutral_trace():
                without = scenario()
        with closing(self.cr.savepoint()):
            with_traces = scenario()
        self.assertEqual(with_traces, without)


_drop_inherited_tests(TestMfTraceStatement, paper.TestBankStatementPaper)
